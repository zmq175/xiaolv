"""Ephemeral ledger for local replay only."""

from collections.abc import Callable
from datetime import datetime

from xiaolv.application.delivery_contracts import DeliveryClaim, DeliveryRequest, DeliveryStatus
from xiaolv.domain.conversation.reply_validity import evaluate_reply_validity


class MemoryDeliveryLedger:
    def __init__(self, clock: Callable[[], datetime], current_epoch: Callable[[str], int]) -> None:
        self._clock = clock
        self._current_epoch = current_epoch
        self._requests: dict[str, DeliveryRequest] = {}
        self._results: dict[str, DeliveryStatus] = {}
        self._epochs: dict[str, int] = {}

    async def can_send(self, conversation_id: str) -> bool:
        return True

    async def claim(self, request: DeliveryRequest) -> DeliveryClaim:
        previous = self._requests.get(request.outgoing_id)
        if previous is not None and previous != request:
            raise ValueError("outgoing_id payload conflict")
        self._requests[request.outgoing_id] = request
        if request.outgoing_id in self._results:
            return DeliveryClaim(self._results[request.outgoing_id])
        decision = evaluate_reply_validity(
            request.expires_at,
            request.generation_epoch,
            self._epochs.get(request.conversation_id, self._current_epoch(request.conversation_id)),
            self._clock(),
        )
        if decision.reason in ("expired", "superseded"):
            self._results[request.outgoing_id] = decision.reason
            return DeliveryClaim(decision.reason)
        return DeliveryClaim(None, "local-replay")

    async def finish(self, outgoing_id: str, token: str, status: DeliveryStatus) -> DeliveryStatus:
        self._results[outgoing_id] = status
        return status

    async def status(self, outgoing_id: str) -> DeliveryStatus | None:
        return self._results.get(outgoing_id)

    async def start_turn(self, conversation_id: str) -> int:
        epoch = self._epochs.get(conversation_id, self._current_epoch(conversation_id)) + 1
        self._epochs[conversation_id] = epoch
        return epoch

    async def recover(self) -> int:
        return 0
