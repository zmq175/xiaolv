"""Native delivery boundary for deterministic replay."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from xiaolv.domain.conversation.reply_validity import evaluate_reply_validity

DeliveryStatus = Literal["confirmed", "unknown", "expired", "superseded", "not_sent"]


@dataclass(frozen=True)
class DeliveryRequest:
    outgoing_id: str
    conversation_id: str
    expires_at: datetime
    generation_epoch: int
    text: str


class NotSent(Exception):
    """The adapter can prove the remote platform did not accept this request."""


class PlatformSender(Protocol):
    async def send(self, request: DeliveryRequest) -> Literal["confirmed", "unknown"]: ...


class DeliveryService:
    def __init__(
        self,
        platform: PlatformSender,
        clock: Callable[[], datetime],
        current_epoch: Callable[[str], int],
    ) -> None:
        self._lock = asyncio.Lock()
        self._requests: dict[str, DeliveryRequest] = {}
        self._results: dict[str, DeliveryStatus] = {}
        self._platform = platform
        self._clock = clock
        self._current_epoch = current_epoch

    async def deliver(self, request: DeliveryRequest) -> DeliveryStatus:
        async with self._lock:
            previous = self._requests.get(request.outgoing_id)
            if previous is not None and previous != request:
                raise ValueError("outgoing_id payload conflict")
            self._requests[request.outgoing_id] = request
            if request.outgoing_id in self._results:
                return self._results[request.outgoing_id]
            decision = evaluate_reply_validity(
                request.expires_at,
                request.generation_epoch,
                self._current_epoch(request.conversation_id),
                self._clock(),
            )
            if decision.reason == "expired":
                self._results[request.outgoing_id] = "expired"
                return "expired"
            if decision.reason == "superseded":
                self._results[request.outgoing_id] = "superseded"
                return "superseded"
            result: DeliveryStatus
            try:
                result = await self._platform.send(request)
            except asyncio.CancelledError:
                self._results[request.outgoing_id] = "unknown"
                raise
            except NotSent:
                result = "not_sent"
            except Exception:  # noqa: BLE001 - after send starts any failure may hide acceptance
                result = "unknown"
            self._results[request.outgoing_id] = result
            return result

    def status(self, outgoing_id: str) -> DeliveryStatus | None:
        return self._results.get(outgoing_id)
