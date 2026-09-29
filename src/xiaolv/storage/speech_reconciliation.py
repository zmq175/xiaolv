"""Administrator-attested cost settlement; never synthesizes or delivers messages."""

import hashlib
import json
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from xiaolv.domain.speech import validate_amount
from xiaolv.storage.postgres_speech import _lock
from xiaolv.storage.profile_publication import PublicationError


class SpeechReconciliation:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list(self, limit: int, after: str) -> dict[str, Any]:
        async with self._engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text("""
                SELECT s.call_id, s.conversation_id, s.provider_id, s.model, s.price_version,
                       s.voice_binding_version, s.period, s.reserved_amount, s.charged_amount,
                       s.state, s.outcome, s.expires_at, r.evidence, r.created_at AS reconciled_at
                FROM app.speech_calls s LEFT JOIN admin.speech_reconciliations r USING(call_id)
                WHERE s.call_id > :after ORDER BY s.call_id LIMIT :limit
            """),
                        {"after": after, "limit": limit + 1},
                    )
                )
                .mappings()
                .all()
            )
            items = []
            for row in rows[:limit]:
                item = dict(row)
                item["reserved_cny"] = str(item.pop("reserved_amount"))
                charge = item.pop("charged_amount")
                item["charged_cny"] = str(charge) if charge is not None else None
                for key in ("period", "expires_at", "reconciled_at"):
                    item[key] = item[key].isoformat() if item[key] is not None else None
                items.append(item)
            return {
                "items": items,
                "next_after": rows[limit - 1]["call_id"] if len(rows) > limit else None,
            }

    async def reconcile(
        self, call_id: str, amount: Decimal, evidence: str, key: str, actor: str
    ) -> dict[str, Any]:
        validate_amount(amount)
        normalized = format(amount, ".6f")
        fingerprint = hashlib.sha256(json.dumps([normalized, evidence]).encode()).hexdigest()
        async with self._engine.begin() as connection:
            await _lock(connection, call_id)
            previous = (
                (
                    await connection.execute(
                        text("SELECT * FROM admin.speech_reconciliations WHERE call_id = :id"),
                        {"id": call_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if previous is not None:
                if previous["idempotency_key"] != key or previous["request_hash"] != fingerprint:
                    raise PublicationError("speech_already_reconciled")
                return dict(previous["response"])
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT *, expires_at <= clock_timestamp() AS expired FROM app.speech_calls WHERE call_id = :id"
                        ),
                        {"id": call_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise PublicationError("speech_call_not_found", 404)
            if row["charged_amount"] is not None:
                raise PublicationError("speech_cost_already_known")
            if row["outcome"] is None and not row["expired"]:
                raise PublicationError("speech_call_active")
            await connection.execute(
                text("""
                UPDATE app.budget_periods SET reserved = reserved - :reserved, spent = spent + :amount,
                    blocked = blocked OR spent + reserved - :reserved + :amount > limit_amount
                WHERE pool_id = :pool AND period = :period
            """),
                {
                    "pool": row["pool_id"],
                    "period": row["period"],
                    "reserved": row["reserved_amount"],
                    "amount": amount,
                },
            )
            await connection.execute(
                text("""
                UPDATE app.speech_calls SET charged_amount = :amount,
                    outcome = COALESCE(outcome, 'voice_unknown'),
                    state = CASE WHEN outcome IS NULL THEN 'unknown' ELSE state END
                WHERE call_id = :id
            """),
                {"id": call_id, "amount": amount},
            )
            response = {
                "call_id": call_id,
                "charged_cny": normalized,
                "evidence": evidence,
                "reconciled": True,
            }
            await connection.execute(
                text("""
                INSERT INTO admin.speech_reconciliations(call_id, idempotency_key, request_hash,
                    charged_amount, evidence, actor, response)
                VALUES (:id, :key, :hash, :amount, :evidence, :actor, CAST(:response AS jsonb))
            """),
                {
                    "id": call_id,
                    "key": key,
                    "hash": fingerprint,
                    "amount": amount,
                    "evidence": evidence,
                    "actor": actor,
                    "response": json.dumps(response),
                },
            )
            return response
