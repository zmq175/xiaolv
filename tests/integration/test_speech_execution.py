import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.application.delivery import DeliveryService
from xiaolv.domain.voice_reply import VoiceReply
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime
from xiaolv.storage.conversation_control import ConversationControl
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger


class Model:
    async def decide(self, candidate):
        return "respond"

    async def reply(self, candidate):
        return VoiceReply("合成语音样本", "warm")


class TextPlatform:
    async def send(self, request):
        raise AssertionError("must not fall back to text")


def runtime(executor):
    clock = lambda: datetime.now(UTC)
    return TextRuntime(
        Model(), DeliveryService(TextPlatform(), clock, lambda _: 1), clock, voice_delivery=executor
    )


async def test_two_runtimes_and_restart_synthesize_same_reply_only_once(database_url):
    from xiaolv.application.speech_execution import SpeechExecution
    from xiaolv.domain.speech import SpeechPolicy, SpeechResult
    from xiaolv.storage.postgres_speech import PostgresSpeechLedger

    engine = create_async_engine(database_url, hide_parameters=True)
    entered, release = asyncio.Event(), asyncio.Event()
    calls, delivered = [], []

    class Provider:
        async def synthesize(self, request):
            calls.append(request)
            entered.set()
            await release.wait()
            return SpeechResult(b"synthetic-audio", Decimal("0.02"))

    async def dispatch(candidate, reply, outgoing_id, result):
        delivered.append(outgoing_id)
        return "confirmed"

    policy = SpeechPolicy(
        "speech", "synthetic", "test-model", "test-price", "voice-v1", Decimal(1), Decimal("0.1")
    )
    try:
        await ConversationControl(engine).register(["chat-1"])
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")
        candidate = ConversationCandidate(
            "chat-1", "turn-1", "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
        )

        def executor():
            return SpeechExecution(PostgresSpeechLedger(engine, policy), Provider(), dispatch)

        first = asyncio.create_task(runtime(executor()).run(candidate))
        await asyncio.wait_for(entered.wait(), 2)
        assert await runtime(executor()).run(candidate) == "voice_inflight"
        release.set()
        assert await first == "confirmed"
        assert await runtime(executor()).run(candidate) == "confirmed"
        assert len(calls) == 1
        assert delivered == ["6:chat-1turn-1"]
    finally:
        release.set()
        await engine.dispose()


async def test_revocation_while_synthesizing_prevents_dispatch(database_url):
    from pwdlib import PasswordHash
    from test_admin_auth import PASSWORD, client

    from xiaolv.application.speech_execution import SpeechExecution
    from xiaolv.domain.speech import SpeechPolicy, SpeechResult
    from xiaolv.storage.postgres_speech import PostgresSpeechLedger

    engine = create_async_engine(database_url, hide_parameters=True)
    entered, release = asyncio.Event(), asyncio.Event()
    delivered = []

    class Provider:
        async def synthesize(self, request):
            entered.set()
            await release.wait()
            return SpeechResult(b"synthetic-audio", Decimal("0.02"))

    async def dispatch(*args):
        delivered.append(args)
        return "confirmed"

    policy = SpeechPolicy(
        "speech", "synthetic", "test-model", "test-price", "voice-v1", Decimal(1), Decimal("0.1")
    )
    task = None
    try:
        await ConversationControl(engine).register(["chat-1"])
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")
        candidate = ConversationCandidate(
            "chat-1", "turn-stop", "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
        )
        executor = SpeechExecution(PostgresSpeechLedger(engine, policy), Provider(), dispatch)
        task = asyncio.create_task(runtime(executor).run(candidate))
        await asyncio.wait_for(entered.wait(), 2)
        async with client(engine, PasswordHash.recommended().hash(PASSWORD)) as http:
            login = await http.post("/admin/api/login", json={"password": PASSWORD})
            http.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            response = await http.put(
                "/admin/api/conversations/chat-1",
                json={"enabled": False, "expected_version": 0},
                headers={"Idempotency-Key": "stop-tts"},
            )
            assert response.status_code == 200
        release.set()
        assert await task == "permission_denied"
        assert delivered == []
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


