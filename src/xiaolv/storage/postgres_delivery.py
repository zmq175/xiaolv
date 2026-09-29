"""PostgreSQL delivery ledger; short transactions, no platform IO."""

import json
from dataclasses import asdict
from datetime import datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from xiaolv.application.delivery_contracts import DeliveryClaim, DeliveryRequest, DeliveryStatus
from xiaolv.domain.conversation.reply_validity import evaluate_reply_validity


class PostgresDeliveryLedger:
    def __init__(self, engine: AsyncEngine, lease_seconds: float = 15) -> None:
        self._engine = engine
        self._lease_seconds = lease_seconds

    async def start_turn(self, conversation_id: str) -> int:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text("""
                INSERT INTO app.conversation_state (conversation_id, epoch) VALUES (:id, 1)
                ON CONFLICT (conversation_id) DO UPDATE
                SET epoch = app.conversation_state.epoch + 1 RETURNING epoch
            """),
                {"id": conversation_id},
            )
            return int(result.scalar_one())

    async def claim(self, request: DeliveryRequest) -> DeliveryClaim:
        async with self._engine.begin() as connection:
            epoch_result = await connection.execute(
                text(
                    "SELECT epoch FROM app.conversation_state WHERE conversation_id = :id FOR UPDATE"
                ),
                {"id": request.conversation_id},
            )
            current_epoch = int(epoch_result.scalar_one())
            previous = await connection.execute(
                text("SELECT * FROM app.outbox WHERE outgoing_id = :id"),
                {"id": request.outgoing_id},
            )
            row = previous.mappings().one_or_none()
            if row is not None:
                stored = DeliveryRequest(
                    row["outgoing_id"],
                    row["conversation_id"],
                    row["expires_at"],
                    row["generation_epoch"],
                    row["body"],
                    tuple(row["mentions"]),
                    row["reply_to"],
                )
                if stored != request:
                    raise ValueError("outgoing_id payload conflict")
                return DeliveryClaim(cast(DeliveryStatus, row["status"]))
            now: datetime = (
                await connection.execute(text("SELECT clock_timestamp()"))
            ).scalar_one()
            decision = evaluate_reply_validity(
                request.expires_at, request.generation_epoch, current_epoch, now
            )
            terminal: DeliveryStatus | None = None
            if decision.reason in ("expired", "superseded"):
                terminal = decision.reason
            token = uuid4().hex
            await connection.execute(
                text("""
                INSERT INTO app.outbox (outgoing_id, conversation_id, expires_at,
                    generation_epoch, body, mentions, reply_to, status, attempt_token, lease_until)
                VALUES (:outgoing_id, :conversation_id, :expires_at, :generation_epoch,
                    :text, CAST(:mentions_json AS jsonb), :reply_to, :status, :token, clock_timestamp() + :lease * interval '1 second')
            """),
                {
                    **asdict(request),
                    "mentions_json": json.dumps(request.mentions),
                    "token": token,
                    "lease": self._lease_seconds,
                    "status": terminal or "sending",
                },
            )
            return DeliveryClaim(terminal, token if terminal is None else None)

    async def finish(self, outgoing_id: str, token: str, status: DeliveryStatus) -> DeliveryStatus:
        async with self._engine.begin() as connection:
            await connection.execute(
                text("""
                UPDATE app.outbox SET status = :status
                WHERE outgoing_id = :id AND attempt_token = :token AND status = 'sending'
            """),
                {"id": outgoing_id, "token": token, "status": status},
            )
            actual = await connection.execute(
                text("SELECT status FROM app.outbox WHERE outgoing_id = :id"), {"id": outgoing_id}
            )
            return cast(DeliveryStatus, actual.scalar_one())

    async def status(self, outgoing_id: str) -> DeliveryStatus | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text("SELECT status FROM app.outbox WHERE outgoing_id = :id"), {"id": outgoing_id}
            )
            return cast(DeliveryStatus | None, result.scalar_one_or_none())

    async def recover(self) -> int:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text("""
                UPDATE app.outbox SET status = 'unknown'
                WHERE status = 'sending' AND lease_until <= clock_timestamp()
                RETURNING outgoing_id
            """)
            )
            return len(result.all())
