import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.application.delivery import DeliveryService
from xiaolv.domain.model_budget import BudgetPolicy
from xiaolv.models.chat_completions import ChatCompletionsGateway
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime
from xiaolv.storage.postgres_budget import PostgresModelBudget


def policy(limit="0.001"):
    return BudgetPolicy(
        "external",
        "synthetic-provider",
        "synthetic-model",
        "test-v1",
        Decimal(limit),
        Decimal(1),
        Decimal(2),
    )


def response(usage=None):
    chunks = [
        {
            "choices": [
                {"index": 0, "delta": {"content": '{"action":"silence"}'}, "finish_reason": "stop"}
            ]
        }
    ]
    if usage is not None:
        chunks.append({"choices": [], "usage": usage})
    body = "".join("data: " + json.dumps(item) + "\n\n" for item in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


class NoPlatform:
    async def send(self, request):
        raise AssertionError("silent or denied turn must not send")


def runner(gateway):
    clock = lambda: datetime.now(UTC)
    return TextRuntime(
        ChatCompletionsModel(gateway), DeliveryService(NoPlatform(), clock, lambda _: 1), clock
    )


def candidate():
    return ConversationCandidate(
        "chat-1", "event-1", "合成测试", datetime.now(UTC) + timedelta(seconds=45), 1
    )


async def test_insufficient_monthly_budget_prevents_any_provider_request(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    calls = []

    async def serve(request):
        calls.append(request)
        return response()

    try:
        budget = PostgresModelBudget(engine, policy())
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "budget_denied"
        assert calls == []
    finally:
        await engine.dispose()


async def test_known_usage_is_settled_and_survives_rebuilding_connection(database_url):
    reports = []

    async def record(report):
        reports.append(report)

    async def serve(request):
        return response(
            {
                "prompt_tokens": 80,
                "completion_tokens": 5,
                "total_tokens": 85,
                "prompt_tokens_details": {"cached_tokens": 32},
            }
        )

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        budget = PostgresModelBudget(engine, policy("1"))
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
            usage_sink=record,
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "silence"
    finally:
        await engine.dispose()
    rebuilt = create_async_engine(database_url, hide_parameters=True)
    try:
        budget = PostgresModelBudget(rebuilt, policy("1"))
        snapshot = await budget.snapshot()
        assert snapshot.limit == Decimal(1)
        assert snapshot.reserved == Decimal(0)
        assert snapshot.spent == Decimal("0.000090")
        assert snapshot.blocked is False
        audit = await budget.audit(reports[0].call_id)
        assert audit.state == "settled"
        assert audit.price_version == "test-v1"
        assert audit.charged_amount == Decimal("0.000090")
        assert audit.report == reports[0]
    finally:
        await rebuilt.dispose()


async def test_actual_cost_over_reservation_is_recorded_and_blocks_new_calls(database_url):
    calls = []

    async def serve(request):
        calls.append(request)
        return response({"prompt_tokens": 20000, "completion_tokens": 0, "total_tokens": 20000})

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        budget = PostgresModelBudget(engine, policy("1"))
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "silence"
            snapshot = await budget.snapshot()
            assert snapshot.spent == Decimal("0.020000")
            assert snapshot.reserved == Decimal(0)
            assert snapshot.blocked is True
            assert await runner(gateway).run(candidate()) == "budget_denied"
        assert len(calls) == 1
    finally:
        await engine.dispose()


async def test_unknown_usage_keeps_reservation_across_restarts(database_url):
    reports = []

    async def record(report):
        reports.append(report)

    async def serve(request):
        return response()

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        budget = PostgresModelBudget(engine, policy("1"))
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
            usage_sink=record,
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "silence"
        before = await budget.snapshot()
        assert before.reserved > 0
        assert before.spent == Decimal(0)
    finally:
        await engine.dispose()
    rebuilt = create_async_engine(database_url, hide_parameters=True)
    try:
        budget = PostgresModelBudget(rebuilt, policy("1"))
        assert await budget.snapshot() == before
        audit = await budget.audit(reports[0].call_id)
        assert audit.state == "unknown"
        assert audit.charged_amount is None
        assert audit.report.usage is None
    finally:
        await rebuilt.dispose()


async def test_shared_budget_prevents_parallel_workers_spending_last_allowance_twice(database_url):
    import asyncio
    from dataclasses import replace

    calls = []

    async def serve(request):
        calls.append(request)
        return response()

    engines = [create_async_engine(database_url, hide_parameters=True) for _ in range(2)]
    try:
        # Measure the immutable reservation for this exact synthetic request through audit.
        budget = PostgresModelBudget(engines[0], policy("1"))
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "silence"
        reserved = (await budget.snapshot()).reserved
        constrained = replace(policy("1"), pool_id="last-allowance", monthly_limit=reserved)
        calls.clear()

        async def run(engine):
            budget = PostgresModelBudget(engine, constrained)
            async with ChatCompletionsGateway(
                base_url="https://model.example/v1",
                api_key="synthetic",
                model="synthetic-model",
                transport=httpx.MockTransport(serve),
                budget=budget,
            ) as gateway:
                return await runner(gateway).run(candidate())

        results = await asyncio.gather(*(run(engine) for engine in engines))
        assert sorted(results) == ["budget_denied", "silence"]
        assert len(calls) == 1
        after = await PostgresModelBudget(engines[1], constrained).snapshot()
        assert after.reserved == reserved
    finally:
        for engine in engines:
            await engine.dispose()


async def test_replayed_audit_is_idempotent_and_conflicting_report_is_rejected(database_url):
    from dataclasses import replace

    import pytest

    reports = []

    async def record(report):
        reports.append(report)

    async def serve(request):
        return response({"prompt_tokens": 80, "completion_tokens": 5, "total_tokens": 85})

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        budget = PostgresModelBudget(engine, policy("1"))
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
            usage_sink=record,
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "silence"
        before = await budget.snapshot()
        await budget.settle(reports[0])
        assert await budget.snapshot() == before
        with pytest.raises(ValueError, match="conflict"):
            await budget.settle(replace(reports[0], status="failed"))
        assert await budget.snapshot() == before
    finally:
        await engine.dispose()


async def test_cache_discount_uses_configured_price_and_microyuan_rounds_up(database_url):
    from dataclasses import replace

    async def serve(request):
        return response(
            {
                "prompt_tokens": 80,
                "completion_tokens": 5,
                "total_tokens": 85,
                "prompt_tokens_details": {"cached_tokens": 32},
            }
        )

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        priced = replace(policy("1"), cached_input_per_million=Decimal("0.333333"))
        budget = PostgresModelBudget(engine, priced)
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "silence"
        assert (await budget.snapshot()).spent == Decimal("0.000069")
    finally:
        await engine.dispose()


async def test_cancelled_model_keeps_durable_reservation(database_url):
    import asyncio

    reports = []
    entered = asyncio.Event()

    async def record(report):
        reports.append(report)

    async def serve(request):
        entered.set()
        await asyncio.Event().wait()

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        budget = PostgresModelBudget(engine, policy("1"))
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
            usage_sink=record,
        ) as gateway:
            task = asyncio.create_task(runner(gateway).run(candidate()))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                reserved = (await budget.snapshot()).reserved
                assert reserved > 0
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                assert task.cancelled()
                snapshot = await budget.snapshot()
                assert snapshot.reserved == reserved
                assert snapshot.spent == Decimal(0)
                audit = await budget.audit(reports[0].call_id)
                assert audit.state == "unknown"
                assert audit.report.status == "cancelled"
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    finally:
        await engine.dispose()


async def test_different_configured_limit_cannot_silently_increase_live_budget(database_url):
    async def serve(request):
        return response()

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=PostgresModelBudget(engine, policy("1")),
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "silence"
        calls = []

        async def forbidden(request):
            calls.append(request)
            return response()

        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(forbidden),
            budget=PostgresModelBudget(engine, policy("2")),
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "budget_denied"
        assert calls == []
        assert (await PostgresModelBudget(engine, policy("1")).snapshot()).limit == Decimal(1)
    finally:
        await engine.dispose()


async def test_sigkill_after_request_start_does_not_release_reservation(database_url):
    import asyncio
    import os
    import signal
    import sys

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "tests/helpers/crash_model_budget.py",
        env={
            "PATH": os.defpath,
            "PYTHONPATH": "src",
            "LANGSMITH_TRACING": "false",
            "XIAOLV_TEST_DATABASE_URL": database_url,
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert process.returncode == -signal.SIGKILL, stderr.decode()
    held = Decimal(json.loads(stdout)["reserved"])
    assert held > 0
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        snapshot = await PostgresModelBudget(engine, policy("1")).snapshot()
        assert snapshot.reserved == held
        assert snapshot.spent == Decimal(0)
    finally:
        await engine.dispose()


async def test_late_settlement_uses_original_month_and_price_version(database_url):
    from dataclasses import replace
    from datetime import date

    from sqlalchemy import text

    from xiaolv.domain.model_usage import ModelCallReport, TokenUsage

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        # Historical fixture represents an unresolved call from a previous billing month.
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO app.budget_periods (pool_id, period, limit_amount, reserved) VALUES ('external', '2001-02-01', 1, 0.1)"
                )
            )
            await connection.execute(
                text("""
                INSERT INTO app.model_calls (call_id, pool_id, period, provider_id, model, price_version, input_rate, output_rate, reserved_amount, started_at)
                VALUES ('historical-call', 'external', '2001-02-01', 'synthetic-provider', 'synthetic-model', 'old-price', 1, 2, 0.1, '2001-02-28T23:59:00Z')
            """)
            )
        changed = replace(
            policy("1"),
            price_version="new-price",
            input_per_million=Decimal(99),
            output_per_million=Decimal(99),
        )
        budget = PostgresModelBudget(engine, changed)
        report = ModelCallReport(
            "historical-call",
            "synthetic-model",
            datetime(2001, 2, 28, 23, 59, tzinfo=UTC),
            datetime.now(UTC),
            "completed",
            TokenUsage(80, 5, 85),
        )
        await budget.settle(report)
        old = await budget.snapshot(period=date(2001, 2, 1))
        assert old.reserved == Decimal(0)
        assert old.spent == Decimal("0.000090")
        assert (await budget.snapshot()).spent == Decimal(0)
        audit = await budget.audit("historical-call")
        assert audit.period == "2001-02-01"
        assert audit.price_version == "old-price"
    finally:
        await engine.dispose()


