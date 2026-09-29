"""ASR behavior through the approved chat replay boundary and native RPC transport."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from xiaolv.application.delivery import DeliveryService
from xiaolv.application.inbound_speech import InboundSpeech
from xiaolv.domain.chat_event import ChatEvent, ConversationContext, MessagePart
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime
from xiaolv.platforms.onebot import QQTarget
from xiaolv.platforms.onebot_speech import OneBotSpeechTranscriber

NOW = datetime(2026, 9, 30, tzinfo=UTC)
SCOPE = "qq:10000:group:20000"


class NativeRPC:
    def __init__(self, transcribed):
        self.transcribed = transcribed
        self.calls = []

    async def call(self, action, params):
        self.calls.append(action)
        if action == "get_msg":
            return {
                "status": "ok",
                "retcode": 0,
                "data": {
                    "message_id": 1,
                    "message_type": "group",
                    "group_id": 20000,
                    "user_id": 10001,
                    "message": [{"type": "record", "data": {"file": "record-ref"}}],
                },
            }
        assert action == "fetch_ptt_text"
        self.transcribed()
        return {"status": "ok", "retcode": 0, "data": {"text": "周末再讨论吧"}}


class Generator:
    def __init__(self):
        self.requests = []

    async def generate(self, **request):
        self.requests.append(request)
        return (
            '{"action":"respond"}'
            if "action" in request["schema"]["properties"]
            else '{"text":"好"}'
        )


class Platform:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return "confirmed"


async def test_revocation_during_asr_prevents_reply_generation():
    allowed = True

    def transcribed():
        nonlocal allowed
        allowed = False

    async def authorize(_):
        return allowed

    rpc = NativeRPC(transcribed)
    platform = Platform()
    generator = Generator()
    event = ChatEvent(
        SCOPE,
        "qq:10001",
        "1",
        "",
        "群友",
        NOW,
        NOW,
        NOW,
        parts=(MessagePart("audio", reference="record-ref"),),
    )
    candidate = ConversationCandidate(
        SCOPE,
        "turn",
        "",
        NOW + timedelta(seconds=30),
        1,
        ConversationContext(1, (event,)),
        source_message_id="1",
    )
    runtime = TextRuntime(
        ChatCompletionsModel(generator),
        DeliveryService(platform, lambda: NOW, lambda _: 1, authorize=authorize),
        lambda: NOW,
        inbound_speech=InboundSpeech(
            OneBotSpeechTranscriber(rpc, {SCOPE: QQTarget("group", 20000)}), [SCOPE]
        ),
    )
    assert await runtime.run(candidate) == "permission_denied"
    assert rpc.calls == ["get_msg", "fetch_ptt_text"]
    assert len(generator.requests) == 1
    assert platform.sent == []


async def test_expired_asr_never_generates_reply_or_renews_deadline():
    now = NOW

    def transcribed():
        nonlocal now
        now = NOW + timedelta(seconds=31)

    rpc = NativeRPC(transcribed)
    platform = Platform()
    generator = Generator()
    event = ChatEvent(
        SCOPE,
        "qq:10001",
        "1",
        "",
        "群友",
        NOW,
        NOW,
        NOW,
        parts=(MessagePart("audio", reference="record-ref"),),
    )
    candidate = ConversationCandidate(
        SCOPE,
        "turn",
        "",
        NOW + timedelta(seconds=30),
        1,
        ConversationContext(1, (event,)),
        source_message_id="1",
    )
    runtime = TextRuntime(
        ChatCompletionsModel(generator),
        DeliveryService(platform, lambda: now, lambda _: 1),
        lambda: now,
        inbound_speech=InboundSpeech(
            OneBotSpeechTranscriber(rpc, {SCOPE: QQTarget("group", 20000)}), [SCOPE]
        ),
    )
    assert await runtime.run(candidate) == "expired"
    assert len(generator.requests) == 1
    assert generator.requests[0]["expires_at"] == NOW + timedelta(seconds=30)
    assert platform.sent == []


@pytest.mark.parametrize("ambiguous", ["two-records", "duplicate-message"])
async def test_ambiguous_audio_never_calls_native_transcriber(ambiguous):
    rpc = NativeRPC(lambda: None)
    platform = Platform()
    generator = Generator()
    audio = MessagePart("audio", reference="record-ref")
    event = ChatEvent(
        SCOPE,
        "qq:10001",
        "1",
        "",
        "群友",
        NOW,
        NOW,
        NOW,
        parts=(audio, audio) if ambiguous == "two-records" else (audio,),
    )
    candidate = ConversationCandidate(
        SCOPE,
        "turn",
        "",
        NOW + timedelta(seconds=30),
        1,
        ConversationContext(1, (event, event) if ambiguous == "duplicate-message" else (event,)),
        source_message_id="1",
    )
    runtime = TextRuntime(
        ChatCompletionsModel(generator),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        inbound_speech=InboundSpeech(
            OneBotSpeechTranscriber(rpc, {SCOPE: QQTarget("group", 20000)}), [SCOPE]
        ),
    )
    assert await runtime.run(candidate) == "media_error"
    assert rpc.calls == []
    assert len(generator.requests) == 1
    assert platform.sent == []


async def test_native_transcription_transport_failure_is_media_error():
    class BrokenRPC(NativeRPC):
        async def call(self, action, params):
            if action == "fetch_ptt_text":
                raise TimeoutError("PRIVATE_TRANSPORT_DETAILS")
            return await super().call(action, params)

    rpc = BrokenRPC(lambda: None)
    platform = Platform()
    generator = Generator()
    event = ChatEvent(
        SCOPE,
        "qq:10001",
        "1",
        "",
        "群友",
        NOW,
        NOW,
        NOW,
        parts=(MessagePart("audio", reference="record-ref"),),
    )
    candidate = ConversationCandidate(
        SCOPE,
        "turn",
        "",
        NOW + timedelta(seconds=30),
        1,
        ConversationContext(1, (event,)),
        source_message_id="1",
    )
    runtime = TextRuntime(
        ChatCompletionsModel(generator),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        inbound_speech=InboundSpeech(
            OneBotSpeechTranscriber(rpc, {SCOPE: QQTarget("group", 20000)}), [SCOPE]
        ),
    )
    assert await runtime.run(candidate) == "media_error"
    assert len(generator.requests) == 1
    assert platform.sent == []


async def test_original_deadline_cancels_pending_transcription():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowRPC(NativeRPC):
        async def call(self, action, params):
            if action == "fetch_ptt_text":
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return await super().call(action, params)

    rpc = SlowRPC(lambda: None)
    platform = Platform()
    generator = Generator()
    event = ChatEvent(
        SCOPE,
        "qq:10001",
        "1",
        "",
        "群友",
        NOW,
        NOW,
        NOW,
        parts=(MessagePart("audio", reference="record-ref"),),
    )
    candidate = ConversationCandidate(
        SCOPE,
        "turn",
        "",
        NOW + timedelta(seconds=0.3),
        1,
        ConversationContext(1, (event,)),
        source_message_id="1",
    )
    runtime = TextRuntime(
        ChatCompletionsModel(generator),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        inbound_speech=InboundSpeech(
            OneBotSpeechTranscriber(rpc, {SCOPE: QQTarget("group", 20000)}), [SCOPE]
        ),
    )
    assert await asyncio.wait_for(runtime.run(candidate), 2) == "expired"
    assert started.is_set() and cancelled.is_set()
    assert len(generator.requests) == 1
    assert platform.sent == []


async def test_transcript_is_counted_before_reply_model_call():
    from xiaolv.domain.context_policy import ContextPolicy

    class LongRPC(NativeRPC):
        async def call(self, action, params):
            result = await super().call(action, params)
            if action == "fetch_ptt_text":
                result["data"]["text"] = "语音内容" * 700
            return result

    rpc = LongRPC(lambda: None)
    platform = Platform()
    generator = Generator()
    event = ChatEvent(
        SCOPE,
        "qq:10001",
        "1",
        "",
        "群友",
        NOW,
        NOW,
        NOW,
        parts=(MessagePart("audio", reference="record-ref"),),
    )
    candidate = ConversationCandidate(
        SCOPE,
        "turn",
        "",
        NOW + timedelta(seconds=30),
        1,
        ConversationContext(1, (event,)),
        source_message_id="1",
    )
    runtime = TextRuntime(
        ChatCompletionsModel(generator, context_policy=ContextPolicy(reply_tokens=1400)),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        inbound_speech=InboundSpeech(
            OneBotSpeechTranscriber(rpc, {SCOPE: QQTarget("group", 20000)}), [SCOPE]
        ),
    )
    assert await runtime.run(candidate) == "context_overflow"
    assert rpc.calls == ["get_msg", "fetch_ptt_text"]
    assert len(generator.requests) == 1
    assert platform.sent == []


@pytest.mark.parametrize("mode", ["silence", "disabled", "old-audio"])
async def test_asr_does_not_process_silent_disabled_or_historical_messages(mode):
    class DecisionGenerator(Generator):
        async def generate(self, **request):
            if mode == "silence":
                self.requests.append(request)
                return '{"action":"silence"}'
            return await super().generate(**request)

    rpc = NativeRPC(lambda: None)
    platform = Platform()
    generator = DecisionGenerator()
    event = ChatEvent(
        SCOPE,
        "qq:10001",
        "1",
        "",
        "群友",
        NOW,
        NOW,
        NOW,
        parts=(MessagePart("audio", reference="record-ref"),),
    )
    messages = (event,)
    if mode == "old-audio":
        messages += (ChatEvent(SCOPE, "qq:10001", "2", "新话题", "群友", NOW, NOW, NOW),)
    candidate = ConversationCandidate(
        SCOPE,
        "turn",
        "",
        NOW + timedelta(seconds=30),
        1,
        ConversationContext(1, messages),
        source_message_id=messages[-1].message_id,
    )
    runtime = TextRuntime(
        ChatCompletionsModel(generator),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        inbound_speech=InboundSpeech(
            OneBotSpeechTranscriber(rpc, {SCOPE: QQTarget("group", 20000)}),
            [] if mode == "disabled" else [SCOPE],
        ),
    )
    assert await runtime.run(candidate) == ("silence" if mode == "silence" else "confirmed")
    assert rpc.calls == []


@pytest.mark.parametrize("subtype", ["friend", "group"])
async def test_private_asr_requires_friend_scope(subtype):
    scope = "qq:10000:private:10001"

    class PrivateRPC(NativeRPC):
        async def call(self, action, params):
            result = await super().call(action, params)
            if action == "get_msg":
                result["data"].update(message_type="private", sub_type=subtype)
                result["data"].pop("group_id")
            return result

    rpc = PrivateRPC(lambda: None)
    platform = Platform()
    generator = Generator()
    event = ChatEvent(
        scope,
        "qq:10001",
        "1",
        "",
        "群友",
        NOW,
        NOW,
        NOW,
        parts=(MessagePart("audio", reference="record-ref"),),
    )
    candidate = ConversationCandidate(
        scope,
        "turn",
        "",
        NOW + timedelta(seconds=30),
        1,
        ConversationContext(1, (event,)),
        source_message_id="1",
    )
    runtime = TextRuntime(
        ChatCompletionsModel(generator),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        inbound_speech=InboundSpeech(
            OneBotSpeechTranscriber(rpc, {scope: QQTarget("private", 10001)}), [scope]
        ),
    )
    assert await runtime.run(candidate) == ("confirmed" if subtype == "friend" else "media_error")
    assert len(platform.sent) == (1 if subtype == "friend" else 0)
    assert ("fetch_ptt_text" in rpc.calls) == (subtype == "friend")


@pytest.mark.parametrize("processor", ["snowluma-native-asr:v1", "old-processor:v0"])
async def test_cached_transcript_reuse_requires_matching_processor(processor):
    import json

    from xiaolv.domain.chat_event import MediaInterpretation

    rpc = NativeRPC(lambda: None)
    platform = Platform()
    generator = Generator()
    audio = MessagePart(
        "audio",
        reference="record-ref",
        interpretation=MediaInterpretation("transcript", "缓存转写", processor),
    )
    event = ChatEvent(
        SCOPE, "qq:10001", "1", "", "群友", NOW, NOW, NOW, parts=(audio,), content_version=3
    )
    candidate = ConversationCandidate(
        SCOPE,
        "turn",
        "",
        NOW + timedelta(seconds=30),
        1,
        ConversationContext(1, (event,)),
        source_message_id="1",
    )
    runtime = TextRuntime(
        ChatCompletionsModel(generator),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
        inbound_speech=InboundSpeech(
            OneBotSpeechTranscriber(rpc, {SCOPE: QQTarget("group", 20000)}), [SCOPE]
        ),
    )
    assert await runtime.run(candidate) == "confirmed"
    cached = processor == "snowluma-native-asr:v1"
    assert rpc.calls == ([] if cached else ["get_msg", "fetch_ptt_text"])
    row = json.loads(generator.requests[1]["context"])["messages"][0]
    assert row["content_version"] == (3 if cached else 4)
    assert row["parts"][0]["interpretation"]["text"] == ("缓存转写" if cached else "周末再讨论吧")
