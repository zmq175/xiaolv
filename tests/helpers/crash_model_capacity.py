"""Die after shared admission, while the provider request is beginning."""

import asyncio
import os
import signal
from datetime import UTC, datetime, timedelta

import httpx2 as httpx
from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.models.chat_completions import ChatCompletionsGateway
from xiaolv.storage.postgres_model_capacity import PostgresModelCapacity


async def main():
    engine = create_async_engine(os.environ["XIAOLV_TEST_DATABASE_URL"], hide_parameters=True)
    expires_at = datetime.now(UTC) + timedelta(seconds=1)

    async def serve(request):
        print(expires_at.timestamp(), flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("SIGKILL did not terminate")

    async with ChatCompletionsGateway(
        base_url="https://model.example/v1",
        api_key="synthetic",
        model="synthetic",
        transport=httpx.MockTransport(serve),
        shared_capacity=PostgresModelCapacity(engine, "chat-model", 1),
    ) as gateway:
        await gateway.generate(instructions="test", context="{}", schema={}, expires_at=expires_at)


asyncio.run(main())
