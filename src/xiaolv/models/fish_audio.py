"""Replaceable speech synthesis using the pinned official Fish Audio SDK."""

import asyncio
import io
import math
import wave
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import httpx
from fishaudio import AsyncFishAudio  # type: ignore[import-untyped]
from fishaudio.core import RequestOptions  # type: ignore[import-untyped]

from xiaolv.domain.speech import SpeechRequest, SpeechResult


class _BoundedStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, limit: int) -> None:
        self._stream, self._limit = stream, limit

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        async for chunk in self._stream:
            total += len(chunk)
            if total > self._limit:
                raise ValueError("speech response exceeds byte limit")
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


class _BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport: httpx.AsyncBaseTransport, limit: int) -> None:
        self._transport, self._limit = transport, limit

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._transport.handle_async_request(request)
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            await response.aclose()
            raise ValueError("encoded speech response is unsupported")
        assert isinstance(response.stream, httpx.AsyncByteStream)
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=_BoundedStream(response.stream, self._limit),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._transport.aclose()


class FishAudioProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        voice_profiles: Mapping[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
        max_audio_bytes: int = 4 * 1024 * 1024,
        max_duration_seconds: float = 20,
    ) -> None:
        if (
            not isinstance(max_audio_bytes, int)
            or isinstance(max_audio_bytes, bool)
            or max_audio_bytes <= 0
            or not math.isfinite(max_duration_seconds)
            or max_duration_seconds <= 0
        ):
            raise ValueError("invalid speech limits")
        self._max_duration = max_duration_seconds
        self._model = model
        self._voices = dict(voice_profiles)
        self._http = httpx.AsyncClient(
            base_url="https://api.fish.audio",
            headers={"Authorization": f"Bearer {api_key}", "Accept-Encoding": "identity"},
            transport=_BoundedTransport(transport or httpx.AsyncHTTPTransport(), max_audio_bytes),
            trust_env=False,
            follow_redirects=False,
        )
        self._client = AsyncFishAudio(api_key=api_key, httpx_client=self._http)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.close()

    async def synthesize(self, request: SpeechRequest) -> SpeechResult:
        remaining = (request.expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise TimeoutError("speech deadline expired")
        async with asyncio.timeout(remaining):
            audio = await self._client.tts.convert(
                text=request.speech_text,
                reference_id=self._voices[request.voice_profile],
                model=self._model,
                format="wav",
                request_options=RequestOptions(timeout=remaining, max_retries=0),
            )
        with wave.open(io.BytesIO(audio), "rb") as wav:
            frames = wav.getnframes()
            if frames <= 0 or frames / wav.getframerate() > self._max_duration:
                raise ValueError("invalid speech duration")
            frame_bytes = wav.getnchannels() * wav.getsampwidth()
            if len(wav.readframes(frames)) != frames * frame_bytes:
                raise ValueError("truncated speech audio")
        return SpeechResult(audio=audio)
