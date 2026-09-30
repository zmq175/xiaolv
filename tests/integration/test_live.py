import asyncio
import json
from datetime import UTC, datetime

import pytest
from websockets.asyncio.server import serve

from xiaolv.live import run_live
from xiaolv.settings import load_settings


def message(message_id=1, group_id=20000, content="小绿怎么看？"):
    return {
        "post_type": "message",
        "self_id": 10000,
        "user_id": 10001,
        "group_id": group_id,
        "message_type": "group",
        "sub_type": "normal",
        "message_id": message_id,
        "time": int(datetime.now(UTC).timestamp()),
        "message": [{"type": "text", "data": {"text": content}}],
    }


class Services:
    def __init__(self):
        self.frames = [message()]
        self.login_user = 10000
        self.sent = []
        self.model_requests = []
        self.delivered = asyncio.Event()
        self.received = asyncio.Event()
        self.action = "respond"
        self.connection = None
        self.model_started = asyncio.Event()
        self.hold = None
        self.mentions = []
        self.member_queries = []
        self.reply_to = None
        self.message_queries = []
        self.drop_quote = False
        self.parts = None
        self.voice = None
        self.transcriptions = []
        self.message_override = None
        self.transcript = "周六下午三点见。"
        self.transcript_status = "ok"
        self.transcription_started = asyncio.Event()
        self.transcription_gate = None
        self.vision_started = asyncio.Event()
        self.vision_gate = None

    async def onebot(self, ws):
        self.connection = ws
        async for raw in ws:
            request = json.loads(raw)
            if request["action"] == "get_login_info":
                await ws.send(
                    json.dumps(
                        {
                            "status": "ok",
                            "retcode": 0,
                            "echo": request["echo"],
                            "data": {"user_id": self.login_user, "nickname": "合成小绿"},
                        }
                    )
                )
                for frame in self.frames:
                    await ws.send(json.dumps(frame))
                self.received.set()
            elif request["action"] == "get_msg":
                message_id = request["params"]["message_id"]
                self.message_queries.append(message_id)
                if message_id == 789:
                    data = {
                        "message_id": 789,
                        "message_type": "group",
                        "group_id": 20000,
                        "message": self.sent[-1]["message"],
                    }
                    if self.drop_quote:
                        data["message"] = [
                            part for part in data["message"] if part["type"] != "reply"
                        ]
                else:
                    data = self.message_override or next(
                        frame for frame in self.frames if frame["message_id"] == message_id
                    )
                await ws.send(
                    json.dumps(
                        {
                            "status": "ok",
                            "retcode": 0,
                            "echo": request["echo"],
                            "data": data,
                        }
                    )
                )
            elif request["action"] == "get_image":
                await ws.send(
                    json.dumps(
                        {
                            "status": "ok",
                            "retcode": 0,
                            "echo": request["echo"],
                            "data": {"url": "https://media.example/image?signature=PRIVATE"},
                        }
                    )
                )
            elif request["action"] == "fetch_ptt_text":
                self.transcriptions.append(request["params"])
                self.transcription_started.set()
                if self.transcription_gate is not None:
                    await self.transcription_gate.wait()
                await ws.send(
                    json.dumps(
                        {
                            "status": self.transcript_status,
                            "retcode": 0,
                            "echo": request["echo"],
                            "data": {"text": self.transcript},
                        }
                    )
                )
            elif request["action"] == "get_group_member_list":
                self.member_queries.append(request["params"])
                await ws.send(
                    json.dumps(
                        {
                            "status": "ok",
                            "retcode": 0,
                            "echo": request["echo"],
                            "data": [{"group_id": 20000, "user_id": 10001}],
                        }
                    )
                )
            elif request["action"] == "send_group_msg":
                self.sent.append(request["params"])
                await ws.send(
                    json.dumps(
                        {
                            "status": "ok",
                            "retcode": 0,
                            "echo": request["echo"],
                            "data": {"message_id": 789},
                        }
                    )
                )
                self.delivered.set()
            else:
                raise AssertionError("unexpected platform action")

    async def model(self, reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1])
                for line in headers.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            request = json.loads(await reader.readexactly(length))
            self.model_requests.append(request)
            self.model_started.set()
            if self.hold is not None:
                await self.hold.wait()
            properties = request["response_format"]["json_schema"]["schema"]["properties"]
            if "description" in properties:
                self.vision_started.set()
                if self.vision_gate is not None:
                    await self.vision_gate.wait()
            value = (
                {"action": self.action} if "action" in properties else {"text": "我觉得先试一下。"}
            )
            if "action" not in properties and (self.mentions or "mentions" in properties):
                value["mentions"] = self.mentions
            if "action" not in properties and (self.reply_to or "reply_to" in properties):
                value["reply_to"] = self.reply_to
            if "action" not in properties and (self.parts is not None or "parts" in properties):
                value = {
                    "parts": self.parts
                    if self.parts is not None
                    else [
                        *({"kind": "mention", "value": ref} for ref in self.mentions),
                        {"kind": "text", "value": "我觉得先试一下。"},
                    ],
                    "reply_to": self.reply_to,
                }
            if "voice" in properties:
                value["voice"] = self.voice
                if self.voice is not None:
                    value["parts"] = []
                    value["reply_to"] = None
            if "description" in properties:
                value = {"description": "持久化的合成图片描述"}
            chunks = [
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": json.dumps(value, ensure_ascii=False)},
                            "finish_reason": "stop",
                        }
                    ]
                },
                {
                    "choices": [],
                    "usage": {"prompt_tokens": 80, "completion_tokens": 5, "total_tokens": 85},
                },
            ]
            body = (
                "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
                + "data: [DONE]\n\n"
            ).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\n\r\n"
                + body
            )
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()


