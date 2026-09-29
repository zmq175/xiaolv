import json
from datetime import UTC, datetime, timedelta

import tiktoken

from xiaolv.application.delivery import DeliveryService
from xiaolv.domain.chat_event import ChatEvent, ConversationContext
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


class Platform:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return "confirmed"


def event(index, text):
    return ChatEvent("chat-1", "user-1", str(index), text, "群友", NOW, NOW, NOW)


async def test_chinese_history_is_selected_by_complete_request_token_budget():
    from xiaolv.domain.context_policy import ContextPolicy

    requests = []

    class Generator:
        async def generate(self, **request):
            requests.append(request)
            return (
                '{"action":"respond"}'
                if "action" in request["schema"]["properties"]
                else '{"text":"好的"}'
            )

    policy = ContextPolicy(decision_tokens=1500, reply_tokens=2000)
    messages = [event(i, f"话题{i}：" + "这里是中文聊天，讨论周末的活动。" * 8) for i in range(60)]
    messages.append(event(60, "那我们周末见？"))
    candidate = ConversationCandidate(
        "chat-1",
        "turn-1",
        "那我们周末见？",
        NOW + timedelta(seconds=45),
        1,
        ConversationContext(1, tuple(messages)),
    )
    platform = Platform()
    runtime = TextRuntime(
        ChatCompletionsModel(Generator(), context_policy=policy),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
    )
    assert await runtime.run(candidate) == "confirmed"
    assert len(requests) == 2
    encoding = tiktoken.get_encoding("cl100k_base")
    for request, limit in zip(requests, (1500, 2000), strict=True):
        encoded = sum(
            len(encoding.encode(text, disallowed_special=()))
            for text in (
                request["instructions"],
                request["context"],
                json.dumps(request["schema"], ensure_ascii=False),
            )
        )
        assert encoded + 128 <= limit
        context = json.loads(request["context"])
        assert context["target_text"] == "那我们周末见？"
        assert 0 < len(context["messages"]) < 61
        assert context["messages"][-1]["text"] == "那我们周末见？"
    assert len(platform.sent) == 1


async def test_required_text_over_budget_never_calls_model_or_sends():
    calls = []

    class Generator:
        async def generate(self, **request):
            calls.append(request)
            return '{"action":"silence"}'

    platform = Platform()
    candidate = ConversationCandidate(
        "chat-1", "turn-1", "中文消息" * 20000, NOW + timedelta(seconds=45), 1
    )
    runtime = TextRuntime(
        ChatCompletionsModel(Generator()),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
    )
    assert await runtime.run(candidate) == "context_overflow"
    assert calls == []
    assert platform.sent == []


async def test_direct_quote_keeps_full_original_ahead_of_unrelated_recent_history():
    from dataclasses import replace

    from xiaolv.domain.chat_event import MessagePart
    from xiaolv.domain.context_policy import ContextPolicy

    requests = []

    class Generator:
        async def generate(self, **request):
            requests.append(request)
            return '{"action":"silence"}'

    original = event(0, "这是被引用的原文。" * 50)
    messages = [original] + [event(i, "不相关的聊天。" * 25) for i in range(1, 40)]
    messages.append(
        replace(event(40, "你怎么看这句话？"), parts=(MessagePart("reply", reference="0"),))
    )
    candidate = ConversationCandidate(
        "chat-1",
        "turn-1",
        "你怎么看这句话？",
        NOW + timedelta(seconds=45),
        1,
        ConversationContext(1, tuple(messages)),
    )
    runtime = TextRuntime(
        ChatCompletionsModel(Generator(), context_policy=ContextPolicy(decision_tokens=1600)),
        DeliveryService(Platform(), lambda: NOW, lambda _: 1),
        lambda: NOW,
    )
    assert await runtime.run(candidate) == "silence"
    rows = json.loads(requests[0]["context"])["messages"]
    assert any(row["text"] == original.text for row in rows)
    assert rows[-1]["replies"] == [{"status": "resolved", "target_ref": "message_41"}]


async def test_special_token_text_is_plain_text_and_budget_log_excludes_content(caplog):
    import logging

    from xiaolv.observability.logging_setup import LineFormatter

    literal = "PRIVATE-SENTINEL <|endoftext|> 这是普通聊天"
    seen = []

    class Generator:
        async def generate(self, **request):
            seen.append(json.loads(request["context"])["target_text"])
            return '{"action":"silence"}'

    caplog.set_level(logging.INFO)
    platform = Platform()
    runtime = TextRuntime(
        ChatCompletionsModel(Generator()),
        DeliveryService(platform, lambda: NOW, lambda _: 1),
        lambda: NOW,
    )
    candidate = ConversationCandidate("chat-1", "turn-1", literal, NOW + timedelta(seconds=45), 1)
    assert await runtime.run(candidate) == "silence"
    assert seen == [literal]
    records = [
        record for record in caplog.records if getattr(record, "event", None) == "context_assembled"
    ]
    assert len(records) == 1
    fields = records[0].fields
    assert fields["encoding"] == "cl100k_base"
    assert fields["stage"] == "participation"
    assert int(fields["input_estimate"]) <= int(fields["input_limit"])
    assert fields["selected_messages"] == "0"
    assert fields["dropped_messages"] == "0"
    formatted = LineFormatter().format(records[0])
    assert "PRIVATE-SENTINEL" not in formatted
    assert literal not in caplog.text
