from datetime import UTC, datetime, timedelta

from xiaolv.application.delivery import DeliveryService
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


class FakeModel:
    async def decide(self, candidate):
        return "silence"

    async def reply(self, candidate):
        raise AssertionError("silence should not generate text")


class RecordingPlatform:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return "confirmed"


def candidate():
    return ConversationCandidate(
        "chat-1", "event-1", "大家在聊什么", NOW + timedelta(seconds=45), 3
    )


def setup(model, clock=lambda: NOW, **kwargs):
    platform = RecordingPlatform()
    delivery = DeliveryService(platform, clock, lambda _: 3)
    return TextRuntime(model, delivery, clock, **kwargs), platform


async def test_model_can_choose_silence_without_generating_or_sending():
    runtime, platform = setup(FakeModel())
    assert await runtime.run(candidate()) == "silence"
    assert platform.sent == []


class ReplyModel(FakeModel):
    async def decide(self, candidate):
        return "respond"

    async def reply(self, candidate):
        return "我也在听，你们继续。"


async def test_model_reply_reaches_native_delivery():
    runtime, platform = setup(ReplyModel())
    assert await runtime.run(candidate()) == "confirmed"
    assert len(platform.sent) == 1
    assert platform.sent[0].text == "我也在听，你们继续。"
    assert platform.sent[0].conversation_id == "chat-1"


async def test_model_cannot_notify_an_account_absent_from_conversation_context():
    from xiaolv.domain.text_reply import TextReply

    class UnknownMember(ReplyModel):
        async def reply(self, candidate):
            return TextReply("你好", ("qq:99999",))

    runtime, platform = setup(UnknownMember())
    assert await runtime.run(candidate()) == "model_error"
    assert platform.sent == []


async def test_member_in_other_conversation_is_not_a_valid_notification_target():
    from dataclasses import replace

    from xiaolv.domain.chat_event import ChatEvent, ConversationContext
    from xiaolv.domain.text_reply import TextReply

    class CrossScopeMember(ReplyModel):
        async def reply(self, candidate):
            return TextReply("你好", ("qq:99999",))

    other = ChatEvent("other-chat", "qq:99999", "m-1", "其他群消息", "群友", NOW, NOW, NOW)
    runtime, platform = setup(CrossScopeMember())
    event = replace(candidate(), context=ConversationContext(1, (other,)))
    assert await runtime.run(event) == "model_error"
    assert platform.sent == []


async def test_expired_candidate_does_not_call_model():
    from dataclasses import replace

    class ForbiddenModel(FakeModel):
        async def decide(self, candidate):
            raise AssertionError("expired event must not call model")

    runtime, platform = setup(ForbiddenModel())
    assert await runtime.run(replace(candidate(), expires_at=NOW)) == "expired"
    assert platform.sent == []


async def test_model_returning_thirty_minutes_late_never_sends():
    now = NOW

    class LateModel(ReplyModel):
        async def reply(self, event):
            nonlocal now
            now = NOW + timedelta(minutes=30)
            return "迟到的回复"

    runtime, platform = setup(LateModel(), clock=lambda: now)
    assert await runtime.run(candidate()) == "expired"
    assert platform.sent == []


async def test_hanging_model_is_cancelled_at_deadline():
    import asyncio
    from dataclasses import replace

    stopped = asyncio.Event()

    class HangingModel(FakeModel):
        async def decide(self, event):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    runtime, platform = setup(HangingModel())
    event = replace(candidate(), expires_at=NOW + timedelta(milliseconds=50))
    assert await asyncio.wait_for(runtime.run(event), timeout=1) == "expired"
    assert stopped.is_set()
    assert platform.sent == []


async def test_oversized_reply_is_not_split_or_sent():
    class VerboseModel(ReplyModel):
        async def reply(self, event):
            return "很长" * 101

    runtime, platform = setup(VerboseModel())
    assert await runtime.run(candidate()) == "invalid_reply"
    assert platform.sent == []


async def test_blank_reply_is_not_sent():
    class BlankModel(ReplyModel):
        async def reply(self, event):
            return " \n\t"

    runtime, platform = setup(BlankModel())
    assert await runtime.run(candidate()) == "invalid_reply"
    assert platform.sent == []


