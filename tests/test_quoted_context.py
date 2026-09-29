import json
from datetime import UTC, datetime, timedelta

from xiaolv.application.delivery import DeliveryService
from xiaolv.domain.chat_event import ChatEvent, ConversationContext, MessagePart
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


class Generator:
    def __init__(self):
        self.contexts = []

    async def generate(self, *, instructions, context, schema, expires_at):
        self.contexts.append(json.loads(context))
        return '{"action":"silence"}'


class Platform:
    async def send(self, request):
        raise AssertionError("silent model cannot send")


def message(message_id, text, reply_to=None):
    return ChatEvent(
        "chat-1",
        "account-1",
        message_id,
        text,
        "群友",
        NOW,
        NOW,
        NOW,
        parts=() if reply_to is None else (MessagePart("reply", reference=reply_to),),
    )


async def observe(messages):
    generator = Generator()
    runtime = TextRuntime(
        ChatCompletionsModel(generator),
        DeliveryService(Platform(), lambda: NOW, lambda _: 1),
        lambda: NOW,
    )
    candidate = ConversationCandidate(
        "chat-1",
        "event-1",
        "这个呢",
        NOW + timedelta(seconds=45),
        1,
        ConversationContext(1, tuple(messages)),
    )
    assert await runtime.run(candidate) == "silence"
    return generator.contexts[0]


async def test_model_can_see_which_visible_message_was_quoted():
    context = await observe([message("-123", "周末去散步？"), message("124", "好啊", "-123")])
    original, reply = context["messages"]
    assert original["message_ref"] == "message_2"
    assert reply["replies"] == [{"status": "resolved", "target_ref": "message_2"}]
    assert original["replies"] == []


async def test_duplicate_message_ids_do_not_silently_choose_one_quote_target():
    context = await observe(
        [message("123", "第一条"), message("123", "冲突的另一条"), message("124", "嗯", "123")]
    )
    assert context["messages"][-1]["replies"] == [{"status": "ambiguous", "target_ref": None}]


async def test_repeated_quote_metadata_preserves_required_original():
    from dataclasses import replace

    messages = [message("original", "旧消息")]
    messages.extend(message(str(index), "长" * 900, "original") for index in range(30))
    messages[-1] = replace(
        messages[-1], parts=tuple(MessagePart("reply", reference="original") for _ in range(100))
    )
    context = await observe(messages)
    assert context["messages"]
    assert context["messages"][0]["text"] == "旧消息"
    assert context["messages"][-1]["replies"] == [
        {"status": "resolved", "target_ref": "message_31"}
    ]


async def test_duplicate_quote_parts_do_not_displace_the_original():
    from dataclasses import replace

    original = message("original", "旧" * 1000)
    latest = replace(
        message("latest", "新" * 900),
        parts=tuple(MessagePart("reply", reference="original") for _ in range(200)),
    )
    context = await observe([original, latest])
    assert len(context["messages"]) == 2
    assert context["messages"][0]["text"] == original.text
    assert context["messages"][-1]["replies"] == [{"status": "resolved", "target_ref": "message_2"}]


async def test_unavailable_original_is_not_invented():
    context = await observe([message("latest", "对这个怎么看", "missing-id")])
    assert context["messages"][0]["replies"] == [{"status": "missing", "target_ref": None}]


async def test_model_cannot_select_ambiguous_message_id_for_outgoing_quote():
    class QuoteGenerator(Generator):
        async def generate(self, *, instructions, context, schema, expires_at):
            if "action" in schema["properties"]:
                return '{"action":"respond"}'
            return '{"text":"好啊","reply_to":"message_1"}'

    runtime = TextRuntime(
        ChatCompletionsModel(QuoteGenerator(), quote_conversations=["chat-1"]),
        DeliveryService(Platform(), lambda: NOW, lambda _: 1),
        lambda: NOW,
    )
    candidate = ConversationCandidate(
        "chat-1",
        "event-1",
        "好啊",
        NOW + timedelta(seconds=45),
        1,
        ConversationContext(1, (message("123", "原文一"), message("123", "原文二"))),
    )
    assert await runtime.run(candidate) == "model_error"
