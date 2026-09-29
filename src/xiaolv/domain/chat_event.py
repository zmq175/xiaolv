"""Platform-independent incoming chat facts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class MediaInterpretation:
    kind: Literal["transcript"]
    text: str
    processor: str


@dataclass(frozen=True)
class MessagePart:
    kind: str
    text: str | None = None
    reference: str | None = None
    url: str | None = None
    interpretation: MediaInterpretation | None = None


@dataclass(frozen=True)
class ChatEvent:
    conversation_id: str
    sender_account_id: str
    message_id: str
    text: str
    display_name: str
    occurred_at: datetime
    received_at: datetime
    effective_time: datetime
    is_historical: bool = False
    clock_skew: bool = False
    parts: tuple[MessagePart, ...] = ()


@dataclass(frozen=True)
class ConversationContext:
    revision: int
    messages: tuple[ChatEvent, ...]
