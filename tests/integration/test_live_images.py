import asyncio
import json

import httpx
import pytest
from test_inbound_images import PNG
from test_live import message, settings, until
from test_live import services as services  # noqa: PLC0414 - shared real network fixture
from test_vision_settings import vision_configuration

from xiaolv.live import LiveSummary, run_live


@pytest.mark.parametrize("enabled", [True, False])
async def test_online_image_description_survives_restart(database_url, services, enabled):
    config = vision_configuration()
    config["base_url"] = services.model_url
    configured = settings(
        database_url,
        services,
        XIAOLV_VISION=json.dumps(config if enabled else None),
        XIAOLV_DELIVERY_POLICY='{"cooldown_seconds":0,"window_seconds":60,"max_messages":6}',
    )
    frame = message(content="")
    frame["message"] = [{"type": "image", "data": {"file": "PRIVATE_IMAGE"}}]
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
            await until(lambda: stats.outcomes.get("confirmed") == 1, task)
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
    assert len(downloads) == 1
    first_reply = json.loads(services.model_requests[-1]["messages"][1]["content"])
    assert first_reply["messages"][0]["content_version"] == 2
    services.frames = [message(message_id=2, content="刚才图片说的什么？")]
    await run_once()
    assert len(services.model_requests) == 5 and len(downloads) == 1
    later = json.loads(services.model_requests[-1]["messages"][1]["content"])
    assert "持久化的合成图片描述" in json.dumps(later, ensure_ascii=False)
    assert "PRIVATE_IMAGE" not in json.dumps(later)
