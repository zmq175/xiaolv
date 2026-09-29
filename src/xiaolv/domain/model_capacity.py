"""Shared admission contract for model calls."""

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol


class ModelCapacity(Protocol):
    def hold(self, call_id: str, expires_at: datetime) -> AbstractAsyncContextManager[None]: ...
