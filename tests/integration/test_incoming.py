from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.application.incoming import IncomingMessages
from xiaolv.platforms.onebot_ingress import OneBotIngress
from xiaolv.storage.postgres_inbox import PostgresInbox

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


def frame(**changes):
    event = {
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "self_id": 10000,
        "user_id": 10001,
        "group_id": 20000,
        "message_id": 123,
        "time": int(NOW.timestamp()),
        "message": [{"type": "text", "data": {"text": "合成文本"}}],
    }
    event.update(changes)
    return event


def incoming(engine, clock=lambda: NOW):
    return IncomingMessages(OneBotIngress(10000), PostgresInbox(engine), clock)


@pytest.mark.parametrize("limit", [0, -1, 201, True, 1.5])
async def test_context_rejects_invalid_window(database_url, limit):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        with pytest.raises(ValueError, match="limit"):
            await incoming(engine).context("qq:10000:group:20000", limit=limit)
    finally:
        await engine.dispose()


async def test_message_context_survives_rebuilding_connection(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        result = await incoming(engine).receive(frame())
        assert result.status == "stored"
    finally:
        await engine.dispose()
    restarted = create_async_engine(database_url, hide_parameters=True)
    try:
        history = await incoming(restarted).recent("qq:10000:group:20000")
        assert history == (result.event,)
        assert history[0].sender_account_id == "qq:10001"
    finally:
        await restarted.dispose()


async def test_duplicate_does_not_refresh_original_content_or_time(database_url):
    from datetime import timedelta

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        first = await incoming(engine).receive(frame())
        second = await incoming(engine, clock=lambda: NOW + timedelta(minutes=30)).receive(
            frame(message=[{"type": "text", "data": {"text": "改变的重放内容"}}])
        )
        assert second.status == "duplicate"
        assert await incoming(engine).recent(first.event.conversation_id) == (first.event,)
    finally:
        await engine.dispose()


async def test_context_revision_counts_new_messages_without_advancing_turn_epoch(database_url):
    from xiaolv.application.delivery import DeliveryService
    from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger

    class NoSending:
        async def send(self, request):
            raise AssertionError("receiving must not send")

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        delivery = DeliveryService(NoSending(), ledger=PostgresDeliveryLedger(engine))
        assert await delivery.start_turn("qq:10000:group:20000") == 1
        pipeline = incoming(engine)
        await pipeline.receive(frame())
        await pipeline.receive(frame())
        context = await pipeline.context("qq:10000:group:20000")
        assert context.revision == 1
        assert len(context.messages) == 1
        assert await delivery.start_turn("qq:10000:group:20000") == 2
    finally:
        await engine.dispose()


async def test_same_message_id_is_isolated_by_conversation(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        pipeline = incoming(engine)
        first = await pipeline.receive(frame())
        other = await pipeline.receive(frame(group_id=30000))
        assert first.status == other.status == "stored"
        assert await pipeline.recent("qq:10000:group:20000") == (first.event,)
        assert await pipeline.recent("qq:10000:group:30000") == (other.event,)
        empty = await pipeline.context("qq:10000:private:10001")
        assert empty.revision == 0
        assert empty.messages == ()
    finally:
        await engine.dispose()


async def test_concurrent_duplicate_delivery_registers_once(database_url):
    import asyncio

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        pipeline = incoming(engine)
        results = await asyncio.gather(*(pipeline.receive(frame()) for _ in range(8)))
        assert [result.status for result in results].count("stored") == 1
        assert [result.status for result in results].count("duplicate") == 7
        context = await pipeline.context("qq:10000:group:20000")
        assert context.revision == 1
        assert len(context.messages) == 1
    finally:
        await engine.dispose()


async def test_context_window_has_stable_chronological_order(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        pipeline = incoming(engine)
        await pipeline.receive(frame(message_id=10))
        await pipeline.receive(frame(message_id=11, time=int(NOW.timestamp()) - 5))
        await pipeline.receive(frame(message_id=12))
        context = await pipeline.context("qq:10000:group:20000", limit=2)
        assert context.revision == 3
        assert [message.message_id for message in context.messages] == ["10", "12"]
        assert [
            message.message_id for message in await pipeline.recent("qq:10000:group:20000")
        ] == ["11", "10", "12"]
    finally:
        await engine.dispose()


async def test_ignored_frames_leave_no_context_but_history_is_preserved(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        pipeline = incoming(engine)
        assert (await pipeline.receive(frame(user_id=10000))).status == "ignored"
        assert (await pipeline.receive({"post_type": "notice"})).status == "ignored"
        assert (await pipeline.context("qq:10000:group:20000")).revision == 0
        result = await pipeline.receive(frame(time=int(NOW.timestamp()) - 1800))
        assert result.status == "stored"
        context = await pipeline.context("qq:10000:group:20000")
        assert context.messages[0].is_historical
    finally:
        await engine.dispose()


async def test_database_failure_rolls_back_message_and_revision(database_url):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        # Inject a real database write fault; assertions remain at the incoming boundary.
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "ALTER TABLE app.conversation_state ADD CONSTRAINT injected_fault CHECK (revision = 0)"
                )
            )
        pipeline = incoming(engine)
        with pytest.raises(DBAPIError):
            await pipeline.receive(frame())
        context = await pipeline.context("qq:10000:group:20000")
        assert context.revision == 0
        assert context.messages == ()
    finally:
        await engine.dispose()
