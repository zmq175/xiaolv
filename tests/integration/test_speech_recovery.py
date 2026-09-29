# ruff: noqa: F811 - imported pytest fixture requested by name
import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import create_async_engine
from test_admin_auth import PASSWORD, client
from test_live import services, settings  # noqa: F401
from test_speech_execution import runtime

from xiaolv.application.speech_execution import SpeechExecution
from xiaolv.domain.speech import SpeechPolicy
from xiaolv.live import run_live
from xiaolv.orchestration.text_runtime import ConversationCandidate
from xiaolv.storage.conversation_control import ConversationControl
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger
from xiaolv.storage.postgres_speech import PostgresSpeechLedger


@pytest.mark.parametrize("workers", [1, 2])
async def test_online_service_audits_expired_sigkill_call_without_releasing_cost(
    database_url, services, workers
):
    engine = create_async_engine(database_url, hide_parameters=True)
    process = None
    tasks = []
    calls = []
    stop = asyncio.Event()
    try:
        await ConversationControl(engine).register(["chat-1"])
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")
        expires = datetime.now(UTC) + timedelta(seconds=5)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "tests/helpers/crash_speech.py",
            env={**os.environ, "PYTHONPATH": "src", "XIAOLV_TEST_WORKER_DB": database_url},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(
                json.dumps({"epoch": epoch, "expires": expires.isoformat()}).encode()
            ),
            5,
        )
        assert process.returncode == -signal.SIGKILL, stderr.decode()
        assert stdout == b"tts-started\n"
        services.frames = []
        config = settings(database_url, services, XIAOLV_SPEECH_RECOVERY_INTERVAL_SECONDS="0.1")
        assert config.speech is None
        tasks = [asyncio.create_task(run_live(config, stop)) for _ in range(workers)]

        class Provider:
            async def synthesize(self, request):
                calls.append(request.call_id)
                raise ConnectionError("synthetic unknown fee")

        async def dispatch(*args):
            raise AssertionError("no artifact after unknown synthesis")

        policy = SpeechPolicy(
            "speech",
            "synthetic",
            "test-model",
            "test-price",
            "voice-v1",
            Decimal("0.10"),
            Decimal("0.06"),
        )

        async def attempt(id):
            executor = SpeechExecution(PostgresSpeechLedger(engine, policy), Provider(), dispatch)
            return await runtime(executor).run(
                ConversationCandidate(
                    "chat-1", id, "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
                )
            )

        async with client(engine, PasswordHash.recommended().hash(PASSWORD)) as browser:
            login = await browser.post("/admin/api/login", json={"password": PASSWORD})
            browser.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            async with asyncio.timeout(10):
                while True:
                    for task in tasks:
                        if task.done():
                            await task
                    response = await browser.get("/admin/api/speech-calls")
                    item = response.json()["items"][0]
                    if item["outcome"] == "voice_unknown":
                        break
                    await asyncio.sleep(0.05)
            assert item["state"] == "unknown"
            assert item["charged_cny"] is None
            assert item["reserved_cny"] == "0.060000"
            assert await attempt("before-invoice") == "budget_denied"
            assert calls == []
            settled = await browser.post(
                f"/admin/api/speech-calls/{item['call_id']}/reconcile",
                json={"charged_cny": "0.02", "evidence": "synthetic recovered invoice"},
                headers={"Idempotency-Key": "crash-invoice"},
            )
            assert settled.status_code == 200
            assert await attempt("after-invoice") == "voice_unknown"
            assert await attempt("still-limited") == "budget_denied"
            assert len(calls) == 1
        stop.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 6)
        assert services.sent == []
        assert services.model_requests == []
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if process is not None and process.returncode is None:
            process.kill()
            await process.communicate()
        await engine.dispose()
