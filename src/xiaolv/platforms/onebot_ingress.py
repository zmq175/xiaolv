"""Normalize authenticated OneBot array messages without side effects."""

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from xiaolv.domain.chat_event import ChatEvent, MessagePart


class IngressError(ValueError):
    """Invalid platform event; never include raw chat content."""


class _WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)


class _Sender(_WireModel):
    nickname: str = ""
    card: str = ""
    group_id: int | None = Field(default=None, gt=0)


class _Segment(_WireModel):
    type: str
    data: dict[str, object]


class _Message(_WireModel):
    self_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    group_id: int | None = Field(default=None, gt=0)
    message_type: Literal["group", "private"]
    sub_type: str
    message_id: int
    time: int = Field(ge=0)
    message: list[_Segment]
    sender: _Sender = Field(default_factory=_Sender)


def _id(value: object, *, positive: bool = True) -> str:
    if type(value) is int or isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
        number = int(value)
        if not positive or number > 0:
            return str(number)
    raise IngressError("invalid identifier")


def _part(segment: _Segment) -> MessagePart:
    kind, data = segment.type, segment.data
    if kind == "text":
        value = data.get("text")
        if not isinstance(value, str):
            raise IngressError("invalid text segment")
        return MessagePart("text", text=value)
    if kind == "at":
        if data.get("qq") == "all":
            return MessagePart("mention_all")
        return MessagePart("mention", reference=f"qq:{_id(data.get('qq'))}")
    if kind == "reply":
        return MessagePart("reply", reference=_id(data.get("id"), positive=False))
    reference = data.get("file", data.get("id"))
    url = data.get("url")
    if reference is not None and not isinstance(reference, (str, int)):
        raise IngressError("invalid media reference")
    if url is not None and not isinstance(url, str):
        raise IngressError("invalid media URL")
    if kind == "mface" or (kind == "image" and data.get("emoji_id")):
        kind = "sticker"
    return MessagePart(
        "audio" if kind == "record" else kind,
        reference=str(reference) if reference is not None else None,
        url=url,
    )


class OneBotIngress:
    def __init__(self, self_id: int, max_age_seconds: float = 10) -> None:
        self._self_id = self_id
        self._max_age = max_age_seconds

    def receive(self, frame: Mapping[str, object], received_at: datetime) -> ChatEvent | None:
        if frame.get("post_type") != "message":
            return None
        try:
            if received_at.utcoffset() is None:
                raise IngressError("received_at must be timezone-aware")
            raw = _Message.model_validate(frame)
            if raw.self_id != self._self_id:
                raise IngressError("unexpected bot account")
            if raw.user_id == self._self_id:
                return None
            if raw.message_type == "group":
                if raw.group_id is None:
                    raise IngressError("missing group")
                scope = f"group:{raw.group_id}"
            elif raw.sub_type == "group":
                if raw.sender.group_id is None:
                    raise IngressError("missing temporary session origin")
                scope = f"temporary:{raw.sender.group_id}:{raw.user_id}"
            elif raw.sub_type == "friend":
                scope = f"private:{raw.user_id}"
            else:
                raise IngressError("unsupported private subtype")
            parts = tuple(_part(segment) for segment in raw.message)
            occurred_at = datetime.fromtimestamp(raw.time, UTC)
            received_at = received_at.astimezone(UTC)
            age = (received_at - occurred_at).total_seconds()
            return ChatEvent(
                conversation_id=f"qq:{self._self_id}:{scope}",
                sender_account_id=f"qq:{raw.user_id}",
                message_id=str(raw.message_id),
                text="".join(part.text or "" for part in parts if part.kind == "text"),
                display_name=(raw.sender.card or raw.sender.nickname)
                if raw.message_type == "group"
                else raw.sender.nickname,
                occurred_at=occurred_at,
                received_at=received_at,
                effective_time=min(occurred_at, received_at),
                is_historical=age > self._max_age,
                clock_skew=age < 0,
                parts=parts,
            )
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            raise IngressError("invalid OneBot message") from None
