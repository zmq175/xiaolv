"""SnowLuma's native transcription action, isolated from chat orchestration."""

import re
from collections.abc import Mapping
from datetime import datetime

from xiaolv.application.inbound_speech import MediaUnavailable
from xiaolv.domain.chat_event import ChatEvent, MediaInterpretation
from xiaolv.platforms.onebot import OneBotRPC, QQTarget, _message_data


class OneBotSpeechTranscriber:
    def __init__(self, rpc: OneBotRPC, routes: Mapping[str, QQTarget]) -> None:
        self._rpc = rpc
        self._routes = dict(routes)

    async def transcribe(
        self, event: ChatEvent, part_index: int, expires_at: datetime
    ) -> MediaInterpretation:
        target = self._routes.get(event.conversation_id)
        if target is None or re.fullmatch(r"-?[1-9][0-9]{0,9}", event.message_id) is None:
            raise MediaUnavailable()
        message_id = int(event.message_id)
        if not -(2**31) <= message_id < 2**31:
            raise MediaUnavailable()
        snapshot = await self._rpc.call("get_msg", {"message_id": message_id})
        source = _message_data(snapshot, message_id, target, outgoing=False)
        if source is None or f"qq:{source.get('user_id')}" != event.sender_account_id:
            raise MediaUnavailable()
        segments = source.get("message")
        if not isinstance(segments, list) or not 0 <= part_index < len(segments):
            raise MediaUnavailable()
        if sum(isinstance(part, dict) and part.get("type") == "record" for part in segments) != 1:
            raise MediaUnavailable()
        segment = segments[part_index]
        original = event.parts[part_index]
        if (
            not isinstance(segment, dict)
            or segment.get("type") != "record"
            or not isinstance(segment.get("data"), dict)
            or segment["data"].get("file") != original.reference
            or not original.reference
        ):
            raise MediaUnavailable()
        response = await self._rpc.call("fetch_ptt_text", {"message_id": message_id})
        data = response.get("data")
        if (
            response.get("status") != "ok"
            or type(response.get("retcode")) is not int
            or response["retcode"] != 0
            or not isinstance(data, dict)
            or not isinstance(data.get("text"), str)
        ):
            raise MediaUnavailable()
        return MediaInterpretation("transcript", data["text"], "snowluma-native-asr:v1")
