"""Exercise the official SDK from the chat boundary, with synthetic provider HTTP."""

import asyncio
import io
import wave
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import ormsgpack
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from test_speech_execution import runtime

from xiaolv.application.speech_execution import SpeechExecution
from xiaolv.domain.speech import SpeechPolicy
from xiaolv.orchestration.text_runtime import ConversationCandidate
from xiaolv.storage.conversation_control import ConversationControl
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger
from xiaolv.storage.postgres_speech import PostgresSpeechLedger


def wav_sample(frames=2400):
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * frames)
    return data.getvalue()


async def run_voice(database_url, transport, *, ttl=30, **options):
    from xiaolv.models.fish_audio import FishAudioProvider

    engine = create_async_engine(database_url, hide_parameters=True)
    delivered = []

    async def dispatch(candidate, reply, outgoing_id, result):
        delivered.append(result)
        return "confirmed"

    policy = SpeechPolicy(
        "speech", "fish", "test-model", "test-price", "voice-v1", Decimal(1), Decimal("0.1")
    )
    try:
        await ConversationControl(engine).register(["chat-1"])
        epoch = await PostgresDeliveryLedger(engine).start_turn("chat-1")
        candidate = ConversationCandidate(
            "chat-1", "fish-turn", "你好", datetime.now(UTC) + timedelta(seconds=ttl), epoch
        )
        async with FishAudioProvider(
            api_key="synthetic-key",
            model="test-model",
            voice_profiles={"warm": "synthetic-reference"},
            transport=transport,
            **options,
        ) as provider:
            executor = SpeechExecution(PostgresSpeechLedger(engine, policy), provider, dispatch)
            outcome = await runtime(executor).run(candidate)
        return outcome, delivered
    finally:
        await engine.dispose()


async def test_voice_choice_uses_official_sdk_with_explicit_binding(database_url):
    calls = []
    audio = wav_sample()

    async def respond(request):
        calls.append(
            (request.url.path, request.headers["model"], ormsgpack.unpackb(request.content))
        )
        return httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})

    outcome, delivered = await run_voice(database_url, httpx.MockTransport(respond))
    assert outcome == "confirmed"
    assert len(calls) == 1
    path, model, payload = calls[0]
    assert (path, model) == ("/v1/tts", "test-model")
    assert payload["text"] == "合成语音样本"
    assert payload["reference_id"] == "synthetic-reference"
    assert payload["format"] == "wav"
    assert len(delivered) == 1
    assert delivered[0].audio == audio
    assert delivered[0].charged_amount is None


async def test_oversized_response_stops_reading_before_buffering_and_never_dispatches(database_url):
    read, closed, calls = [], [], []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index in range(100):
                read.append(index)
                yield b"x" * 1024

        async def aclose(self):
            closed.append(True)

    async def respond(request):
        calls.append(request)
        return httpx.Response(200, stream=Body())

    outcome, delivered = await run_voice(
        database_url, httpx.MockTransport(respond), max_audio_bytes=2048
    )
    assert outcome == "voice_unknown"
    assert delivered == []
    assert len(calls) == 1
    assert read == [0, 1, 2]
    assert closed


async def test_compressed_provider_response_is_rejected_before_decompression(database_url):
    import gzip

    read, closed, encodings = [], [], []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            read.append(True)
            yield gzip.compress(wav_sample())

        async def aclose(self):
            closed.append(True)

    async def respond(request):
        encodings.append(request.headers["accept-encoding"])
        return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=Body())

    outcome, delivered = await run_voice(database_url, httpx.MockTransport(respond))
    assert outcome == "voice_unknown"
    assert delivered == []
    assert read == []
    assert closed
    assert encodings == ["identity"]


@pytest.mark.parametrize(
    "audio",
    [b"not audio", wav_sample()[:-2], wav_sample(480001), wav_sample(0)],
    ids=["invalid", "truncated", "overlong", "empty"],
)
async def test_invalid_or_overlong_audio_never_reaches_dispatch(database_url, audio):
    async def respond(request):
        return httpx.Response(200, content=audio)

    outcome, delivered = await run_voice(database_url, httpx.MockTransport(respond))
    assert outcome == "voice_unknown"
    assert delivered == []


async def test_slow_audio_is_cancelled_at_original_turn_deadline(database_url):
    calls, closed, timeouts = [], [], []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"RIFF"
            await asyncio.Event().wait()

        async def aclose(self):
            closed.append(True)

    async def respond(request):
        calls.append(request)
        timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, stream=Body())

    outcome, delivered = await asyncio.wait_for(
        run_voice(database_url, httpx.MockTransport(respond), ttl=0.3), 3
    )
    assert outcome == "expired"
    assert delivered == []
    assert len(calls) == 1
    assert closed
    assert all(0 < value <= 0.3 for value in timeouts[0].values())


@pytest.mark.parametrize("status", [302, 503])
async def test_provider_error_does_not_retry_or_follow_redirect(database_url, status):
    calls = []

    async def respond(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"location": "https://untrusted.invalid"}, content=b"bad"
        )

    outcome, delivered = await run_voice(database_url, httpx.MockTransport(respond))
    assert outcome == "voice_unknown"
    assert delivered == []
    assert len(calls) == 1


@pytest.mark.parametrize(
    "options",
    [{"max_audio_bytes": 0}, {"max_duration_seconds": float("nan")}, {"max_duration_seconds": 0}],
    ids=["zero-bytes", "nan-duration", "zero-duration"],
)
async def test_invalid_speech_limits_fail_before_external_request(database_url, options):
    calls = []

    async def respond(request):
        calls.append(request)
        return httpx.Response(200, content=wav_sample())

    with pytest.raises(ValueError, match="speech limits"):
        await run_voice(database_url, httpx.MockTransport(respond), **options)
    assert calls == []
