"""Text intent with server-resolved account references."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TextReply:
    text: str
    mentions: tuple[str, ...] = ()
    reply_to: str | None = None
