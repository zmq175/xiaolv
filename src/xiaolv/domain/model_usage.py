"""Provider-reported usage and content-free model call audit facts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int | None = None


@dataclass(frozen=True)
class ModelCallReport:
    call_id: str
    model: str
    started_at: datetime
    finished_at: datetime
    status: Literal["completed", "failed", "cancelled"]
    usage: TokenUsage | None
