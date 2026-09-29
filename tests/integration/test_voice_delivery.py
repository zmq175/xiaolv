import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import create_async_engine
from test_fish_voice import wav_sample
from test_speech_execution import runtime

from xiaolv.application.delivery import DeliveryService
from xiaolv.application.speech_execution import SpeechExecution
from xiaolv.domain.speech import SpeechPolicy, SpeechResult
from xiaolv.orchestration.text_runtime import ConversationCandidate
from xiaolv.platforms.onebot import OneBotPreparation, OneBotSender, QQTarget
from xiaolv.storage.conversation_control import ConversationControl
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger
from xiaolv.storage.postgres_speech import PostgresSpeechLedger


async def test_chat_voice_sends_one_native_record_and_restart_does_not_repeat(
    database_url, tmp_path
):
    from xiaolv.application.voice_dispatch import VoiceDispatch
    from xiaolv.storage.audio_artifacts import LocalAudioArtifacts

    engine = create_async_engine(database_url, hide_parameters=True)
    calls, syntheses = [], []
    audio = wav_sample()

    class Provider:
        async def synthesize(self, request):
            syntheses.append(request)
            return SpeechResult(audio)

    class RPC:
        async def call(self, action, params):
            calls.append((action, params))
            return {"status": "ok", "retcode": 0, "data": {"message_id": 88}}

    try:
        await ConversationControl(engine).register(["chat-1"])
        ledger = PostgresDeliveryLedger(engine)
        epoch = await ledger.start_turn("chat-1")
        candidate = ConversationCandidate(
            "chat-1", "voice-turn", "你好", datetime.now(UTC) + timedelta(seconds=30), epoch
        )
        policy = SpeechPolicy(
            "speech", "synthetic", "model", "price", "v1", Decimal(1), Decimal("0.1")
        )

        def build():
            artifacts = LocalAudioArtifacts(tmp_path)
            rpc, routes = RPC(), {"chat-1": QQTarget("group", 123)}
            delivery = DeliveryService(
                OneBotSender(rpc, routes),
                ledger=PostgresDeliveryLedger(engine),
                prepare=OneBotPreparation(rpc, routes, artifacts=artifacts),
            )
            return runtime(
                SpeechExecution(
                    PostgresSpeechLedger(engine, policy),
                    Provider(),
                    VoiceDispatch(artifacts, delivery),
                )
            )

        assert await build().run(candidate) == "confirmed"
        assert await build().run(candidate) == "confirmed"
        assert len(syntheses) == 1
        assert calls == [
            (
                "send_group_msg",
                {
                    "group_id": 123,
                    "message": [
                        {
                            "type": "record",
                            "data": {"file": "base64://" + base64.b64encode(audio).decode("ascii")},
                        }
                    ],
                },
            )
        ]
    finally:
        await engine.dispose()


async def test_audio_delivery_restart_preserves_unknown_and_rejects_changed_payload(
    database_url, tmp_path
):
    from dataclasses import replace

    import pytest

    from xiaolv.application.delivery import DeliveryRequest
    from xiaolv.storage.audio_artifacts import LocalAudioArtifacts

    engine = create_async_engine(database_url, hide_parameters=True)
    calls = []

    class RPC:
        async def call(self, action, params):
            calls.append((action, params))
            raise ConnectionError("receipt lost after send")

    try:
        artifacts = LocalAudioArtifacts(tmp_path)
        artifact = await artifacts.save("chat-1", wav_sample())
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")
        request = DeliveryRequest(
            "voice-once",
            "chat-1",
            datetime.now(UTC) + timedelta(seconds=30),
            epoch,
            "",
            audio=artifact,
        )

        def build():
            rpc, routes = RPC(), {"chat-1": QQTarget("group", 123)}
            return DeliveryService(
                OneBotSender(rpc, routes),
                ledger=PostgresDeliveryLedger(engine),
                prepare=OneBotPreparation(rpc, routes, artifacts=artifacts),
            )

        assert await build().deliver(request) == "unknown"
        assert await build().deliver(request) == "unknown"
        other = await artifacts.save("chat-1", wav_sample(4800))
        with pytest.raises(ValueError, match="payload conflict"):
            await build().deliver(replace(request, audio=other))
        assert len(calls) == 1
    finally:
        await engine.dispose()


