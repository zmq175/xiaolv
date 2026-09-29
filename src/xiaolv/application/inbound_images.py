"""On-demand image interpretation within the original conversational turn."""

from collections.abc import Awaitable, Callable, Collection
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from xiaolv.application.inbound_speech import InterpretationStore, MediaUnavailable
from xiaolv.domain.authorization import PermissionDenied
from xiaolv.domain.chat_event import ChatEvent, MediaInterpretation
from xiaolv.domain.model_budget import BudgetDenied

if TYPE_CHECKING:
    from xiaolv.orchestration.text_runtime import ConversationCandidate


class ImageInterpreter(Protocol):
    processor: str

    async def interpret(
        self,
        event: ChatEvent,
        part_index: int,
        expires_at: datetime,
        before_vision: Callable[[], Awaitable[None]],
    ) -> MediaInterpretation: ...


class InboundImages:
    def __init__(
        self,
        interpreter: ImageInterpreter,
        conversations: Collection[str],
        store: InterpretationStore | None = None,
    ) -> None:
        self._interpreter, self._conversations, self._store = (
            interpreter,
            frozenset(conversations),
            store,
        )

    async def enrich(
        self,
        candidate: "ConversationCandidate",
        require_permission: Callable[[str], Awaitable[None]],
    ) -> "ConversationCandidate":
        if candidate.conversation_id not in self._conversations:
            return candidate
        messages = list(candidate.context.messages)

        async def before_vision() -> None:
            await require_permission(candidate.conversation_id)

        for index, event in enumerate(messages):
            if event.message_id != candidate.source_message_id:
                continue
            images = [i for i, part in enumerate(event.parts) if part.kind in {"image", "sticker"}]
            if not images:
                continue
            if len(images) != 1 or event.conversation_id != candidate.conversation_id:
                raise MediaUnavailable()
            part_index = images[0]
            try:
                interpretation = await self._interpreter.interpret(
                    event, part_index, candidate.expires_at, before_vision
                )
            except (PermissionDenied, BudgetDenied):
                raise
            except Exception:  # noqa: BLE001 - stable media error without response bodies
                raise MediaUnavailable() from None
            if not interpretation.text.strip() or len(interpretation.text) > 3000:
                raise MediaUnavailable()
            if self._store is not None:
                messages[index] = await self._store.save(
                    candidate, event, part_index, interpretation
                )
            else:
                parts = list(event.parts)
                parts[part_index] = replace(parts[part_index], interpretation=interpretation)
                messages[index] = replace(
                    event, parts=tuple(parts), content_version=event.content_version + 1
                )
        return replace(candidate, context=replace(candidate.context, messages=tuple(messages)))
