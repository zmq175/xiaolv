"""Kill after durable speech reservation reaches the external provider boundary."""

import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.application.delivery import DeliveryService
from xiaolv.application.speech_execution import SpeechExecution
from xiaolv.domain.speech import SpeechPolicy
from xiaolv.domain.voice_reply import VoiceReply
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime
from xiaolv.storage.postgres_speech import PostgresSpeechLedger


class Model:
    async def decide(self, candidate):
        return "respond"

    async def reply(self, candidate):
        return VoiceReply("合成语音样本", "warm")


class Platform:
    async def send(self, request):
        raise AssertionError("no text fallback")


class Provider:
    async def synthesize(self, request):
        print("tts-started", flush=True)
        os.kill(os.getpid(), signal.SIGKILL)


async def dispatch(*args):
    raise AssertionError("crashed synthesis must not dispatch")


async def main():
    data = json.loads(sys.stdin.readline())
    engine = create_async_engine(os.environ["XIAOLV_TEST_WORKER_DB"], hide_parameters=True)
    policy = SpeechPolicy(
        "speech",
        "synthetic",
        "test-model",
        "test-price",
        "voice-v1",
        Decimal("0.10"),
        Decimal("0.06"),
    )
    executor = SpeechExecution(PostgresSpeechLedger(engine, policy), Provider(), dispatch)
    clock = lambda: datetime.now(UTC)
    runtime = TextRuntime(
        Model(),
        DeliveryService(Platform(), clock, lambda _: data["epoch"]),
        clock,
        voice_delivery=executor,
    )
    candidate = ConversationCandidate(
        "chat-1", "crash", "你好", datetime.fromisoformat(data["expires"]), data["epoch"]
    )
    await runtime.run(candidate)


asyncio.run(main())
