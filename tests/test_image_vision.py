"""Vision SDK exercised through the approved chat replay boundary."""

import base64
import json
from io import BytesIO

import httpx
import httpx2
import pytest
from PIL import Image
from test_chat_model import stream_json
from test_inbound_images import PNG, RPC, replay

from xiaolv.models.chat_completions import ChatCompletionsGateway
from xiaolv.platforms.media_http import MediaDownloader


@pytest.mark.parametrize(
    "window_tokens,description",
    [
        (8192, "白色背景上的合成图。"),
        (2048, "白色背景上的合成图。"),
        (8192, ""),
        (8192, " "),
        (8192, "x" * 3001),
        (8192, 123),
    ],
)
async def test_image_replay_uses_official_sdk_and_passes_description_to_reply(
    window_tokens, description
):
    from xiaolv.models.vision import ImageDescriber

    requests, reports = [], []

    async def serve(request):
        requests.append(json.loads(request.content))
        return stream_json({"description": description})

    async def report(value):
        reports.append(value)

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def download(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    async with ChatCompletionsGateway(
        base_url="https://vision.example/v1",
        api_key="synthetic",
        model="synthetic-vision",
        transport=httpx2.MockTransport(serve),
        usage_sink=report,
    ) as gateway:
        vision = ImageDescriber(
            gateway, processor="synthetic-vision:v1", image_tokens=2048, window_tokens=window_tokens
        )
        outcome, generator, platform = await replay(
            RPC(),
            MediaDownloader(resolver=resolve, transport=httpx.MockTransport(download)),
            vision,
        )
    if window_tokens == 2048:
        assert outcome == "media_error"
        assert requests == [] and reports == [] and platform.sent == []
        assert len(generator.requests) == 1
        return
    if description != "白色背景上的合成图。":
        assert outcome == "media_error" and platform.sent == []
        assert len(requests) == 1 and len(generator.requests) == 1
        return
    assert outcome == "confirmed" and len(platform.sent) == 1
    assert len(requests) == 1 and reports[0].status == "completed"
    request = requests[0]
    assert request["model"] == "synthetic-vision"
    content = request["messages"][1]["content"]
    assert content[1]["image_url"]["detail"] == "low"
    url = content[1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        assert image.size == (1, 1)
    meta = json.loads(content[0]["text"])
    assert meta["original_frames"] == 1 and meta["sampled_frames"] == [0]
    assert "PRIVATE" not in json.dumps(request)
    reply_context = generator.requests[-1]["context"]
    assert "白色背景上的合成图。" in reply_context
    assert "base64" not in reply_context


@pytest.mark.parametrize(
    "field,value",
    [
        ("image_tokens", 0),
        ("image_tokens", -1),
        ("image_tokens", True),
        ("image_tokens", 2_000_001),
        ("window_tokens", 0),
        ("window_tokens", True),
        ("window_tokens", 2_000_001),
        ("processor", " "),
    ],
)
async def test_vision_configuration_rejects_invalid_reservations(field, value):
    from xiaolv.models.vision import ImageDescriber

    async with ChatCompletionsGateway(
        base_url="https://vision.example/v1",
        api_key="synthetic",
        model="synthetic-vision",
    ) as gateway:
        options = {"processor": "synthetic:v1", "image_tokens": 2048, "window_tokens": 8192}
        options[field] = value
        with pytest.raises(ValueError):
            ImageDescriber(gateway, **options)
