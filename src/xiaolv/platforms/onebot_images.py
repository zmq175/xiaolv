"""Native image references resolved before bounded downloading and vision processing."""

import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Protocol

from xiaolv.application.inbound_speech import MediaUnavailable
from xiaolv.domain.chat_event import ChatEvent, MediaInterpretation
from xiaolv.domain.image import PreparedImage
from xiaolv.media.image_normalizer import ImageNormalizer
from xiaolv.platforms.media_http import MediaDownloader
from xiaolv.platforms.onebot import OneBotRPC, QQTarget, _message_data


class VisionDescriber(Protocol):
    """Describe normalized pixels, preserving sampling limits and reserving media cost.

    Decoding occurs before this boundary. No production vision provider is wired yet.
    """

    processor: str

    async def describe(
        self, image: PreparedImage | tuple[PreparedImage, ...], expires_at: datetime
    ) -> str: ...


class OneBotImageInterpreter:
    def __init__(
        self,
        rpc: OneBotRPC,
        routes: Mapping[str, QQTarget],
        downloader: MediaDownloader,
        vision: VisionDescriber,
    ) -> None:
        self._rpc, self._routes = rpc, dict(routes)
        self._downloader, self._vision = downloader, vision
        self.processor = f"{vision.processor}|image-normalizer:v1"
        self._normalizer = ImageNormalizer()

    async def interpret(
        self,
        event: ChatEvent,
        part_index: int | tuple[int, ...],
        expires_at: datetime,
        before_vision: Callable[[], Awaitable[None]],
    ) -> MediaInterpretation:
        target = self._routes.get(event.conversation_id)
        if target is None or re.fullmatch(r"-?[1-9][0-9]{0,9}", event.message_id) is None:
            raise MediaUnavailable()
        message_id = int(event.message_id)
        if not -(2**31) <= message_id < 2**31:
            raise MediaUnavailable()
        response = await self._rpc.call("get_msg", {"message_id": message_id})
        source = _message_data(response, message_id, target, outgoing=False)
        if source is None or f"qq:{source.get('user_id')}" != event.sender_account_id:
            raise MediaUnavailable()
        indices = (part_index,) if isinstance(part_index, int) else part_index
        prepared_images = []
        for index in indices:
            reference = event.parts[index].reference
            segments = source.get("message")
            if not isinstance(segments, list) or not 0 <= index < len(segments):
                raise MediaUnavailable()
            segment = segments[index]
            if (
                not isinstance(segment, dict)
                or segment.get("type") not in {"image", "mface"}
                or not isinstance(segment.get("data"), dict)
                or segment["data"].get("file") != reference
                or not reference
            ):
                raise MediaUnavailable()
            response = await self._rpc.call("get_image", {"file": reference})
            data = response.get("data")
            if (
                response.get("status") != "ok"
                or type(response.get("retcode")) is not int
                or response["retcode"] != 0
                or not isinstance(data, dict)
                or not isinstance(data.get("url"), str)
            ):
                raise MediaUnavailable()
            image = await self._downloader.fetch(data["url"], expires_at)
            await before_vision()
            prepared = await self._normalizer.prepare(image, expires_at)
            await before_vision()
            prepared_images.append(prepared)
        vision_input = prepared_images[0] if len(prepared_images) == 1 else tuple(prepared_images)
        description = await self._vision.describe(vision_input, expires_at)
        return MediaInterpretation("image_description", description, self.processor)
