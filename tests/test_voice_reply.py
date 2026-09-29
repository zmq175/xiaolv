import json
from datetime import UTC, datetime, timedelta

from xiaolv.application.delivery import DeliveryService
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime

NOW = datetime(2026, 9, 30, tzinfo=UTC)


class Platform:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return "confirmed"


class Generator:
    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    async def generate(self, **request):
        self.requests.append(request)
        return (
            '{"action":"respond"}'
            if "action" in request["schema"]["properties"]
            else json.dumps(self.reply)
        )


async def test_llm_voice_intent_reaches_replaceable_voice_execution_only():
    generator = Generator(
        {
            "parts": [],
            "reply_to": None,
            "voice": {"speech_text": "晚安，明天见。", "voice_profile": "warm"},
        }
    )
    platform = Platform()
    spoken = []

    class Voice:
        async def deliver(self, candidate, reply, outgoing_id):
            spoken.append(
                (
                    candidate.conversation_id,
                    reply.speech_text,
                    reply.voice_profile,
                    outgoing_id,
                    candidate.expires_at,
                )
            )
            return "confirmed"

    runtime = TextRuntime(
        ChatCompletionsModel(generator, voice_profiles={"chat-1": ("warm",)}),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        voice_delivery=Voice(),
    )
    candidate = ConversationCandidate("chat-1", "turn-1", "晚安", NOW + timedelta(seconds=30), 1)
    assert await runtime.run(candidate) == "confirmed"
    assert spoken == [("chat-1", "晚安，明天见。", "warm", "6:chat-1turn-1", candidate.expires_at)]
    assert platform.sent == []
    assert "warm" in generator.requests[-1]["instructions"]


async def test_expired_voice_intent_never_enters_synthesis():
    from xiaolv.domain.voice_reply import VoiceReply

    now = NOW
    calls = []

    class Model:
        async def decide(self, candidate):
            return "respond"

        async def reply(self, candidate):
            nonlocal now
            now = candidate.expires_at + timedelta(seconds=1)
            return VoiceReply("晚安", "warm")

    class Voice:
        async def deliver(self, *args):
            calls.append(args)
            return "confirmed"

    platform = Platform()
    runtime = TextRuntime(
        Model(),
        DeliveryService(platform, lambda: now, lambda _: 1),
        lambda: now,
        voice_delivery=Voice(),
    )
    candidate = ConversationCandidate("chat-1", "late", "晚安", NOW + timedelta(seconds=1), 1)
    assert await runtime.run(candidate) == "expired"
    assert calls == []
    assert platform.sent == []


async def test_voice_execution_failure_is_not_a_model_error():
    from xiaolv.domain.voice_reply import VoiceReply

    class Model:
        async def decide(self, candidate):
            return "respond"

        async def reply(self, candidate):
            return VoiceReply("你好", "warm")

    class Voice:
        async def deliver(self, *args):
            raise ConnectionError("PRIVATE_TTS_CREDENTIAL")

    platform = Platform()
    runtime = TextRuntime(
        Model(),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        voice_delivery=Voice(),
    )
    candidate = ConversationCandidate("chat-1", "error", "你好", NOW + timedelta(seconds=30), 1)
    assert await runtime.run(candidate) == "voice_error"
    assert platform.sent == []


async def test_overlong_voice_reply_is_rejected_before_execution():
    from xiaolv.domain.voice_reply import VoiceReply

    class Model:
        async def decide(self, candidate):
            return "respond"

        async def reply(self, candidate):
            return VoiceReply("字" * 201, "warm")

    calls = []

    class Voice:
        async def deliver(self, *args):
            calls.append(args)
            return "confirmed"

    platform = Platform()
    runtime = TextRuntime(
        Model(),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        voice_delivery=Voice(),
    )
    assert (
        await runtime.run(
            ConversationCandidate("chat-1", "long", "你好", NOW + timedelta(seconds=30), 1)
        )
        == "invalid_reply"
    )
    assert calls == []


