"""Shared read-only migration gate for process entrypoints."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def schema_is_current(engine: AsyncEngine) -> bool:
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    expected = ScriptDirectory.from_config(config).get_current_head()
    async with engine.connect() as connection:
        revisions: list[str] = list(
            (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars()
        )
    return revisions == [expected]
