"""Text replay entrypoint."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.application.inbound_images import InboundImages
from xiaolv.application.inbound_speech import InboundSpeech, MediaUnavailable
from xiaolv.domain.authorization import PermissionDenied
from xiaolv.domain.bot_profile import ProfileSnapshot
from xiaolv.domain.chat_event import ConversationContext
from xiaolv.domain.context_policy import ContextOverflow
from xiaolv.domain.model_budget import BudgetDenied
from xiaolv.domain.text_reply import TextPart, TextReply, validate_text_parts
from xiaolv.domain.voice_reply import VoiceReply


@dataclass(frozen=True)
class ConversationCandidate:
    conversation_id: str
    event_id: str
    text: str
    expires_at: datetime
    generation_epoch: int
    context: ConversationContext = field(default_factory=lambda: ConversationContext(0, ()))
    profile_snapshot: ProfileSnapshot | None = None
    source_message_id: str | None = None


class ConversationModel(Protocol):
    async def decide(self, candidate: ConversationCandidate) -> Literal["respond", "silence"]: ...

    async def reply(self, candidate: ConversationCandidate) -> str | TextReply | VoiceReply: ...


class VoiceDelivery(Protocol):
    """Voice execution boundary; implementations own durable synthesis and guarded delivery.

    Must retain outgoing_id, conversation scope, epoch and original deadline,
    check authorization after synthesis, and use DeliveryService for platform IO.
    No production implementation is wired until accounting and artifacts exist.
    """

    async def deliver(
        self, candidate: ConversationCandidate, reply: VoiceReply, outgoing_id: str
    ) -> str: ...


class _State(TypedDict, total=False):
    candidate: ConversationCandidate
    decision: str
    text: str
    mentions: tuple[str, ...]
    reply_to: str | None
    parts: tuple[TextPart, ...]
    voice: VoiceReply


class TextRuntime:
    def __init__(
        self,
        model: ConversationModel,
        delivery: DeliveryService,
        clock: Callable[[], datetime],
        max_chars: int = 200,
        profile_loader: Callable[[], Awaitable[ProfileSnapshot]] | None = None,
        voice_delivery: VoiceDelivery | None = None,
        inbound_speech: InboundSpeech | None = None,
        inbound_images: InboundImages | None = None,
    ) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._model = model
        self._voice_delivery = voice_delivery
        self._inbound_speech = inbound_speech
        self._inbound_images = inbound_images
        self._profile_loader = profile_loader
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
                if self._profile_loader is not None:
                    try:
                        snapshot = await self._profile_loader()
                    except Exception:  # noqa: BLE001 - no stale fallback or exception body exposure
                        return "profile_error"
                    candidate = replace(candidate, profile_snapshot=snapshot)
                    logging.getLogger(__name__).info(
                        "回合人设已选择",
                        extra={
                            "event": "profile_selected",
                            "fields": {
                                "turn_id": candidate.event_id,
                                "profile_source": "startup"
                                if snapshot.version is None
                                else "published",
                                "profile_version": str(snapshot.version)
                                if snapshot.version is not None
                                else "none",
                            },
                        },
                    )
                state = await self._graph.ainvoke({"candidate": candidate})
                if "voice" in state:
                    voice = state["voice"]
                    if (
                        not voice.speech_text.strip()
                        or len(voice.speech_text) > self._max_chars
                        or not voice.voice_profile.strip()
                    ):
                        return "invalid_reply"
                    if self._clock() >= candidate.expires_at:
                        return "expired"
                    if self._voice_delivery is None:
                        return "voice_unavailable"
                    await self._delivery.require_permission(candidate.conversation_id)
                    try:
                        return await self._voice_delivery.deliver(
                            candidate, state["voice"], outgoing_id
                        )
                    except (PermissionDenied, BudgetDenied):
                        raise
                    except TimeoutError:
                        if deadline.expired():
                            raise
                        return "voice_error"
                    except Exception:  # noqa: BLE001 - stable outcome, never provider error details
                        return "voice_error"
        except PermissionDenied as exc:
            return exc.reason
        except ContextOverflow:
            return "context_overflow"
        except MediaUnavailable:
            return "media_error"
        except BudgetDenied:
            return "budget_denied"
        except TimeoutError:
            return (
                "expired"
                if deadline.expired() or self._clock() >= candidate.expires_at
                else "model_error"
            )
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
                parts=state.get("parts", ()),
            )
        )

    async def _decide(self, state: _State) -> dict[str, str]:
        await self._delivery.require_permission(state["candidate"].conversation_id)
        decision = await self._model.decide(state["candidate"])
        logging.getLogger(__name__).info(
            "参与判断完成", extra={"event": "chat_decision", "fields": {"action": decision}}
        )
        return {"decision": decision}

    async def _reply(self, state: _State) -> _State:
        await self._delivery.require_permission(state["candidate"].conversation_id)
        for preparation in (self._inbound_speech, self._inbound_images):
            if preparation is None:
                continue
            if isinstance(preparation, InboundImages):
                state["candidate"] = await preparation.enrich(
                    state["candidate"], self._delivery.require_permission
                )
            else:
                state["candidate"] = await preparation.enrich(state["candidate"])
            await self._delivery.require_permission(state["candidate"].conversation_id)
            if self._clock() >= state["candidate"].expires_at:
                raise TimeoutError()
        reply = await self._model.reply(state["candidate"])
        if isinstance(reply, VoiceReply):
            return {"voice": reply}
        if isinstance(reply, str):
            return {"text": reply, "mentions": ()}
        candidate = state["candidate"]
        validate_text_parts(reply.text, reply.mentions, reply.parts)
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
        return {
            "text": reply.text,
            "mentions": reply.mentions,
            "reply_to": reply.reply_to,
            "parts": reply.parts,
        }

    async def _route(self, state: _State) -> str:
        return state["decision"]
