from datetime import UTC, datetime

import pytest

from xiaolv.platforms.onebot_ingress import OneBotIngress

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


def frame(**changes):
    result = {
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "self_id": 10000,
        "user_id": 10001,
        "group_id": 20000,
        "message_id": 123,
        "time": int(NOW.timestamp()),
        "message": [{"type": "text", "data": {"text": "你好"}}],
        "sender": {"nickname": "昵称", "card": "群昵称"},
    }
    result.update(changes)
    return result


def test_group_message_separates_identity_from_conversation_and_nickname():
    ingress = OneBotIngress(10000)
    event = ingress.receive(frame(), NOW)
    assert event.conversation_id == "qq:10000:group:20000"
    assert event.sender_account_id == "qq:10001"
    assert event.message_id == "123"
    assert event.text == "你好"
    assert event.display_name == "群昵称"
    assert event.occurred_at == NOW


def test_private_and_temporary_sessions_are_isolated_for_same_account():
    ingress = OneBotIngress(10000)
    friend = ingress.receive(frame(message_type="private", sub_type="friend"), NOW)
    temporary = ingress.receive(
        frame(message_type="private", sub_type="group", sender={"group_id": 30000}), NOW
    )
    group = ingress.receive(frame(), NOW)
    assert friend.conversation_id == "qq:10000:private:10001"
    assert temporary.conversation_id == "qq:10000:temporary:30000:10001"
    assert (
        group.sender_account_id
        == friend.sender_account_id
        == temporary.sender_account_id
        == "qq:10001"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"post_type": "meta_event"},
        {"post_type": "notice"},
        {"post_type": "request"},
        {"post_type": "message_sent"},
        {"user_id": 10000},
    ],
)
def test_non_chat_and_self_messages_do_not_trigger_conversation(changes):
    assert OneBotIngress(10000).receive(frame(**changes), NOW) is None


def test_message_parts_preserve_media_mentions_and_quotes_without_interpreting_text():
    segments = [
        {"type": "reply", "data": {"id": "-123"}},
        {"type": "at", "data": {"qq": "10002"}},
        {"type": "text", "data": {"text": "[CQ:at,qq=all] 看这个"}},
        {"type": "image", "data": {"file": "synthetic.png", "url": "https://example.test/image"}},
        {"type": "record", "data": {"file": "synthetic.amr"}},
        {"type": "face", "data": {"id": "1"}},
    ]
    event = OneBotIngress(10000).receive(frame(message=segments), NOW)
    assert event.text == "[CQ:at,qq=all] 看这个"
    assert [(part.kind, part.reference) for part in event.parts] == [
        ("reply", "-123"),
        ("mention", "qq:10002"),
        ("text", None),
        ("image", "synthetic.png"),
        ("audio", "synthetic.amr"),
        ("face", "1"),
    ]
    assert event.parts[3].url == "https://example.test/image"


@pytest.mark.parametrize(
    "changes",
    [
        {"self_id": 99999},
        {"user_id": True},
        {"group_id": 0},
        {"message_id": False},
        {"message_type": "unknown"},
        {"time": float("inf")},
        {"message": "raw CQ input"},
        {"message": [{"type": "text", "data": {"text": 123}}]},
        {"message": [{"type": "at", "data": {"qq": "not-an-account"}}]},
    ],
)
def test_invalid_frames_are_rejected_with_sanitized_error(changes):
    from xiaolv.platforms.onebot_ingress import IngressError

    with pytest.raises(IngressError) as error:
        OneBotIngress(10000).receive(frame(**changes), NOW)
    assert "raw CQ input" not in str(error.value)
    assert "not-an-account" not in str(error.value)


def test_naive_received_time_is_rejected():
    from xiaolv.platforms.onebot_ingress import IngressError

    with pytest.raises(IngressError):
        OneBotIngress(10000).receive(frame(), NOW.replace(tzinfo=None))


def test_historical_event_keeps_original_time_but_is_not_a_live_candidate():
    old_time = int(NOW.timestamp()) - 1800
    event = OneBotIngress(10000).receive(frame(time=old_time), NOW)
    assert event.is_historical is True
    assert event.clock_skew is False
    assert event.effective_time == datetime.fromtimestamp(old_time, UTC)


def test_future_timestamp_cannot_extend_effective_reply_window():
    future_time = int(NOW.timestamp()) + 1800
    event = OneBotIngress(10000).receive(frame(time=future_time), NOW)
    assert event.occurred_at == datetime.fromtimestamp(future_time, UTC)
    assert event.clock_skew is True
    assert event.is_historical is False
    assert event.effective_time == NOW
