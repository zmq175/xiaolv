"""Transient search evidence and native model tool requests."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class NativeToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class NativeToolTurn:
    calls: tuple[NativeToolCall, ...]


class ToolUnavailable(Exception):
    """Tool processing stopped without publishing an answer."""
