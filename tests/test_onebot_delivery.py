from datetime import UTC, datetime, timedelta

import pytest

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.platforms.onebot import OneBotSender, QQTarget

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


class RecordingRPC:
    def __init__(self, response=None):
        self.requests = []
        self.response = (
            response
            if response is not None
            else {"status": "ok", "retcode": 0, "data": {"message_id": 123}}
        )

    async def call(self, action, params):
        self.requests.append((action, params))
        return self.response


def request():
    return DeliveryRequest(
        "out-1", "internal-chat", NOW + timedelta(seconds=45), 1, "@朋友 [CQ:image,file=bad]"
    )


def service(rpc, routes):
    return DeliveryService(OneBotSender(rpc, routes), lambda: NOW, lambda _: 1)


async def test_group_reply_uses_native_array_text_and_trusted_target():
    rpc = RecordingRPC()
    sender = service(rpc, {"internal-chat": QQTarget("group", 10001)})
    assert await sender.deliver(request()) == "confirmed"
    assert rpc.requests == [
        (
            "send_group_msg",
            {
                "group_id": 10001,
                "message": [{"type": "text", "data": {"text": "@朋友 [CQ:image,file=bad]"}}],
            },
        )
    ]


async def test_private_reply_uses_private_action():
    rpc = RecordingRPC()
    sender = service(rpc, {"internal-chat": QQTarget("private", 10002)})
    assert await sender.deliver(request()) == "confirmed"
    assert rpc.requests == [
        (
            "send_private_msg",
            {
                "user_id": 10002,
                "message": [{"type": "text", "data": {"text": request().text}}],
            },
        )
    ]


async def test_unregistered_conversation_never_calls_rpc():
    rpc = RecordingRPC()
    assert await service(rpc, {}).deliver(request()) == "not_sent"
    assert rpc.requests == []


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"status": "ok", "retcode": 0, "data": None},
        {"status": "ok", "retcode": False, "data": {"message_id": 123}},
        {"status": "ok", "retcode": 0, "data": {"message_id": True}},
        {"status": "failed", "retcode": 1200, "data": None},
    ],
)
async def test_ambiguous_responses_are_unknown_and_not_retried(response):
    rpc = RecordingRPC(response)
    sender = service(rpc, {"internal-chat": QQTarget("group", 10001)})
    assert await sender.deliver(request()) == "unknown"
    assert await sender.deliver(request()) == "unknown"
    assert len(rpc.requests) == 1


@pytest.mark.parametrize("retcode", [1400, 1404])
async def test_explicit_protocol_rejection_is_not_sent(retcode):
    rpc = RecordingRPC({"status": "failed", "retcode": retcode, "data": None})
    sender = service(rpc, {"internal-chat": QQTarget("group", 10001)})
    assert await sender.deliver(request()) == "not_sent"


@pytest.mark.parametrize("kind,target_id", [("group", -1), ("group", True), ("unknown", 10001)])
async def test_invalid_local_target_never_reaches_rpc(kind, target_id):
    rpc = RecordingRPC()
    sender = service(rpc, {"internal-chat": QQTarget(kind, target_id)})
    assert await sender.deliver(request()) == "not_sent"
    assert rpc.requests == []


async def test_registered_member_is_a_real_at_segment():
    from dataclasses import replace

    rpc = RecordingRPC()
    adapter = OneBotSender(
        rpc,
        {"internal-chat": QQTarget("group", 10001)},
        member_accounts={"internal-chat": {"account-alice": 10002}},
    )
    sender = DeliveryService(adapter, lambda: NOW, lambda _: 1)
    outgoing = replace(request(), mentions=("account-alice",))
    assert await sender.deliver(outgoing) == "confirmed"
    assert rpc.requests[0][1]["message"] == [
        {"type": "at", "data": {"qq": "10002"}},
        {"type": "text", "data": {"text": outgoing.text}},
    ]


@pytest.mark.parametrize(
    "kind,mentions,members",
    [
        ("group", ("missing",), {}),
        ("group", ("account-alice",), {"other-chat": {"account-alice": 10002}}),
        ("group", ("all",), {"internal-chat": {"all": 10002}}),
        ("private", ("account-alice",), {"internal-chat": {"account-alice": 10002}}),
        ("group", ("account-alice",), {"internal-chat": {"account-alice": True}}),
    ],
)
async def test_unresolved_or_disallowed_mention_is_not_sent(kind, mentions, members):
    from dataclasses import replace

    rpc = RecordingRPC()
    adapter = OneBotSender(rpc, {"internal-chat": QQTarget(kind, 10001)}, member_accounts=members)
    sender = DeliveryService(adapter, lambda: NOW, lambda _: 1)
    assert await sender.deliver(replace(request(), mentions=mentions)) == "not_sent"
    assert rpc.requests == []


