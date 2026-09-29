"""Administrator-configured conversation send limits."""

from pydantic import BaseModel, ConfigDict, Field


class DeliveryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    cooldown_seconds: float = Field(default=5, ge=0, allow_inf_nan=False)
    window_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)
    max_messages: int = Field(default=6, gt=0, strict=True)
