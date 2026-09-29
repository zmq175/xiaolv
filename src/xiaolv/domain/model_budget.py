"""Model budget policy and preflight intent."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from xiaolv.domain.model_usage import ModelCallReport


@dataclass(frozen=True)
class ModelCallIntent:
    call_id: str
    model: str
    started_at: datetime
    max_input_tokens: int
    max_output_tokens: int


@dataclass(frozen=True)
class BudgetPolicy:
    pool_id: str
    provider_id: str
    model: str
    price_version: str
    monthly_limit: Decimal
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal | None = None

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.pool_id, self.provider_id, self.model, self.price_version)
        ):
            raise ValueError("invalid budget policy identifiers")
        amounts = [self.monthly_limit, self.input_per_million, self.output_per_million]
        if self.cached_input_per_million is not None:
            amounts.append(self.cached_input_per_million)
        for amount in amounts:
            if (
                not isinstance(amount, Decimal)
                or not amount.is_finite()
                or not Decimal(0) <= amount < Decimal(100000000000000)
                or amount != amount.quantize(Decimal("0.000001"))
            ):
                raise ValueError("invalid budget policy amount")
        if (
            self.cached_input_per_million is not None
            and self.cached_input_per_million > self.input_per_million
        ):
            raise ValueError("invalid budget policy cached price")


class BudgetDenied(Exception):
    """No paid request may start."""


class ModelBudget(Protocol):
    async def reserve(self, intent: ModelCallIntent) -> None: ...

    async def settle(self, report: ModelCallReport) -> None: ...


@dataclass(frozen=True)
class BudgetSnapshot:
    period: str
    limit: Decimal
    reserved: Decimal
    spent: Decimal
    blocked: bool


@dataclass(frozen=True)
class CallAudit:
    period: str
    price_version: str
    state: str
    reserved_amount: Decimal
    charged_amount: Decimal | None
    report: ModelCallReport | None
