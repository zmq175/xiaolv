"""Text intent with server-resolved account references."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TextPart:
    kind: Literal["text", "mention"]
    value: str


def validate_text_parts(text: str, mentions: tuple[str, ...], parts: tuple[TextPart, ...]) -> None:
    """Require one unambiguous intent for authorization, limits and rendering."""
    if not parts:
        return
    if len(parts) > 32 or any(
        part.kind not in ("text", "mention") or not isinstance(part.value, str) or not part.value
        for part in parts
    ):
        raise ValueError("invalid text parts")
    body = "".join(part.value for part in parts if part.kind == "text")
    accounts = tuple(part.value for part in parts if part.kind == "mention")
    if (
        not body.strip()
        or body != text
        or accounts != mentions
        or len(accounts) > 8
        or len(set(accounts)) != len(accounts)
    ):
        raise ValueError("inconsistent text parts")


@dataclass(frozen=True)
class TextReply:
    text: str
    mentions: tuple[str, ...] = ()
    reply_to: str | None = None
    parts: tuple[TextPart, ...] = ()
