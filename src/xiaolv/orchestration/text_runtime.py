"""Text replay entrypoint."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.domain.chat_event import ConversationContext


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

    async def reply(self, candidate: ConversationCandidate) -> str: ...


class _State(TypedDict, total=False):
    candidate: ConversationCandidate
    decision: str
    text: str


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
        deadline = asyncio.timeout(remaining)
        try:
            async with deadline:
                state = await self._graph.ainvoke({"candidate": candidate})
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
            )
        )

    async def _decide(self, state: _State) -> dict[str, str]:
        return {"decision": await self._model.decide(state["candidate"])}

    async def _reply(self, state: _State) -> dict[str, str]:
        return {"text": await self._model.reply(state["candidate"])}

    async def _route(self, state: _State) -> str:
        return state["decision"]
