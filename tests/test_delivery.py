import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from xiaolv.application.delivery import DeliveryRequest, DeliveryService

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


class RecordingPlatform:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return "confirmed"


def request(*, expiry=NOW + timedelta(seconds=45), epoch=3, text="你好"):
    return DeliveryRequest("out-1", "chat-1", expiry, epoch, text)


async def test_expired_reply_never_reaches_platform():
    platform = RecordingPlatform()
    service = DeliveryService(platform, lambda: NOW, lambda _: 3)
    assert await service.deliver(request(expiry=NOW)) == "expired"
    assert platform.sent == []


async def test_valid_reply_reaches_native_platform():
    platform = RecordingPlatform()
    service = DeliveryService(platform, lambda: NOW, lambda _: 3)
    outgoing = request()
    assert await service.deliver(outgoing) == "confirmed"
    assert platform.sent == [outgoing]


async def test_old_epoch_never_reaches_platform():
    platform = RecordingPlatform()
    service = DeliveryService(platform, lambda: NOW, lambda _: 4)
    assert await service.deliver(request()) == "superseded"
    assert platform.sent == []


async def test_repeated_id_is_delivered_once_and_status_is_queryable():
    platform = RecordingPlatform()
    service = DeliveryService(platform, lambda: NOW, lambda _: 3)
    outgoing = request()
    assert await service.deliver(outgoing) == "confirmed"
    assert await service.deliver(outgoing) == "confirmed"
    assert platform.sent == [outgoing]
    assert service.status(outgoing.outgoing_id) == "confirmed"


async def test_concurrent_duplicate_is_delivered_once():
    class YieldingPlatform(RecordingPlatform):
        async def send(self, outgoing):
            await asyncio.sleep(0)
            return await super().send(outgoing)

    platform = YieldingPlatform()
    service = DeliveryService(platform, lambda: NOW, lambda _: 3)
    outgoing = request()
    results = await asyncio.gather(service.deliver(outgoing), service.deliver(outgoing))
    assert results == ["confirmed", "confirmed"]
    assert platform.sent == [outgoing]


async def test_lost_receipt_is_unknown_and_never_retried():
    class LostReceiptPlatform(RecordingPlatform):
        async def send(self, outgoing):
            self.sent.append(outgoing)
            raise TimeoutError("receipt lost")

    platform = LostReceiptPlatform()
    service = DeliveryService(platform, lambda: NOW, lambda _: 3)
    outgoing = request()
    assert await service.deliver(outgoing) == "unknown"
    assert await service.deliver(outgoing) == "unknown"
    assert service.status(outgoing.outgoing_id) == "unknown"
    assert platform.sent == [outgoing]


async def test_reusing_id_for_changed_payload_is_rejected():
    platform = RecordingPlatform()
    service = DeliveryService(platform, lambda: NOW, lambda _: 3)
    outgoing = request()
    await service.deliver(outgoing)
    with pytest.raises(ValueError, match="conflict"):
        await service.deliver(request(text="另一条消息"))
    assert platform.sent == [outgoing]


async def test_waiting_reply_is_checked_again_after_queue_delay():
    from dataclasses import replace

    started = asyncio.Event()
    release = asyncio.Event()
    now = NOW

    class PausedPlatform(RecordingPlatform):
        async def send(self, outgoing):
            self.sent.append(outgoing)
            started.set()
            await release.wait()
            return "confirmed"

    platform = PausedPlatform()
    service = DeliveryService(platform, lambda: now, lambda _: 3)
    first = request()
    task = asyncio.create_task(service.deliver(first))
    await asyncio.wait_for(started.wait(), timeout=1)
    queued = asyncio.create_task(service.deliver(replace(first, outgoing_id="out-2")))
    await asyncio.sleep(0)
    now = NOW + timedelta(minutes=30)
    release.set()
    assert await asyncio.wait_for(task, timeout=1) == "confirmed"
    assert await asyncio.wait_for(queued, timeout=1) == "expired"
    assert platform.sent == [first]


async def test_cancelling_inflight_send_records_unknown_without_retry():
    started = asyncio.Event()

    class HangingPlatform(RecordingPlatform):
        async def send(self, outgoing):
            self.sent.append(outgoing)
            started.set()
            await asyncio.Event().wait()

    platform = HangingPlatform()
    service = DeliveryService(platform, lambda: NOW, lambda _: 3)
    outgoing = request()
    task = asyncio.create_task(service.deliver(outgoing))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert service.status(outgoing.outgoing_id) == "unknown"
    assert await service.deliver(outgoing) == "unknown"
    assert platform.sent == [outgoing]


async def test_explicit_not_sent_is_distinct_from_unknown():
    from xiaolv.application.delivery import NotSent

    class RejectingPlatform(RecordingPlatform):
        async def send(self, outgoing):
            raise NotSent("connection unavailable before send")

    platform = RejectingPlatform()
    service = DeliveryService(platform, lambda: NOW, lambda _: 3)
    assert await service.deliver(request()) == "not_sent"
    assert service.status("out-1") == "not_sent"
    assert platform.sent == []


async def test_rejected_reply_has_stable_terminal_status():
    epoch = 4
    platform = RecordingPlatform()
    service = DeliveryService(platform, lambda: NOW, lambda _: epoch)
    outgoing = request()
    assert await service.deliver(outgoing) == "superseded"
    assert service.status(outgoing.outgoing_id) == "superseded"
    epoch = 3
    assert await service.deliver(outgoing) == "superseded"
    assert platform.sent == []
