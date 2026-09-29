"""Conversation behavior over a replaceable structured generation boundary."""

import json
from datetime import datetime
from importlib.resources import files
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from xiaolv.domain.bot_profile import BotProfile
from xiaolv.orchestration.text_runtime import ConversationCandidate


class StructuredGenerator(Protocol):
    async def generate(
        self, *, instructions: str, context: str, schema: dict[str, Any], expires_at: datetime
    ) -> str: ...


class _Decision(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    action: Literal["respond", "silence"]


class _Reply(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    text: str


class ChatCompletionsModel:
    def __init__(
        self,
        generator: StructuredGenerator,
        *,
        profile: BotProfile | None = None,
        max_reply_chars: int = 200,
    ) -> None:
        if type(max_reply_chars) is not int or max_reply_chars <= 0:
            raise ValueError("invalid reply length")
        self._generator = generator
        self._profile = profile if profile is not None else BotProfile()
        self._max_reply_chars = max_reply_chars

    def _instructions(self, stage: str) -> str:
        template = files("xiaolv.prompts").joinpath(stage + ".txt").read_text(encoding="utf-8")
        rules = template.format(max_reply_chars=self._max_reply_chars)
        return (
            rules
            + "\n管理员配置的机器人资料（JSON）：\n"
            + json.dumps(self._profile.model_dump(), ensure_ascii=False)
        )

    async def decide(self, candidate: ConversationCandidate) -> Literal["respond", "silence"]:
        result = await self._generator.generate(
            instructions=self._instructions("participation"),
            context=self._context(candidate),
            schema=_Decision.model_json_schema(),
            expires_at=candidate.expires_at,
        )
        return _Decision.model_validate_json(result).action

    async def reply(self, candidate: ConversationCandidate) -> str:
        result = await self._generator.generate(
            instructions=self._instructions("reply"),
            context=self._context(candidate),
            schema=_Reply.model_json_schema(),
            expires_at=candidate.expires_at,
        )
        return _Reply.model_validate_json(result).text

    @staticmethod
    def _context(candidate: ConversationCandidate) -> str:
        if any(
            item.conversation_id != candidate.conversation_id for item in candidate.context.messages
        ):
            raise ValueError("conversation context scope mismatch")
        messages: list[dict[str, object]] = []
        payload = {
            "target_text": candidate.text[:1000],
            "target_truncated": len(candidate.text) > 1000,
            "messages": messages,
        }
        for item in reversed(candidate.context.messages[-30:]):
            messages.insert(
                0,
                {
                    "account": item.sender_account_id[:128],
                    "name": item.display_name[:128],
                    "text": item.text[:1000],
                    "truncated": len(item.text) > 1000,
                },
            )
            if len(json.dumps(payload, ensure_ascii=False)) > 12000:
                messages.pop(0)
                break
        return json.dumps(payload, ensure_ascii=False)
