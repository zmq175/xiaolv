from datetime import UTC, datetime, timedelta

from xiaolv.application.delivery import DeliveryRequest, DeliveryService

NOW = datetime(2026, 9, 29, tzinfo=UTC)


class Platform:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return "confirmed"


async def test_revocation_during_preparation_is_terminal_without_sending():
    allowed = True
    platform = Platform()

    async def authorize(conversation_id):
        assert conversation_id == "chat-1"
        return allowed

    async def prepare(request):
        nonlocal allowed
        allowed = False
        return platform

    delivery = DeliveryService(
        platform, lambda: NOW, lambda _: 1, prepare=prepare, authorize=authorize
    )
    request = DeliveryRequest("out-1", "chat-1", NOW + timedelta(seconds=30), 1, "你好")
    assert await delivery.deliver(request) == "not_sent"
    allowed = True
    assert await delivery.deliver(request) == "not_sent"
    assert platform.sent == []


async def test_permission_read_failure_does_not_send_or_leave_unknown(caplog):
    platform = Platform()

    async def authorize(conversation_id):
        raise RuntimeError("PRIVATE_PERMISSION_DATABASE_URL")

    delivery = DeliveryService(platform, lambda: NOW, lambda _: 1, authorize=authorize)
    request = DeliveryRequest("out-2", "chat-1", NOW + timedelta(seconds=30), 1, "你好")
    assert await delivery.deliver(request) == "not_sent"
    assert await delivery.status("out-2") == "not_sent"
    assert platform.sent == []
    assert "PRIVATE_PERMISSION_DATABASE_URL" not in caplog.text


async def test_permission_lookup_cannot_outlive_original_delivery_deadline():
    import asyncio

    platform = Platform()

    async def authorize(conversation_id):
        await asyncio.sleep(0.1)
        return True

    clock = lambda: datetime.now(UTC)
    delivery = DeliveryService(platform, clock, lambda _: 1, authorize=authorize)
    request = DeliveryRequest("out-3", "chat-1", clock() + timedelta(seconds=0.03), 1, "你好")
    assert await delivery.deliver(request) == "expired"
    assert platform.sent == []


async def test_cancel_during_permission_lookup_records_definitely_not_sent():
    import asyncio

    import pytest

    entered = asyncio.Event()
    platform = Platform()

    async def authorize(conversation_id):
        entered.set()
        await asyncio.Event().wait()

    delivery = DeliveryService(platform, lambda: NOW, lambda _: 1, authorize=authorize)
    request = DeliveryRequest("out-4", "chat-1", NOW + timedelta(seconds=30), 1, "你好")
    task = asyncio.create_task(delivery.deliver(request))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await delivery.status("out-4") == "not_sent"
    assert platform.sent == []


async def test_revocation_during_decision_prevents_reply_generation():
    from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime

    allowed = True
    calls = []
    platform = Platform()

    async def authorize(conversation_id):
        return allowed

    class Model:
        async def decide(self, candidate):
            nonlocal allowed
            calls.append("decide")
            allowed = False
            return "respond"

        async def reply(self, candidate):
            calls.append("reply")
            return "你好"

    delivery = DeliveryService(platform, lambda: NOW, lambda _: 1, authorize=authorize)
    runtime = TextRuntime(Model(), delivery, lambda: NOW)
    candidate = ConversationCandidate("chat-1", "turn-1", "在吗", NOW + timedelta(seconds=30), 1)
    assert await runtime.run(candidate) == "permission_denied"
    assert calls == ["decide"]
    assert platform.sent == []


async def test_denied_conversation_skips_all_model_calls():
    from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime

    async def authorize(conversation_id):
        return False

    class Model:
        async def decide(self, candidate):
            raise AssertionError("model must not run")

    platform = Platform()
    delivery = DeliveryService(platform, lambda: NOW, lambda _: 1, authorize=authorize)
    runtime = TextRuntime(Model(), delivery, lambda: NOW)
    candidate = ConversationCandidate("chat-1", "turn-2", "在吗", NOW + timedelta(seconds=30), 1)
    assert await runtime.run(candidate) == "permission_denied"
    assert platform.sent == []


async def test_revocation_during_generation_prevents_send():
    from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime

    allowed = True

    async def authorize(conversation_id):
        return allowed

    class Model:
        async def decide(self, candidate):
            return "respond"

        async def reply(self, candidate):
            nonlocal allowed
            allowed = False
            return "你好"

    platform = Platform()
    delivery = DeliveryService(platform, lambda: NOW, lambda _: 1, authorize=authorize)
    runtime = TextRuntime(Model(), delivery, lambda: NOW)
    candidate = ConversationCandidate("chat-1", "turn-3", "在吗", NOW + timedelta(seconds=30), 1)
    assert await runtime.run(candidate) == "not_sent"
    assert platform.sent == []


async def test_confirmed_delivery_remains_confirmed_after_revocation():
    allowed = True

    async def authorize(conversation_id):
        return allowed

    platform = Platform()
    delivery = DeliveryService(platform, lambda: NOW, lambda _: 1, authorize=authorize)
    request = DeliveryRequest("out-5", "chat-1", NOW + timedelta(seconds=30), 1, "你好")
    assert await delivery.deliver(request) == "confirmed"
    allowed = False
    assert await delivery.deliver(request) == "confirmed"
    assert len(platform.sent) == 1


async def test_new_turn_during_permission_lookup_supersedes_old_reply():
    epoch = 1
    platform = Platform()

    async def authorize(conversation_id):
        nonlocal epoch
        epoch = 2
        return True

    delivery = DeliveryService(platform, lambda: NOW, lambda _: epoch, authorize=authorize)
    request = DeliveryRequest("out-6", "chat-1", NOW + timedelta(seconds=30), 1, "你好")
    assert await delivery.deliver(request) == "superseded"
    assert platform.sent == []
