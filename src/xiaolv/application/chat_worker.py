"""Run one durable conversational candidate."""

import asyncio
import logging
from typing import Protocol

from opentelemetry import trace

from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime


class TurnQueue(Protocol):
    async def claim(self) -> ConversationCandidate | None: ...

    async def finish(self, candidate: ConversationCandidate, status: str) -> None: ...

    async def recover(self) -> int: ...

    async def status(self, turn_id: str) -> str | None: ...


class ChatWorker:
    def __init__(self, queue: TurnQueue, runtime: TextRuntime) -> None:
        self._queue = queue
        self._runtime = runtime

    async def recover(self) -> int:
        return await self._queue.recover()

    async def turn_status(self, turn_id: str) -> str | None:
        return await self._queue.status(turn_id)

    async def run_once(self) -> str:
        candidate = await self._queue.claim()
        if candidate is None:
            return "idle"
        with trace.get_tracer(__name__).start_as_current_span(
            "chat_turn", record_exception=False, set_status_on_exception=False
        ):
            result = "failed"
            try:
                result = await self._runtime.run(candidate)
                return result
            except asyncio.CancelledError:
                result = "cancelled"
                raise
            finally:
                await asyncio.shield(self._queue.finish(candidate, result))
                logging.getLogger(__name__).info(
                    "回合结束",
                    extra={
                        "event": "turn_finished",
                        "fields": {
                            "turn_id": candidate.event_id,
                            "status": result,
                        },
                    },
                )