@pytest.fixture
async def services():
    fixture = Services()
    http = await asyncio.start_server(fixture.model, "127.0.0.1", 0)
    async with http, serve(fixture.onebot, "127.0.0.1", 0) as ws:
        fixture.model_url = f"http://127.0.0.1:{http.sockets[0].getsockname()[1]}/v1"
        fixture.onebot_url = f"ws://127.0.0.1:{ws.sockets[0].getsockname()[1]}"
        yield fixture


def settings(database_url, services, **changes):
    env = {
        "XIAOLV_MODE": "live",
        "XIAOLV_DATABASE_URL": database_url,
        "XIAOLV_MODEL_BASE_URL": services.model_url,
        "XIAOLV_MODEL_API_KEY": "synthetic",
        "XIAOLV_MODEL_ID": "synthetic-model",
        "XIAOLV_MODEL_PROVIDER": "synthetic-provider",
        "XIAOLV_MODEL_PRICE_VERSION": "test-v1",
        "XIAOLV_MODEL_INPUT_CNY_PER_MILLION": "1",
        "XIAOLV_MODEL_OUTPUT_CNY_PER_MILLION": "2",
        "XIAOLV_MONTHLY_EXTERNAL_BUDGET_CNY": "1",
        "XIAOLV_MONTHLY_FIXED_COST_CNY": "100",
        "XIAOLV_QQ_SELF_ID": "10000",
        "XIAOLV_ONEBOT_URL": services.onebot_url,
        "XIAOLV_ONEBOT_TOKEN": "synthetic",
        "XIAOLV_ENABLED_GROUP_IDS": "[20000]",
    }
    env.update(changes)
    return load_settings(env)


async def test_online_text_composition_reaches_native_send(database_url, services):
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop))
    try:
        ready = asyncio.create_task(services.delivered.wait())
        done, _ = await asyncio.wait({task, ready}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        assert ready in done, "composition did not deliver"
        stop.set()
        summary = await asyncio.wait_for(task, 6)
        assert summary.stored == 1
        assert summary.outcomes == {"confirmed": 1}
        assert len(services.model_requests) == 2
        assert services.member_queries == []
        assert services.sent == [
            {"group_id": 20000, "message": [{"type": "text", "data": {"text": "我觉得先试一下。"}}]}
        ]
    finally:
        stop.set()
        task.cancel()
        ready.cancel()
        await asyncio.gather(task, ready, return_exceptions=True)


async def test_online_model_selects_member_reference_for_native_mention(database_url, services):
    services.mentions = ["member_1"]
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop))
    try:
        await asyncio.wait_for(services.delivered.wait(), 5)
        stop.set()
        summary = await asyncio.wait_for(task, 6)
        assert summary.outcomes == {"confirmed": 1}
        context = json.loads(services.model_requests[-1]["messages"][1]["content"])
        assert context["messages"][-1]["member_ref"] == "member_1"
        assert services.member_queries == [{"group_id": 20000, "no_cache": True}]
        assert services.sent == [
            {
                "group_id": 20000,
                "message": [
                    {"type": "at", "data": {"qq": "10001"}},
                    {"type": "text", "data": {"text": "我觉得先试一下。"}},
                ],
            }
        ]
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "mentions,drop_quote,expected",
    [
        ([], False, "confirmed"),
        (["member_1"], False, "confirmed"),
        ([], True, "unknown"),
    ],
)
async def test_online_model_quotes_visible_message_and_verifies_readback(
    database_url, services, mentions, drop_quote, expected
):
    from xiaolv.live import LiveSummary

    services.reply_to = "message_1"
    services.mentions = mentions
    services.drop_quote = drop_quote
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    try:
        await until(lambda: stats.outcomes.get(expected) == 1, task)
        stop.set()
        await asyncio.wait_for(task, 6)
        assert services.message_queries == [1, 789]
        assert services.member_queries == (
            [{"group_id": 20000, "no_cache": True}] if mentions else []
        )
        assert services.sent == [
            {
                "group_id": 20000,
                "message": [
                    {"type": "reply", "data": {"id": "1"}},
                    *([{"type": "at", "data": {"qq": "10001"}}] if mentions else []),
                    {"type": "text", "data": {"text": "我觉得先试一下。"}},
                ],
            }
        ]
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("reference", ["message_999", "1"])
async def test_online_model_cannot_invent_quote_reference(database_url, services, reference):
    from xiaolv.live import LiveSummary

    services.reply_to = reference
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    try:
        await until(lambda: stats.outcomes.get("model_error") == 1, task)
        stop.set()
        await asyncio.wait_for(task, 6)
        assert services.message_queries == []
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("reference", ["member_999", "qq:10001", "all"])
async def test_online_model_cannot_invent_a_member_reference(database_url, services, reference):
    from xiaolv.live import LiveSummary

    services.mentions = [reference]
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    try:
        await until(lambda: stats.outcomes.get("model_error") == 1, task)
        stop.set()
        assert (await asyncio.wait_for(task, 6)).outcomes == {"model_error": 1}
        assert services.member_queries == []
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_wrong_logged_in_account_stops_before_model_or_send(database_url, services):
    from xiaolv.live import LiveRuntimeError

    services.login_user = 99999
    with pytest.raises(LiveRuntimeError, match="account"):
        await asyncio.wait_for(run_live(settings(database_url, services), asyncio.Event()), 3)
    assert services.model_requests == []
    assert services.sent == []


