"""Serialized monthly credit reservations, shared by Search and Extract."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from xiaolv.domain.model_budget import BudgetDenied


class PostgresWebCredits:
    def __init__(self, engine: AsyncEngine, *, monthly_limit: int) -> None:
        if type(monthly_limit) is not int or not 1 <= monthly_limit <= 900:
            raise ValueError("invalid web credit limit")
        self._engine, self._limit = engine, monthly_limit

    async def reserve(
        self, call_id: str, operation: Literal["search", "extract"], expires_at: datetime
    ) -> None:
        async with self._engine.begin() as connection:
            period: date = (
                await connection.execute(
                    text("SELECT date_trunc('month', clock_timestamp() AT TIME ZONE 'UTC')::date")
                )
            ).scalar_one()
            params = {
                "pool": "tavily",
                "period": period,
                "limit": self._limit,
                "call": call_id,
                "operation": operation,
                "expires": expires_at,
            }
            await connection.execute(
                text("""
                INSERT INTO app.web_credit_periods (pool_id, period, limit_credits)
                VALUES (:pool, :period, :limit) ON CONFLICT DO NOTHING
            """),
                params,
            )
            row = (
                (
                    await connection.execute(
                        text("""
                SELECT *, :expires > clock_timestamp() AS valid FROM app.web_credit_periods
                WHERE pool_id = :pool AND period = :period FOR UPDATE
            """),
                        params,
                    )
                )
                .mappings()
                .one()
            )
            if not row["valid"]:
                raise TimeoutError()
            if row["limit_credits"] != self._limit:
                raise BudgetDenied("web credit configuration conflict")
            if row["blocked"] or row["spent"] + row["reserved"] + 1 > row["limit_credits"]:
                raise BudgetDenied("web credits exhausted")
            await connection.execute(
                text("""
                INSERT INTO app.web_credit_calls (call_id, pool_id, period, operation, reserved, expires_at)
                VALUES (:call, :pool, :period, :operation, 1, :expires)
            """),
                params,
            )
            await connection.execute(
                text("""
                UPDATE app.web_credit_periods SET reserved = reserved + 1
                WHERE pool_id = :pool AND period = :period
            """),
                params,
            )

    async def settle(self, call_id: str, charged: Decimal | None) -> None:
        if charged is not None and (
            not isinstance(charged, Decimal)
            or not charged.is_finite()
            or not Decimal(0) <= charged <= Decimal(1000000)
            or charged != charged.quantize(Decimal("0.000001"))
        ):
            raise ValueError("invalid credits")
        async with self._engine.begin() as connection:
            key = (
                (
                    await connection.execute(
                        text("""
                SELECT pool_id, period FROM app.web_credit_calls WHERE call_id = :call AND pool_id = 'tavily'
            """),
                        {"call": call_id},
                    )
                )
                .mappings()
                .one()
            )
            params = {**dict(key), "call": call_id, "charge": charged}
            await connection.execute(
                text("""
                SELECT pool_id FROM app.web_credit_periods
                WHERE pool_id = :pool_id AND period = :period FOR UPDATE
            """),
                params,
            )
            row = (
                (
                    await connection.execute(
                        text("SELECT * FROM app.web_credit_calls WHERE call_id = :call FOR UPDATE"),
                        params,
                    )
                )
                .mappings()
                .one()
            )
            if row["state"] != "reserved":
                if row["charged"] != charged:
                    raise ValueError("web credit settlement conflict")
                return
            if charged is not None:
                await connection.execute(
                    text("""
                    UPDATE app.web_credit_periods SET reserved = reserved - :held, spent = spent + :charge,
                        blocked = blocked OR :charge > :held
                    WHERE pool_id = :pool_id AND period = :period
                """),
                    {**params, "held": row["reserved"]},
                )
            await connection.execute(
                text("""
                UPDATE app.web_credit_calls SET charged = :charge, state = :state, finished_at = clock_timestamp()
                WHERE call_id = :call
            """),
                {**params, "state": "unknown" if charged is None else "settled"},
            )
