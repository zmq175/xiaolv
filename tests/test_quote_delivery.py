from datetime import UTC, datetime, timedelta

import pytest

from xiaolv.application.delivery import DeliveryRequest, DeliveryService, NotSent
from xiaolv.platforms.onebot import OneBotPreparation, OneBotSender, QQTarget

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


class QuoteRPC:
    def __init__(self, kind="group"):
        self.calls = []
        self.original = {
            "message_id": -123,
            "message_type": kind,
            "sub_type": "friend",
            "group_id": 10001,
            "user_id": 10001,
        }
        self.readback = {
            "message_id": 789,
            "message_type": kind,
            "sub_type": "friend",
            "group_id": 10001,
            "target_id": 10001,
            "message": [{"type": "reply", "data": {"id": "-123"}}],
        }

    async def call(self, action, params):
        self.calls.append((action, params))
        data = {"message_id": 789}
        if action == "get_msg":
            data = self.original if params["message_id"] == -123 else self.readback
            if isinstance(data, Exception):
                raise data
        return {"status": "ok", "retcode": 0, "data": data}


def setup(rpc, kind="group"):
    routes = {"chat-1": QQTarget(kind, 10001)}
    service = DeliveryService(
        OneBotSender(rpc, routes),
        lambda: NOW,
        lambda _: 1,
        prepare=OneBotPreparation(rpc, routes),
    )
    request = DeliveryRequest(
        "out-1", "chat-1", NOW + timedelta(seconds=45), 1, "好啊", reply_to="-123"
    )
    return service, request


@pytest.mark.parametrize("kind", ["group", "private"])
async def test_quote_readback_preserves_native_target_and_prevents_duplicate_send(kind):
    rpc = QuoteRPC(kind)
    service, request = setup(rpc, kind)
    assert await service.deliver(request) == "confirmed"
    assert await service.deliver(request) == "confirmed"
    assert rpc.calls == [
        ("get_msg", {"message_id": -123}),
        (
            f"send_{kind}_msg",
            {
                "group_id" if kind == "group" else "user_id": 10001,
                "message": [
                    {"type": "reply", "data": {"id": "-123"}},
                    {"type": "text", "data": {"text": "好啊"}},
                ],
            },
        ),
        ("get_msg", {"message_id": 789}),
    ]


@pytest.mark.parametrize(
    "corruption", ["missing", "wrong_quote", "wrong_scope", "wrong_id", "read_error"]
)
async def test_failed_quote_readback_is_unknown_and_never_resent(corruption):
    rpc = QuoteRPC()
    if corruption == "missing":
        rpc.readback["message"] = [{"type": "text", "data": {"text": "好啊"}}]
    elif corruption == "wrong_quote":
        rpc.readback["message"] = [{"type": "reply", "data": {"id": "999"}}]
    elif corruption == "wrong_scope":
        rpc.readback["group_id"] = 99999
    elif corruption == "wrong_id":
        rpc.readback["message_id"] = True
    else:
        rpc.readback = NotSent("read request did not reach platform")
    service, request = setup(rpc)
    assert await service.deliver(request) == "unknown"
    assert await service.deliver(request) == "unknown"
    assert [action for action, _ in rpc.calls] == ["get_msg", "send_group_msg", "get_msg"]


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("group", "group_id", 99999),
        ("group", "message_id", 123),
        ("private", "user_id", 99999),
        ("private", "sub_type", "group"),
    ],
)
async def test_quote_target_outside_route_is_not_sent(kind, field, value):
    rpc = QuoteRPC(kind)
    rpc.original[field] = value
    service, request = setup(rpc, kind)
    assert await service.deliver(request) == "not_sent"
    assert rpc.calls == [("get_msg", {"message_id": -123})]
