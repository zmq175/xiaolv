"""Turn-local speech evidence; platform and third-party transcribers share this boundary."""

from collections.abc import Collection
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from xiaolv.domain.authorization import PermissionDenied
from xiaolv.domain.chat_event import ChatEvent, MediaInterpretation
from xiaolv.domain.model_budget import BudgetDenied

if TYPE_CHECKING:
    from xiaolv.orchestration.text_runtime import ConversationCandidate


class MediaUnavailable(Exception):
    """Media could not be interpreted; never carry platform/provider response bodies."""


class SpeechTranscriber(Protocol):
    async def transcribe(
        self, event: ChatEvent, part_index: int, expires_at: datetime
    ) -> MediaInterpretation: ...


class InboundSpeech:
    def __init__(self, transcriber: SpeechTranscriber, conversations: Collection[str]) -> None:
        self._transcriber = transcriber
        self._conversations = frozenset(conversations)

    async def enrich(self, candidate: "ConversationCandidate") -> "ConversationCandidate":
        if candidate.conversation_id not in self._conversations:
            return candidate
        messages = list(candidate.context.messages)
        if sum(event.message_id == candidate.source_message_id for event in messages) > 1:
            raise MediaUnavailable()
        for index, event in enumerate(messages):
            if event.message_id != candidate.source_message_id:
                continue
            audio = [i for i, part in enumerate(event.parts) if part.kind == "audio"]
            if not audio:
                continue
            if len(audio) != 1 or event.conversation_id != candidate.conversation_id:
                raise MediaUnavailable()
            part_index = audio[0]
            try:
                interpretation = await self._transcriber.transcribe(
                    event, part_index, candidate.expires_at
                )
            except (PermissionDenied, BudgetDenied):
                raise
            except Exception:  # noqa: BLE001 - never include provider errors in model or logs
                raise MediaUnavailable() from None
            if not interpretation.text.strip() or len(interpretation.text) > 3000:
                raise MediaUnavailable()
            parts = list(event.parts)
            parts[part_index] = replace(parts[part_index], interpretation=interpretation)
            messages[index] = replace(event, parts=tuple(parts))
        return replace(candidate, context=replace(candidate.context, messages=tuple(messages)))
