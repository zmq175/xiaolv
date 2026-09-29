"""Platform-neutral delivery contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

DeliveryStatus = Literal["confirmed", "unknown", "expired", "superseded", "not_sent", "sending"]


@dataclass(frozen=True)
class DeliveryRequest:
    outgoing_id: str
    conversation_id: str
    expires_at: datetime
    generation_epoch: int
    text: str


@dataclass(frozen=True)
class DeliveryClaim:
    status: DeliveryStatus | None
    token: str | None = None


class NotSent(Exception):
    """The adapter can prove the platform did not accept the request."""


class PlatformSender(Protocol):
    async def send(self, request: DeliveryRequest) -> Literal["confirmed", "unknown"]: ...


class DeliveryLedger(Protocol):
    async def claim(self, request: DeliveryRequest) -> DeliveryClaim: ...

    async def finish(
        self, outgoing_id: str, token: str, status: DeliveryStatus
    ) -> DeliveryStatus: ...

    async def status(self, outgoing_id: str) -> DeliveryStatus | None: ...

    async def start_turn(self, conversation_id: str) -> int: ...

    async def recover(self) -> int: ...
