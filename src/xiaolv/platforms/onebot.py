"""Native OneBot sender contracts."""

import base64
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from xiaolv.application.delivery_contracts import DeliveryRequest, NotSent
from xiaolv.domain.audio_artifact import AudioArtifacts
from xiaolv.domain.text_reply import TextPart


class OneBotRPC(Protocol):
    async def call(self, action: str, params: dict[str, object]) -> dict[str, object]: ...


@dataclass(frozen=True)
class QQTarget:
    kind: Literal["group", "private"]
    id: int


def _message_data(
    response: dict[str, object], message_id: int, target: QQTarget, *, outgoing: bool
) -> dict[str, object] | None:
    data = response.get("data")
    if (
        response.get("status") != "ok"
        or type(response.get("retcode")) is not int
        or response["retcode"] != 0
        or not isinstance(data, dict)
        or type(data.get("message_id")) is not int
        or data["message_id"] != message_id
        or data.get("message_type") != target.kind
    ):
        return None
    key = "group_id" if target.kind == "group" else "target_id" if outgoing else "user_id"
    if type(data.get(key)) is not int or data[key] != target.id:
        return None
    if target.kind == "private" and data.get("sub_type") != "friend":
        return None
    return data


class OneBotPreparation:
    """Read-only resolution; the returned sender performs no member lookup."""

    def __init__(
        self,
        rpc: OneBotRPC,
        routes: Mapping[str, QQTarget],
        *,
        artifacts: AudioArtifacts | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._rpc = rpc
        self._routes = dict(routes)

    async def __call__(self, request: DeliveryRequest) -> "OneBotSender":
        target = self._routes.get(request.conversation_id)
        if (
            target is None
            or target.kind not in ("group", "private")
            or type(target.id) is not int
            or target.id <= 0
        ):
            raise NotSent("conversation route is unavailable")
        if request.audio is not None:
            if self._artifacts is None or request.audio.conversation_id != request.conversation_id:
                raise NotSent("audio artifact unavailable")
            audio = await self._artifacts.read(request.audio)
            return OneBotSender(
                self._rpc, self._routes, audio_content={request.audio.sha256: audio}
            )
        if request.mentions and (
            target.kind != "group"
            or any(re.fullmatch(r"qq:[1-9][0-9]*", member) is None for member in request.mentions)
        ):
            raise NotSent("mention target is unavailable or not authorized")
        replies: dict[str, int] = {}
        if request.reply_to is not None:
            if re.fullmatch(r"-?[1-9][0-9]{0,9}", request.reply_to) is None:
                raise NotSent("invalid quote reference")
            message_id = int(request.reply_to)
            if not -(2**31) <= message_id < 2**31:
                raise NotSent("invalid quote reference")
            response = await self._rpc.call("get_msg", {"message_id": message_id})
            if _message_data(response, message_id, target, outgoing=False) is None:
                raise NotSent("quote target unavailable in this conversation")
            replies[request.reply_to] = message_id
        if not request.mentions:
            return OneBotSender(
                self._rpc,
                self._routes,
                reply_messages={request.conversation_id: replies},
                verify_quotes=True,
            )
        response = await self._rpc.call(
            "get_group_member_list", {"group_id": target.id, "no_cache": True}
        )
        data = response.get("data")
        if (
            response.get("status") != "ok"
            or type(response.get("retcode")) is not int
            or response["retcode"] != 0
            or not isinstance(data, list)
        ):
            raise NotSent("member lookup failed")
        members: dict[str, int] = {}
        for item in data:
            if (
                not isinstance(item, dict)
                or type(item.get("group_id")) is not int
                or item["group_id"] != target.id
                or type(item.get("user_id")) is not int
                or item["user_id"] <= 0
            ):
                raise NotSent("invalid member snapshot")
            members[f"qq:{item['user_id']}"] = item["user_id"]
        return OneBotSender(
            self._rpc,
            self._routes,
            member_accounts={request.conversation_id: members},
            reply_messages={request.conversation_id: replies},
            verify_quotes=True,
        )


class OneBotSender:
    def __init__(
        self,
        rpc: OneBotRPC,
        routes: Mapping[str, QQTarget],
        *,
        member_accounts: Mapping[str, Mapping[str, int]] | None = None,
        reply_messages: Mapping[str, Mapping[str, int]] | None = None,
        verify_quotes: bool = False,
        audio_content: Mapping[str, bytes] | None = None,
    ) -> None:
        self._rpc = rpc
        self._routes = dict(routes)
        self._members = {key: dict(value) for key, value in (member_accounts or {}).items()}
        self._replies = {key: dict(value) for key, value in (reply_messages or {}).items()}
        self._verify_quotes = verify_quotes
        self._audio = dict(audio_content or {})

    async def send(self, request: DeliveryRequest) -> Literal["confirmed", "unknown"]:
        target = self._routes.get(request.conversation_id)
        if (
            target is None
            or target.kind not in ("group", "private")
            or type(target.id) is not int
            or target.id <= 0
        ):
            raise NotSent("conversation route is unavailable")
        segments = []
        if request.reply_to is not None:
            message_id = self._replies.get(request.conversation_id, {}).get(request.reply_to)
            if type(message_id) is not int or message_id == 0 or not -(2**31) <= message_id < 2**31:
                raise NotSent("reply target is unavailable")
            segments.append({"type": "reply", "data": {"id": str(message_id)}})
        members = self._members.get(request.conversation_id, {})
        content_parts = request.parts or (
            *(TextPart("mention", member) for member in dict.fromkeys(request.mentions)),
            TextPart("text", request.text),
        )
        for part in content_parts:
            if part.kind == "text":
                segments.append({"type": "text", "data": {"text": part.value}})
                continue
            member = part.value
            qq = members.get(member)
            if target.kind != "group" or member == "all" or type(qq) is not int or qq <= 0:
                raise NotSent("mention target is unavailable or not authorized")
            segments.append({"type": "at", "data": {"qq": str(qq)}})
        if request.audio is not None:
            audio = self._audio.get(request.audio.sha256)
            if audio is None:
                raise NotSent("audio artifact was not prepared")
            segments = [
                {
                    "type": "record",
                    "data": {"file": "base64://" + base64.b64encode(audio).decode("ascii")},
                }
            ]
        response = await self._rpc.call(
            f"send_{target.kind}_msg",
            {
                "group_id" if target.kind == "group" else "user_id": target.id,
                "message": segments,
            },
        )
        if response.get("status") == "failed" and response.get("retcode") in (1400, 1404):
            raise NotSent("OneBot rejected action or parameters")
        data = response.get("data")
        if (
            response.get("status") == "ok"
            and type(response.get("retcode")) is int
            and response["retcode"] == 0
            and isinstance(data, dict)
            and type(data.get("message_id")) is int
        ):
            if request.reply_to is not None and self._verify_quotes:
                try:
                    readback = await self._rpc.call("get_msg", {"message_id": data["message_id"]})
                    stored = _message_data(readback, data["message_id"], target, outgoing=True)
                    parts = stored.get("message") if stored is not None else None
                    if not isinstance(parts, list):
                        return "unknown"
                    quotes = [
                        part
                        for part in parts
                        if isinstance(part, dict) and part.get("type") == "reply"
                    ]
                    if quotes != [segments[0]]:
                        return "unknown"
                except Exception:  # noqa: BLE001 - send already accepted; no retry on failed readback
                    return "unknown"
            return "confirmed"
        return "unknown"
