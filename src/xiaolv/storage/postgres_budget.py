"""PostgreSQL-backed model budget; network work stays outside transactions."""

import json
from datetime import date
from decimal import ROUND_CEILING, Decimal

from pydantic import TypeAdapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from xiaolv.domain.model_budget import (
    BudgetDenied,
    BudgetPolicy,
    BudgetSnapshot,
    CallAudit,
    ModelCallIntent,
)
from xiaolv.domain.model_usage import ModelCallReport

_REPORT = TypeAdapter(ModelCallReport)


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


class PostgresModelBudget:
    def __init__(self, engine: AsyncEngine, policy: BudgetPolicy) -> None:
        self._engine = engine
        self._policy = policy

    async def reserve(self, intent: ModelCallIntent) -> None:
        policy = self._policy
        if intent.model != policy.model:
            raise BudgetDenied("budget model mismatch")
        amount = money(
            (
                intent.max_input_tokens * policy.input_per_million
                + intent.max_output_tokens * policy.output_per_million
            )
            / 1000000
        )
        async with self._engine.begin() as connection:
            period: date = (
                await connection.execute(
                    text("SELECT date_trunc('month', clock_timestamp() AT TIME ZONE 'UTC')::date")
                )
            ).scalar_one()
            params = {"pool": policy.pool_id, "period": period, "limit": policy.monthly_limit}
            await connection.execute(
                text("""
                INSERT INTO app.budget_periods (pool_id, period, limit_amount)
                VALUES (:pool, :period, :limit) ON CONFLICT DO NOTHING
            """),
                params,
            )
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT * FROM app.budget_periods WHERE pool_id = :pool AND period = :period FOR UPDATE"
                        ),
                        params,
                    )
                )
                .mappings()
                .one()
            )
            if row["limit_amount"] != policy.monthly_limit:
                raise BudgetDenied("budget configuration conflict")
            if row["blocked"] or row["spent"] + row["reserved"] + amount > row["limit_amount"]:
                raise BudgetDenied("budget exhausted")
            previous = (
                await connection.execute(
                    text("SELECT call_id FROM app.model_calls WHERE call_id = :call"),
                    {"call": intent.call_id},
                )
            ).scalar_one_or_none()
            if previous is not None:
                raise BudgetDenied("call already reserved")
            await connection.execute(
                text("""
                INSERT INTO app.model_calls (call_id, pool_id, period, provider_id, model, price_version,
                    input_rate, output_rate, cached_rate, reserved_amount, started_at)
                VALUES (:call, :pool, :period, :provider, :model, :version, :input, :output, :cached, :amount, :started)
            """),
                {
                    **params,
                    "call": intent.call_id,
                    "provider": policy.provider_id,
                    "model": policy.model,
                    "version": policy.price_version,
                    "input": policy.input_per_million,
                    "output": policy.output_per_million,
                    "cached": policy.cached_input_per_million,
                    "amount": amount,
                    "started": intent.started_at,
                },
            )
            await connection.execute(
                text(
                    "UPDATE app.budget_periods SET reserved = reserved + :amount WHERE pool_id = :pool AND period = :period"
                ),
                {**params, "amount": amount},
            )

    async def settle(self, report: ModelCallReport) -> None:
        encoded = json.loads(_REPORT.dump_json(report))
        async with self._engine.begin() as connection:
            key = (
                (
                    await connection.execute(
                        text(
                            "SELECT pool_id, period FROM app.model_calls WHERE call_id = :call AND pool_id = :pool"
                        ),
                        {"call": report.call_id, "pool": self._policy.pool_id},
                    )
                )
                .mappings()
                .one()
            )
            params = {"pool": key["pool_id"], "period": key["period"], "call": report.call_id}
            await connection.execute(
                text(
                    "SELECT pool_id FROM app.budget_periods WHERE pool_id = :pool AND period = :period FOR UPDATE"
                ),
                params,
            )
            row = (
                (
                    await connection.execute(
                        text("SELECT * FROM app.model_calls WHERE call_id = :call FOR UPDATE"),
                        params,
                    )
                )
                .mappings()
                .one()
            )
            if row["provider_id"] != self._policy.provider_id or row["model"] != report.model:
                raise BudgetDenied("call settlement scope mismatch")
            if row["report"] is not None:
                if row["report"] != encoded:
                    raise ValueError("call report conflict")
                return
            charge = None
            if report.status == "completed" and report.usage is not None:
                usage = report.usage
                cached = usage.cached_input_tokens or 0
                cache_rate = (
                    row["cached_rate"] if row["cached_rate"] is not None else row["input_rate"]
                )
                charge = money(
                    (
                        (usage.input_tokens - cached) * row["input_rate"]
                        + cached * cache_rate
                        + usage.output_tokens * row["output_rate"]
                    )
                    / 1000000
                )
                await connection.execute(
                    text("""
                    UPDATE app.budget_periods SET reserved = reserved - :reserved, spent = spent + :charge,
                        blocked = blocked OR :charge > :reserved
                    WHERE pool_id = :pool AND period = :period
                """),
                    {**params, "reserved": row["reserved_amount"], "charge": charge},
                )
            await connection.execute(
                text("""
                UPDATE app.model_calls SET state = :state, charged_amount = :charge, report = CAST(:report AS jsonb)
                WHERE call_id = :call
            """),
                {
                    **params,
                    "state": "settled" if charge is not None else "unknown",
                    "charge": charge,
                    "report": json.dumps(encoded),
                },
            )

    async def snapshot(self, period: date | None = None) -> BudgetSnapshot:
        async with self._engine.connect() as connection:
            if period is None:
                period = (
                    await connection.execute(
                        text(
                            "SELECT date_trunc('month', clock_timestamp() AT TIME ZONE 'UTC')::date"
                        )
                    )
                ).scalar_one()
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT * FROM app.budget_periods WHERE pool_id = :pool AND period = :period"
                        ),
                        {"pool": self._policy.pool_id, "period": period},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return BudgetSnapshot(
                    str(period), self._policy.monthly_limit, Decimal(0), Decimal(0), False
                )
            return BudgetSnapshot(
                str(period), row["limit_amount"], row["reserved"], row["spent"], row["blocked"]
            )

    async def audit(self, call_id: str) -> CallAudit | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT * FROM app.model_calls WHERE call_id = :call AND pool_id = :pool"
                        ),
                        {"call": call_id, "pool": self._policy.pool_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            report = _REPORT.validate_python(row["report"]) if row["report"] is not None else None
            return CallAudit(
                str(row["period"]),
                row["price_version"],
                row["state"],
                row["reserved_amount"],
                row["charged_amount"],
                report,
            )
