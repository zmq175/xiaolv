"""Shared admission with short transactions and deadline-bounded crash recovery."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class PostgresModelCapacity:
    def __init__(self, engine: AsyncEngine, pool_id: str, capacity: int) -> None:
        if not pool_id.strip() or type(capacity) is not int or capacity <= 0:
            raise ValueError("invalid shared model capacity")
        self._engine = engine
        self._pool_id = pool_id
        self._capacity = capacity

    async def initialize(self) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                text("""
                INSERT INTO app.model_capacity_pools VALUES (:pool, :capacity)
                ON CONFLICT (pool_id) DO NOTHING
            """),
                {"pool": self._pool_id, "capacity": self._capacity},
            )
            actual: int = (
                await connection.execute(
                    text("SELECT capacity FROM app.model_capacity_pools WHERE pool_id = :pool"),
                    {"pool": self._pool_id},
                )
            ).scalar_one()
            if actual != self._capacity:
                raise ValueError("shared model capacity configuration conflict")

    @asynccontextmanager
    async def hold(self, call_id: str, expires_at: datetime) -> AsyncIterator[None]:
        await self.initialize()
        while True:
            remaining = (expires_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise TimeoutError("model admission deadline expired")
            if await self._acquire(call_id, expires_at):
                break
            await asyncio.sleep(min(0.1, remaining))
        try:
            yield
        finally:
            await asyncio.shield(self._release(call_id))

    async def _acquire(self, call_id: str, expires_at: datetime) -> bool:
        async with self._engine.begin() as connection:
            actual: int = (
                await connection.execute(
                    text("""
                SELECT capacity FROM app.model_capacity_pools WHERE pool_id = :pool FOR UPDATE
            """),
                    {"pool": self._pool_id},
                )
            ).scalar_one()
            if actual != self._capacity:
                raise ValueError("shared model capacity configuration conflict")
            await connection.execute(
                text("""
                DELETE FROM app.model_capacity_leases
                WHERE pool_id = :pool AND lease_until <= clock_timestamp()
            """),
                {"pool": self._pool_id},
            )
            row = (
                await connection.execute(
                    text("""
                INSERT INTO app.model_capacity_leases (call_id, pool_id, lease_until)
                SELECT :call_id, :pool, :expires_at + interval '5 seconds'
                WHERE :expires_at > clock_timestamp()
                  AND (SELECT count(*) FROM app.model_capacity_leases WHERE pool_id = :pool) < :capacity
                RETURNING call_id
            """),
                    {
                        "call_id": call_id,
                        "pool": self._pool_id,
                        "expires_at": expires_at,
                        "capacity": self._capacity,
                    },
                )
            ).scalar_one_or_none()
            return row is not None

    async def _release(self, call_id: str) -> None:
        async with asyncio.timeout(2), self._engine.begin() as connection:
            await connection.execute(
                text("""
                DELETE FROM app.model_capacity_leases WHERE call_id = :call_id AND pool_id = :pool
            """),
                {"call_id": call_id, "pool": self._pool_id},
            )
