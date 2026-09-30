"""Credit accounting is separate from model currency and token accounting."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol


class WebCredits(Protocol):
    async def reserve(
        self, call_id: str, operation: Literal["search", "extract"], expires_at: datetime
    ) -> None: ...

    async def settle(self, call_id: str, charged: Decimal | None) -> None: ...
