"""Image acquisition exercised through the approved chat replay boundary."""

import json
from datetime import UTC, datetime, timedelta

import httpx

from xiaolv.application.delivery import DeliveryService
from xiaolv.domain.chat_event import ChatEvent, ConversationContext, MessagePart
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime
from xiaolv.platforms.onebot import QQTarget

SCOPE = "qq:10000:group:20000"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360606060000000050001a5f645400000000049454e44ae426082"
)


class Platform:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return "confirmed"


class Generator:
    def __init__(self):
        self.requests = []

    async def generate(self, **request):
        self.requests.append(request)
        return (
            '{"action":"respond"}'
            if "action" in request["schema"]["properties"]
            else '{"text":"看到了"}'
        )


class RPC:
    def __init__(self):
        self.calls = []
        self.url = "https://media.example/image?signature=PRIVATE"
        self.source_changes = {}
        self.refresh_status = "ok"

    async def call(self, action, params):
        self.calls.append((action, params))
        if action == "get_msg":
            data = {
                "message_id": 1,
                "message_type": "group",
                "group_id": 20000,
                "user_id": 10001,
                "message": [{"type": "image", "data": {"file": "image-ref"}}],
            }
        else:
            assert action == "get_image"
            data = {"url": self.url}
        if action == "get_msg":
            data.update(self.source_changes)
        return {
            "status": "ok" if action == "get_msg" else self.refresh_status,
            "retcode": 0,
            "data": data,
        }


class Vision:
    processor = "synthetic-vision:v1"

    def __init__(self):
        self.images = []

    async def describe(self, image, expires_at):
        self.images.append(image)
        return "一张合成测试图片。"


async def replay(rpc, downloader, vision, *, authorize=None, ttl=5):
    from xiaolv.application.inbound_images import InboundImages
    from xiaolv.platforms.onebot_images import OneBotImageInterpreter

    now = datetime.now(UTC)
    event = ChatEvent(
        SCOPE,
        "qq:10001",
        "1",
        "",
        "群友",
        now,
        now,
        now,
        parts=(MessagePart("image", reference="image-ref"),),
    )
    candidate = ConversationCandidate(
        SCOPE,
        "turn",
        "",
        now + timedelta(seconds=ttl),
        1,
        ConversationContext(1, (event,)),
        source_message_id="1",
    )
    platform = Platform()
    generator = Generator()
    runtime = TextRuntime(
        ChatCompletionsModel(generator),
        DeliveryService(platform, lambda: datetime.now(UTC), lambda _: 1, authorize=authorize),
        lambda: datetime.now(UTC),
        inbound_images=InboundImages(
            OneBotImageInterpreter(rpc, {SCOPE: QQTarget("group", 20000)}, downloader, vision),
            [SCOPE],
        ),
    )
    outcome = await runtime.run(candidate)
    return outcome, generator, platform


async def test_image_download_pins_public_ip_and_keeps_tls_hostname():
    from xiaolv.platforms.media_http import MediaDownloader

    requests = []
    resolutions = []

    async def resolve(host, port):
        resolutions.append((host, port))
        return ("93.184.215.14",)

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    rpc = RPC()
    vision = Vision()
    outcome, generator, platform = await replay(
        rpc, MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)), vision
    )
    assert outcome == "confirmed"
    assert rpc.calls == [("get_msg", {"message_id": 1}), ("get_image", {"file": "image-ref"})]
    assert resolutions == [("media.example", 443)]
    assert len(requests) == 1
    assert requests[0].url.host == "93.184.215.14"
    assert requests[0].headers["host"] == "media.example"
    assert requests[0].extensions["sni_hostname"] == "media.example"
    assert "authorization" not in requests[0].headers
    assert vision.images[0].data.startswith(b"\xff\xd8")
    assert (vision.images[0].width, vision.images[0].height) == (1, 1)
    context = json.loads(generator.requests[1]["context"])
    assert context["messages"][0]["parts"][0]["interpretation"] == {
        "kind": "image_description",
        "text": "一张合成测试图片。",
        "processor": "synthetic-vision:v1",
    }
    assert "PRIVATE" not in generator.requests[1]["context"]
    assert len(platform.sent) == 1


import pytest


