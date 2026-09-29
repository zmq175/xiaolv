"""Provider-neutral synthesis requests and conservative monetary reservations."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol


def validate_amount(amount: Decimal) -> None:
    if (
        not isinstance(amount, Decimal)
        or not amount.is_finite()
        or not Decimal(0) <= amount < Decimal(100000000000000)
        or amount != amount.quantize(Decimal("0.000001"))
    ):
        raise ValueError("invalid speech amount")


@dataclass(frozen=True)
class SpeechPolicy:
    pool_id: str
    provider_id: str
    model: str
    price_version: str
    voice_binding_version: str
    monthly_limit: Decimal
    reservation_amount: Decimal

    def __post_init__(self) -> None:
        for value in (
            self.pool_id,
            self.provider_id,
            self.model,
            self.price_version,
            self.voice_binding_version,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("invalid speech policy")
        validate_amount(self.monthly_limit)
        validate_amount(self.reservation_amount)


@dataclass(frozen=True)
class SpeechRequest:
    call_id: str
    conversation_id: str
    generation_epoch: int
    expires_at: datetime
    speech_text: str
    voice_profile: str


@dataclass(frozen=True)
class SpeechResult:
    audio: bytes
    charged_amount: Decimal | None = None


class SpeechSynthesizer(Protocol):
    async def synthesize(self, request: SpeechRequest) -> SpeechResult: ...


class SpeechLedger(Protocol):
    async def reserve(self, request: SpeechRequest) -> str | None: ...
    async def check(self, request: SpeechRequest) -> str | None: ...
    async def synthesized(self, call_id: str, charge: Decimal | None) -> bool: ...
    async def finish(self, call_id: str, outcome: str) -> str: ...