async def test_database_failure_before_reservation_commit_never_calls_provider(database_url):
    from sqlalchemy import text

    calls = []

    async def serve(request):
        calls.append(request)
        return response()

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        # Fault injection in a disposable database, not a private-state assertion.
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE app.model_calls"))
        budget = PostgresModelBudget(engine, policy("1"))
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "model_error"
        assert calls == []
        assert (await budget.snapshot()).reserved == Decimal(0)
    finally:
        await engine.dispose()


async def test_model_without_matching_price_cannot_make_paid_request(database_url):
    from dataclasses import replace

    calls = []

    async def serve(request):
        calls.append(request)
        return response()

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        budget = PostgresModelBudget(engine, replace(policy("1"), model="different-priced-model"))
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "budget_denied"
        assert calls == []
    finally:
        await engine.dispose()


async def test_failed_settlement_preserves_previously_committed_reservation(database_url):
    from sqlalchemy import text

    calls = []
    engine = create_async_engine(database_url, hide_parameters=True)

    async def serve(request):
        calls.append(request)
        return response({"prompt_tokens": 80, "completion_tokens": 5, "total_tokens": 85})

    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "ALTER TABLE app.budget_periods ADD CONSTRAINT injected_settlement_fault CHECK (spent = 0)"
                )
            )
        budget = PostgresModelBudget(engine, policy("1"))
        async with ChatCompletionsGateway(
            base_url="https://model.example/v1",
            api_key="synthetic",
            model="synthetic-model",
            transport=httpx.MockTransport(serve),
            budget=budget,
        ) as gateway:
            assert await runner(gateway).run(candidate()) == "model_error"
        snapshot = await budget.snapshot()
        assert snapshot.reserved > 0
        assert snapshot.spent == Decimal(0)
        assert len(calls) == 1
    finally:
        await engine.dispose()
