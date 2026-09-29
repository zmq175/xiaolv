"""Conversation behavior over a replaceable structured generation boundary."""

import json
from collections.abc import Collection
from datetime import datetime
from importlib.resources import files
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from xiaolv.domain.bot_profile import BotProfile
from xiaolv.domain.text_reply import TextReply
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


class _MentionReply(_Reply):
    mentions: list[str]


class ChatCompletionsModel:
    def __init__(
        self,
        generator: StructuredGenerator,
        *,
        profile: BotProfile | None = None,
        max_reply_chars: int = 200,
        mention_conversations: Collection[str] = (),
    ) -> None:
        if type(max_reply_chars) is not int or max_reply_chars <= 0:
            raise ValueError("invalid reply length")
        self._generator = generator
        self._profile = profile if profile is not None else BotProfile()
        self._max_reply_chars = max_reply_chars
        self._mention_conversations = frozenset(mention_conversations)

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

    async def reply(self, candidate: ConversationCandidate) -> str | TextReply:
        context = self._context(candidate)
        enabled = candidate.conversation_id in self._mention_conversations
        result = await self._generator.generate(
            instructions=self._instructions("reply"),
            context=context,
            schema=(_MentionReply if enabled else _Reply).model_json_schema(),
            expires_at=candidate.expires_at,
        )
        if not enabled:
            return _Reply.model_validate_json(result).text
        reply = _MentionReply.model_validate_json(result)
        members = {item["member_ref"]: item["account"] for item in json.loads(context)["messages"]}
        return TextReply(reply.text, tuple(dict.fromkeys(members[ref] for ref in reply.mentions)))

    def _context(self, candidate: ConversationCandidate) -> str:
        if any(
            item.conversation_id != candidate.conversation_id for item in candidate.context.messages
        ):
            raise ValueError("conversation context scope mismatch")
        messages: list[dict[str, object]] = []
        events = {
            f"message_{index}": item
            for index, item in enumerate(reversed(candidate.context.messages[-30:]), 1)
        }
        payload = {
            "target_text": candidate.text[:1000],
            "target_truncated": len(candidate.text) > 1000,
            "messages": messages,
        }
        for index, item in enumerate(reversed(candidate.context.messages[-30:]), 1):
            messages.insert(
                0,
                {
                    "message_ref": f"message_{index}",
                    "account": item.sender_account_id,
                    "name": item.display_name[:128],
                    "text": item.text[:1000],
                    "truncated": len(item.text) > 1000,
                },
            )
            if candidate.conversation_id in self._mention_conversations:
                messages[0]["member_ref"] = f"member_{index}"
            if len(json.dumps(payload, ensure_ascii=False)) > 12000:
                messages.pop(0)
                break
        counts: dict[str, int] = {}
        for event in candidate.context.messages:
            counts[event.message_id] = counts.get(event.message_id, 0) + 1
        while True:
            by_id = {
                events[str(row["message_ref"])].message_id: row["message_ref"] for row in messages
            }
            for row in messages:
                row["replies"] = [
                    {
                        "status": (
                            "ambiguous"
                            if counts.get(part.reference or "", 0) > 1
                            else "resolved"
                            if part.reference in by_id
                            else "missing"
                        ),
                        "target_ref": (
                            by_id.get(part.reference or "")
                            if counts.get(part.reference or "", 0) == 1
                            else None
                        ),
                    }
                    for part in events[str(row["message_ref"])].parts
                    if part.kind == "reply"
                ]
            serialized = json.dumps(payload, ensure_ascii=False)
            if len(serialized) <= 12000 or not messages:
                return serialized
            messages.pop(0)
