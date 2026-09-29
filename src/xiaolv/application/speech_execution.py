"""Durable synthesis before a separately guarded media delivery boundary."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from uuid import uuid4

from xiaolv.domain.model_capacity import ModelCapacity
from xiaolv.domain.speech import SpeechLedger, SpeechRequest, SpeechResult, SpeechSynthesizer
from xiaolv.domain.voice_reply import VoiceReply
from xiaolv.orchestration.text_runtime import ConversationCandidate


class SpeechExecution:
    def __init__(
        self,
        ledger: SpeechLedger,
        provider: SpeechSynthesizer,
        dispatch: Callable[[ConversationCandidate, VoiceReply, str, SpeechResult], Awaitable[str]],
        *,
        capacity: ModelCapacity | None = None,
    ) -> None:
        self._ledger, self._provider, self._dispatch = ledger, provider, dispatch
        self._capacity = capacity

    async def deliver(
        self, candidate: ConversationCandidate, reply: VoiceReply, outgoing_id: str
    ) -> str:
        request = SpeechRequest(
            "speech:" + outgoing_id,
            candidate.conversation_id,
            candidate.generation_epoch,
            candidate.expires_at,
            reply.speech_text,
            reply.voice_profile,
        )
        admission = (
            self._capacity.hold("speech-attempt:" + uuid4().hex, candidate.expires_at)
            if self._capacity
            else nullcontext()
        )
        async with admission:
            return await self._execute(request, candidate, reply, outgoing_id)

    async def _execute(
        self,
        request: SpeechRequest,
        candidate: ConversationCandidate,
        reply: VoiceReply,
        outgoing_id: str,
    ) -> str:
        previous = await self._ledger.reserve(request)
        if previous is not None:
            return previous
        try:
            result = await self._provider.synthesize(request)
            if not await self._ledger.synthesized(request.call_id, result.charged_amount):
                return "voice_unknown"
            denied = await self._ledger.check(request)
            if denied is not None:
                return await self._ledger.finish(request.call_id, denied)
            outcome = await self._dispatch(candidate, reply, outgoing_id, result)
            return await self._ledger.finish(request.call_id, outcome)
        except asyncio.CancelledError:
            await asyncio.shield(self._ledger.finish(request.call_id, "voice_unknown"))
            raise
        except Exception:  # noqa: BLE001 - uncertainty retains reservation, no provider details
            return await self._ledger.finish(request.call_id, "voice_unknown")
