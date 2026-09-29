"""Native OneBot sender contracts."""

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


class OneBotSender:
    def __init__(
        self,
        rpc: OneBotRPC,
        routes: Mapping[str, QQTarget],
        *,
        member_accounts: Mapping[str, Mapping[str, int]] | None = None,
    ) -> None:
        self._rpc = rpc
        self._routes = dict(routes)
        self._members = {key: dict(value) for key, value in (member_accounts or {}).items()}

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