async def test_schema_mismatch_is_rejected_before_platform_connection(database_url, services):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from xiaolv.live import LiveRuntimeError

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE alembic_version SET version_num = '0004_candidates'")
            )
    finally:
        await engine.dispose()
    with pytest.raises(LiveRuntimeError, match="schema"):
        await asyncio.wait_for(run_live(settings(database_url, services), asyncio.Event()), 3)
    assert not services.received.is_set()
    assert services.model_requests == []


async def until(predicate, task):
    async with asyncio.timeout(5):
        while not predicate():
            if task.done():
                await task
                raise AssertionError("service stopped before expected observation")
            await asyncio.sleep(0.01)


async def test_duplicate_and_disabled_conversations_do_not_generate_extra_replies(
    database_url, services
):
    from xiaolv.live import LiveSummary

    services.frames = [message(), message(), message(message_id=2, group_id=30000)]
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    try:
        await until(lambda: stats.outcomes.get("confirmed") == 1, task)
        stop.set()
        summary = await asyncio.wait_for(task, 6)
        assert summary.stored == 2
        assert summary.duplicate == 1
        assert summary.outcomes == {"confirmed": 1}
        assert len(services.model_requests) == 2
        assert len(services.sent) == 1
        assert services.sent[0]["group_id"] == 20000
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_live_silence_is_normal_terminal_outcome_without_send(database_url, services):
    from xiaolv.live import LiveSummary

    services.action = "silence"
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    try:
        await until(lambda: stats.outcomes.get("silence") == 1, task)
        stop.set()
        assert (await asyncio.wait_for(task, 6)).outcomes == {"silence": 1}
        assert len(services.model_requests) == 1
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_live_budget_is_mandatory_and_zero_allowance_never_calls_model(
    database_url, services
):
    from xiaolv.live import LiveSummary

    stats = LiveSummary()
    stop = asyncio.Event()
    configured = settings(database_url, services, XIAOLV_MONTHLY_EXTERNAL_BUDGET_CNY="0")
    task = asyncio.create_task(run_live(configured, stop, statistics=stats))
    try:
        await until(lambda: stats.outcomes.get("budget_denied") == 1, task)
        stop.set()
        await asyncio.wait_for(task, 6)
        assert services.model_requests == []
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_invalid_frame_does_not_prevent_following_valid_message(database_url, services):
    from xiaolv.live import LiveSummary

    services.frames = [{**message(), "user_id": True}, message()]
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    try:
        await until(lambda: stats.outcomes.get("confirmed") == 1, task)
        stop.set()
        await asyncio.wait_for(task, 6)
        assert stats.invalid == 1
        assert stats.stored == 1
        assert len(services.sent) == 1
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_platform_disconnect_cancels_model_and_stops_service(database_url, services):
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import create_async_engine

    from xiaolv.domain.model_budget import BudgetPolicy
    from xiaolv.live import LiveRuntimeError
    from xiaolv.storage.postgres_budget import PostgresModelBudget

    services.hold = asyncio.Event()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop))
    try:
        await until(services.model_started.is_set, task)
        await services.connection.close()
        with pytest.raises(LiveRuntimeError, match="connection"):
            await asyncio.wait_for(task, 3)
        assert services.sent == []
        engine = create_async_engine(database_url, hide_parameters=True)
        try:
            budget = PostgresModelBudget(
                engine,
                BudgetPolicy(
                    "external",
                    "synthetic-provider",
                    "synthetic-model",
                    "test-v1",
                    Decimal(1),
                    Decimal(1),
                    Decimal(2),
                ),
            )
            assert (await budget.snapshot()).reserved > 0
        finally:
            await engine.dispose()
    finally:
        services.hold.set()
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_normal_stop_bounds_hanging_model_and_does_not_send(database_url, services):
    services.hold = asyncio.Event()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop))
    try:
        await until(services.model_started.is_set, task)
        stop.set()
        summary = await asyncio.wait_for(task, 8)
        assert summary.stored == 1
        assert summary.outcomes == {}
        assert len(services.model_requests) == 1
        assert services.sent == []
    finally:
        services.hold.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_live_command_sends_and_exits_cleanly_on_sigterm(database_url, services):
    import os
    import signal
    import sys
    from pathlib import Path

    from pydantic import BaseModel, SecretStr

    configured = settings(database_url, services)
    env = {key: value for key, value in os.environ.items() if not key.startswith("XIAOLV_")}
    for key in type(configured).model_fields:
        value = getattr(configured, key)
        if value is not None:
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            elif isinstance(value, BaseModel):
                value = value.model_dump_json()
            elif isinstance(value, tuple):
                value = json.dumps(value)
            env["XIAOLV_" + key.upper()] = str(value)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "xiaolv",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output = asyncio.create_task(process.communicate())
    delivered = asyncio.create_task(services.delivered.wait())
    try:
        done, _ = await asyncio.wait(
            {output, delivered}, timeout=8, return_when=asyncio.FIRST_COMPLETED
        )
        assert delivered in done, "live command failed to deliver: " + repr(
            output.result() if output.done() else None
        )
        process.send_signal(signal.SIGTERM)
        stdout, stderr = await asyncio.wait_for(output, 8)
        assert process.returncode == 0, stderr.decode()
        summary = json.loads(stdout)
        assert summary["mode"] == "live"
        assert summary["stored"] == 1
        assert summary["outcomes"] == {"confirmed": 1}
        assert "Traceback" not in stderr.decode()
        from xiaolv.observability.log_format import parse_log

        entries = [parse_log(line) for line in stderr.decode().splitlines()]
        events = {entry.event for entry in entries}
        assert {
            "service_started",
            "service_ready",
            "event_received",
            "chat_decision",
            "model_call",
            "outbox_transition",
            "turn_finished",
            "service_stopped",
        } <= events
        turn_entries = [
            entry
            for entry in entries
            if entry.event in {"chat_decision", "model_call", "outbox_transition", "turn_finished"}
        ]
        assert len({entry.traceid for entry in turn_entries}) == 1
        assert turn_entries[0].traceid != "0" * 32
        assert sum(entry.event == "model_call" for entry in entries) == 2
        assert len({entry.spanid for entry in entries if entry.event == "model_call"}) == 2
        assert "小绿怎么看" not in stderr.decode()
        assert "我觉得先试一下" not in stderr.decode()
        assert len(services.sent) == 1
    finally:
        if process.returncode is None:
            process.kill()
        await asyncio.gather(output, return_exceptions=True)
        delivered.cancel()
        await asyncio.gather(delivered, return_exceptions=True)


