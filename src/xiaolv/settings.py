"""Validated startup settings."""

from collections.abc import Mapping
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator


class ConfigError(ValueError):
    """Invalid startup configuration; messages contain field names only."""


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    mode: Literal["replay", "live"] = "replay"
    database_url: SecretStr | None = None
    model_base_url: str | None = None
    model_api_key: SecretStr | None = None
    model_id: str | None = None
    onebot_url: str | None = None
    onebot_token: SecretStr | None = None
    chat_ttl_seconds: float = Field(default=45, gt=0, allow_inf_nan=False)
    queue_max_age_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)
    model_concurrency: int = Field(default=2, gt=0)
    max_reply_chars: int = Field(default=200, gt=0)

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        if self.queue_max_age_seconds > self.chat_ttl_seconds:
            raise ValueError("queue_max_age_seconds exceeds chat_ttl_seconds")
        if self.mode == "live":
            for name in (
                "database_url",
                "model_base_url",
                "model_api_key",
                "model_id",
                "onebot_url",
                "onebot_token",
            ):
                value = getattr(self, name)
                if isinstance(value, SecretStr):
                    value = value.get_secret_value()
                if not value or not value.strip():
                    raise ValueError(f"missing {name}")
        for name, schemes in (
            ("database_url", {"postgresql+psycopg"}),
            ("model_base_url", {"http", "https"}),
            ("onebot_url", {"ws", "wss"}),
        ):
            value = getattr(self, name)
            if value is None:
                continue
            raw = value.get_secret_value() if isinstance(value, SecretStr) else value
            parsed = urlsplit(raw)
            if parsed.scheme not in schemes or any(char.isspace() for char in raw):
                raise ValueError(f"invalid {name}")
            if name == "database_url":
                if not parsed.path.strip("/"):
                    raise ValueError("missing database name")
            elif (
                not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"invalid {name}")
        return self


def load_settings(environ: Mapping[str, str]) -> Settings:
    values = {
        key.removeprefix("XIAOLV_").lower(): value
        for key, value in environ.items()
        if key.startswith("XIAOLV_")
    }
    try:
        return Settings.model_validate(values)
    except ValidationError as error:
        fields = sorted({".".join(map(str, item["loc"])) or "runtime" for item in error.errors()})
        raise ConfigError("invalid configuration: " + ", ".join(fields)) from None
