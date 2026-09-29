"""Validated startup settings."""

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from xiaolv.domain.bot_profile import BotProfile
from xiaolv.domain.context_policy import ContextPolicy
from xiaolv.domain.delivery_policy import DeliveryPolicy

Money = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=6, allow_inf_nan=False)]
QQId = Annotated[int, Field(strict=True, gt=0)]


class ConfigError(ValueError):
    """Invalid startup configuration; messages contain field names only."""


class SpeechSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    api_key: SecretStr
    model: str = Field(min_length=1)
    voice_binding_version: str = Field(min_length=1)
    price_version: str = Field(min_length=1)
    reservation_cny: Money
    voices: dict[str, str]
    conversations: dict[str, tuple[str, ...]]
    artifact_root: Path
    max_audio_bytes: int = Field(default=4 * 1024 * 1024, gt=0)
    max_total_bytes: int = Field(default=256 * 1024 * 1024, gt=0)
    max_duration_seconds: float = Field(default=20, gt=0, allow_inf_nan=False)
    retention_seconds: float = Field(default=86400, gt=0, allow_inf_nan=False)
    cleanup_interval_seconds: float = Field(default=600, gt=0, allow_inf_nan=False)
    concurrency: int = Field(default=1, gt=0)

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if (
            not all(
                value.strip()
                for value in (
                    self.api_key.get_secret_value(),
                    self.model,
                    self.voice_binding_version,
                    self.price_version,
                )
            )
            or self.reservation_cny <= 0
            or not self.artifact_root.is_absolute()
            or not self.voices
            or not self.conversations
            or any(not key.strip() or not value.strip() for key, value in self.voices.items())
            or any(
                not names
                or any(name not in self.voices for name in names)
                or len(names) != len(set(names))
                for names in self.conversations.values()
            )
        ):
            raise ValueError("invalid speech binding")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    speech: SpeechSettings | None = None
    native_asr_conversations: tuple[str, ...] = ()
    speech_recovery_interval_seconds: float = Field(default=30, gt=0, le=3600, allow_inf_nan=False)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_file: Path | None = None
    log_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)
    log_backup_count: int = Field(default=5, ge=1, le=100)
    bot_profile: BotProfile = Field(default_factory=BotProfile)
    context_policy: ContextPolicy = Field(default_factory=ContextPolicy)
    delivery_policy: DeliveryPolicy = Field(default_factory=DeliveryPolicy)
    mode: Literal["replay", "live"] = "replay"
    database_url: SecretStr | None = None
    model_base_url: str | None = None
    model_api_key: SecretStr | None = None
    model_id: str | None = None
    onebot_url: str | None = None
    onebot_token: SecretStr | None = None
    qq_self_id: int | None = Field(default=None, gt=0)
    enabled_group_ids: tuple[QQId, ...] = ()
    enabled_private_ids: tuple[QQId, ...] = ()
    model_provider: str | None = None
    model_price_version: str | None = None
    model_input_cny_per_million: Money | None = None
    model_output_cny_per_million: Money | None = None
    model_cached_input_cny_per_million: Money | None = None
    monthly_external_budget_cny: Money | None = None
    monthly_fixed_cost_cny: Money | None = None
    chat_ttl_seconds: float = Field(default=45, gt=0, allow_inf_nan=False)
    queue_max_age_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)
    model_concurrency: int = Field(default=2, gt=0)
    max_reply_chars: int = Field(default=200, gt=0)

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        if self.queue_max_age_seconds > self.chat_ttl_seconds:
            raise ValueError("queue_max_age_seconds exceeds chat_ttl_seconds")
        if self.native_asr_conversations:
            asr_routes = {f"qq:{self.qq_self_id}:group:{id}" for id in self.enabled_group_ids}
            asr_routes.update(
                f"qq:{self.qq_self_id}:private:{id}" for id in self.enabled_private_ids
            )
            if not set(self.native_asr_conversations).issubset(asr_routes):
                raise ValueError("invalid native ASR scope")
        if self.speech is not None:
            routes = {f"qq:{self.qq_self_id}:group:{id}" for id in self.enabled_group_ids}
            routes.update(f"qq:{self.qq_self_id}:private:{id}" for id in self.enabled_private_ids)
            if (
                self.speech.retention_seconds <= self.chat_ttl_seconds
                or not set(self.speech.conversations).issubset(routes)
                or self.monthly_external_budget_cny is None
                or self.speech.reservation_cny > self.monthly_external_budget_cny
            ):
                raise ValueError("invalid speech scope or limits")
        if self.mode == "live":
            for name in (
                "database_url",
                "model_base_url",
                "model_api_key",
                "model_id",
                "onebot_url",
                "onebot_token",
                "model_provider",
                "model_price_version",
            ):
                value = getattr(self, name)
                if isinstance(value, SecretStr):
                    value = value.get_secret_value()
                if not value or not value.strip():
                    raise ValueError(f"missing {name}")
            for name in (
                "qq_self_id",
                "model_input_cny_per_million",
                "model_output_cny_per_million",
                "monthly_external_budget_cny",
            ):
                if getattr(self, name) is None:
                    raise ValueError(f"missing {name}")
        if self.model_cached_input_cny_per_million is not None and (
            self.model_input_cny_per_million is None
            or self.model_cached_input_cny_per_million > self.model_input_cny_per_million
        ):
            raise ValueError("invalid cached input price")
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
    values: dict[str, object] = {
        key.removeprefix("XIAOLV_").lower(): value
        for key, value in environ.items()
        if key.startswith("XIAOLV_")
    }
    for name in (
        "enabled_group_ids",
        "enabled_private_ids",
        "bot_profile",
        "delivery_policy",
        "context_policy",
        "speech",
        "native_asr_conversations",
    ):
        key = "XIAOLV_" + name.upper()
        if key in environ:
            try:
                values[name] = json.loads(environ[key])
            except json.JSONDecodeError:
                raise ConfigError("invalid configuration: " + name) from None
    try:
        return Settings.model_validate(values)
    except ValidationError as error:
        fields = sorted({".".join(map(str, item["loc"])) or "runtime" for item in error.errors()})
        raise ConfigError("invalid configuration: " + ", ".join(fields)) from None
