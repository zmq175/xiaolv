import asyncio
import json

import httpx
import pytest
from test_inbound_images import PNG
from test_live import message, settings, until
from test_live import services as services  # noqa: PLC0414 - shared real network fixture
from test_vision_settings import vision_configuration

from xiaolv.live import LiveSummary, run_live


@pytest.mark.parametrize(
    "enabled,next_group,image_count",
    [(True, 20000, 1), (True, 20000, 2), (True, 30000, 1), (False, 20000, 1)],
)
async def test_online_image_description_survives_restart(
    database_url, services, enabled, next_group, image_count
):
    config = vision_configuration()
    config["base_url"] = services.model_url
    configured = settings(
        database_url,
        services,
        XIAOLV_VISION=json.dumps(config if enabled else None),
        XIAOLV_ENABLED_GROUP_IDS="[20000,30000]",
        XIAOLV_DELIVERY_POLICY='{"cooldown_seconds":0,"window_seconds":60,"max_messages":6}',
    )
    frame = message(content="")
    frame["message"] = [{"type": "image", "data": {"file": "PRIVATE_IMAGE"}}]
    if image_count == 2:
        frame["message"].append({"type": "image", "data": {"file": "PRIVATE_SECOND"}})
    services.frames = [frame]
    downloads = []

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def download(request):
        downloads.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    async def run_once():
        stop, stats = asyncio.Event(), LiveSummary()
        task = asyncio.create_task(
            run_live(
                configured,
                stop,
                statistics=stats,
                media_resolver=resolve,
                media_transport=httpx.MockTransport(download),
            )
        )
        try:
            await until(lambda: bool(stats.outcomes), task)
            assert stats.outcomes == {"confirmed": 1}
        finally:
            stop.set()
            try:
                await asyncio.wait_for(task, 6)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    await run_once()
    if not enabled:
        assert len(services.model_requests) == 2 and downloads == []
        reply = services.model_requests[-1]["messages"][1]["content"]
        assert "unprocessed" in reply and "持久化的合成图片描述" not in reply
        return
    assert len(services.model_requests) == 3
    assert len(downloads) == image_count
    first_reply = json.loads(services.model_requests[-1]["messages"][1]["content"])
    assert first_reply["messages"][0]["content_version"] == 2
    assert all(part["status"] == "interpreted" for part in first_reply["messages"][0]["parts"])
    services.frames = [message(message_id=2, group_id=next_group, content="刚才图片说的什么？")]
    await run_once()
    assert len(services.model_requests) == 5 and len(downloads) == image_count
    later = json.loads(services.model_requests[-1]["messages"][1]["content"])
    if next_group == 20000:
        assert "持久化的合成图片描述" in json.dumps(later, ensure_ascii=False)
        if image_count == 2:
            saved = next(row for row in later["messages"] if "parts" in row)
            assert saved["content_version"] == 2
            assert len(saved["parts"]) == 2
            assert saved["parts"][0]["interpretation"] == saved["parts"][1]["interpretation"]
            assert len(saved["parts"][0]["interpretation"]["source_media_refs"]) == 2
    else:
        assert "持久化的合成图片描述" not in json.dumps(later, ensure_ascii=False)
        assert len(later["messages"]) == 1
    assert "PRIVATE_IMAGE" not in json.dumps(later)


@pytest.mark.parametrize("interruption", ["revoke", "restore", "expire"])
async def test_interrupted_vision_never_publishes_late_evidence(
    database_url, services, interruption
):
    from contextlib import asynccontextmanager

    from pwdlib import PasswordHash
    from sqlalchemy.ext.asyncio import create_async_engine
    from test_admin_auth import PASSWORD, client

    config = vision_configuration()
    config["base_url"] = services.model_url
    configured = settings(
        database_url,
        services,
        XIAOLV_VISION=json.dumps(config),
        XIAOLV_CHAT_TTL_SECONDS="3",
        XIAOLV_QUEUE_MAX_AGE_SECONDS="2",
        XIAOLV_DELIVERY_POLICY='{"cooldown_seconds":0,"window_seconds":60,"max_messages":6}',
    )
    frame = message(content="")
    frame["message"] = [{"type": "image", "data": {"file": "PRIVATE_IMAGE"}}]
    services.frames = [frame]
    services.vision_gate = asyncio.Event()

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def download(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    @asynccontextmanager
    async def running():
        stop, stats = asyncio.Event(), LiveSummary()
        task = asyncio.create_task(
            run_live(
                configured,
                stop,
                statistics=stats,
                media_resolver=resolve,
                media_transport=httpx.MockTransport(download),
            )
        )
        try:
            yield stats, task
        finally:
            stop.set()
            try:
                await asyncio.wait_for(task, 6)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, PasswordHash.recommended().hash(PASSWORD)) as http:
            login = await http.post("/admin/api/login", json={"password": PASSWORD})
            http.headers["X-CSRF-Token"] = login.json()["csrf_token"]

            async def set_enabled(enabled, version):
                result = await http.put(
                    "/admin/api/conversations/qq:10000:group:20000",
                    json={"enabled": enabled, "expected_version": version},
                    headers={"Idempotency-Key": f"vision-{version}"},
                )
                assert result.status_code == 200

            async with running() as (stats, task):
                await until(services.vision_started.is_set, task)
                if interruption == "expire":
                    await until(lambda: stats.outcomes.get("expired") == 1, task)
                else:
                    await set_enabled(False, 0)
                    if interruption == "restore":
                        await set_enabled(True, 1)
                services.vision_gate.set()
                await until(lambda: bool(stats.outcomes), task)
                assert stats.outcomes == {
                    {"revoke": "permission_denied", "restore": "media_error", "expire": "expired"}[
                        interruption
                    ]: 1
                }
                assert len(services.model_requests) == 2 and services.sent == []
            if interruption == "revoke":
                await set_enabled(True, 1)
        services.frames = [message(message_id=2, content="现在聊别的")]
        async with running() as (stats, task):
            await until(lambda: stats.outcomes.get("confirmed") == 1, task)
        context = json.loads(services.model_requests[-1]["messages"][1]["content"])
        original = next(row for row in context["messages"] if "parts" in row)
        assert original["content_version"] == 1
        assert original["parts"][0]["status"] == "unprocessed"
        assert "持久化的合成图片描述" not in json.dumps(context, ensure_ascii=False)
        assert len(services.sent) == 1
    finally:
        services.vision_gate.set()
        await engine.dispose()
