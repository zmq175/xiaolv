"""Reply validity at a caller-supplied instant."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


@dataclass(frozen=True)
class ValidityDecision:
    allowed: bool
    reason: Literal["valid", "expired", "superseded"]


def evaluate_reply_validity(
    expires_at: datetime, generation_epoch: int, current_epoch: int, now: datetime
) -> ValidityDecision:
    if expires_at.utcoffset() is None or now.utcoffset() is None:
        raise ValueError("expires_at and now must be timezone-aware")
    if now.astimezone(UTC) >= expires_at.astimezone(UTC):
        return ValidityDecision(False, "expired")
    if generation_epoch != current_epoch:
        return ValidityDecision(False, "superseded")
    return ValidityDecision(True, "valid")
