"""Migrations run explicitly; never at bot startup."""

import asyncio
import os

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    url = os.environ.get("XIAOLV_DATABASE_URL")
    if not url:
        raise RuntimeError("XIAOLV_DATABASE_URL is required for migrations")
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if config.attributes.get("connection") is not None:
    run_migrations(config.attributes["connection"])
else:
    asyncio.run(run_online())
