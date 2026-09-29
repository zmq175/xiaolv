"""Durable chat candidate scheduling; no model calls in transactions."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from xiaolv.domain.chat_event import ChatEvent, ConversationContext
from xiaolv.orchestration.text_runtime import ConversationCandidate

_CODEC = TypeAdapter(ChatEvent)


@dataclass(frozen=True)
class CandidatePolicy:
    enabled_conversations: frozenset[str] = frozenset()
    merge_seconds: float = 0.8
    max_merge_seconds: float = 2
    ttl_seconds: float = 45
    queue_age_seconds: float = 10

    def __post_init__(self) -> None:
        durations = (
            self.merge_seconds,
            self.max_merge_seconds,
            self.ttl_seconds,
            self.queue_age_seconds,
        )
        if any(type(value) not in (int, float) or not isfinite(value) for value in durations):
            raise ValueError("invalid candidate policy durations")
        if (
            min(self.merge_seconds, self.max_merge_seconds) < 0
            or not 0 < self.queue_age_seconds <= self.ttl_seconds
        ):
            raise ValueError("invalid candidate policy limits")
        if not isinstance(self.enabled_conversations, frozenset) or any(
            not isinstance(item, str) or not item.strip() for item in self.enabled_conversations
        ):
            raise ValueError("invalid candidate policy conversations")


async def offer_candidate(
    connection: AsyncConnection, event: ChatEvent, policy: CandidatePolicy
) -> None:
    if event.is_historical or event.conversation_id not in policy.enabled_conversations:
        return
    await connection.execute(
        text("""
        DELETE FROM app.chat_candidates WHERE conversation_id = :conversation
        AND LEAST(queue_until, expires_at) <= clock_timestamp()
    """),
        {"conversation": event.conversation_id},
    )
    await connection.execute(
        text("""
        INSERT INTO app.chat_candidates (conversation_id, message_id, pending_since, ready_at, expires_at, queue_until)
        VALUES (:conversation, :message, clock_timestamp(), clock_timestamp() + LEAST(:merge, :max_merge) * interval '1 second', :expires, :queue_until)
        ON CONFLICT (conversation_id) DO UPDATE SET
            message_id = EXCLUDED.message_id,
            ready_at = LEAST(EXCLUDED.ready_at, app.chat_candidates.pending_since + :max_merge * interval '1 second'),
            expires_at = LEAST(app.chat_candidates.expires_at, EXCLUDED.expires_at),
            queue_until = LEAST(app.chat_candidates.queue_until, EXCLUDED.queue_until)
    """),
        {
            "conversation": event.conversation_id,
            "message": event.message_id,
            "merge": policy.merge_seconds,
            "max_merge": policy.max_merge_seconds,
            "expires": event.effective_time + timedelta(seconds=policy.ttl_seconds),
            "queue_until": event.received_at + timedelta(seconds=policy.queue_age_seconds),
        },
    )


class PostgresTurns:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def status(self, turn_id: str) -> str | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text("SELECT status FROM app.chat_turns WHERE turn_id = :turn"), {"turn": turn_id}
            )
            status: str | None = result.scalar_one_or_none()
            return status

    async def recover(self) -> int:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text("""
                SELECT t.turn_id, t.conversation_id FROM app.chat_turns t
                JOIN app.conversation_state s USING (conversation_id)
                WHERE t.status = 'running' AND t.expires_at <= clock_timestamp()
                ORDER BY t.expires_at LIMIT 100 FOR UPDATE OF s SKIP LOCKED
            """)
            )
            rows = result.mappings().all()
            for row in rows:
                await connection.execute(
                    text("""
                    UPDATE app.conversation_state SET active_turn_id = NULL, turn_lease_until = NULL
                    WHERE conversation_id = :conversation AND active_turn_id = :turn
                """),
                    {"conversation": row["conversation_id"], "turn": row["turn_id"]},
                )
                await connection.execute(
                    text(
                        "UPDATE app.chat_turns SET status = 'expired' WHERE turn_id = :turn AND status = 'running'"
                    ),
                    {"turn": row["turn_id"]},
                )
            return len(rows)

    async def claim(self) -> ConversationCandidate | None:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text("""
                SELECT c.*, s.revision, s.epoch, m.payload FROM app.chat_candidates c
                JOIN app.conversation_state s USING (conversation_id)
                JOIN app.messages m ON m.conversation_id = c.conversation_id AND m.message_id = c.message_id
                WHERE (c.ready_at <= clock_timestamp() OR LEAST(c.queue_until, c.expires_at) <= clock_timestamp())
                  AND (s.turn_lease_until IS NULL OR s.turn_lease_until <= clock_timestamp())
                ORDER BY c.ready_at
                FOR UPDATE OF s SKIP LOCKED LIMIT 1
            """)
            )
            row = result.mappings().one_or_none()
            if row is None:
                return None
            now: datetime = (
                await connection.execute(text("SELECT clock_timestamp()"))
            ).scalar_one()
            if min(row["queue_until"], row["expires_at"]) <= now:
                await connection.execute(
                    text("DELETE FROM app.chat_candidates WHERE conversation_id = :conversation"),
                    {"conversation": row["conversation_id"]},
                )
                return None
            event = _CODEC.validate_python(row["payload"])
            turn_id = uuid4().hex
            epoch = row["epoch"] + 1
            await connection.execute(
                text("""
                UPDATE app.conversation_state SET epoch = :epoch, active_turn_id = :turn,
                    turn_lease_until = :expires WHERE conversation_id = :conversation
            """),
                {
                    "epoch": epoch,
                    "turn": turn_id,
                    "expires": row["expires_at"],
                    "conversation": event.conversation_id,
                },
            )
            await connection.execute(
                text("""
                INSERT INTO app.chat_turns (turn_id, conversation_id, epoch, revision, expires_at)
                VALUES (:turn, :conversation, :epoch, :revision, :expires)
            """),
                {
                    "turn": turn_id,
                    "conversation": event.conversation_id,
                    "epoch": epoch,
                    "revision": row["revision"],
                    "expires": row["expires_at"],
                },
            )
            await connection.execute(
                text("DELETE FROM app.chat_candidates WHERE conversation_id = :conversation"),
                {"conversation": event.conversation_id},
            )
            history = await connection.execute(
                text("""
                SELECT payload FROM app.messages WHERE conversation_id = :conversation
                ORDER BY occurred_at DESC, sequence DESC LIMIT 30
            """),
                {"conversation": event.conversation_id},
            )
            payloads: list[object] = list(history.scalars().all())
            context = ConversationContext(
                row["revision"],
                tuple(_CODEC.validate_python(payload) for payload in reversed(payloads)),
            )
            return ConversationCandidate(
                event.conversation_id, turn_id, event.text, row["expires_at"], epoch, context
            )

    async def finish(self, candidate: ConversationCandidate, status: str) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text("""
                UPDATE app.conversation_state SET active_turn_id = NULL, turn_lease_until = NULL
                WHERE conversation_id = :conversation AND active_turn_id = :turn
            """),
                {"conversation": candidate.conversation_id, "turn": candidate.event_id},
            )
            await connection.execute(
                text(
                    "UPDATE app.chat_turns SET status = :status WHERE turn_id = :turn AND status = 'running'"
                ),
                {"status": status, "turn": candidate.event_id},
            )
