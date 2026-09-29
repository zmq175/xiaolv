"""Text replay entrypoint."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.domain.chat_event import ConversationContext
from xiaolv.domain.model_budget import BudgetDenied
from xiaolv.domain.text_reply import TextReply


@dataclass(frozen=True)
class ConversationCandidate:
    conversation_id: str
    event_id: str
    text: str
    expires_at: datetime
    generation_epoch: int
    context: ConversationContext = field(default_factory=lambda: ConversationContext(0, ()))


class ConversationModel(Protocol):
    async def decide(self, candidate: ConversationCandidate) -> Literal["respond", "silence"]: ...

    async def reply(self, candidate: ConversationCandidate) -> str | TextReply: ...


class _State(TypedDict, total=False):
    candidate: ConversationCandidate
    decision: str
    text: str
    mentions: tuple[str, ...]
    reply_to: str | None


class TextRuntime:
    def __init__(
        self,
        model: ConversationModel,
        delivery: DeliveryService,
        clock: Callable[[], datetime],
        max_chars: int = 200,
    ) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._model = model
        self._delivery = delivery
        self._clock = clock
        self._max_chars = max_chars
        builder = StateGraph(_State)
        builder.add_node("decide", self._decide)
        builder.add_edge(START, "decide")
        builder.add_node("reply", self._reply)
        builder.add_conditional_edges("decide", self._route, {"silence": END, "respond": "reply"})
        builder.add_edge("reply", END)
        self._graph = builder.compile()

    async def run(self, candidate: ConversationCandidate) -> str:
        outgoing_id = (
            f"{len(candidate.conversation_id)}:{candidate.conversation_id}{candidate.event_id}"
        )
        async with self._locks.setdefault(outgoing_id, asyncio.Lock()):
            previous = await self._delivery.status(outgoing_id)
            if previous is not None:
                return previous
            return await self._run(candidate, outgoing_id)

    async def _run(self, candidate: ConversationCandidate, outgoing_id: str) -> str:
        now = self._clock()
        if now.utcoffset() is None or candidate.expires_at.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        remaining = (candidate.expires_at.astimezone(UTC) - now.astimezone(UTC)).total_seconds()
        if remaining <= 0:
            return "expired"
        expires = asyncio.get_running_loop().time() + remaining
        preflight_deadline = asyncio.timeout_at(expires)
        try:
            async with preflight_deadline:
                if not await self._delivery.can_send(candidate.conversation_id):
                    return "rate_limited"
        except TimeoutError:
            if preflight_deadline.expired():
                return "expired"
            raise
        deadline = asyncio.timeout_at(expires)
        try:
            async with deadline:
                state = await self._graph.ainvoke({"candidate": candidate})
        except BudgetDenied:
            return "budget_denied"
        except TimeoutError:
            return "expired" if deadline.expired() else "model_error"
        except Exception:  # noqa: BLE001 - graph/model failure is a terminal replay outcome
            return "model_error"
        if state["decision"] == "silence":
            return "silence"
        if not state["text"].strip() or len(state["text"]) > self._max_chars:
            return "invalid_reply"
        return await self._delivery.deliver(
            DeliveryRequest(
                outgoing_id,
                candidate.conversation_id,
                candidate.expires_at,
                candidate.generation_epoch,
                state["text"],
                mentions=state.get("mentions", ()),
                reply_to=state.get("reply_to"),
            )
        )

    async def _decide(self, state: _State) -> dict[str, str]:
        decision = await self._model.decide(state["candidate"])
        logging.getLogger(__name__).info(
            "参与判断完成", extra={"event": "chat_decision", "fields": {"action": decision}}
        )
        return {"decision": decision}

    async def _reply(self, state: _State) -> _State:
        reply = await self._model.reply(state["candidate"])
        if isinstance(reply, str):
            return {"text": reply, "mentions": ()}
        candidate = state["candidate"]
        if any(
            item.conversation_id != candidate.conversation_id for item in candidate.context.messages
        ):
            raise ValueError("conversation context scope mismatch")
        accounts = {item.sender_account_id for item in candidate.context.messages}
        if any(account not in accounts for account in reply.mentions):
            raise ValueError("mention target is outside conversation context")
        if (
            reply.reply_to is not None
            and sum(item.message_id == reply.reply_to for item in candidate.context.messages) != 1
        ):
            raise ValueError("quote target is missing or ambiguous")
        return {"text": reply.text, "mentions": reply.mentions, "reply_to": reply.reply_to}

    async def _route(self, state: _State) -> str:
        return state["decision"]