async def test_event_ids_are_scoped_to_conversation_and_replays_do_not_resend():
    from dataclasses import replace

    runtime, platform = setup(ReplyModel())
    event = candidate()
    assert await runtime.run(event) == "confirmed"
    assert await runtime.run(event) == "confirmed"
    assert await runtime.run(replace(event, conversation_id="chat-2")) == "confirmed"
    assert [item.conversation_id for item in platform.sent] == ["chat-1", "chat-2"]


async def test_provider_error_is_reported_without_sending():
    class FailingModel(FakeModel):
        async def decide(self, event):
            raise ConnectionError("provider unavailable")

    runtime, platform = setup(FailingModel())
    assert await runtime.run(candidate()) == "model_error"
    assert platform.sent == []


async def test_invalid_model_decision_never_generates_or_sends():
    class InvalidModel(FakeModel):
        async def decide(self, event):
            return "install_skill"

    runtime, platform = setup(InvalidModel())
    assert await runtime.run(candidate()) == "model_error"
    assert platform.sent == []


async def test_provider_timeout_before_deadline_is_model_error():
    class TimeoutModel(FakeModel):
        async def decide(self, event):
            raise TimeoutError("provider timed out before turn deadline")

    runtime, platform = setup(TimeoutModel())
    assert await runtime.run(candidate()) == "model_error"
    assert platform.sent == []


async def test_replay_keeps_first_response_when_model_is_nondeterministic():
    import asyncio

    class ChangingModel(ReplyModel):
        def __init__(self):
            self.counter = 0

        async def reply(self, event):
            self.counter += 1
            text = str(self.counter)
            await asyncio.sleep(0)
            return text

    runtime, platform = setup(ChangingModel())
    result = await asyncio.gather(runtime.run(candidate()), runtime.run(candidate()))
    assert result == ["confirmed", "confirmed"]
    assert [item.text for item in platform.sent] == ["1"]


def test_replay_demo_runs_without_network_or_credentials():
    import json
    import os
    import subprocess
    import sys

    env = {"PATH": os.defpath, "PYTHONPATH": "src", "LANGSMITH_TRACING": "false"}
    result = subprocess.run(
        [sys.executable, "-m", "xiaolv.replay"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["mode"] == "local_fake_replay"
    assert data["outcomes"] == ["silence", "confirmed"]
    assert data["sent"] == ["我也在听，你们继续。"]


async def test_profile_read_failure_stops_before_model_and_send():
    calls = []

    class Model(ReplyModel):
        async def decide(self, candidate):
            calls.append(candidate)
            return "respond"

    async def load():
        raise ConnectionError("synthetic unavailable profile database")

    runtime, platform = setup(Model(), profile_loader=load)
    assert await runtime.run(candidate()) == "profile_error"
    assert calls == []
    assert platform.sent == []


async def test_profile_read_uses_turn_deadline_and_cancels_before_generation():
    import asyncio
    from dataclasses import replace

    cancelled = asyncio.Event()
    calls = []

    async def load():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    class Model(ReplyModel):
        async def decide(self, candidate):
            calls.append(candidate)
            return "respond"

    runtime, platform = setup(Model(), profile_loader=load)
    event = replace(candidate(), expires_at=NOW + timedelta(seconds=0.03))
    assert await asyncio.wait_for(runtime.run(event), 1) == "expired"
    assert cancelled.is_set()
    assert calls == []
    assert platform.sent == []


async def test_expired_turn_does_not_read_profile():
    from dataclasses import replace

    from xiaolv.domain.bot_profile import BotProfile, ProfileSnapshot

    calls = []

    async def load():
        calls.append(True)
        return ProfileSnapshot(BotProfile())

    runtime, platform = setup(ReplyModel(), profile_loader=load)
    assert await runtime.run(replace(candidate(), expires_at=NOW)) == "expired"
    assert calls == []
    assert await runtime.run(candidate()) == "confirmed"
    assert calls == [True]
    assert len(platform.sent) == 1