async def test_startup_recovers_more_than_one_batch_without_replaying_old_turns(
    database_url, services
):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from xiaolv.live import LiveSummary
    from xiaolv.storage.postgres_turns import PostgresTurns

    engine = create_async_engine(database_url)
    # Historical crash fixture; assertions use the public turn audit boundary.
    async with engine.begin() as connection:
        await connection.execute(
            text("""
            INSERT INTO app.conversation_state (conversation_id, epoch, revision)
            VALUES ('historical', 101, 101)
        """)
        )
        await connection.execute(
            text("""
            INSERT INTO app.chat_turns (turn_id, conversation_id, epoch, revision, expires_at)
            SELECT 'old-' || n, 'historical', n, n, '2001-01-01'::timestamptz
            FROM generate_series(1, 101) n
        """)
        )
        await connection.execute(
            text("""
            INSERT INTO app.outbox
                (outgoing_id, conversation_id, expires_at, generation_epoch, body,
                 status, attempt_token, lease_until)
            VALUES ('old-send', 'historical', '2001-01-01', 101, 'synthetic',
                    'sending', 'old-token', '2001-01-01')
        """)
        )
    services.frames = [message(group_id=30000)]
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    try:
        await until(lambda: stats.stored == 1, task)
        stop.set()
        await asyncio.wait_for(task, 6)
        audit = PostgresTurns(engine)
        statuses = [await audit.status(f"old-{n}") for n in range(1, 102)]
        assert set(statuses) == {"expired"}
        from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger

        assert await PostgresDeliveryLedger(engine).status("old-send") == "unknown"
        assert services.model_requests == []
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


@pytest.mark.parametrize("invalid_id", [True, "10000", None])
async def test_invalid_login_reply_stops_before_model(database_url, services, invalid_id):
    from xiaolv.live import LiveRuntimeError

    services.login_user = invalid_id
    with pytest.raises(LiveRuntimeError, match="login_invalid"):
        await asyncio.wait_for(run_live(settings(database_url, services), asyncio.Event()), 3)
    assert services.model_requests == []
    assert services.sent == []


async def test_deadline_cancels_hanging_generation_without_late_reply(database_url, services):
    from xiaolv.live import LiveSummary

    services.hold = asyncio.Event()
    stats = LiveSummary()
    stop = asyncio.Event()
    configured = settings(
        database_url, services, XIAOLV_CHAT_TTL_SECONDS="3", XIAOLV_QUEUE_MAX_AGE_SECONDS="2"
    )
    task = asyncio.create_task(run_live(configured, stop, statistics=stats))
    try:
        await until(services.model_started.is_set, task)
        await until(lambda: bool(stats.outcomes), task)
        assert stats.outcomes == {"expired": 1}
        services.hold.set()
        stop.set()
        await asyncio.wait_for(task, 6)
        assert services.sent == []
        assert len(services.model_requests) == 1
    finally:
        services.hold.set()
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_database_failure_stops_service_without_model_or_send(database_url, services):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from xiaolv.live import LiveRuntimeError, LiveSummary

    services.frames = [message(group_id=30000)]
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    engine = create_async_engine(database_url)
    try:
        await until(lambda: stats.stored == 1, task)
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE app.messages RENAME TO unavailable_messages")
            )
        await services.connection.send(json.dumps(message(message_id=2)))
        with pytest.raises(LiveRuntimeError, match="database_unavailable"):
            await asyncio.wait_for(task, 3)
        assert services.model_requests == []
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


