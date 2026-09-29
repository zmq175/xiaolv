"""Chat-side read access to published persona only."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from xiaolv.domain.bot_profile import BotProfile, ProfileSnapshot


class PublishedProfiles:
    def __init__(self, engine: AsyncEngine, startup: BotProfile) -> None:
        self._engine = engine
        self._startup = startup

    async def load(self) -> ProfileSnapshot:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                SELECT r.version, r.profile FROM app.bot_profile_current c
                LEFT JOIN app.bot_profile_releases r ON r.version = c.version
                WHERE c.id = 1
            """)
                    )
                )
                .mappings()
                .one()
            )
            if row["version"] is None:
                return ProfileSnapshot(self._startup)
            return ProfileSnapshot(BotProfile.model_validate(row["profile"]), row["version"])
