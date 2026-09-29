"""Transactional control-plane profile drafts and release snapshots."""

import hashlib
import json
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from xiaolv.domain.bot_profile import BotProfile


class PublicationError(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


class ProfilePublication:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def current(self) -> dict[str, Any]:
        async with self._engine.connect() as connection:
            return await self._snapshot(connection)

    async def history(self, limit: int, before: int | None) -> dict[str, Any]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text("""
                SELECT version, profile->>'name' AS name, created_at
                FROM app.bot_profile_releases
                WHERE (CAST(:before AS bigint) IS NULL OR version < :before)
                ORDER BY version DESC LIMIT :count
            """),
                        {"before": before, "count": limit + 1},
                    )
                )
                .mappings()
                .all()
            )
            items = [
                {
                    "version": row["version"],
                    "name": row["name"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in rows[:limit]
            ]
            return {
                "items": items,
                "next_before": items[-1]["version"] if len(rows) > limit else None,
            }

    async def release(self, version: int) -> dict[str, Any]:
        async with self._engine.connect() as connection:
            return {"version": version, "profile": await self._release(connection, version)}

    async def _release(self, connection: AsyncConnection, version: int) -> Any:
        row = (
            (
                await connection.execute(
                    text("SELECT profile FROM app.bot_profile_releases WHERE version = :version"),
                    {"version": version},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise PublicationError("release_not_found", 404)
        return row["profile"]

    async def _snapshot(self, connection: AsyncConnection) -> dict[str, Any]:
        row = (
            (
                await connection.execute(
                    text("""
            SELECT s.revision, s.draft, r.version, r.profile
            FROM admin.profile_state s CROSS JOIN app.bot_profile_current c
            LEFT JOIN app.bot_profile_releases r ON r.version = c.version
            WHERE s.id = 1 AND c.id = 1
        """)
                )
            )
            .mappings()
            .one()
        )
        return {
            "version": row["revision"],
            "draft": row["draft"],
            "published": {"version": row["version"], "profile": row["profile"]}
            if row["version"] is not None
            else None,
        }

    async def change(
        self,
        action: Literal["draft", "publish", "rollback"],
        profile: BotProfile | None,
        expected_version: int,
        idempotency_key: str,
        release_version: int | None = None,
    ) -> dict[str, Any]:
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "action": action,
                    "expected_version": expected_version,
                    "profile": profile.model_dump(mode="json") if profile else None,
                    "release_version": release_version,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        async with self._engine.begin() as connection:
            state = (
                (
                    await connection.execute(
                        text(
                            "SELECT revision, draft FROM admin.profile_state WHERE id = 1 FOR UPDATE"
                        )
                    )
                )
                .mappings()
                .one()
            )
            previous = (
                (
                    await connection.execute(
                        text(
                            "SELECT request_hash, response FROM admin.profile_mutations WHERE idempotency_key = :key"
                        ),
                        {"key": idempotency_key},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous is not None:
                if previous["request_hash"] != request_hash:
                    raise PublicationError("idempotency_conflict")
                return dict(previous["response"])
            if state["revision"] != expected_version:
                raise PublicationError("version_conflict")
            if action == "draft":
                if profile is None:
                    raise PublicationError("profile_required", 422)
                await connection.execute(
                    text("""
                    UPDATE admin.profile_state SET draft = CAST(:profile AS jsonb) WHERE id = 1
                """),
                    {"profile": profile.model_dump_json()},
                )
            else:
                content = (
                    await self._release(connection, release_version)
                    if action == "rollback" and release_version is not None
                    else state["draft"]
                )
                if content is None:
                    raise PublicationError("draft_required")
                version: int = (
                    await connection.execute(
                        text("""
                    INSERT INTO app.bot_profile_releases(profile) VALUES (CAST(:profile AS jsonb))
                    RETURNING version
                """),
                        {"profile": json.dumps(content)},
                    )
                ).scalar_one()
                await connection.execute(
                    text("UPDATE app.bot_profile_current SET version = :version WHERE id = 1"),
                    {"version": version},
                )
            await connection.execute(
                text("UPDATE admin.profile_state SET revision = revision + 1 WHERE id = 1")
            )
            response = await self._snapshot(connection)
            await connection.execute(
                text("""
                INSERT INTO admin.profile_mutations(idempotency_key, request_hash, response)
                VALUES (:key, :hash, CAST(:response AS jsonb))
            """),
                {"key": idempotency_key, "hash": request_hash, "response": json.dumps(response)},
            )
            return response