async def test_live_uses_configured_persona_and_reply_limit(database_url, services):
    from xiaolv.live import LiveSummary

    stats = LiveSummary()
    stop = asyncio.Event()
    configured = settings(
        database_url,
        services,
        XIAOLV_BOT_PROFILE='{"name":"阿栀","aliases":["栀子"]}',
        XIAOLV_MAX_REPLY_CHARS="60",
    )
    task = asyncio.create_task(run_live(configured, stop, statistics=stats))
    try:
        await until(lambda: stats.outcomes.get("confirmed") == 1, task)
        stop.set()
        await asyncio.wait_for(task, 6)
        assert len(services.model_requests) == 2
        for request in services.model_requests:
            assert "阿栀" in request["messages"][0]["content"]
            assert "小绿" not in request["messages"][0]["content"]
        assert "60字" in services.model_requests[1]["messages"][0]["content"]
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_live_quota_drops_next_reply_instead_of_queueing_it(database_url, services, caplog):
    import logging

    caplog.set_level(logging.INFO)
    from xiaolv.live import LiveSummary

    stats = LiveSummary()
    stop = asyncio.Event()
    configured = settings(
        database_url,
        services,
        XIAOLV_DELIVERY_POLICY='{"cooldown_seconds":0,"window_seconds":60,"max_messages":1}',
    )
    task = asyncio.create_task(run_live(configured, stop, statistics=stats))
    try:
        await until(lambda: stats.outcomes.get("confirmed") == 1, task)
        await services.connection.send(json.dumps(message(message_id=2, content="还有呢？")))
        await until(lambda: stats.outcomes.get("rate_limited") == 1, task)
        stop.set()
        summary = await asyncio.wait_for(task, 6)
        assert summary.outcomes == {"confirmed": 1, "rate_limited": 1}
        assert sum(getattr(r, "event", None) == "profile_selected" for r in caplog.records) == 1
        assert len(services.sent) == 1
        assert len(services.model_requests) == 2
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_online_model_places_mention_between_text_parts(database_url, services):
    from xiaolv.live import LiveSummary

    services.parts = [
        {"kind": "text", "value": "这件事问 "},
        {"kind": "mention", "value": "member_1"},
        {"kind": "text", "value": " 比较清楚"},
    ]
    services.reply_to = "message_1"
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    try:
        await until(lambda: bool(stats.outcomes), task)
        assert stats.outcomes == {"confirmed": 1}
        assert services.sent[0]["message"] == [
            {"type": "reply", "data": {"id": "1"}},
            {"type": "text", "data": {"text": "这件事问 "}},
            {"type": "at", "data": {"qq": "10001"}},
            {"type": "text", "data": {"text": " 比较清楚"}},
        ]
        assert services.member_queries == [{"group_id": 20000, "no_cache": True}]
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "parts,expected",
    [
        (
            [{"kind": "text", "value": "hi"}, {"kind": "mention", "value": "qq:10001"}],
            "model_error",
        ),
        (
            [{"kind": "text", "value": "hi"}, {"kind": "mention", "value": "member_999"}],
            "model_error",
        ),
        (
            [
                {"kind": "text", "value": "hi"},
                {"kind": "mention", "value": "member_1"},
                {"kind": "mention", "value": "member_1"},
            ],
            "model_error",
        ),
        ([{"kind": "image", "value": "https://example.invalid/image"}], "model_error"),
        ([], "model_error"),
        ([{"kind": "text", "value": "长" * 201}], "invalid_reply"),
        ([{"kind": "text", "value": "字"}] * 33, "model_error"),
    ],
)
async def test_online_ordered_reply_rejects_invalid_intent(database_url, services, parts, expected):
    from xiaolv.live import LiveSummary

    services.parts = parts
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    try:
        await until(lambda: bool(stats.outcomes), task)
        assert stats.outcomes == {expected: 1}
        assert services.sent == []
        assert services.member_queries == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_online_turn_uses_admin_published_persona(database_url, services):
    from pwdlib import PasswordHash
    from sqlalchemy.ext.asyncio import create_async_engine
    from test_admin_auth import PASSWORD, client
    from test_profile_publication import PROFILE
    from test_turn_profile import save_publish

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, PasswordHash.recommended().hash(PASSWORD)) as http:
            login = await http.post("/admin/api/login", json={"password": PASSWORD})
            http.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            await save_publish(http, PROFILE, 0, "live")
    finally:
        await engine.dispose()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop))
    try:
        await asyncio.wait_for(services.delivered.wait(), 5)
        stop.set()
        await asyncio.wait_for(task, 6)
        assert len(services.model_requests) == 2
        for request in services.model_requests:
            assert '"name": "青禾"' in request["messages"][0]["content"]
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_live_context_policy_bounds_tokens_and_reads_more_than_thirty_messages(
    database_url, services
):
    import tiktoken

    services.frames = [message(message_id=i, content=f"第{i}条合成短消息") for i in range(1, 42)]
    configured = settings(
        database_url,
        services,
        XIAOLV_CONTEXT_POLICY='{"history_messages":40,"decision_tokens":12000,"reply_tokens":12000}',
    )
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(configured, stop))
    try:
        await asyncio.wait_for(services.delivered.wait(), 5)
        stop.set()
        await asyncio.wait_for(task, 6)
        encoding = tiktoken.get_encoding("cl100k_base")
        for request in services.model_requests:
            context = json.loads(request["messages"][1]["content"])
            assert len(context["messages"]) == 40
            assert context["messages"][-1]["text"] == "第41条合成短消息"
            texts = [item["content"] for item in request["messages"]]
            texts.append(
                json.dumps(request["response_format"]["json_schema"]["schema"], ensure_ascii=False)
            )
            assert (
                sum(len(encoding.encode(text, disallowed_special=())) for text in texts) + 128
                <= 12000
            )
        assert len(services.model_requests) == 2
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_missing_tokenizer_assets_fail_before_platform_connection(
    database_url, services, monkeypatch, tmp_path
):
    from xiaolv.settings import ConfigError

    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match="tokenizer assets"):
        await asyncio.wait_for(run_live(settings(database_url, services), asyncio.Event()), 3)
    assert services.model_requests == []
    assert services.sent == []


