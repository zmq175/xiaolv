import json
from datetime import UTC, datetime, timedelta

import pytest
from websockets.asyncio.server import serve

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.platforms.onebot import OneBotSender, QQTarget
from xiaolv.platforms.onebot_ws import OneBotWebSocket


def outgoing(outgoing_id="out-1"):
    return DeliveryRequest(
        outgoing_id, "chat", datetime.now(UTC) + timedelta(seconds=10), 1, "合成消息"
    )


def delivery(rpc):
    return DeliveryService(
        OneBotSender(rpc, {"chat": QQTarget("group", 10001)}),
        lambda: datetime.now(UTC),
        lambda _: 1,
    )


def acknowledgement(request):
    return json.dumps(
        {"status": "ok", "retcode": 0, "data": {"message_id": 123}, "echo": request["echo"]}
    )


async def test_real_socket_authenticates_and_sends_native_action():
    observed = []

    async def handler(ws):
        observed.append(ws.request.headers.get("Authorization"))
        request = json.loads(await ws.recv())
        observed.append(request)
        await ws.send(acknowledgement(request))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with OneBotWebSocket(f"ws://127.0.0.1:{port}", "fake-token") as rpc:
            assert await delivery(rpc).deliver(outgoing()) == "confirmed"
    assert observed[0] == "Bearer fake-token"
    assert observed[1]["action"] == "send_group_msg"
    assert observed[1]["params"]["group_id"] == 10001
    assert isinstance(observed[1]["echo"], str)


async def test_interleaved_event_and_unrelated_echo_do_not_replace_receipt():
    event = {"post_type": "message", "message_id": 7, "message_type": "group"}

    async def handler(ws):
        request = json.loads(await ws.recv())
        await ws.send(json.dumps(event))
        await ws.send(json.dumps({"echo": "unrelated", "status": "failed", "retcode": 1400}))
        await ws.send(acknowledgement(request))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with OneBotWebSocket(f"ws://127.0.0.1:{port}", "fake-token") as rpc:
            assert await delivery(rpc).deliver(outgoing()) == "confirmed"
            assert await rpc.next_event() == event


async def test_parallel_calls_match_out_of_order_receipts():
    import asyncio

    observed = []

    async def handler(ws):
        for _ in range(2):
            observed.append(json.loads(await ws.recv()))
        for request in reversed(observed):
            await ws.send(acknowledgement(request))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with OneBotWebSocket(f"ws://127.0.0.1:{port}", "fake-token") as rpc:
            first, second = delivery(rpc), delivery(rpc)
            result = await asyncio.gather(
                first.deliver(outgoing("a")), second.deliver(outgoing("b"))
            )
            assert result == ["confirmed", "confirmed"]
    assert len({frame["echo"] for frame in observed}) == 2


async def test_disconnect_after_request_does_not_resend():
    observed = []

    async def handler(ws):
        observed.append(json.loads(await ws.recv()))
        await ws.close()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with OneBotWebSocket(f"ws://127.0.0.1:{port}", "fake-token") as rpc:
            sender = delivery(rpc)
            request = outgoing()
            assert await sender.deliver(request) == "unknown"
            assert await sender.deliver(request) == "unknown"
    assert len(observed) == 1


async def test_unopened_connection_reports_not_sent():
    rpc = OneBotWebSocket("ws://127.0.0.1:1", "fake-token")
    assert await delivery(rpc).deliver(outgoing()) == "not_sent"


async def test_waiting_event_consumer_is_woken_when_peer_closes():
    import asyncio

    import pytest

    async def handler(ws):
        await asyncio.sleep(0.02)
        await ws.close()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with OneBotWebSocket(f"ws://127.0.0.1:{port}", "fake-token") as rpc:
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(rpc.next_event(), timeout=1)


@pytest.mark.parametrize("frame", ["not json", "[]", "null", "123"])
async def test_malformed_json_closes_session_and_wakes_callers(frame):
    import asyncio

    import pytest

    async def handler(ws):
        await ws.recv()
        await ws.send(frame)
        await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with OneBotWebSocket(f"ws://127.0.0.1:{port}", "fake-token") as rpc:
            assert await delivery(rpc).deliver(outgoing()) == "unknown"
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(rpc.next_event(), 1)


async def test_event_queue_overflow_closes_connection_without_losing_queued_events():
    import asyncio

    import pytest

    async def handler(ws):
        await ws.recv()
        for index in range(129):
            await ws.send(json.dumps({"post_type": "message", "message_id": index}))
        await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with OneBotWebSocket(f"ws://127.0.0.1:{port}", "fake-token") as rpc:
            assert await delivery(rpc).deliver(outgoing()) == "unknown"
            events = [await asyncio.wait_for(rpc.next_event(), 1) for _ in range(128)]
            assert [event["message_id"] for event in events] == list(range(128))
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(rpc.next_event(), 1)


async def test_cancelled_request_does_not_break_following_request():
    import asyncio

    seen = asyncio.Event()

    async def handler(ws):
        first = json.loads(await ws.recv())
        seen.set()
        second = json.loads(await ws.recv())
        await ws.send(acknowledgement(first))
        await ws.send(acknowledgement(second))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with OneBotWebSocket(f"ws://127.0.0.1:{port}", "fake-token") as rpc:
            sender = delivery(rpc)
            task = asyncio.create_task(sender.deliver(outgoing("first")))
            await asyncio.wait_for(seen.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await sender.status("first") == "unknown"
            assert await sender.deliver(outgoing("second")) == "confirmed"


async def test_missing_receipt_times_out_without_reconnecting():
    observed = []

    async def handler(ws):
        observed.append(json.loads(await ws.recv()))
        await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with OneBotWebSocket(
            f"ws://127.0.0.1:{port}", "fake-token", request_timeout=0.05
        ) as rpc:
            sender = delivery(rpc)
            request = outgoing()
            assert await sender.deliver(request) == "unknown"
            assert await sender.deliver(request) == "unknown"
    assert len(observed) == 1
