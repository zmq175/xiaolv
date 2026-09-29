"""Native delivery through a swappable state ledger."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from xiaolv.application.delivery_contracts import (
    DeliveryLedger,
    DeliveryRequest,
    DeliveryStatus,
    NotSent,
    PlatformSender,
)
from xiaolv.application.memory_delivery import MemoryDeliveryLedger

__all__ = ["DeliveryRequest", "DeliveryService", "DeliveryStatus", "NotSent", "PlatformSender"]


class DeliveryService:
    def __init__(
        self,
        platform: PlatformSender,
        clock: Callable[[], datetime] | None = None,
        current_epoch: Callable[[str], int] | None = None,
        *,
        ledger: DeliveryLedger | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._platform = platform
        self._serial: asyncio.Lock | None = None
        if ledger is None:
            if clock is None or current_epoch is None:
                raise ValueError("replay requires clock and current_epoch")
            ledger = MemoryDeliveryLedger(clock, current_epoch)
            self._serial = asyncio.Lock()
        self._ledger = ledger

    async def deliver(self, request: DeliveryRequest) -> DeliveryStatus:
        if self._serial is not None:
            async with self._serial:
                return await self._deliver(request)
        return await self._deliver(request)

    async def _deliver(self, request: DeliveryRequest) -> DeliveryStatus:
        claim = await self._ledger.claim(request)
        if claim.status is not None:
            return claim.status
        if claim.token is None:
            raise RuntimeError("ledger did not issue a send token")
        remaining = (
            request.expires_at.astimezone(UTC) - self._clock().astimezone(UTC)
        ).total_seconds()
        if remaining <= 0:
            return await self._ledger.finish(request.outgoing_id, claim.token, "expired")
        result: DeliveryStatus
        try:
            async with asyncio.timeout(min(10, remaining)):
                result = await self._platform.send(request)
        except asyncio.CancelledError:
            await asyncio.shield(self._ledger.finish(request.outgoing_id, claim.token, "unknown"))
            raise
        except NotSent:
            result = "not_sent"
        except Exception:  # noqa: BLE001 - platform may have accepted before failure
            result = "unknown"
        return await self._ledger.finish(request.outgoing_id, claim.token, result)

    async def status(self, outgoing_id: str) -> DeliveryStatus | None:
        return await self._ledger.status(outgoing_id)

    async def start_turn(self, conversation_id: str) -> int:
        return await self._ledger.start_turn(conversation_id)

    async def recover(self) -> int:
        return await self._ledger.recover()