async def test_unknown_synthesis_keeps_budget_reserved_across_restart(database_url):
    from xiaolv.application.speech_execution import SpeechExecution
    from xiaolv.domain.speech import SpeechPolicy
    from xiaolv.storage.postgres_speech import PostgresSpeechLedger

    engine = create_async_engine(database_url, hide_parameters=True)
    calls = []

    class Provider:
        async def synthesize(self, request):
            calls.append(request.call_id)
            raise ConnectionError("private vendor failure")

    async def dispatch(*args):
        raise AssertionError("failed synthesis cannot dispatch")

    policy = SpeechPolicy(
        "speech",
        "synthetic",
        "test-model",
        "test-price",
        "voice-v1",
        Decimal("0.10"),
        Decimal("0.06"),
    )
    try:
        await ConversationControl(engine).register(["chat-1"])
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")
        candidate = ConversationCandidate(
            "chat-1", "unknown", "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
        )
        make = lambda: SpeechExecution(PostgresSpeechLedger(engine, policy), Provider(), dispatch)
        assert await runtime(make()).run(candidate) == "voice_unknown"
        assert await runtime(make()).run(candidate) == "voice_unknown"
        other = ConversationCandidate("chat-1", "next", "你好", candidate.expires_at, epoch)
        assert await runtime(make()).run(other) == "budget_denied"
        assert len(calls) == 1
    finally:
        await engine.dispose()


async def test_reported_speech_charge_settles_reservation_without_fake_tokens(database_url):
    from xiaolv.application.speech_execution import SpeechExecution
    from xiaolv.domain.speech import SpeechPolicy, SpeechResult
    from xiaolv.storage.postgres_speech import PostgresSpeechLedger

    engine = create_async_engine(database_url, hide_parameters=True)
    calls = []

    class Provider:
        async def synthesize(self, request):
            calls.append(request.call_id)
            return SpeechResult(b"synthetic-audio", Decimal("0.02"))

    async def dispatch(*args):
        return "confirmed"

    policy = SpeechPolicy(
        "speech",
        "synthetic",
        "test-model",
        "test-price",
        "voice-v1",
        Decimal("0.10"),
        Decimal("0.06"),
    )
    try:
        await ConversationControl(engine).register(["chat-1"])
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")
        executor = SpeechExecution(PostgresSpeechLedger(engine, policy), Provider(), dispatch)
        results = []
        for i in range(4):
            candidate = ConversationCandidate(
                "chat-1", f"charge-{i}", "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
            )
            results.append(await runtime(executor).run(candidate))
        assert results == ["confirmed", "confirmed", "confirmed", "budget_denied"]
        assert len(calls) == 3
    finally:
        await engine.dispose()


async def test_cancelled_synthesis_is_not_automatically_retried(database_url):
    import pytest

    from xiaolv.application.speech_execution import SpeechExecution
    from xiaolv.domain.speech import SpeechPolicy
    from xiaolv.storage.postgres_speech import PostgresSpeechLedger

    engine = create_async_engine(database_url, hide_parameters=True)
    entered = asyncio.Event()
    calls = []

    class Provider:
        async def synthesize(self, request):
            calls.append(request.call_id)
            entered.set()
            await asyncio.Event().wait()

    async def dispatch(*args):
        raise AssertionError("cancelled synthesis cannot dispatch")

    policy = SpeechPolicy(
        "speech",
        "synthetic",
        "test-model",
        "test-price",
        "voice-v1",
        Decimal("0.10"),
        Decimal("0.06"),
    )
    task = None
    try:
        await ConversationControl(engine).register(["chat-1"])
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")
        candidate = ConversationCandidate(
            "chat-1", "cancel", "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
        )
        make = lambda: SpeechExecution(PostgresSpeechLedger(engine, policy), Provider(), dispatch)
        task = asyncio.create_task(runtime(make()).run(candidate))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await runtime(make()).run(candidate) == "voice_unknown"
        other = ConversationCandidate("chat-1", "next", "你好", candidate.expires_at, epoch)
        assert await runtime(make()).run(other) == "budget_denied"
        assert len(calls) == 1
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


