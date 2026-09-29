"""Administrator-supplied persona, independent of platform account identity."""

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ProfileName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class BotProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    name: ProfileName = "小绿"
    aliases: tuple[ProfileName, ...] = Field(default=(), max_length=32)
    personality: str = Field(default="", max_length=2000)
    participation_style: str = Field(
        default="有合适的话题再自然参与，不强行接话。", max_length=1000
    )
    reply_style: str = Field(
        default="自然简短，贴合当前话题，不写客服式开场或长篇总结。", max_length=1000
    )


@dataclass(frozen=True)
class ProfileSnapshot:
    profile: BotProfile
    version: int | None = None
