"""Speech call ownership and shared monetary pool; never stores spoken text."""

import hashlib
import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from xiaolv.domain.speech import SpeechPolicy, SpeechRequest, validate_amount


async def _lock(connection: AsyncConnection, call_id: str) -> None:
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 13))"), {"id": call_id}
    )


class PostgresSpeechLedger:
    def __init__(self, engine: AsyncEngine, policy: SpeechPolicy) -> None:
        self._engine, self._policy = engine, policy

    async def reserve(self, request: SpeechRequest) -> str | None:
        policy = self._policy
        fingerprint = hashlib.sha256(
            json.dumps(
                {"request": asdict(request), "policy": asdict(policy)}, default=str, sort_keys=True
            ).encode()
        ).hexdigest()
        async with self._engine.begin() as connection:
            await _lock(connection, request.call_id)
            previous = (
                (
                    await connection.execute(
                        text(
                            "SELECT *, expires_at <= clock_timestamp() AS expired FROM app.speech_calls WHERE call_id = :id"
                        ),
                        {"id": request.call_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous is not None:
                if previous["request_hash"] != fingerprint:
                    return "voice_conflict"
                if previous["outcome"] is not None:
                    return str(previous["outcome"])
                if previous["expired"]:
                    await connection.execute(
                        text(
                            "UPDATE app.speech_calls SET state = 'unknown', outcome = 'voice_unknown' WHERE call_id = :id"
                        ),
                        {"id": request.call_id},
                    )
                    return "voice_unknown"
                return "voice_inflight"
            state = (
                (
                    await connection.execute(
                        text(
                            "SELECT s.epoch, c.enabled, :expires > clock_timestamp() AS valid FROM app.conversation_state s LEFT JOIN app.conversation_controls c USING(conversation_id) WHERE s.conversation_id = :conversation FOR UPDATE OF s"
                        ),
                        {"conversation": request.conversation_id, "expires": request.expires_at},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if state is None or state["enabled"] is not True:
                return "permission_denied"
            if not state["valid"]:
                return "expired"
            if state["epoch"] != request.generation_epoch:
                return "superseded"
            period: date = (
                await connection.execute(
                    text("SELECT date_trunc('month', clock_timestamp() AT TIME ZONE 'UTC')::date")
                )
            ).scalar_one()
            params = {"pool": policy.pool_id, "period": period, "limit": policy.monthly_limit}
            await connection.execute(
                text(
                    "INSERT INTO app.budget_periods(pool_id, period, limit_amount) VALUES (:pool, :period, :limit) ON CONFLICT DO NOTHING"
                ),
                params,
            )
            budget = (
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
            if (
                budget["limit_amount"] != policy.monthly_limit
                or budget["blocked"]
                or budget["reserved"] + budget["spent"] + policy.reservation_amount
                > policy.monthly_limit
            ):
                return "budget_denied"
            await connection.execute(
                text("""
                INSERT INTO app.speech_calls(call_id, request_hash, conversation_id, generation_epoch, expires_at,
                    pool_id, period, provider_id, model, price_version, voice_binding_version, reserved_amount)
                VALUES (:id, :hash, :conversation, :epoch, :expires, :pool, :period, :provider, :model, :price, :voice, :amount)
            """),
                {
                    **params,
                    "id": request.call_id,
                    "hash": fingerprint,
                    "conversation": request.conversation_id,
                    "epoch": request.generation_epoch,
                    "expires": request.expires_at,
                    "provider": policy.provider_id,
                    "model": policy.model,
                    "price": policy.price_version,
                    "voice": policy.voice_binding_version,
                    "amount": policy.reservation_amount,
                },
            )
            await connection.execute(
                text(
                    "UPDATE app.budget_periods SET reserved = reserved + :amount WHERE pool_id = :pool AND period = :period"
                ),
                {**params, "amount": policy.reservation_amount},
            )
            return None

    async def check(self, request: SpeechRequest) -> str | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT s.epoch, c.enabled, :expires > clock_timestamp() AS valid FROM app.conversation_state s LEFT JOIN app.conversation_controls c USING(conversation_id) WHERE s.conversation_id = :conversation"
                        ),
                        {"conversation": request.conversation_id, "expires": request.expires_at},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["enabled"] is not True:
                return "permission_denied"
            if not row["valid"]:
                return "expired"
            if row["epoch"] != request.generation_epoch:
                return "superseded"
            return None

    async def synthesized(self, call_id: str, charge: Decimal | None) -> bool:
        if charge is not None:
            validate_amount(charge)
        async with self._engine.begin() as connection:
            await _lock(connection, call_id)
            row = (
                (
                    await connection.execute(
                        text("SELECT * FROM app.speech_calls WHERE call_id = :id"), {"id": call_id}
                    )
                )
                .mappings()
                .one()
            )
            if row["state"] != "running" or row["outcome"] is not None:
                return False
            if charge is not None:
                await connection.execute(
                    text("""
                    UPDATE app.budget_periods SET reserved = reserved - :reserved, spent = spent + :charge,
                        blocked = blocked OR spent + reserved - :reserved + :charge > limit_amount
                    WHERE pool_id = :pool AND period = :period
                """),
                    {
                        "pool": row["pool_id"],
                        "period": row["period"],
                        "reserved": row["reserved_amount"],
                        "charge": charge,
                    },
                )
            await connection.execute(
                text(
                    "UPDATE app.speech_calls SET state = 'synthesized', charged_amount = :charge WHERE call_id = :id"
                ),
                {"id": call_id, "charge": charge},
            )
            return True

    async def finish(self, call_id: str, outcome: str) -> str:
        async with self._engine.begin() as connection:
            await _lock(connection, call_id)
            await connection.execute(
                text(
                    "UPDATE app.speech_calls SET state = 'finished', outcome = :outcome WHERE call_id = :id AND outcome IS NULL"
                ),
                {"id": call_id, "outcome": outcome},
            )
            value: str = (
                await connection.execute(
                    text("SELECT outcome FROM app.speech_calls WHERE call_id = :id"),
                    {"id": call_id},
                )
            ).scalar_one()
            return str(value)