@pytest.mark.parametrize(
    ("url", "addresses"),
    [
        ("file:///etc/passwd", ("93.184.215.14",)),
        ("http://media.example/a", ("93.184.215.14",)),
        ("https://user:pass@media.example/a", ("93.184.215.14",)),
        ("https://media.example:8443/a", ("93.184.215.14",)),
        ("https://media.example/a#fragment", ("93.184.215.14",)),
        ("https://127.0.0.1/a", ("127.0.0.1",)),
        ("https://media.example/a", ("10.0.0.1",)),
        ("https://media.example/a", ("93.184.215.14", "169.254.169.254")),
        ("https://media.example/a", ("::1",)),
        ("https://media.example/a", ("224.0.0.1",)),
        ("https://media.example/a", ("2002:7f00:1::",)),
    ],
    ids=[
        "file",
        "http",
        "credentials",
        "port",
        "fragment",
        "loopback",
        "private",
        "mixed-dns",
        "ipv6-local",
        "multicast",
        "transition",
    ],
)
async def test_unsafe_image_location_never_reaches_http_or_vision(url, addresses):
    from xiaolv.platforms.media_http import MediaDownloader

    requests = []

    async def resolve(host, port):
        return addresses

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    rpc = RPC()
    rpc.url = url
    vision = Vision()
    outcome, generator, platform = await replay(
        rpc, MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)), vision
    )
    assert outcome == "media_error"
    assert requests == []
    assert vision.images == []
    assert len(generator.requests) == 1
    assert platform.sent == []


@pytest.mark.parametrize(
    ("status", "headers", "body"),
    [
        (302, {"content-type": "image/png", "location": "https://127.0.0.1/a"}, PNG),
        (404, {"content-type": "image/png"}, PNG),
        (200, {"content-type": "text/html"}, b"not an image"),
        (200, {"content-type": "image/png"}, b""),
        (200, {"content-type": "image/png", "content-length": "99999"}, PNG),
        (200, {"content-type": "image/png"}, b"x" * 129),
    ],
    ids=["redirect", "error", "mime", "empty", "declared-length", "actual-length"],
)
async def test_invalid_media_response_never_reaches_vision(status, headers, body):
    from xiaolv.platforms.media_http import MediaDownloader

    requests = []

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        requests.append(request)
        return httpx.Response(status, headers=headers, content=body)

    vision = Vision()
    outcome, generator, platform = await replay(
        RPC(),
        MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond), max_bytes=128),
        vision,
    )
    assert outcome == "media_error"
    assert len(requests) == 1
    assert vision.images == []
    assert len(generator.requests) == 1
    assert platform.sent == []


async def test_oversized_image_stream_is_closed_before_reading_remainder():
    from xiaolv.platforms.media_http import MediaDownloader

    read = []
    closed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in (b"a" * 80, b"b" * 80, b"not-read"):
                read.append(len(chunk))
                yield chunk

        async def aclose(self):
            closed.append(True)

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, stream=Stream())

    vision = Vision()
    outcome, _, platform = await replay(
        RPC(),
        MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond), max_bytes=128),
        vision,
    )
    assert outcome == "media_error"
    assert read == [80, 80]
    assert closed
    assert vision.images == [] and platform.sent == []


async def test_compressed_image_response_is_rejected_before_decoding():
    import gzip

    from xiaolv.platforms.media_http import MediaDownloader

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        return httpx.Response(
            200,
            headers={"content-type": "image/png", "content-encoding": "gzip"},
            content=gzip.compress(PNG),
        )

    vision = Vision()
    outcome, _, platform = await replay(
        RPC(), MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)), vision
    )
    assert outcome == "media_error"
    assert vision.images == [] and platform.sent == []


@pytest.mark.parametrize(
    "change",
    [
        {"user_id": 99999},
        {"message": [{"type": "image", "data": {"file": "OTHER_IMAGE"}}]},
        {"message": [{"type": "record", "data": {"file": "image-ref"}}]},
    ],
)
async def test_image_source_mismatch_stops_before_refresh_or_download(change):
    from xiaolv.platforms.media_http import MediaDownloader

    requests = []

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    rpc = RPC()
    rpc.source_changes = change
    vision = Vision()
    outcome, _, platform = await replay(
        rpc, MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)), vision
    )
    assert outcome == "media_error"
    assert rpc.calls == [("get_msg", {"message_id": 1})]
    assert requests == [] and vision.images == [] and platform.sent == []


async def test_failed_image_refresh_does_not_use_returned_url():
    from xiaolv.platforms.media_http import MediaDownloader

    requests = []

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    rpc = RPC()
    rpc.refresh_status = "failed"
    vision = Vision()
    outcome, _, platform = await replay(
        rpc, MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)), vision
    )
    assert outcome == "media_error"
    assert requests == [] and vision.images == [] and platform.sent == []


async def test_revocation_during_download_prevents_vision_call():
    from xiaolv.platforms.media_http import MediaDownloader

    allowed = True

    async def authorize(_):
        return allowed

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        nonlocal allowed
        allowed = False
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    vision = Vision()
    outcome, generator, platform = await replay(
        RPC(),
        MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)),
        vision,
        authorize=authorize,
    )
    assert outcome == "permission_denied"
    assert vision.images == []
    assert len(generator.requests) == 1 and platform.sent == []


