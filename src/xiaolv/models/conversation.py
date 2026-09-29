"""Conversation behavior over a replaceable structured generation boundary."""

import asyncio
import json
from collections.abc import Collection, Mapping
from datetime import datetime
from importlib.resources import files
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from xiaolv.domain.bot_profile import BotProfile
from xiaolv.domain.context_policy import ContextPolicy
from xiaolv.domain.text_reply import TextPart, TextReply, validate_text_parts
from xiaolv.domain.voice_reply import VoiceReply
from xiaolv.models.context import ContextAssembler
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


class _QuoteReply(_Reply):
    reply_to: str | None


class _AddressedReply(_MentionReply, _QuoteReply):
    pass


class _Part(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    kind: Literal["text", "mention"]
    value: str


class _OrderedReply(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    parts: list[_Part] = Field(min_length=1, max_length=32)
    reply_to: str | None


class _VoiceIntent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    speech_text: str = Field(min_length=1)
    voice_profile: str = Field(min_length=1)


class _MediaReply(_OrderedReply):
    parts: list[_Part] = Field(max_length=32)
    voice: _VoiceIntent | None


class ChatCompletionsModel:
    def __init__(
        self,
        generator: StructuredGenerator,
        *,
        profile: BotProfile | None = None,
        max_reply_chars: int = 200,
        context_policy: ContextPolicy | None = None,
        mention_conversations: Collection[str] = (),
        quote_conversations: Collection[str] = (),
        ordered_conversations: Collection[str] = (),
        voice_profiles: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        if type(max_reply_chars) is not int or max_reply_chars <= 0:
            raise ValueError("invalid reply length")
        self._generator = generator
        self._assembler = ContextAssembler(context_policy or ContextPolicy())
        self._profile = profile if profile is not None else BotProfile()
        self._max_reply_chars = max_reply_chars
        self._mention_conversations = frozenset(mention_conversations)
        self._quote_conversations = frozenset(quote_conversations)
        self._ordered_conversations = frozenset(ordered_conversations)
        self._voice_profiles = dict(voice_profiles or {})

    def _instructions(self, stage: str, candidate: ConversationCandidate) -> str:
        template = files("xiaolv.prompts").joinpath(stage + ".txt").read_text(encoding="utf-8")
        rules = template.format(max_reply_chars=self._max_reply_chars)
        profile = (
            candidate.profile_snapshot.profile if candidate.profile_snapshot else self._profile
        )
        return (
            rules
            + "\n管理员配置的机器人资料（JSON）：\n"
            + json.dumps(profile.model_dump(), ensure_ascii=False)
        )

    async def decide(self, candidate: ConversationCandidate) -> Literal["respond", "silence"]:
        instructions = self._instructions("participation", candidate)
        schema = _Decision.model_json_schema()
        context = await asyncio.to_thread(
            self._assembler.assemble,
            candidate,
            instructions,
            schema,
            "participation",
            candidate.conversation_id in self._mention_conversations,
        )
        result = await self._generator.generate(
            instructions=instructions,
            context=context,
            schema=schema,
            expires_at=candidate.expires_at,
        )
        return _Decision.model_validate_json(result).action

    async def reply(self, candidate: ConversationCandidate) -> str | TextReply | VoiceReply:
        enabled = candidate.conversation_id in self._mention_conversations
        quotes = candidate.conversation_id in self._quote_conversations
        ordered = candidate.conversation_id in self._ordered_conversations
        voices = self._voice_profiles.get(candidate.conversation_id, ())
        schema_type = (
            _MediaReply
            if voices
            else _OrderedReply
            if ordered
            else _AddressedReply
            if enabled and quotes
            else _MentionReply
            if enabled
            else _QuoteReply
            if quotes
            else _Reply
        )
        instructions = self._instructions("reply", candidate)
        if voices:
            instructions += "\n" + files("xiaolv.prompts").joinpath("voice.txt").read_text(
                encoding="utf-8"
            )
            instructions += "\n允许的逻辑音色：" + json.dumps(voices, ensure_ascii=False)
        schema = schema_type.model_json_schema()
        context = await asyncio.to_thread(
            self._assembler.assemble, candidate, instructions, schema, "reply", enabled
        )
        result = await self._generator.generate(
            instructions=instructions,
            context=context,
            schema=schema,
            expires_at=candidate.expires_at,
        )
        if not enabled and not quotes and not ordered and not voices:
            return _Reply.model_validate_json(result).text
        reply = schema_type.model_validate_json(result)
        if isinstance(reply, _MediaReply) and reply.voice is not None:
            if reply.parts or reply.reply_to is not None:
                raise ValueError("voice cannot mix with text or quote")
            if reply.voice.voice_profile not in voices or not reply.voice.speech_text.strip():
                raise ValueError("voice intent is unavailable")
            if len(reply.voice.speech_text) > self._max_reply_chars:
                raise ValueError("voice text exceeds reply limit")
            return VoiceReply(reply.voice.speech_text, reply.voice.voice_profile)
        if isinstance(reply, _MediaReply) and not reply.parts:
            raise ValueError("text reply must include parts")
        visible = json.loads(context)["messages"]
        mentions: tuple[str, ...] = ()
        if isinstance(reply, _MentionReply):
            members = {item["member_ref"]: item["account"] for item in visible}
            mentions = tuple(dict.fromkeys(members[ref] for ref in reply.mentions))
        reply_to = None
        if isinstance(reply, (_QuoteReply, _OrderedReply)) and reply.reply_to is not None:
            if not quotes:
                raise ValueError("quote is unavailable in this conversation")
            available = {item["message_ref"] for item in visible}
            if reply.reply_to not in available:
                raise ValueError("quote reference is not visible")
            events = {
                f"message_{index}": item
                for index, item in enumerate(reversed(candidate.context.messages), 1)
            }
            reply_to = events[reply.reply_to].message_id
            if sum(item.message_id == reply_to for item in candidate.context.messages) != 1:
                raise ValueError("quote reference is ambiguous")
        if isinstance(reply, _OrderedReply):
            members = {item["member_ref"]: item["account"] for item in visible} if enabled else {}
            parts = tuple(
                TextPart(part.kind, members[part.value] if part.kind == "mention" else part.value)
                for part in reply.parts
            )
            body = "".join(part.value for part in parts if part.kind == "text")
            mentions = tuple(part.value for part in parts if part.kind == "mention")
            validate_text_parts(body, mentions, parts)
            return TextReply(body, mentions, reply_to, parts)
        return TextReply(reply.text, mentions, reply_to)