async def test_voice_enabled_text_reply_preserves_mentions_and_quotes():
    from xiaolv.domain.chat_event import ChatEvent, ConversationContext

    generator = Generator(
        {
            "parts": [{"kind": "text", "value": "好的"}, {"kind": "mention", "value": "member_1"}],
            "reply_to": "message_1",
            "voice": None,
        }
    )
    platform = Platform()

    class Voice:
        async def deliver(self, *args):
            raise AssertionError("text must not synthesize")

    model = ChatCompletionsModel(
        generator,
        voice_profiles={"chat-1": ("warm",)},
        mention_conversations=["chat-1"],
        quote_conversations=["chat-1"],
        ordered_conversations=["chat-1"],
    )
    event = ChatEvent("chat-1", "user-1", "msg-1", "在吗", "群友", NOW, NOW, NOW)
    candidate = ConversationCandidate(
        "chat-1", "text", "在吗", NOW + timedelta(seconds=30), 1, ConversationContext(1, (event,))
    )
    runtime = TextRuntime(
        model,
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        voice_delivery=Voice(),
    )
    assert await runtime.run(candidate) == "confirmed"
    assert platform.sent[0].text == "好的"
    assert platform.sent[0].mentions == ("user-1",)
    assert platform.sent[0].reply_to == "msg-1"
    assert [part.kind for part in platform.sent[0].parts] == ["text", "mention"]


async def test_voice_without_executor_is_not_sent_as_text():
    generator = Generator(
        {"parts": [], "reply_to": None, "voice": {"speech_text": "晚安", "voice_profile": "warm"}}
    )
    platform = Platform()
    runtime = TextRuntime(
        ChatCompletionsModel(generator, voice_profiles={"chat-1": ("warm",)}),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
    )
    assert (
        await runtime.run(
            ConversationCandidate("chat-1", "missing", "晚安", NOW + timedelta(seconds=30), 1)
        )
        == "voice_unavailable"
    )
    assert platform.sent == []


async def test_unapproved_voice_profile_is_rejected_without_execution():
    generator = Generator(
        {
            "parts": [],
            "reply_to": None,
            "voice": {"speech_text": "晚安", "voice_profile": "https://untrusted.invalid/voice"},
        }
    )
    platform = Platform()
    runtime = TextRuntime(
        ChatCompletionsModel(generator, voice_profiles={"chat-1": ("warm",)}),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
    )
    assert (
        await runtime.run(
            ConversationCandidate("chat-1", "invalid", "晚安", NOW + timedelta(seconds=30), 1)
        )
        == "model_error"
    )
    assert platform.sent == []


async def test_voice_execution_is_cancelled_at_original_deadline():
    import asyncio

    from xiaolv.domain.voice_reply import VoiceReply

    cancelled = asyncio.Event()

    class Model:
        async def decide(self, candidate):
            return "respond"

        async def reply(self, candidate):
            return VoiceReply("晚安", "warm")

    class Voice:
        async def deliver(self, *args):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    platform = Platform()
    clock = lambda: datetime.now(UTC)
    runtime = TextRuntime(
        Model(), DeliveryService(platform, clock, lambda _: 1), clock, voice_delivery=Voice()
    )
    candidate = ConversationCandidate(
        "chat-1", "timeout", "晚安", clock() + timedelta(seconds=0.05), 1
    )
    assert await runtime.run(candidate) == "expired"
    assert cancelled.is_set()
    assert platform.sent == []


async def test_revoked_conversation_never_enters_voice_execution():
    from xiaolv.domain.voice_reply import VoiceReply

    allowed = True
    calls = []

    async def authorize(conversation):
        return allowed

    class Model:
        async def decide(self, candidate):
            return "respond"

        async def reply(self, candidate):
            nonlocal allowed
            allowed = False
            return VoiceReply("晚安", "warm")

    class Voice:
        async def deliver(self, *args):
            calls.append(args)
            return "confirmed"

    platform = Platform()
    runtime = TextRuntime(
        Model(),
        DeliveryService(platform, lambda: NOW, lambda _: 1, authorize=authorize),
        lambda: NOW,
        voice_delivery=Voice(),
    )
    assert (
        await runtime.run(
            ConversationCandidate("chat-1", "revoked", "晚安", NOW + timedelta(seconds=30), 1)
        )
        == "permission_denied"
    )
    assert calls == []
    assert platform.sent == []
