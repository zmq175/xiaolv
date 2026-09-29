"""Create only disposable databases, never clear an existing database."""

import os
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
async def database_url():
    configured = os.environ.get("XIAOLV_TEST_DATABASE_URL")
    if not configured:
        pytest.skip("XIAOLV_TEST_DATABASE_URL required for real PostgreSQL tests")
    base = make_url(configured)
    if base.database != "xiaolv_test":
        pytest.fail("test DSN must point to dedicated xiaolv_test database")
    name = "xiaolv_test_" + uuid4().hex
    # Setup uses the native driver to create a disposable DB outside any transaction.
    dsn = base.set(drivername="postgresql").render_as_string(hide_password=False)
    admin = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    await admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = base.set(database=name).render_as_string(hide_password=False)
    engine = create_async_engine(url, hide_parameters=True)
    try:

        def migrate(connection):
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        async with engine.begin() as connection:
            await connection.run_sync(migrate)
        await engine.dispose()
        yield url
    finally:
        await engine.dispose()
        await admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        await admin.close()
