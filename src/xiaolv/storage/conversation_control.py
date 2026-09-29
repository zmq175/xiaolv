"""Registered routes and persistent administrator overrides."""

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from xiaolv.storage.profile_publication import PublicationError


class ConversationControl:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def register(self, conversations: Iterable[str]) -> None:
        async with self._engine.begin() as connection:
            for conversation in sorted(set(conversations)):
                await connection.execute(
                    text("""
                    INSERT INTO app.conversation_state(conversation_id, epoch)
                    VALUES (:id, 0) ON CONFLICT DO NOTHING
                """),
                    {"id": conversation},
                )
                await connection.execute(
                    text("""
                    INSERT INTO app.conversation_controls(conversation_id)
                    VALUES (:id) ON CONFLICT DO NOTHING
                """),
                    {"id": conversation},
                )

    async def allowed(self, conversation: str) -> bool:
        async with self._engine.connect() as connection:
            value = (
                await connection.execute(
                    text(
                        "SELECT enabled FROM app.conversation_controls WHERE conversation_id = :id"
                    ),
                    {"id": conversation},
                )
            ).scalar_one_or_none()
            return value is True

    async def list(self, limit: int = 20, after: str = "") -> dict[str, Any]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text("""
                SELECT conversation_id, enabled, revision AS version
                FROM app.conversation_controls WHERE conversation_id > :after
                ORDER BY conversation_id LIMIT :limit
            """),
                        {"after": after, "limit": limit + 1},
                    )
                )
                .mappings()
                .all()
            )
            return {
                "items": [dict(row) for row in rows[:limit]],
                "next_after": rows[limit - 1]["conversation_id"] if len(rows) > limit else None,
            }

    async def change(
        self, conversation: str, enabled: bool, version: int, key: str, actor: str
    ) -> dict[str, Any]:
        fingerprint = hashlib.sha256(json.dumps([enabled, version]).encode()).hexdigest()
        async with self._engine.begin() as connection:
            # Same first lock as delivery claim; updates invalidate old epochs atomically.
            await connection.execute(
                text(
                    "SELECT epoch FROM app.conversation_state WHERE conversation_id = :id FOR UPDATE"
                ),
                {"id": conversation},
            )
            state = (
                (
                    await connection.execute(
                        text(
                            "SELECT enabled, revision FROM app.conversation_controls WHERE conversation_id = :id"
                        ),
                        {"id": conversation},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if state is None:
                raise PublicationError("conversation_not_registered", 404)
            previous = (
                (
                    await connection.execute(
                        text(
                            "SELECT request_hash, response FROM admin.conversation_mutations WHERE conversation_id = :id AND idempotency_key = :key"
                        ),
                        {"id": conversation, "key": key},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous is not None:
                if previous["request_hash"] != fingerprint:
                    raise PublicationError("idempotency_conflict")
                return dict(previous["response"])
            if state["revision"] != version:
                raise PublicationError("version_conflict")
            await connection.execute(
                text(
                    "UPDATE app.conversation_controls SET enabled = :enabled, revision = revision + 1 WHERE conversation_id = :id"
                ),
                {"id": conversation, "enabled": enabled},
            )
            if not enabled:
                await connection.execute(
                    text(
                        "UPDATE app.conversation_state SET epoch = epoch + 1 WHERE conversation_id = :id"
                    ),
                    {"id": conversation},
                )
            response = {"conversation_id": conversation, "enabled": enabled, "version": version + 1}
            await connection.execute(
                text("""
                INSERT INTO admin.conversation_mutations(conversation_id, idempotency_key, request_hash, response, actor)
                VALUES (:id, :key, :hash, CAST(:response AS jsonb), :actor)
            """),
                {
                    "id": conversation,
                    "key": key,
                    "hash": fingerprint,
                    "response": json.dumps(response),
                    "actor": actor,
                },
            )
            return response
