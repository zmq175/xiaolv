from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.domain.text_reply import TextPart
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger


class Platform:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return "confirmed"


async def test_restart_preserves_order_for_idempotency(database_url):
    platform = Platform()
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        service = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
        epoch = await service.start_turn("chat")
        request = DeliveryRequest(
            "out",
            "chat",
            datetime.now(UTC) + timedelta(seconds=30),
            epoch,
            "请看看",
            mentions=("qq:10002",),
            parts=(
                TextPart("text", "请"),
                TextPart("mention", "qq:10002"),
                TextPart("text", "看看"),
            ),
        )
        assert await service.deliver(request) == "confirmed"
    finally:
        await engine.dispose()
    restarted = create_async_engine(database_url, hide_parameters=True)
    try:
        service = DeliveryService(platform, ledger=PostgresDeliveryLedger(restarted))
        assert await service.deliver(request) == "confirmed"
        changed = replace(
            request, parts=(TextPart("mention", "qq:10002"), TextPart("text", "请看看"))
        )
        with pytest.raises(ValueError, match="conflict"):
            await service.deliver(changed)
        assert platform.sent == [request]
    finally:
        await restarted.dispose()
