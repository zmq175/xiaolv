"""PostgreSQL inbox storage."""

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from xiaolv.domain.chat_event import ChatEvent, ConversationContext
from xiaolv.storage.postgres_turns import CandidatePolicy, offer_candidate

_CODEC = TypeAdapter(ChatEvent)


class PostgresInbox:
    def __init__(
        self, engine: AsyncEngine, candidate_policy: CandidatePolicy | None = None
    ) -> None:
        self._engine = engine
        self._candidate_policy = candidate_policy

    async def accept(self, event: ChatEvent) -> bool:
        async with self._engine.begin() as connection:
            await connection.execute(
                text("""
                INSERT INTO app.conversation_state (conversation_id) VALUES (:conversation)
                ON CONFLICT DO NOTHING
            """),
                {"conversation": event.conversation_id},
            )
            inserted = await connection.execute(
                text("""
                INSERT INTO app.messages (conversation_id, message_id, occurred_at, payload)
                VALUES (:conversation, :message, :occurred_at, CAST(:payload AS jsonb))
                ON CONFLICT (conversation_id, message_id) DO NOTHING RETURNING message_id
            """),
                {
                    "conversation": event.conversation_id,
                    "message": event.message_id,
                    "occurred_at": event.occurred_at,
                    "payload": _CODEC.dump_json(event).decode(),
                },
            )
            if inserted.scalar_one_or_none() is None:
                return False
            await connection.execute(
                text("""
                UPDATE app.conversation_state SET revision = revision + 1
                WHERE conversation_id = :conversation
            """),
                {"conversation": event.conversation_id},
            )
            if self._candidate_policy is not None:
                await offer_candidate(connection, event, self._candidate_policy)
            return True

    async def context(self, conversation_id: str, limit: int) -> ConversationContext:
        async with self._engine.connect() as connection:
            rows = await connection.execute(
                text("""
                SELECT s.revision, m.payload FROM app.conversation_state s
                LEFT JOIN LATERAL (
                    SELECT payload, occurred_at, sequence FROM app.messages
                    WHERE conversation_id = s.conversation_id
                    ORDER BY occurred_at DESC, sequence DESC LIMIT :limit
                ) m ON true
                WHERE s.conversation_id = :conversation
                ORDER BY m.occurred_at, m.sequence
            """),
                {"conversation": conversation_id, "limit": limit},
            )
            snapshot = rows.all()
            return ConversationContext(
                revision=snapshot[0].revision if snapshot else 0,
                messages=tuple(
                    _CODEC.validate_python(row.payload)
                    for row in snapshot
                    if row.payload is not None
                ),
            )
