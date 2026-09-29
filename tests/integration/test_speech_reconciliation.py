from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import create_async_engine
from test_admin_auth import PASSWORD, client
from test_speech_execution import runtime

from xiaolv.application.speech_execution import SpeechExecution
from xiaolv.domain.speech import SpeechPolicy
from xiaolv.orchestration.text_runtime import ConversationCandidate
from xiaolv.storage.conversation_control import ConversationControl
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger
from xiaolv.storage.postgres_speech import PostgresSpeechLedger


@pytest.fixture
async def scenario(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    calls = []

    class Provider:
        async def synthesize(self, request):
            calls.append(request.call_id)
            raise ConnectionError("synthetic lost synthesis receipt")

    async def dispatch(*args):
        raise AssertionError("unknown synthesis must not dispatch")

    policy = SpeechPolicy(
        "speech", "synthetic", "model", "price", "v1", Decimal("0.1"), Decimal("0.06")
    )
    try:
        await ConversationControl(engine).register(["chat-1"])
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")

        async def chat(id):
            executor = SpeechExecution(PostgresSpeechLedger(engine, policy), Provider(), dispatch)
            return await runtime(executor).run(
                ConversationCandidate(
                    "chat-1", id, "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
                )
            )

        yield engine, chat, calls, PasswordHash.recommended().hash(PASSWORD)
    finally:
        await engine.dispose()


async def test_admin_reconciles_unknown_cost_once_and_chat_regains_capacity(scenario):
    engine, chat, calls, password_hash = scenario
    assert await chat("first") == "voice_unknown"
    assert await chat("blocked") == "budget_denied"
    body = {"charged_cny": "0.02", "evidence": "synthetic invoice line 1"}
    async with client(engine, password_hash) as browser:
        login = await browser.post("/admin/api/login", json={"password": PASSWORD})
        browser.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        listing = await browser.get("/admin/api/speech-calls")
        assert listing.status_code == 200
        call_id = listing.json()["items"][0]["call_id"]
        assert listing.json()["items"][0]["charged_cny"] is None
        response = await browser.post(
            f"/admin/api/speech-calls/{call_id}/reconcile",
            json=body,
            headers={"Idempotency-Key": "reconcile-first"},
        )
        assert response.status_code == 200
        assert response.json()["charged_cny"] == "0.020000"
        cookie = browser.cookies.get("xiaolv_admin")
        csrf = browser.headers["X-CSRF-Token"]
    async with client(engine, password_hash) as restarted:
        restarted.cookies.set("xiaolv_admin", cookie)
        restarted.headers["X-CSRF-Token"] = csrf
        replay = await restarted.post(
            f"/admin/api/speech-calls/{call_id}/reconcile",
            json=body,
            headers={"Idempotency-Key": "reconcile-first"},
        )
        assert replay.json() == response.json()
        changed = await restarted.post(
            f"/admin/api/speech-calls/{call_id}/reconcile",
            json={**body, "charged_cny": "0"},
            headers={"Idempotency-Key": "reconcile-other"},
        )
        assert changed.status_code == 409
    assert await chat("second") == "voice_unknown"
    assert await chat("third") == "budget_denied"
    assert len(calls) == 2


async def test_reconciliation_requires_login_csrf_and_original_origin(scenario):
    engine, chat, calls, password_hash = scenario
    assert await chat("secure") == "voice_unknown"
    path = "/admin/api/speech-calls/speech:6:chat-1secure/reconcile"
    body = {"charged_cny": "0", "evidence": "supplier confirms no charge"}
    async with client(engine, password_hash) as browser:
        assert (await browser.get("/admin/api/speech-calls")).status_code == 401
        assert (await browser.post(path, json=body)).status_code == 401
        login = await browser.post("/admin/api/login", json={"password": PASSWORD})
        assert (
            await browser.post(path, json=body, headers={"Idempotency-Key": "secure"})
        ).status_code == 403
        browser.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        assert (
            await browser.post(
                path,
                json=body,
                headers={"Idempotency-Key": "secure", "Origin": "https://untrusted.invalid"},
            )
        ).status_code == 403
        assert (await browser.post(path, json=body)).status_code == 422
    assert await chat("still-blocked") == "budget_denied"
    assert len(calls) == 1


async def test_concurrent_reconciliation_settles_once_and_excess_charge_blocks_future_calls(
    scenario,
):
    import asyncio

    engine, chat, calls, password_hash = scenario
    assert await chat("cost") == "voice_unknown"
    path = "/admin/api/speech-calls/speech:6:chat-1cost/reconcile"
    async with client(engine, password_hash) as browser:
        login = await browser.post("/admin/api/login", json={"password": PASSWORD})
        browser.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        responses = await asyncio.gather(
            *[
                browser.post(
                    path,
                    json={"charged_cny": "0.12", "evidence": "invoice reviewed"},
                    headers={"Idempotency-Key": "same-invoice"},
                )
                for _ in range(3)
            ]
        )
        assert all(response.status_code == 200 for response in responses)
        assert all(response.json() == responses[0].json() for response in responses)
        listing = (await browser.get("/admin/api/speech-calls")).json()
        assert listing["items"][0]["charged_cny"] == "0.120000"
        assert listing["items"][0]["evidence"] == "invoice reviewed"
    assert await chat("overrun") == "budget_denied"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"charged_cny": "-1", "evidence": "bad"},
        {"charged_cny": "100000000000000", "evidence": "bad"},
        {"charged_cny": "NaN", "evidence": "bad"},
        {"charged_cny": "0.0000001", "evidence": "bad"},
        {"charged_cny": "0", "evidence": "   "},
    ],
)
async def test_invalid_reconciliation_does_not_release_reservation(scenario, body):
    engine, chat, calls, password_hash = scenario
    assert await chat("invalid") == "voice_unknown"
    async with client(engine, password_hash) as browser:
        login = await browser.post("/admin/api/login", json={"password": PASSWORD})
        browser.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        response = await browser.post(
            "/admin/api/speech-calls/speech:6:chat-1invalid/reconcile",
            json=body,
            headers={"Idempotency-Key": "invalid"},
        )
        assert response.status_code == 422
    assert await chat("blocked") == "budget_denied"
    assert len(calls) == 1


