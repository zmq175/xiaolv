"""Native OneBot sender contracts."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from xiaolv.application.delivery_contracts import DeliveryRequest, NotSent


class OneBotRPC(Protocol):
    async def call(self, action: str, params: dict[str, object]) -> dict[str, object]: ...


@dataclass(frozen=True)
class QQTarget:
    kind: Literal["group", "private"]
    id: int


class OneBotPreparation:
    """Read-only resolution; the returned sender performs no member lookup."""

    def __init__(self, rpc: OneBotRPC, routes: Mapping[str, QQTarget]) -> None:
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
        if request.reply_to is not None:
            raise NotSent("dynamic quote resolution is unavailable")
        if request.mentions and (
            target.kind != "group"
            or any(re.fullmatch(r"qq:[1-9][0-9]*", member) is None for member in request.mentions)
        ):
            raise NotSent("mention target is unavailable or not authorized")
        if not request.mentions:
            return OneBotSender(self._rpc, self._routes)
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
            self._rpc, self._routes, member_accounts={request.conversation_id: members}
        )


class OneBotSender:
    def __init__(
        self,
        rpc: OneBotRPC,
        routes: Mapping[str, QQTarget],
        *,
        member_accounts: Mapping[str, Mapping[str, int]] | None = None,
        reply_messages: Mapping[str, Mapping[str, int]] | None = None,
    ) -> None:
        self._rpc = rpc
        self._routes = dict(routes)
        self._members = {key: dict(value) for key, value in (member_accounts or {}).items()}
        self._replies = {key: dict(value) for key, value in (reply_messages or {}).items()}

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
        for member in dict.fromkeys(request.mentions):
            qq = members.get(member)
            if target.kind != "group" or member == "all" or type(qq) is not int or qq <= 0:
                raise NotSent("mention target is unavailable or not authorized")
            segments.append({"type": "at", "data": {"qq": str(qq)}})
        segments.append({"type": "text", "data": {"text": request.text}})
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
            return "confirmed"
        return "unknown"