async def test_signed_media_url_is_not_written_to_http_logs(caplog):
    from xiaolv.platforms.media_http import MediaDownloader

    caplog.set_level("DEBUG", logger="httpx")
    caplog.set_level("DEBUG", logger="httpcore")

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    outcome, _, _ = await replay(
        RPC(), MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)), Vision()
    )
    assert outcome == "confirmed"
    assert "PRIVATE" not in caplog.text
    assert "signature=" not in caplog.text


async def test_original_deadline_closes_stalled_image_stream():
    import asyncio

    from xiaolv.platforms.media_http import MediaDownloader

    closed = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"a"
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, stream=Stream())

    vision = Vision()
    outcome, generator, platform = await asyncio.wait_for(
        replay(
            RPC(),
            MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)),
            vision,
            ttl=0.2,
        ),
        2,
    )
    assert outcome == "expired"
    assert closed.is_set()
    assert vision.images == [] and platform.sent == []
    assert len(generator.requests) == 1


async def test_large_image_is_decoded_and_resized_before_vision():
    from io import BytesIO

    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    from xiaolv.platforms.media_http import MediaDownloader

    data = BytesIO()
    metadata = PngInfo()
    metadata.add_text("Comment", "PRIVATE_METADATA")
    Image.new("RGBA", (1600, 800), (255, 0, 0, 0)).save(data, format="PNG", pnginfo=metadata)

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=data.getvalue())

    vision = Vision()
    outcome, _, platform = await replay(
        RPC(), MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)), vision
    )
    assert outcome == "confirmed"
    normalized = vision.images[0]
    with Image.open(BytesIO(normalized.data)) as im:
        assert im.format == "JPEG"
        assert im.size == (512, 256)
        assert im.convert("RGB").getpixel((0, 0)) == (255, 255, 255)
        assert "Comment" not in im.info
        assert not im.getexif()
    assert b"PRIVATE_METADATA" not in normalized.data
    assert normalized.content_type == "image/jpeg"
    assert (normalized.width, normalized.height, normalized.original_frames) == (512, 256, 1)
    assert len(platform.sent) == 1


@pytest.mark.parametrize("case", ["invalid", "truncated", "pixels", "edge", "mime", "format"])
async def test_invalid_image_never_reaches_vision(case):
    from io import BytesIO

    from PIL import Image

    from xiaolv.platforms.media_http import MediaDownloader

    mime = "image/png"
    if case == "invalid":
        raw = b"PRIVATE_INVALID_IMAGE"
    elif case == "truncated":
        raw = PNG[:40]
    else:
        size = (6000, 3000) if case == "pixels" else (17000, 1) if case == "edge" else (1, 1)
        data = BytesIO()
        Image.new("RGB", size, "white").save(data, format="BMP" if case == "format" else "PNG")
        raw = data.getvalue()
        if case == "mime":
            mime = "image/jpeg"

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        return httpx.Response(200, headers={"content-type": mime}, content=raw)

    vision = Vision()
    outcome, generator, platform = await replay(
        RPC(), MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)), vision
    )
    assert outcome == "media_error"
    assert vision.images == [] and platform.sent == []
    assert len(generator.requests) == 1


@pytest.mark.parametrize("kind", ["rotated_jpeg", "animated_gif"])
async def test_vision_receives_oriented_image_and_explicit_frame_sampling(kind):
    from io import BytesIO

    from PIL import Image

    from xiaolv.platforms.media_http import MediaDownloader

    data = BytesIO()
    if kind == "rotated_jpeg":
        original = Image.new("RGB", (80, 40), "red")
        exif = Image.Exif()
        exif[274] = 6  # EXIF orientation: 90 degrees clockwise.
        original.save(data, format="JPEG", exif=exif)
        mime = "image/jpeg"
    else:
        first = Image.new("RGB", (80, 40), "red")
        second = Image.new("RGB", (80, 40), "blue")
        first.save(data, format="GIF", save_all=True, append_images=[second], duration=100, loop=0)
        mime = "image/gif"

    async def resolve(host, port):
        return ("93.184.215.14",)

    async def respond(request):
        return httpx.Response(200, headers={"content-type": mime}, content=data.getvalue())

    vision = Vision()
    outcome, _, _ = await replay(
        RPC(), MediaDownloader(resolver=resolve, transport=httpx.MockTransport(respond)), vision
    )
    assert outcome == "confirmed"
    normalized = vision.images[0]
    assert normalized.sampled_frames == (0,)
    with Image.open(BytesIO(normalized.data)) as image:
        assert image.format == "JPEG"
        assert not image.getexif()
        if kind == "rotated_jpeg":
            assert image.size == (40, 80)
            assert (normalized.width, normalized.height) == (40, 80)
            assert normalized.original_frames == 1
        else:
            assert normalized.original_frames == 2
            red, green, blue = image.getpixel((20, 20))
            assert red > 240 and green < 10 and blue < 10