async def test_active_synthesis_cannot_be_reconciled_or_reexecuted(scenario):
    import asyncio

    from xiaolv.domain.speech import SpeechResult

    engine, _, _, password_hash = scenario
    entered, release = asyncio.Event(), asyncio.Event()
    calls, sent = [], []

    class Provider:
        async def synthesize(self, request):
            calls.append(request.call_id)
            entered.set()
            await release.wait()
            return SpeechResult(b"synthetic-audio")

    async def dispatch(*args):
        sent.append(args)
        return "confirmed"

    epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")
    candidate = ConversationCandidate(
        "chat-1", "active", "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
    )
    executor = SpeechExecution(
        PostgresSpeechLedger(
            engine,
            SpeechPolicy(
                "speech", "synthetic", "model", "price", "v1", Decimal("0.1"), Decimal("0.06")
            ),
        ),
        Provider(),
        dispatch,
    )
    task = asyncio.create_task(runtime(executor).run(candidate))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        async with client(engine, password_hash) as browser:
            login = await browser.post("/admin/api/login", json={"password": PASSWORD})
            browser.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            path = "/admin/api/speech-calls/speech:6:chat-1active/reconcile"
            body = {"charged_cny": "0.01", "evidence": "synthetic bill"}
            denied = await browser.post(path, json=body, headers={"Idempotency-Key": "active"})
            assert denied.status_code == 409
            assert denied.json()["detail"] == "speech_call_active"
            release.set()
            assert await task == "confirmed"
            assert (
                await browser.post(path, json=body, headers={"Idempotency-Key": "active"})
            ).status_code == 200
        assert await runtime(executor).run(candidate) == "confirmed"
        assert len(calls) == len(sent) == 1
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
