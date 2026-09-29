"""Bounded deadline audit; preserves all monetary reservations and delivery receipts."""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def recover_speech_calls(engine: AsyncEngine) -> int:
    async with engine.begin() as connection:
        ids: Sequence[str] = (
            (
                await connection.execute(
                    text("""
            SELECT call_id FROM app.speech_calls
            WHERE outcome IS NULL AND expires_at <= clock_timestamp()
            ORDER BY expires_at, call_id LIMIT 100 FOR UPDATE SKIP LOCKED
        """)
                )
            )
            .scalars()
            .all()
        )
        recovered = 0
        for call_id in ids:
            # Nonblocking acquisition avoids reversing the normal call-lock/row-lock wait order.
            owned: bool = (
                await connection.execute(
                    text("SELECT pg_try_advisory_xact_lock(hashtextextended(:id, 13))"),
                    {"id": call_id},
                )
            ).scalar_one()
            if not owned:
                continue
            row = await connection.execute(
                text("""
                UPDATE app.speech_calls SET state = 'unknown', outcome = 'voice_unknown'
                WHERE call_id = :id AND outcome IS NULL AND expires_at <= clock_timestamp()
                RETURNING call_id
            """),
                {"id": call_id},
            )
            if row.scalar_one_or_none() is not None:
                recovered += 1
        return recovered
