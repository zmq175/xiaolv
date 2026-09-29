"""SIGKILL after durable reservation and before any provider response."""

import asyncio
import json
import os
import signal
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


class NoPlatform:
    async def send(self, request):
        raise AssertionError("crashed model cannot send")


async def main():
    engine = create_async_engine(os.environ["XIAOLV_TEST_DATABASE_URL"], hide_parameters=True)
    policy = BudgetPolicy(
        "external",
        "synthetic-provider",
        "synthetic-model",
        "test-v1",
        Decimal(1),
        Decimal(1),
        Decimal(2),
    )
    budget = PostgresModelBudget(engine, policy)

    async def serve(request):
        snapshot = await budget.snapshot()
        print(json.dumps({"reserved": str(snapshot.reserved)}), flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("SIGKILL did not terminate")

    clock = lambda: datetime.now(UTC)
    async with ChatCompletionsGateway(
        base_url="https://model.example/v1",
        api_key="synthetic",
        model="synthetic-model",
        transport=httpx.MockTransport(serve),
        budget=budget,
    ) as gateway:
        runtime = TextRuntime(
            ChatCompletionsModel(gateway), DeliveryService(NoPlatform(), clock, lambda _: 1), clock
        )
        await runtime.run(
            ConversationCandidate(
                "chat-1", "event-1", "合成消息", clock() + timedelta(seconds=45), 1
            )
        )
    raise AssertionError("crash fixture did not run")


asyncio.run(main())
