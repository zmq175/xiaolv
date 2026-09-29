"""Persisted media evidence observed only through live chat and administrator HTTP."""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import create_async_engine
from test_admin_auth import PASSWORD, client
from test_live import message, settings, until
from test_live import services as services  # noqa: PLC0414 - explicit pytest fixture re-export

from xiaolv.live import LiveSummary, run_live


@asynccontextmanager
async def running(config):
    stop = asyncio.Event()
    stats = LiveSummary()
    task = asyncio.create_task(run_live(config, stop, statistics=stats))
    try:
        yield stats, task
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, 6)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def audio():
    frame = message(content="")
    frame["message"] = [{"type": "record", "data": {"file": "PRIVATE_AUDIO"}}]
    return frame


def configured(database_url, services, **changes):
    return settings(
        database_url,
        services,
        XIAOLV_NATIVE_ASR_CONVERSATIONS='["qq:10000:group:20000"]',
        XIAOLV_DELIVERY_POLICY='{"cooldown_seconds":0,"window_seconds":60,"max_messages":6}',
        **changes,
    )


async def test_saved_transcript_never_crosses_conversations(database_url, services):
    services.frames = [audio()]
    config = configured(database_url, services, XIAOLV_ENABLED_GROUP_IDS="[20000,30000]")
    async with running(config) as (stats, task):
        await until(lambda: stats.outcomes.get("confirmed") == 1, task)
    services.frames = [message(message_id=2, group_id=30000, content="聊些什么？")]
    async with running(config) as (stats, task):
        await until(lambda: stats.outcomes.get("confirmed") == 1, task)
    context = json.loads(services.model_requests[2]["messages"][1]["content"])
    assert len(context["messages"]) == 1
    assert context["messages"][0]["text"] == "聊些什么？"
    assert "周六下午三点见" not in json.dumps(context, ensure_ascii=False)
    assert services.transcriptions == [{"message_id": 1}]


@pytest.mark.parametrize("restore_before_result", [False, True])
async def test_revoked_asr_result_is_not_published(database_url, services, restore_before_result):
    services.frames = [audio()]
    services.transcription_gate = asyncio.Event()
    config = configured(database_url, services)
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, PasswordHash.recommended().hash(PASSWORD)) as http:
            login = await http.post("/admin/api/login", json={"password": PASSWORD})
            http.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            async with running(config) as (stats, task):
                await until(services.transcription_started.is_set, task)
                response = await http.put(
                    "/admin/api/conversations/qq:10000:group:20000",
                    json={"enabled": False, "expected_version": 0},
                    headers={"Idempotency-Key": "disable"},
                )
                assert response.status_code == 200
                if restore_before_result:
                    response = await http.put(
                        "/admin/api/conversations/qq:10000:group:20000",
                        json={"enabled": True, "expected_version": 1},
                        headers={"Idempotency-Key": "restore"},
                    )
                    assert response.status_code == 200
                services.transcription_gate.set()
                await until(lambda: bool(stats.outcomes), task)
                assert stats.outcomes == {
                    "media_error" if restore_before_result else "permission_denied": 1
                }
                assert len(services.model_requests) == 1
                assert services.sent == []
            if not restore_before_result:
                response = await http.put(
                    "/admin/api/conversations/qq:10000:group:20000",
                    json={"enabled": True, "expected_version": 1},
                    headers={"Idempotency-Key": "restore"},
                )
                assert response.status_code == 200
        services.frames = [message(message_id=2, content="现在可以聊天了")]
        async with running(config) as (stats, task):
            await until(lambda: stats.outcomes.get("confirmed") == 1, task)
        original = json.loads(services.model_requests[1]["messages"][1]["content"])["messages"][0]
        assert original["parts"][0]["status"] == "unprocessed"
        assert original["content_version"] == 1
    finally:
        services.transcription_gate.set()
        await engine.dispose()


async def test_late_asr_result_never_publishes_or_wakes_old_turn(database_url, services):
    services.frames = [audio()]
    services.transcription_gate = asyncio.Event()
    expiring = configured(
        database_url, services, XIAOLV_CHAT_TTL_SECONDS="2.5", XIAOLV_QUEUE_MAX_AGE_SECONDS="2"
    )
    async with running(expiring) as (stats, task):
        await until(services.transcription_started.is_set, task)
        await until(lambda: stats.outcomes.get("expired") == 1, task)
        services.transcription_gate.set()
        assert len(services.model_requests) == 1
        assert services.sent == []
    services.frames = [message(message_id=2, content="换个话题")]
    async with running(configured(database_url, services)) as (stats, task):
        await until(lambda: stats.outcomes.get("confirmed") == 1, task)
        assert stats.outcomes == {"confirmed": 1}
    context = json.loads(services.model_requests[1]["messages"][1]["content"])
    assert context["messages"][0]["parts"][0]["status"] == "unprocessed"
    assert context["messages"][0]["content_version"] == 1
    assert len(services.sent) == 1
