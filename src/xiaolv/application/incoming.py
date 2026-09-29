"""Authenticated events into a durable, scoped inbox."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from xiaolv.domain.chat_event import ChatEvent, ConversationContext


class EventNormalizer(Protocol):
    def receive(self, frame: Mapping[str, object], received_at: datetime) -> ChatEvent | None: ...


class InboxStore(Protocol):
    async def accept(self, event: ChatEvent) -> bool: ...

    async def context(self, conversation_id: str, limit: int) -> ConversationContext: ...


@dataclass(frozen=True)
class IncomingResult:
    status: Literal["stored", "duplicate", "ignored"]
    event: ChatEvent | None


class IncomingMessages:
    def __init__(
        self, ingress: EventNormalizer, store: InboxStore, clock: Callable[[], datetime]
    ) -> None:
        self._ingress = ingress
        self._store = store
        self._clock = clock

    async def receive(self, frame: Mapping[str, object]) -> IncomingResult:
        event = self._ingress.receive(frame, self._clock())
        if event is None:
            return IncomingResult("ignored", None)
        stored = await self._store.accept(event)
        return IncomingResult("stored" if stored else "duplicate", event)

    async def recent(self, conversation_id: str, limit: int = 30) -> tuple[ChatEvent, ...]:
        return (await self.context(conversation_id, limit)).messages

    async def context(self, conversation_id: str, limit: int = 30) -> ConversationContext:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer between 1 and 200")
        return await self._store.context(conversation_id, limit)