async def test_voice_cannot_mix_text_or_reuse_another_conversation_artifact(tmp_path):
    from dataclasses import replace

    from xiaolv.application.delivery import DeliveryRequest
    from xiaolv.domain.text_reply import TextPart
    from xiaolv.storage.audio_artifacts import LocalAudioArtifacts

    artifacts = LocalAudioArtifacts(tmp_path)
    artifact = await artifacts.save("private-chat", wav_sample())
    now = datetime.now(UTC)
    request = DeliveryRequest(
        "voice", "private-chat", now + timedelta(seconds=30), 1, "", audio=artifact
    )
    calls = []

    class Platform:
        async def send(self, request):
            calls.append(request)
            return "confirmed"

    variants = [
        replace(request, text="hidden fallback"),
        replace(request, mentions=("qq:123",)),
        replace(request, reply_to="123"),
        replace(request, parts=(TextPart("text", "hidden"),)),
        replace(request, conversation_id="another-group"),
    ]
    for item in variants:
        service = DeliveryService(Platform(), lambda: now, lambda _: 1)
        assert await service.deliver(item) == "not_sent"
    assert calls == []


async def test_new_turn_after_audio_read_prevents_native_send(database_url, tmp_path):
    from xiaolv.application.delivery import DeliveryRequest
    from xiaolv.storage.audio_artifacts import LocalAudioArtifacts

    engine = create_async_engine(database_url, hide_parameters=True)
    calls = []
    try:
        control = ConversationControl(engine)
        await control.register(["chat-1"])
        ledger = PostgresDeliveryLedger(engine)
        epoch = await ledger.start_turn("chat-1")
        artifacts = LocalAudioArtifacts(tmp_path)
        artifact = await artifacts.save("chat-1", wav_sample())

        class ReadThenNewTurn:
            async def read(self, artifact):
                audio = await artifacts.read(artifact)
                await ledger.start_turn("chat-1")
                return audio

        class RPC:
            async def call(self, *args):
                calls.append(args)
                return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}

        rpc, routes = RPC(), {"chat-1": QQTarget("group", 123)}
        service = DeliveryService(
            OneBotSender(rpc, routes),
            ledger=ledger,
            prepare=OneBotPreparation(rpc, routes, artifacts=ReadThenNewTurn()),
        )
        request = DeliveryRequest(
            "late-audio",
            "chat-1",
            datetime.now(UTC) + timedelta(seconds=30),
            epoch,
            "",
            audio=artifact,
        )
        assert await service.deliver(request) == "superseded"
        assert calls == []
    finally:
        await engine.dispose()


async def test_cleaned_audio_is_not_sent_but_newer_artifact_remains_available(tmp_path):
    from xiaolv.application.delivery import DeliveryRequest
    from xiaolv.storage.audio_artifacts import LocalAudioArtifacts

    artifacts = LocalAudioArtifacts(tmp_path)
    old = await artifacts.save("chat-1", wav_sample())
    cutoff = datetime.now(UTC)
    fresh = await artifacts.save("chat-1", wav_sample(4800))
    await artifacts.cleanup(before=cutoff)
    calls = []

    class RPC:
        async def call(self, action, params):
            calls.append((action, params))
            return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}

    rpc, routes = RPC(), {"chat-1": QQTarget("group", 123)}
    now = datetime.now(UTC)
    service = DeliveryService(
        OneBotSender(rpc, routes),
        lambda: now,
        lambda _: 1,
        prepare=OneBotPreparation(rpc, routes, artifacts=artifacts),
    )
    for id, artifact, expected in [("old", old, "not_sent"), ("fresh", fresh, "confirmed")]:
        assert (
            await service.deliver(
                DeliveryRequest(
                    id,
                    "chat-1",
                    now + timedelta(seconds=30),
                    1,
                    "",
                    audio=artifact,
                )
            )
            == expected
        )
    assert len(calls) == 1
