"""Real monetary ledger with native-image chat replay and synthetic provider HTTP."""

import asyncio
import json
from decimal import Decimal

import httpx
import httpx2
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from test_chat_model import stream_json
from test_inbound_images import PNG, RPC, replay

from xiaolv.domain.model_budget import BudgetPolicy
from xiaolv.models.chat_completions import ChatCompletionsGateway
from xiaolv.models.vision import ImageDescriber
from xiaolv.platforms.media_http import MediaDownloader
from xiaolv.storage.postgres_budget import PostgresModelBudget


def policy():
    return BudgetPolicy(
        "external",
        "synthetic-provider",
        "synthetic-vision",
        "test-v1",
        Decimal("0.004"),
        Decimal(1),
        Decimal(2),
    )


async def run_image(
    engine, *, image_tokens, known_usage=True, provider_mode="success", ttl=5, image_count=1
):
    requests = []

    async def serve(request):
        requests.append(request)
        if provider_mode == "stall":
            await asyncio.Event().wait()
        if provider_mode == "reject":
            return httpx2.Response(429, json={"error": {"message": "synthetic rejection"}})
        response = stream_json({"description": "合成图片"})
        if known_usage:
            usage = {
                "choices": [],
                "usage": {
                    "prompt_tokens": 80,
                    "completion_tokens": 5,
                    "total_tokens": 85,
                },
            }
            body = response.content.replace(
                b"data: [DONE]", ("data: " + json.dumps(usage) + "\n\ndata: [DONE]").encode()
            )
            return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)
        return response

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def download(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    from xiaolv.domain.chat_event import MessagePart

    rpc = RPC()
    parts = None
    if image_count == 2:
        rpc.source_changes["message"] = [
            {"type": "image", "data": {"file": ref}} for ref in ("one", "two")
        ]
        parts = tuple(MessagePart("image", reference=ref) for ref in ("one", "two"))
    async with ChatCompletionsGateway(
        base_url="https://vision.example/v1",
        api_key="synthetic",
        model="synthetic-vision",
        transport=httpx2.MockTransport(serve),
        budget=PostgresModelBudget(engine, policy()),
    ) as gateway:
        outcome, generator, platform = await replay(
            rpc,
            MediaDownloader(resolver=resolve, transport=httpx.MockTransport(download)),
            ImageDescriber(
                gateway, processor="synthetic:v1", image_tokens=image_tokens, window_tokens=16384
            ),
            ttl=ttl,
            parts=parts,
        )
    return outcome, generator, platform, requests


@pytest.mark.parametrize("image_tokens", [1, 5000])
async def test_media_reservation_counts_before_vision_request(database_url, image_tokens):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, generator, platform, requests = await run_image(engine, image_tokens=image_tokens)
        if image_tokens == 5000:
            assert outcome == "budget_denied"
            assert requests == [] and platform.sent == []
            assert len(generator.requests) == 1
        else:
            assert outcome == "confirmed"
            assert len(requests) == 1 and len(platform.sent) == 1
    finally:
        await engine.dispose()


@pytest.mark.parametrize("known_usage", [True, False])
async def test_vision_usage_and_unknown_reservations_survive_restart(database_url, known_usage):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, _, _, requests = await run_image(engine, image_tokens=1, known_usage=known_usage)
        assert outcome == "confirmed" and len(requests) == 1
    finally:
        await engine.dispose()

    rebuilt = create_async_engine(database_url, hide_parameters=True)
    try:
        snapshot = await PostgresModelBudget(rebuilt, policy()).snapshot()
        if known_usage:
            assert snapshot.spent == Decimal("0.000090")
            assert snapshot.reserved == Decimal(0)
        else:
            assert snapshot.spent == Decimal(0)
            assert Decimal("0.002") < snapshot.reserved <= Decimal("0.004")
        outcome, _, platform, requests = await run_image(rebuilt, image_tokens=1)
        if known_usage:
            assert outcome == "confirmed" and len(requests) == 1
        else:
            assert outcome == "budget_denied" and requests == [] and platform.sent == []
    finally:
        await rebuilt.dispose()


@pytest.mark.parametrize(
    "provider_mode,expected", [("stall", "expired"), ("reject", "media_error")]
)
async def test_failed_vision_keeps_unknown_cost_and_never_retries(
    database_url, provider_mode, expected
):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, generator, platform, requests = await asyncio.wait_for(
            run_image(engine, image_tokens=1, provider_mode=provider_mode, ttl=2), 6
        )
        assert outcome == expected
        assert len(requests) == 1 and platform.sent == []
        assert len(generator.requests) == 1
    finally:
        await engine.dispose()
    rebuilt = create_async_engine(database_url, hide_parameters=True)
    try:
        snapshot = await PostgresModelBudget(rebuilt, policy()).snapshot()
        assert snapshot.spent == Decimal(0)
        assert Decimal("0.002") < snapshot.reserved <= Decimal("0.004")
        outcome, _, platform, requests = await run_image(rebuilt, image_tokens=1)
        assert outcome == "budget_denied"
        assert requests == [] and platform.sent == []
    finally:
        await rebuilt.dispose()


@pytest.mark.parametrize("image_count", [1, 2])
async def test_joint_image_cost_reserves_each_image(database_url, image_count):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, _, platform, requests = await run_image(
            engine, image_tokens=1000, image_count=image_count
        )
        if image_count == 1:
            assert outcome == "confirmed" and len(requests) == 1
        else:
            assert outcome == "budget_denied" and requests == [] and platform.sent == []
    finally:
        await engine.dispose()
