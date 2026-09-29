import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx2 as httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.application.delivery import DeliveryService
from xiaolv.models.chat_completions import ChatCompletionsGateway
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime


class NoPlatform:
    async def send(self, request):
        raise AssertionError("silent turn cannot send")


def runner(gateway):
    clock = lambda: datetime.now(UTC)
    return TextRuntime(
        ChatCompletionsModel(gateway), DeliveryService(NoPlatform(), clock, lambda _: 1), clock
    )


def candidate():
    return ConversationCandidate(
        "chat-1", "turn-1", "合成消息", datetime.now(UTC) + timedelta(seconds=5), 1
    )


def response():
    chunk = {
        "choices": [
            {"index": 0, "delta": {"content": '{"action":"silence"}'}, "finish_reason": "stop"}
        ]
    }
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode(),
    )


@pytest.mark.parametrize("cancel_first", [False, True])
async def test_shared_capacity_wait_expires_before_second_provider_call(database_url, cancel_first):
    from decimal import Decimal

    from xiaolv.domain.model_budget import BudgetPolicy
    from xiaolv.storage.postgres_budget import PostgresModelBudget
    from xiaolv.storage.postgres_model_capacity import PostgresModelCapacity

    engines = [create_async_engine(database_url, hide_parameters=True) for _ in range(2)]
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def serve(request):
        calls.append(request)
        started.set()
        await release.wait()
        return response()

    first = None
    budget = PostgresModelBudget(
        engines[1],
        BudgetPolicy(
            "capacity-test", "synthetic", "synthetic", "test", Decimal(1), Decimal(1), Decimal(2)
        ),
    )
    try:
        async with (
            ChatCompletionsGateway(
                base_url="https://model.example/v1",
                api_key="synthetic",
                model="synthetic",
                transport=httpx.MockTransport(serve),
                shared_capacity=PostgresModelCapacity(engines[0], "chat-model", 1),
            ) as one,
            ChatCompletionsGateway(
                base_url="https://model.example/v1",
                api_key="synthetic",
                model="synthetic",
                transport=httpx.MockTransport(serve),
                shared_capacity=PostgresModelCapacity(engines[1], "chat-model", 1),
                budget=budget,
            ) as two,
        ):
            first = asyncio.create_task(runner(one).run(candidate()))
            await asyncio.wait_for(started.wait(), 2)
            short = replace(
                candidate(),
                event_id="turn-2",
                expires_at=datetime.now(UTC) + timedelta(milliseconds=100),
            )
            assert await runner(two).run(short) == "expired"
            assert len(calls) == 1
            assert (await budget.snapshot()).reserved == 0
            assert (await budget.snapshot()).spent == 0
            if cancel_first:
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
            release.set()
            if not cancel_first:
                assert await asyncio.wait_for(first, 2) == "silence"
            assert await runner(two).run(replace(candidate(), event_id="fresh")) == "silence"
            assert len(calls) == 2
    finally:
        release.set()
        if first is not None:
            await asyncio.gather(first, return_exceptions=True)
        for engine in engines:
            await engine.dispose()


async def test_capacity_configuration_mismatch_cannot_start_provider_call(database_url):
    from xiaolv.storage.postgres_model_capacity import PostgresModelCapacity

    engine = create_async_engine(database_url, hide_parameters=True)
    calls = []

    async def serve(request):
        calls.append(request)
        return response()

    try:
        for capacity, expected in [(1, "silence"), (2, "model_error")]:
            async with ChatCompletionsGateway(
                base_url="https://model.example/v1",
                api_key="synthetic",
                model="synthetic",
                transport=httpx.MockTransport(serve),
                shared_capacity=PostgresModelCapacity(engine, "chat-model", capacity),
            ) as gateway:
                assert await runner(gateway).run(candidate()) == expected
        assert len(calls) == 1
    finally:
        await engine.dispose()


async def test_sigkill_lease_blocks_then_expires_without_manual_cleanup(database_url):
    import os
    import signal
    import sys

    from xiaolv.storage.postgres_model_capacity import PostgresModelCapacity

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "tests/helpers/crash_model_capacity.py",
        env={**os.environ, "PYTHONPATH": "src", "XIAOLV_TEST_DATABASE_URL": database_url},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
        assert process.returncode == -signal.SIGKILL, stderr.decode()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    expires_at = float(stdout.decode().strip())
    engine = create_async_engine(database_url, hide_parameters=True)
    calls = []

    async def serve(request):
        calls.append(request)
        return response()

    try:
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic",
            transport=httpx.MockTransport(serve),
            shared_capacity=PostgresModelCapacity(engine, "chat-model", 1),
        ) as gateway:
            short = replace(candidate(), expires_at=datetime.now(UTC) + timedelta(milliseconds=100))
            assert await runner(gateway).run(short) == "expired"
            assert calls == []
            await asyncio.sleep(max(0, expires_at + 5.1 - datetime.now(UTC).timestamp()))
            assert await runner(gateway).run(candidate()) == "silence"
            assert len(calls) == 1
    finally:
        await engine.dispose()