async def test_shared_speech_capacity_serializes_distinct_runtimes(database_url):
    from xiaolv.application.speech_execution import SpeechExecution
    from xiaolv.domain.speech import SpeechPolicy, SpeechResult
    from xiaolv.storage.postgres_model_capacity import PostgresModelCapacity
    from xiaolv.storage.postgres_speech import PostgresSpeechLedger

    engine = create_async_engine(database_url, hide_parameters=True)
    entered, release = asyncio.Event(), asyncio.Event()
    calls, active, peak = [], 0, 0

    class Provider:
        async def synthesize(self, request):
            nonlocal active, peak
            calls.append(request.call_id)
            active += 1
            peak = max(peak, active)
            try:
                if len(calls) == 1:
                    entered.set()
                    await release.wait()
                return SpeechResult(b"synthetic-audio", Decimal("0.02"))
            finally:
                active -= 1

    async def dispatch(*args):
        return "confirmed"

    policy = SpeechPolicy(
        "speech", "synthetic", "test-model", "test-price", "voice-v1", Decimal(1), Decimal("0.1")
    )
    tasks = []
    try:
        await ConversationControl(engine).register(["chat-1"])
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")

        def executor():
            return SpeechExecution(
                PostgresSpeechLedger(engine, policy),
                Provider(),
                dispatch,
                capacity=PostgresModelCapacity(engine, "speech-model", 1),
            )

        first = ConversationCandidate(
            "chat-1", "capacity-1", "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
        )
        second = ConversationCandidate("chat-1", "capacity-2", "你好", first.expires_at, epoch)
        tasks.append(asyncio.create_task(runtime(executor()).run(first)))
        await asyncio.wait_for(entered.wait(), 2)
        tasks.append(asyncio.create_task(runtime(executor()).run(second)))
        await asyncio.sleep(0.1)
        assert len(calls) == 1
        release.set()
        assert await asyncio.gather(*tasks) == ["confirmed", "confirmed"]
        assert len(calls) == 2 and peak == 1
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()


async def test_sigkill_after_speech_reservation_retains_cost_and_does_not_retry(database_url):
    import json
    import os
    import signal
    import sys

    from xiaolv.application.speech_execution import SpeechExecution
    from xiaolv.domain.speech import SpeechPolicy
    from xiaolv.storage.postgres_speech import PostgresSpeechLedger

    engine = create_async_engine(database_url, hide_parameters=True)
    process = None

    class Provider:
        async def synthesize(self, request):
            raise AssertionError("crashed request must not synthesize again")

    async def dispatch(*args):
        raise AssertionError("no artifact after crash")

    policy = SpeechPolicy(
        "speech",
        "synthetic",
        "test-model",
        "test-price",
        "voice-v1",
        Decimal("0.10"),
        Decimal("0.06"),
    )
    try:
        await ConversationControl(engine).register(["chat-1"])
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")
        candidate = ConversationCandidate(
            "chat-1", "crash", "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "tests/helpers/crash_speech.py",
            env={**os.environ, "PYTHONPATH": "src", "XIAOLV_TEST_WORKER_DB": database_url},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        payload = json.dumps({"epoch": epoch, "expires": candidate.expires_at.isoformat()}).encode()
        stdout, stderr = await asyncio.wait_for(process.communicate(payload), 5)
        assert process.returncode == -signal.SIGKILL, stderr.decode()
        assert stdout == b"tts-started\n"
        executor = SpeechExecution(PostgresSpeechLedger(engine, policy), Provider(), dispatch)
        assert await runtime(executor).run(candidate) == "voice_inflight"
        other = ConversationCandidate("chat-1", "after-crash", "你好", candidate.expires_at, epoch)
        assert await runtime(executor).run(other) == "budget_denied"
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.communicate()
        await engine.dispose()
