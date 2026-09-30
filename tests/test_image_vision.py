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


@pytest.mark.parametrize("image_count,window_tokens", [(2, 16384), (2, 5000), (5, 16384)])
async def test_multiple_images_are_sent_in_one_ordered_vision_request(image_count, window_tokens):
    from xiaolv.domain.chat_event import MessagePart
    from xiaolv.models.vision import ImageDescriber

    requests, downloads = [], []
    rpc = RPC()
    rpc.source_changes["message"] = [
        {"type": "image", "data": {"file": "image-ref"}},
        {"type": "text", "data": {"text": "比较这两张"}},
        {"type": "image", "data": {"file": "second-ref"}},
    ]

    async def serve(request):
        requests.append(json.loads(request.content))
        return stream_json({"description": "图1和图2都是合成测试图片。"})

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def download(request):
        downloads.append(request)
        buffer = BytesIO()
        Image.new("RGB", (len(downloads), 1), "blue").save(buffer, format="PNG")
        return httpx.Response(200, headers={"content-type": "image/png"}, content=buffer.getvalue())

    async with ChatCompletionsGateway(
        base_url="https://vision.example/v1",
        api_key="synthetic",
        model="synthetic-vision",
        transport=httpx2.MockTransport(serve),
    ) as gateway:
        outcome, generator, _ = await replay(
            rpc,
            MediaDownloader(resolver=resolve, transport=httpx.MockTransport(download)),
            ImageDescriber(
                gateway, processor="synthetic:v1", image_tokens=2048, window_tokens=window_tokens
            ),
            parts=(
                MessagePart("image", reference="image-ref"),
                MessagePart("text", text="比较这两张"),
                MessagePart("image", reference="second-ref"),
                *(MessagePart("image", reference=f"extra-{i}") for i in range(image_count - 2)),
            ),
        )
    if image_count > 4 or window_tokens == 5000:
        assert outcome == "media_error" and requests == []
        if image_count > 4:
            assert rpc.calls == [] and downloads == []
        return
    assert outcome == "confirmed"
    assert len(requests) == 1
    content = requests[0]["messages"][1]["content"]
    assert [part["type"] for part in content] == ["text", "image_url", "image_url"]
    assert [row["image_number"] for row in json.loads(content[0]["text"])["images"]] == [1, 2]
    for number, part in enumerate(content[1:], 1):
        raw = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
        with Image.open(BytesIO(raw)) as image:
            assert image.size == (number, 1)
    assert rpc.calls == [
        ("get_msg", {"message_id": 1}),
        ("get_image", {"file": "image-ref"}),
        ("get_image", {"file": "second-ref"}),
    ]
    context = json.loads(generator.requests[-1]["context"])
    row = context["messages"][0]
    assert row["content_version"] == 2
    for index in (0, 2):
        evidence = row["parts"][index]["interpretation"]
        assert evidence["text"] == "图1和图2都是合成测试图片。"
        assert evidence["source_media_refs"] == ["media_1_1", "media_1_3"]
