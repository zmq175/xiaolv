"""Publish derived media content under the active turn's original scope and lifetime."""

import logging
from dataclasses import replace

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from xiaolv.application.inbound_speech import MediaUnavailable
from xiaolv.domain.authorization import PermissionDenied
from xiaolv.domain.chat_event import ChatEvent, MediaInterpretation
from xiaolv.orchestration.text_runtime import ConversationCandidate

_CODEC = TypeAdapter(ChatEvent)


class PostgresInterpretations:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(
        self,
        candidate: ConversationCandidate,
        event: ChatEvent,
        part_index: int | tuple[int, ...],
        interpretation: MediaInterpretation,
    ) -> ChatEvent:
        indices = (part_index,) if isinstance(part_index, int) else part_index
        if (
            not indices
            or len(indices) > 4
            or len(set(indices)) != len(indices)
            or any(not 0 <= index < len(event.parts) for index in indices)
        ):
            raise MediaUnavailable()
        if (
            event.conversation_id != candidate.conversation_id
            or event.message_id != candidate.source_message_id
        ):
            raise MediaUnavailable()
        async with self._engine.begin() as connection:
            state = (
                (
                    await connection.execute(
                        text("""
                SELECT s.epoch, s.active_turn_id, c.enabled
                FROM app.conversation_state s
                JOIN app.conversation_controls c USING (conversation_id)
                WHERE s.conversation_id = :conversation FOR UPDATE OF s
            """),
                        {"conversation": candidate.conversation_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if state is None or not state["enabled"]:
                raise PermissionDenied("permission_denied")
            if (
                state["epoch"] != candidate.generation_epoch
                or state["active_turn_id"] != candidate.event_id
            ):
                raise MediaUnavailable()
            payload = (
                await connection.execute(
                    text("""
                SELECT payload FROM app.messages
                WHERE conversation_id = :conversation AND message_id = :message FOR UPDATE
            """),
                    {"conversation": event.conversation_id, "message": event.message_id},
                )
            ).scalar_one_or_none()
            if payload is None or _CODEC.validate_python(payload) != event:
                raise MediaUnavailable()
            parts = list(event.parts)
            for index in indices:
                parts[index] = replace(parts[index], interpretation=interpretation)
            updated = replace(event, parts=tuple(parts), content_version=event.content_version + 1)
            result = await connection.execute(
                text("""
                UPDATE app.messages SET payload = CAST(:payload AS jsonb)
                WHERE conversation_id = :conversation AND message_id = :message
                  AND :expires > clock_timestamp()
                  AND EXISTS (
                    SELECT 1 FROM app.chat_turns WHERE turn_id = :turn
                    AND conversation_id = :conversation AND status = 'running'
                    AND expires_at > clock_timestamp()
                  )
                RETURNING message_id
            """),
                {
                    "conversation": event.conversation_id,
                    "message": event.message_id,
                    "expires": candidate.expires_at,
                    "turn": candidate.event_id,
                    "payload": _CODEC.dump_json(updated).decode(),
                },
            )
            if result.scalar_one_or_none() is None:
                raise TimeoutError()
            await connection.execute(
                text("""
                UPDATE app.conversation_state SET revision = revision + 1
                WHERE conversation_id = :conversation
            """),
                {"conversation": event.conversation_id},
            )
        logging.getLogger(__name__).info(
            "媒体派生内容已保存",
            extra={
                "event": "media_interpretation_saved",
                "fields": {
                    "turn_id": candidate.event_id,
                    "content_version": str(updated.content_version),
                    "processor": interpretation.processor,
                },
            },
        )
        return updated