async def test_admin_disabled_conversation_skips_models_after_live_restart(database_url, services):
    from pwdlib import PasswordHash
    from sqlalchemy.ext.asyncio import create_async_engine
    from test_admin_auth import PASSWORD, client

    from xiaolv.live import LiveSummary
    from xiaolv.storage.conversation_control import ConversationControl

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        await ConversationControl(engine).register(["qq:10000:group:20000"])
        async with client(engine, PasswordHash.recommended().hash(PASSWORD)) as http:
            login = await http.post("/admin/api/login", json={"password": PASSWORD})
            http.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            response = await http.put(
                "/admin/api/conversations/qq:10000:group:20000",
                json={"enabled": False, "expected_version": 0},
                headers={"Idempotency-Key": "stop-live"},
            )
            assert response.status_code == 200
    finally:
        await engine.dispose()
    stop = asyncio.Event()
    stats = LiveSummary()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    try:
        await until(lambda: bool(stats.outcomes), task)
        assert stats.outcomes == {"permission_denied": 1}
        assert services.model_requests == []
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_admin_stop_during_model_decision_prevents_followup_call(database_url, services):
    from pwdlib import PasswordHash
    from sqlalchemy.ext.asyncio import create_async_engine
    from test_admin_auth import PASSWORD, client

    from xiaolv.live import LiveSummary

    services.hold = asyncio.Event()
    stop = asyncio.Event()
    stats = LiveSummary()
    task = asyncio.create_task(run_live(settings(database_url, services), stop, statistics=stats))
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        await asyncio.wait_for(services.model_started.wait(), 5)
        async with client(engine, PasswordHash.recommended().hash(PASSWORD)) as http:
            login = await http.post("/admin/api/login", json={"password": PASSWORD})
            http.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            response = await http.put(
                "/admin/api/conversations/qq:10000:group:20000",
                json={"enabled": False, "expected_version": 0},
                headers={"Idempotency-Key": "stop-running"},
            )
            assert response.status_code == 200
        services.hold.set()
        await until(lambda: bool(stats.outcomes), task)
        assert stats.outcomes == {"permission_denied": 1}
        assert len(services.model_requests) == 1
        assert services.sent == []
    finally:
        services.hold.set()
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


