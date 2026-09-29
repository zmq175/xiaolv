from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger


class RecordingPlatform:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return "confirmed"


def outgoing(epoch):
    return DeliveryRequest(
        "out-1", "chat-1", datetime.now(UTC) + timedelta(seconds=30), epoch, "合成消息"
    )


async def test_confirmed_delivery_survives_service_and_connection_recreation(database_url):
    platform = RecordingPlatform()
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        service = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
        request = outgoing(await service.start_turn("chat-1"))
        assert await service.deliver(request) == "confirmed"
    finally:
        await engine.dispose()
    restarted_engine = create_async_engine(database_url, hide_parameters=True)
    try:
        restarted = DeliveryService(platform, ledger=PostgresDeliveryLedger(restarted_engine))
        assert await restarted.status("out-1") == "confirmed"
        assert await restarted.deliver(request) == "confirmed"
        assert platform.sent == [request]
    finally:
        await restarted_engine.dispose()


async def test_competing_instances_claim_one_send(database_url):
    import asyncio

    platform = RecordingPlatform()
    engines = [create_async_engine(database_url, hide_parameters=True) for _ in range(8)]
    try:
        services = [
            DeliveryService(platform, ledger=PostgresDeliveryLedger(engine)) for engine in engines
        ]
        request = outgoing(await services[0].start_turn("chat-1"))
        results = await asyncio.gather(*(service.deliver(request) for service in services))
        assert all(result in {"confirmed", "sending"} for result in results)
        assert platform.sent == [request]
    finally:
        for engine in engines:
            await engine.dispose()


async def test_new_turn_rejects_old_epoch_using_database_state(database_url):
    platform = RecordingPlatform()
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        service = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
        request = outgoing(await service.start_turn("chat-1"))
        next_epoch = await service.start_turn("chat-1")
        assert next_epoch == request.generation_epoch + 1
        assert await service.deliver(request) == "superseded"
        assert await service.status(request.outgoing_id) == "superseded"
        assert platform.sent == []
    finally:
        await engine.dispose()


async def test_database_expiry_prevents_sending_even_with_old_epoch(database_url):
    from dataclasses import replace

    platform = RecordingPlatform()
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        service = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
        request = outgoing(await service.start_turn("chat-1"))
        await service.start_turn("chat-1")
        expired = replace(request, expires_at=datetime.now(UTC) - timedelta(seconds=1))
        assert await service.deliver(expired) == "expired"
        assert await service.status("out-1") == "expired"
        assert platform.sent == []
    finally:
        await engine.dispose()


async def test_reusing_persistent_id_for_changed_content_is_rejected(database_url):
    from dataclasses import replace

    import pytest

    platform = RecordingPlatform()
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        service = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
        request = outgoing(await service.start_turn("chat-1"))
        await service.deliver(request)
        with pytest.raises(ValueError, match="conflict"):
            await service.deliver(replace(request, text="不应覆盖"))
        assert platform.sent == [request]
        assert await service.status("out-1") == "confirmed"
    finally:
        await engine.dispose()


async def test_lost_receipt_remains_unknown_across_instances(database_url):
    class LostReceipt(RecordingPlatform):
        async def send(self, request):
            self.sent.append(request)
            raise TimeoutError("receipt lost")

    platform = LostReceipt()
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        first = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
        request = outgoing(await first.start_turn("chat-1"))
        assert await first.deliver(request) == "unknown"
        second = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
        assert await second.deliver(request) == "unknown"
        assert platform.sent == [request]
    finally:
        await engine.dispose()


async def test_crashed_sender_is_recovered_as_unknown_without_resend(database_url):
    import asyncio

    import pytest

    class ProcessDisappeared(BaseException):
        pass

    class CrashPlatform(RecordingPlatform):
        async def send(self, request):
            self.sent.append(request)
            raise ProcessDisappeared

    platform = CrashPlatform()
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        first = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine, lease_seconds=0.2))
        request = outgoing(await first.start_turn("chat-1"))
        with pytest.raises(ProcessDisappeared):
            await first.deliver(request)
        restarted = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
        assert await restarted.status("out-1") == "sending"
        assert await restarted.recover() == 0
        await asyncio.sleep(0.25)
        assert await restarted.recover() == 1
        assert await restarted.status("out-1") == "unknown"
        assert await restarted.deliver(request) == "unknown"
        assert platform.sent == [request]
    finally:
        await engine.dispose()


async def test_late_worker_cannot_overwrite_recovered_terminal_state(database_url):
    import asyncio

    started = asyncio.Event()
    release = asyncio.Event()

    class SlowPlatform(RecordingPlatform):
        async def send(self, request):
            self.sent.append(request)
            started.set()
            await release.wait()
            return "confirmed"

    platform = SlowPlatform()
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        service = DeliveryService(
            platform, ledger=PostgresDeliveryLedger(engine, lease_seconds=0.1)
        )
        request = outgoing(await service.start_turn("chat-1"))
        task = asyncio.create_task(service.deliver(request))
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.sleep(0.15)
        assert await service.recover() == 1
        release.set()
        assert await asyncio.wait_for(task, 1) == "unknown"
        assert await service.status("out-1") == "unknown"
    finally:
        release.set()
        await engine.dispose()


async def test_other_conversation_is_not_blocked_by_slow_send(database_url):
    import asyncio
    from dataclasses import replace

    started = asyncio.Event()
    release = asyncio.Event()

    class SlowFirstPlatform(RecordingPlatform):
        async def send(self, request):
            if request.conversation_id == "chat-1":
                started.set()
                await release.wait()
            return await super().send(request)

    platform = SlowFirstPlatform()
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        service = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
        first = outgoing(await service.start_turn("chat-1"))
        second_epoch = await service.start_turn("chat-2")
        task = asyncio.create_task(service.deliver(first))
        await asyncio.wait_for(started.wait(), 1)
        second = replace(
            first, outgoing_id="out-2", conversation_id="chat-2", generation_epoch=second_epoch
        )
        assert await asyncio.wait_for(service.deliver(second), 1) == "confirmed"
        # A new epoch can be committed while the prior network call is still waiting.
        assert await asyncio.wait_for(service.start_turn("chat-1"), 1) == 2
        release.set()
        assert await asyncio.wait_for(task, 1) == "confirmed"
    finally:
        release.set()
        await engine.dispose()


async def test_downgraded_database_fails_closed_then_upgrade_restores_service(database_url):
    import pytest
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import ProgrammingError

    engine = create_async_engine(database_url, hide_parameters=True)
    platform = RecordingPlatform()
    try:

        def migrate(connection, revision):
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            if revision == "base":
                command.downgrade(config, revision)
            else:
                command.upgrade(config, revision)

        async with engine.begin() as connection:
            await connection.run_sync(migrate, "base")
        service = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
        with pytest.raises(ProgrammingError):
            await service.deliver(outgoing(1))
        assert platform.sent == []
        async with engine.begin() as connection:
            await connection.run_sync(migrate, "head")
        request = outgoing(await service.start_turn("chat-1"))
        assert await service.deliver(request) == "confirmed"
    finally:
        await engine.dispose()