async def test_repeated_member_reference_only_notifies_once():
    from dataclasses import replace

    rpc = RecordingRPC()
    adapter = OneBotSender(
        rpc,
        {"internal-chat": QQTarget("group", 10001)},
        member_accounts={"internal-chat": {"account-alice": 10002}},
    )
    sender = DeliveryService(adapter, lambda: NOW, lambda _: 1)
    assert (
        await sender.deliver(replace(request(), mentions=("account-alice", "account-alice")))
        == "confirmed"
    )
    assert rpc.requests[0][1]["message"] == [
        {"type": "at", "data": {"qq": "10002"}},
        {"type": "text", "data": {"text": request().text}},
    ]


async def test_quote_uses_native_reply_without_adding_a_mention():
    from dataclasses import replace

    rpc = RecordingRPC()
    adapter = OneBotSender(
        rpc,
        {"internal-chat": QQTarget("group", 10001)},
        reply_messages={"internal-chat": {"message-first": -123}},
    )
    sender = DeliveryService(adapter, lambda: NOW, lambda _: 1)
    outgoing = replace(request(), reply_to="message-first")
    assert await sender.deliver(outgoing) == "confirmed"
    assert rpc.requests == [
        (
            "send_group_msg",
            {
                "group_id": 10001,
                "message": [
                    {"type": "reply", "data": {"id": "-123"}},
                    {"type": "text", "data": {"text": outgoing.text}},
                ],
            },
        )
    ]


@pytest.mark.parametrize("message_id", [0, True, "123", -(2**31) - 1, 2**31])
async def test_invalid_quote_id_is_rejected_without_sending(message_id):
    from dataclasses import replace

    rpc = RecordingRPC()
    adapter = OneBotSender(
        rpc,
        {"internal-chat": QQTarget("group", 10001)},
        reply_messages={"internal-chat": {"message-first": message_id}},
    )
    sender = DeliveryService(adapter, lambda: NOW, lambda _: 1)
    assert await sender.deliver(replace(request(), reply_to="message-first")) == "not_sent"
    assert rpc.requests == []


@pytest.mark.parametrize("references", [{}, {"other-chat": {"message-first": 123}}])
async def test_quote_cannot_resolve_from_another_conversation(references):
    from dataclasses import replace

    rpc = RecordingRPC()
    adapter = OneBotSender(
        rpc,
        {"internal-chat": QQTarget("group", 10001)},
        reply_messages=references,
    )
    sender = DeliveryService(adapter, lambda: NOW, lambda _: 1)
    assert await sender.deliver(replace(request(), reply_to="message-first")) == "not_sent"
    assert rpc.requests == []


async def test_quote_and_explicit_mention_can_be_combined():
    from dataclasses import replace

    rpc = RecordingRPC()
    adapter = OneBotSender(
        rpc,
        {"internal-chat": QQTarget("group", 10001)},
        reply_messages={"internal-chat": {"message-first": 123}},
        member_accounts={"internal-chat": {"account-alice": 10002}},
    )
    sender = DeliveryService(adapter, lambda: NOW, lambda _: 1)
    outgoing = replace(request(), reply_to="message-first", mentions=("account-alice",))
    assert await sender.deliver(outgoing) == "confirmed"
    assert rpc.requests[0][1]["message"] == [
        {"type": "reply", "data": {"id": "123"}},
        {"type": "at", "data": {"qq": "10002"}},
        {"type": "text", "data": {"text": outgoing.text}},
    ]


async def test_private_quote_keeps_private_route():
    from dataclasses import replace

    rpc = RecordingRPC()
    adapter = OneBotSender(
        rpc,
        {"internal-chat": QQTarget("private", 10002)},
        reply_messages={"internal-chat": {"message-first": -(2**31)}},
    )
    sender = DeliveryService(adapter, lambda: NOW, lambda _: 1)
    assert await sender.deliver(replace(request(), reply_to="message-first")) == "confirmed"
    assert rpc.requests == [
        (
            "send_private_msg",
            {
                "user_id": 10002,
                "message": [
                    {"type": "reply", "data": {"id": "-2147483648"}},
                    {"type": "text", "data": {"text": request().text}},
                ],
            },
        )
    ]


@pytest.mark.parametrize("stale,expected", [("expired", "expired"), ("epoch", "superseded")])
async def test_quote_does_not_bypass_delivery_validity(stale, expected):
    from dataclasses import replace

    rpc = RecordingRPC()
    adapter = OneBotSender(
        rpc,
        {"internal-chat": QQTarget("group", 10001)},
        reply_messages={"internal-chat": {"message-first": 123}},
    )
    sender = DeliveryService(adapter, lambda: NOW, lambda _: 1)
    outgoing = replace(request(), reply_to="message-first")
    if stale == "expired":
        outgoing = replace(outgoing, expires_at=NOW)
    else:
        outgoing = replace(outgoing, generation_epoch=0)
    assert await sender.deliver(outgoing) == expected
    assert rpc.requests == []