@pytest.mark.parametrize("choice", ["voice", "text", "cleanup_failure"])
async def test_online_voice_uses_official_sdk_and_native_record(
    database_url, services, tmp_path, caplog, choice
):
    import base64

    import httpx
    import ormsgpack
    from test_fish_voice import wav_sample

    services.voice = {"speech_text": "晚安", "voice_profile": "warm"} if choice == "voice" else None
    if choice == "cleanup_failure":
        tmp_path = tmp_path / "private-audio-path"
        tmp_path.write_text("synthetic unavailable directory")
    audio, calls = wav_sample(), []

    async def respond(request):
        calls.append(ormsgpack.unpackb(request.content))
        return httpx.Response(200, content=audio)

    config = settings(
        database_url,
        services,
        XIAOLV_SPEECH=json.dumps(
            {
                "api_key": "synthetic-tts-secret",
                "model": "explicit-model",
                "voice_binding_version": "voice-v1",
                "price_version": "price-v1",
                "reservation_cny": "0.1",
                "voices": {"warm": "supplier-reference"},
                "conversations": {"qq:10000:group:20000": ["warm"]},
                "artifact_root": str(tmp_path),
            }
        ),
    )
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_live(config, stop, speech_transport=httpx.MockTransport(respond))
    )
    ready = asyncio.create_task(services.delivered.wait())
    try:
        done, _ = await asyncio.wait({task, ready}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
        assert ready in done
        stop.set()
        summary = await asyncio.wait_for(task, 6)
        assert summary.outcomes == {"confirmed": 1}
        if choice == "voice":
            assert len(calls) == 1
            assert calls[0]["text"] == "晚安"
            assert calls[0]["reference_id"] == "supplier-reference"
            assert services.sent == [
                {
                    "group_id": 20000,
                    "message": [
                        {
                            "type": "record",
                            "data": {"file": "base64://" + base64.b64encode(audio).decode("ascii")},
                        }
                    ],
                }
            ]
        else:
            assert calls == []
            assert services.sent == [
                {
                    "group_id": 20000,
                    "message": [{"type": "text", "data": {"text": "我觉得先试一下。"}}],
                }
            ]
        if choice == "cleanup_failure":
            assert any(
                getattr(record, "event", "") == "audio_cleanup_failed" for record in caplog.records
            )
            assert "private-audio-path" not in caplog.text
            assert "synthetic-tts-secret" not in caplog.text
    finally:
        stop.set()
        task.cancel()
        ready.cancel()
        await asyncio.gather(task, ready, return_exceptions=True)


async def test_online_audio_cleanup_runs_periodically_and_stops_with_service(
    database_url, services, tmp_path, caplog
):
    import logging

    from test_fish_voice import wav_sample

    from xiaolv.storage.audio_artifacts import LocalAudioArtifacts

    services.frames = []
    config = settings(
        database_url,
        services,
        XIAOLV_CHAT_TTL_SECONDS="0.05",
        XIAOLV_QUEUE_MAX_AGE_SECONDS="0.01",
        XIAOLV_SPEECH=json.dumps(
            {
                "api_key": "synthetic",
                "model": "explicit-model",
                "voice_binding_version": "v1",
                "price_version": "p1",
                "reservation_cny": "0.1",
                "voices": {"warm": "reference"},
                "conversations": {"qq:10000:group:20000": ["warm"]},
                "artifact_root": str(tmp_path),
                "retention_seconds": 0.1,
                "cleanup_interval_seconds": 0.03,
            }
        ),
    )
    caplog.set_level(logging.INFO, logger="xiaolv.live")
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(config, stop))
    try:
        await asyncio.wait_for(services.received.wait(), 3)
        await LocalAudioArtifacts(tmp_path).save("qq:10000:group:20000", wav_sample())

        async def cleaned():
            while not any(
                getattr(record, "event", "") == "audio_cleanup" and record.fields["removed"] == "1"
                for record in caplog.records
            ):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(cleaned(), 1)
        stop.set()
        await asyncio.wait_for(task, 6)
        count = len(caplog.records)
        await asyncio.sleep(0.1)
        assert len(caplog.records) == count
        assert services.sent == []
        assert services.model_requests == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_online_media_parts_reach_model_without_raw_media_locations(database_url, services):
    incoming = message(content="看看这个")
    incoming["message"] = [
        {"type": "text", "data": {"text": "看看这个"}},
        {
            "type": "image",
            "data": {
                "file": "PRIVATE_MEDIA_FILE",
                "url": "https://media.invalid/?key=PRIVATE_MEDIA_KEY",
            },
        },
        {
            "type": "record",
            "data": {"file": "PRIVATE_AUDIO_FILE", "url": "https://media.invalid/voice"},
        },
        {"type": "face", "data": {"id": "14"}},
    ]
    services.frames = [incoming]
    services.action = "silence"
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop))
    try:
        await asyncio.wait_for(services.model_started.wait(), 5)
        stop.set()
        summary = await asyncio.wait_for(task, 6)
        assert summary.outcomes == {"silence": 1}
        context = services.model_requests[0]["messages"][1]["content"]
        row = json.loads(context)["messages"][-1]
        assert row["parts"] == [
            {"kind": "text", "text": "看看这个"},
            {"kind": "image", "media_ref": "media_1_2", "status": "unprocessed"},
            {"kind": "audio", "media_ref": "media_1_3", "status": "unprocessed"},
            {"kind": "sticker", "media_ref": "media_1_4", "status": "unprocessed"},
        ]
        assert "PRIVATE_" not in context
        assert "https://media.invalid" not in context
        instructions = services.model_requests[0]["messages"][0]["content"]
        assert "unprocessed" in instructions
        assert "unsupported" in instructions
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        ({"type": "image", "data": {"emoji_id": "42", "file": "PRIVATE"}}, "sticker"),
        ({"type": "mface", "data": {"file": "PRIVATE"}}, "sticker"),
        ({"type": "UNTRUSTED_KIND", "data": {"file": "PRIVATE"}}, "unsupported"),
    ],
)
async def test_media_only_messages_expose_safe_types(database_url, services, segment, expected):
    incoming = message(content="")
    incoming["message"] = [segment]
    services.frames = [incoming]
    services.action = "silence"
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(settings(database_url, services), stop))
    try:
        await asyncio.wait_for(services.model_started.wait(), 5)
        stop.set()
        summary = await asyncio.wait_for(task, 6)
        assert summary.outcomes == {"silence": 1}
        context = services.model_requests[0]["messages"][1]["content"]
        row = json.loads(context)["messages"][-1]
        assert row["text"] == ""
        assert row["parts"] == [
            {
                "kind": expected,
                "media_ref": "media_1_1",
                "status": "unsupported" if expected == "unsupported" else "unprocessed",
            }
        ]
        assert "PRIVATE" not in context
        assert "UNTRUSTED_KIND" not in context
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_native_asr_reaches_reply_as_scoped_evidence(database_url, services):
    incoming = message(content="")
    incoming["message"] = [{"type": "record", "data": {"file": "PRIVATE_AUDIO"}}]
    services.frames = [incoming]
    config = settings(
        database_url, services, XIAOLV_NATIVE_ASR_CONVERSATIONS='["qq:10000:group:20000"]'
    )
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(config, stop))
    try:
        await asyncio.wait_for(services.delivered.wait(), 5)
        stop.set()
        summary = await asyncio.wait_for(task, 6)
        assert summary.outcomes == {"confirmed": 1}
        assert services.transcriptions == [{"message_id": 1}]
        decision = json.loads(services.model_requests[0]["messages"][1]["content"])
        reply = json.loads(services.model_requests[1]["messages"][1]["content"])
        assert decision["messages"][-1]["parts"][0]["status"] == "unprocessed"
        row = reply["messages"][-1]
        assert row["text"] == ""
        assert row["parts"] == [
            {
                "kind": "audio",
                "media_ref": "media_1_1",
                "status": "interpreted",
                "interpretation": {
                    "kind": "transcript",
                    "text": "周六下午三点见。",
                    "processor": "snowluma-native-asr:v1",
                },
            }
        ]
        assert "PRIVATE_AUDIO" not in json.dumps(reply)
        assert "interpretation" in services.model_requests[1]["messages"][0]["content"]
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "change",
    [
        {"group_id": 30000},
        {"user_id": 99999},
        {"message_id": 2},
        {"message": [{"type": "record", "data": {"file": "OTHER_AUDIO"}}]},
        {
            "message": [
                {"type": "record", "data": {"file": "PRIVATE_AUDIO"}},
                {"type": "record", "data": {"file": "OTHER_AUDIO"}},
            ]
        },
    ],
)
async def test_native_asr_rejects_mismatched_source(database_url, services, change):
    from xiaolv.live import LiveSummary

    incoming = message(content="")
    incoming["message"] = [{"type": "record", "data": {"file": "PRIVATE_AUDIO"}}]
    services.frames = [incoming]
    services.message_override = {**incoming, **change}
    config = settings(
        database_url, services, XIAOLV_NATIVE_ASR_CONVERSATIONS='["qq:10000:group:20000"]'
    )
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(config, stop, statistics=stats))
    try:
        await until(lambda: bool(stats.outcomes), task)
        assert stats.outcomes == {"media_error": 1}
        assert services.transcriptions == []
        assert len(services.model_requests) == 1
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    ("transcript", "status"),
    [
        ("", "ok"),
        ("   ", "ok"),
        ("字" * 3001, "ok"),
        (123, "ok"),
        ("不得采用这个失败结果", "failed"),
    ],
    ids=["empty", "blank", "too-long", "wrong-type", "failed"],
)
async def test_native_asr_failure_never_generates_reply(database_url, services, transcript, status):
    from xiaolv.live import LiveSummary

    incoming = message(content="")
    incoming["message"] = [{"type": "record", "data": {"file": "PRIVATE_AUDIO"}}]
    services.frames = [incoming]
    services.transcript = transcript
    services.transcript_status = status
    config = settings(
        database_url, services, XIAOLV_NATIVE_ASR_CONVERSATIONS='["qq:10000:group:20000"]'
    )
    stats = LiveSummary()
    stop = asyncio.Event()
    task = asyncio.create_task(run_live(config, stop, statistics=stats))
    try:
        await until(lambda: bool(stats.outcomes), task)
        assert stats.outcomes == {"media_error": 1}
        assert services.transcriptions == [{"message_id": 1}]
        assert len(services.model_requests) == 1
        assert services.sent == []
    finally:
        stop.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_transcript_survives_restart_in_later_conversation_context(
    database_url, services, caplog
):
    from xiaolv.live import LiveSummary

    incoming = message(content="")
    incoming["message"] = [{"type": "record", "data": {"file": "PRIVATE_AUDIO"}}]
    services.frames = [incoming]
    config = settings(
        database_url,
        services,
        XIAOLV_NATIVE_ASR_CONVERSATIONS='["qq:10000:group:20000"]',
        XIAOLV_DELIVERY_POLICY='{"cooldown_seconds":0,"window_seconds":60,"max_messages":6}',
    )
    caplog.set_level("INFO", logger="xiaolv.storage.media_interpretations")
    for round_number in range(2):
        stats = LiveSummary()
        stop = asyncio.Event()
        if round_number == 1:
            services.frames = [message(message_id=2, content="刚才语音约的几点？")]
        task = asyncio.create_task(run_live(config, stop, statistics=stats))
        try:
            await until(lambda stats=stats: bool(stats.outcomes), task)
            assert stats.outcomes == {"confirmed": 1}
            stop.set()
            await asyncio.wait_for(task, 6)
        finally:
            stop.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert services.transcriptions == [{"message_id": 1}]
    second_decision = json.loads(services.model_requests[2]["messages"][1]["content"])
    original = second_decision["messages"][0]
    assert original["text"] == ""
    assert original["parts"][0]["interpretation"]["text"] == "周六下午三点见。"
    assert original["content_version"] == 2
    assert second_decision["messages"][1]["content_version"] == 1
    saved = [
        record
        for record in caplog.records
        if getattr(record, "event", "") == "media_interpretation_saved"
    ]
    assert len(saved) == 1
    assert saved[0].fields["content_version"] == "2"
    assert "PRIVATE_AUDIO" not in caplog.text
    assert "周六下午三点见" not in caplog.text
