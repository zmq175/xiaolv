"""Native delivery through a swappable state ledger."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from opentelemetry import trace

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
        prepare: Callable[[DeliveryRequest], Awaitable[PlatformSender]] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._platform = platform
        self._prepare = prepare
        self._serial: asyncio.Lock | None = None
        if ledger is None:
            if clock is None or current_epoch is None:
                raise ValueError("replay requires clock and current_epoch")
            ledger = MemoryDeliveryLedger(clock, current_epoch)
            self._serial = asyncio.Lock()
        self._ledger = ledger

    async def deliver(self, request: DeliveryRequest) -> DeliveryStatus:
        with trace.get_tracer(__name__).start_as_current_span(
            "delivery", record_exception=False, set_status_on_exception=False
        ):
            try:
                if self._serial is not None:
                    async with self._serial:
                        result = await self._deliver(request)
                else:
                    result = await self._deliver(request)
            except asyncio.CancelledError:
                logging.getLogger(__name__).warning(
                    "发送任务取消，请核对持久发送状态",
                    extra={"event": "send_cancelled"},
                )
                raise
            logging.getLogger(__name__).log(
                logging.WARNING if result == "unknown" else logging.INFO,
                "发送状态已确认" if result != "unknown" else "发送结果未知，不自动重发",
                extra={
                    "event": "send_unknown" if result == "unknown" else "outbox_transition",
                    "fields": {"status": result},
                },
            )
            return result

    async def _deliver(self, request: DeliveryRequest) -> DeliveryStatus:
        platform = self._platform
        preparation_failed = False
        if self._prepare is not None and await self._ledger.status(request.outgoing_id) is None:
            remaining = (
                request.expires_at.astimezone(UTC) - self._clock().astimezone(UTC)
            ).total_seconds()
            if remaining > 0:
                try:
                    async with asyncio.timeout(min(5, remaining)):
                        platform = await self._prepare(request)
                except Exception:  # noqa: BLE001 - preparation is strictly read-only
                    preparation_failed = True
            else:
                preparation_failed = True
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
        if preparation_failed:
            return await self._ledger.finish(request.outgoing_id, claim.token, "not_sent")
        result: DeliveryStatus
        try:
            async with asyncio.timeout(min(10, remaining)):
                result = await platform.send(request)
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
