"""Offline SDK feasibility probe; synthetic transport, no external API request."""

import asyncio
import hashlib
import inspect
import json
from importlib.metadata import version

import httpx
import ormsgpack
from fishaudio import AsyncFishAudio
from fishaudio.core import RequestOptions


async def main():
    entered, release = asyncio.Event(), asyncio.Event()
    observations = {"sdk_version": version("fish-audio-sdk")}

    class Audio(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"first"
            entered.set()
            await release.wait()
            yield b"last"

    async def respond(request):
        payload = ormsgpack.unpackb(request.content)
        observations.update(
            path=request.url.path, model=request.headers["model"], format=payload["format"]
        )
        return httpx.Response(200, stream=Audio())

    transport = httpx.MockTransport(respond)
    async with (
        httpx.AsyncClient(transport=transport, base_url="https://synthetic.invalid") as http,
        AsyncFishAudio(api_key="synthetic-key", httpx_client=http) as client,
    ):
        task = asyncio.create_task(
            client.tts.stream(text="合成样本", format="pcm", model="explicit-test-model")
        )
        try:
            await asyncio.wait_for(entered.wait(), 1)
            observations["stream_returns_before_complete_body"] = task.done()
        finally:
            release.set()
        stream = await task
        assert await stream.collect() == b"firstlast"
    calls = 0

    async def fail(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"detail": "synthetic error"})

    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(fail), base_url="https://synthetic.invalid"
        ) as http,
        AsyncFishAudio(api_key="synthetic-key", httpx_client=http) as client,
    ):
        try:
            await client.tts.convert(text="合成样本", request_options=RequestOptions(max_retries=0))
        except Exception as exc:  # noqa: BLE001 - report class, never response or credentials
            observations["error_class"] = type(exc).__name__
    observations["requests_on_503"] = calls
    observations["client_source_sha256"] = hashlib.sha256(
        inspect.getsource(AsyncFishAudio).encode()
    ).hexdigest()
    print(json.dumps(observations, ensure_ascii=False, indent=2))


asyncio.run(main())
