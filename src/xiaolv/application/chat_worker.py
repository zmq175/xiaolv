"""Run one durable conversational candidate."""

import asyncio
from typing import Protocol

from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime


class TurnQueue(Protocol):
    async def claim(self) -> ConversationCandidate | None: ...

    async def finish(self, candidate: ConversationCandidate, status: str) -> None: ...


class ChatWorker:
    def __init__(self, queue: TurnQueue, runtime: TextRuntime) -> None:
        self._queue = queue
        self._runtime = runtime

    async def run_once(self) -> str:
        candidate = await self._queue.claim()
        if candidate is None:
            return "idle"
        result = "failed"
        try:
            result = await self._runtime.run(candidate)
            return result
        except asyncio.CancelledError:
            result = "cancelled"
            raise
        finally:
            await asyncio.shield(self._queue.finish(candidate, result))
