from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.domain.text_reply import TextPart
from xiaolv.platforms.onebot import OneBotSender, QQTarget

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


class RPC:
    def __init__(self):
        self.calls = []

    async def call(self, action, params):
        self.calls.append((action, params))
        return {"status": "ok", "retcode": 0, "data": {"message_id": 123}}


def setup():
    rpc = RPC()
    adapter = OneBotSender(
        rpc,
        {"chat": QQTarget("group", 10001)},
        member_accounts={"chat": {"qq:10002": 10002}},
        reply_messages={"chat": {"original": -123}},
    )
    return rpc, DeliveryService(adapter, lambda: NOW, lambda _: 1)


def outgoing():
    return DeliveryRequest(
        "out",
        "chat",
        NOW + timedelta(seconds=45),
        1,
        "这件事问  比较清楚",
        mentions=("qq:10002",),
        reply_to="original",
        parts=(
            TextPart("text", "这件事问 "),
            TextPart("mention", "qq:10002"),
            TextPart("text", " 比较清楚"),
        ),
    )


async def test_delivery_preserves_inline_mention_and_separate_quote():
    rpc, service = setup()
    assert await service.deliver(outgoing()) == "confirmed"
    assert rpc.calls == [
        (
            "send_group_msg",
            {
                "group_id": 10001,
                "message": [
                    {"type": "reply", "data": {"id": "-123"}},
                    {"type": "text", "data": {"text": "这件事问 "}},
                    {"type": "at", "data": {"qq": "10002"}},
                    {"type": "text", "data": {"text": " 比较清楚"}},
                ],
            },
        )
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"text": "不一致"},
        {"mentions": ()},
        {"parts": (TextPart("image", "bad"),)},
        {"text": "", "parts": (TextPart("mention", "qq:10002"),)},
        {"text": "x" * 33, "mentions": (), "parts": (TextPart("text", "x"),) * 33},
        {
            "text": "x",
            "mentions": ("qq:10002",) * 2,
            "parts": (
                TextPart("text", "x"),
                TextPart("mention", "qq:10002"),
                TextPart("mention", "qq:10002"),
            ),
        },
    ],
)
async def test_inconsistent_or_invalid_parts_never_send(changes):
    rpc, service = setup()
    assert await service.deliver(replace(outgoing(), **changes)) == "not_sent"
    assert rpc.calls == []


async def test_replay_preserves_ordered_reply():
    from xiaolv.domain.chat_event import ChatEvent, ConversationContext
    from xiaolv.domain.text_reply import TextReply
    from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime

    class Model:
        async def decide(self, candidate):
            return "respond"

        async def reply(self, candidate):
            request = outgoing()
            return TextReply(request.text, request.mentions, request.reply_to, request.parts)

    rpc, service = setup()
    event = ChatEvent("chat", "qq:10002", "original", "找谁", "朋友", NOW, NOW, NOW)
    candidate = ConversationCandidate(
        "chat",
        "event",
        "找谁",
        NOW + timedelta(seconds=45),
        1,
        ConversationContext(1, (event,)),
    )
    assert await TextRuntime(Model(), service, lambda: NOW).run(candidate) == "confirmed"
    assert rpc.calls[0][1]["message"] == [
        {"type": "reply", "data": {"id": "-123"}},
        {"type": "text", "data": {"text": "这件事问 "}},
        {"type": "at", "data": {"qq": "10002"}},
        {"type": "text", "data": {"text": " 比较清楚"}},
    ]
