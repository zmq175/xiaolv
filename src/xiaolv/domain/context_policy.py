"""Configured local token estimates, not a claim about provider tokenizer limits."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContextOverflow(ValueError):
    pass


class ContextPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    encoding: Literal["cl100k_base", "o200k_base"] = "cl100k_base"
    window_tokens: int = Field(default=16384, ge=1024, le=2000000)
    decision_tokens: int = Field(default=4096, ge=256)
    reply_tokens: int = Field(default=8192, ge=256)
    output_tokens: Literal[512] = 512
    safety_tokens: int = Field(default=512, ge=0)
    framing_tokens: int = Field(default=128, ge=0)
    history_messages: int = Field(default=100, ge=1, le=500)

    @model_validator(mode="after")
    def validate_capacity(self) -> Self:
        if self.window_tokens <= self.output_tokens + self.safety_tokens + self.framing_tokens:
            raise ValueError("no context capacity")
        return self

    def input_limit(self, stage: str) -> int:
        configured = self.decision_tokens if stage == "participation" else self.reply_tokens
        return min(configured, self.window_tokens - self.output_tokens - self.safety_tokens)
