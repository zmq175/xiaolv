"""Native image references resolved before bounded downloading and vision processing."""

import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Protocol

from xiaolv.application.inbound_speech import MediaUnavailable
from xiaolv.domain.chat_event import ChatEvent, MediaInterpretation
from xiaolv.platforms.media_http import ImageBytes, MediaDownloader
from xiaolv.platforms.onebot import OneBotRPC, QQTarget, _message_data


class VisionDescriber(Protocol):
    """Implementations must validate/decode bounded bytes and reserve media cost before calling a model.

    No production vision provider is wired yet; image Content-Type is not format validation.
    """

    processor: str

    async def describe(self, image: ImageBytes, expires_at: datetime) -> str: ...


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
        self.processor = vision.processor

    async def interpret(
        self,
        event: ChatEvent,
        part_index: int,
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
        reference = event.parts[part_index].reference
        segments = source.get("message")
        if not isinstance(segments, list) or not 0 <= part_index < len(segments):
            raise MediaUnavailable()
        segment = segments[part_index]
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
        description = await self._vision.describe(image, expires_at)
        return MediaInterpretation("image_description", description, self.processor)
