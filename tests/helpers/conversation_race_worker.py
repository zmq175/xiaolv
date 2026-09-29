"""Synthetic process for management revocation at public execution boundaries."""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.storage.conversation_control import ConversationControl
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger


async def main():
    engine = create_async_engine(os.environ["XIAOLV_TEST_WORKER_DB"], hide_parameters=True)
    mode = sys.argv[1]
    sent = []

    async def pause():
        print("ready", flush=True)
        await asyncio.to_thread(sys.stdin.readline)

    class Platform:
        async def send(self, request):
            sent.append(request.outgoing_id)
            if mode == "inflight":
                await pause()
            return "confirmed"

    async def authorize(conversation):
        allowed = await ConversationControl(engine).allowed(conversation)
        if mode == "before_claim":
            await pause()
        return allowed

    try:
        service = DeliveryService(
            Platform(), ledger=PostgresDeliveryLedger(engine), authorize=authorize
        )
        epoch = await service.start_turn("qq:1:group:2")
        request = DeliveryRequest(
            "worker", "qq:1:group:2", datetime.now(UTC) + timedelta(seconds=30), epoch, "合成消息"
        )
        result = await service.deliver(request)
        print(json.dumps({"status": result, "sent": len(sent)}), flush=True)
    finally:
        await engine.dispose()


asyncio.run(main())
