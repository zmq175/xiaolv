from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.application.chat_worker import ChatWorker
from xiaolv.application.delivery import DeliveryService
from xiaolv.application.incoming import IncomingMessages
from xiaolv.orchestration.text_runtime import TextRuntime
from xiaolv.platforms.onebot_ingress import OneBotIngress
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger
from xiaolv.storage.postgres_inbox import PostgresInbox
from xiaolv.storage.postgres_turns import CandidatePolicy, PostgresTurns

CONVERSATION = "qq:10000:group:20000"


def clock():
    return datetime.now(UTC)


def frame(message_id=123, group_id=20000, content="聊点什么", **changes):
    event = {
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "self_id": 10000,
        "user_id": 10001,
        "group_id": group_id,
        "message_id": message_id,
        "time": int(clock().timestamp()),
        "message": [{"type": "text", "data": {"text": content}}],
    }
    event.update(changes)
    return event


class Model:
    def __init__(self):
        self.candidates = []

    async def decide(self, candidate):
        self.candidates.append(candidate)
        return "respond"

    async def reply(self, candidate):
        return "我也这么觉得。"


class Platform:
    def __init__(self):
        self.sent = []

    async def send(self, request):
        self.sent.append(request)
        return "confirmed"


def setup(engine, model=None, policy=None):
    model = model or Model()
    platform = Platform()
    policy = policy or CandidatePolicy(frozenset({CONVERSATION}), merge_seconds=0)
    incoming = IncomingMessages(
        OneBotIngress(10000), PostgresInbox(engine, candidate_policy=policy), clock
    )
    delivery = DeliveryService(platform, ledger=PostgresDeliveryLedger(engine))
    worker = ChatWorker(PostgresTurns(engine), TextRuntime(model, delivery, clock))
    return incoming, worker, model, platform


async def test_fresh_enabled_message_runs_once_through_native_delivery(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        incoming, worker, model, platform = setup(engine)
        assert (await incoming.receive(frame())).status == "stored"
        assert await worker.run_once() == "confirmed"
        assert [request.text for request in platform.sent] == ["我也这么觉得。"]
        assert model.candidates[0].conversation_id == CONVERSATION
        assert await worker.run_once() == "idle"
    finally:
        await engine.dispose()


async def test_same_group_candidates_merge_and_keep_scoped_context(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        incoming, worker, model, platform = setup(engine)
        await incoming.receive(frame(message_id=1, content="第一句"))
        await incoming.receive(frame(message_id=2, content="补充一句"))
        await incoming.receive(frame(message_id=3, group_id=30000, content="另一群的消息"))
        assert await worker.run_once() == "confirmed"
        candidate = model.candidates[0]
        assert candidate.text == "补充一句"
        assert [message.text for message in candidate.context.messages] == ["第一句", "补充一句"]
        assert candidate.context.revision == 2
        assert await worker.run_once() == "idle"
        assert len(platform.sent) == 1
    finally:
        await engine.dispose()


async def test_busy_group_keeps_next_candidate_without_blocking_other_groups(database_url):
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowModel(Model):
        async def reply(self, candidate):
            if len(self.candidates) == 1:
                entered.set()
                await release.wait()
            return "处理好了"

    engine = create_async_engine(database_url, hide_parameters=True)
    task = None
    try:
        policy = CandidatePolicy(frozenset({CONVERSATION, "qq:10000:group:30000"}), merge_seconds=0)
        incoming, worker, model, platform = setup(engine, SlowModel(), policy)
        await incoming.receive(frame(message_id=1))
        task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(incoming.receive(frame(message_id=2, content="补充")), 2)
        assert await worker.run_once() == "idle"
        await incoming.receive(frame(message_id=3, group_id=30000))
        assert await worker.run_once() == "confirmed"
        release.set()
        assert await task == "confirmed"
        assert await worker.run_once() == "confirmed"
        assert len(platform.sent) == 3
        assert [
            candidate.generation_epoch
            for candidate in model.candidates
            if candidate.conversation_id == CONVERSATION
        ] == [1, 2]
    finally:
        release.set()
        if task is not None:
            await task
        await engine.dispose()


async def test_aged_queue_is_discarded_before_model_even_with_remaining_ttl(database_url):
    from datetime import timedelta

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        _, worker, model, platform = setup(engine)
        received_at = clock() - timedelta(seconds=20)
        policy = CandidatePolicy(frozenset({CONVERSATION}), merge_seconds=0)
        incoming = IncomingMessages(
            OneBotIngress(10000),
            PostgresInbox(engine, candidate_policy=policy),
            lambda: received_at,
        )
        await incoming.receive(frame(time=int(received_at.timestamp())))
        assert await worker.run_once() == "idle"
        assert model.candidates == []
        assert platform.sent == []
        assert await worker.run_once() == "idle"
    finally:
        await engine.dispose()


async def test_merging_does_not_extend_original_deadline(database_url):
    from datetime import timedelta

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        _, worker, model, _ = setup(engine)
        now = clock() - timedelta(seconds=5)
        policy = CandidatePolicy(frozenset({CONVERSATION}), merge_seconds=0)
        incoming = IncomingMessages(
            OneBotIngress(10000), PostgresInbox(engine, candidate_policy=policy), lambda: now
        )
        first = await incoming.receive(frame(message_id=1, time=int(now.timestamp())))
        now = clock()
        await incoming.receive(frame(message_id=2))
        assert await worker.run_once() == "confirmed"
        assert model.candidates[0].expires_at == first.event.effective_time + timedelta(seconds=45)
    finally:
        await engine.dispose()


async def test_merge_wait_is_capped_by_first_candidate_maximum(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        policy = CandidatePolicy(frozenset({CONVERSATION}), merge_seconds=60, max_merge_seconds=0)
        incoming, worker, model, _ = setup(engine, policy=policy)
        await incoming.receive(frame(message_id=1))
        await incoming.receive(frame(message_id=2))
        assert await worker.run_once() == "confirmed"
        assert len(model.candidates) == 1
    finally:
        await engine.dispose()


async def test_new_message_replaces_expired_candidate_instead_of_inheriting_expiry(database_url):
    from datetime import timedelta

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        fresh, worker, model, _ = setup(engine)
        old_time = clock() - timedelta(seconds=20)
        policy = CandidatePolicy(frozenset({CONVERSATION}), merge_seconds=0)
        old = IncomingMessages(
            OneBotIngress(10000), PostgresInbox(engine, candidate_policy=policy), lambda: old_time
        )
        await old.receive(frame(message_id=1, time=int(old_time.timestamp())))
        await fresh.receive(frame(message_id=2, content="现在的新话题"))
        assert await worker.run_once() == "confirmed"
        assert model.candidates[0].text == "现在的新话题"
    finally:
        await engine.dispose()


async def test_cancelled_worker_releases_lease_and_does_not_replay_old_turn(database_url):
    import asyncio

    import pytest

    entered = asyncio.Event()

    class Cancellable(Model):
        async def reply(self, candidate):
            if len(self.candidates) == 1:
                entered.set()
                await asyncio.Event().wait()
            return "新的回复"

    engine = create_async_engine(database_url, hide_parameters=True)
    task = None
    try:
        incoming, worker, _, platform = setup(engine, Cancellable())
        await incoming.receive(frame(message_id=1))
        task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await worker.run_once() == "idle"
        await incoming.receive(frame(message_id=2))
        assert await worker.run_once() == "confirmed"
        assert [request.text for request in platform.sent] == ["新的回复"]
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


async def test_parallel_workers_consume_a_silent_candidate_once(database_url):
    import asyncio

    class Silent(Model):
        async def decide(self, candidate):
            self.candidates.append(candidate)
            return "silence"

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        incoming, worker, model, platform = setup(engine, Silent())
        await incoming.receive(frame())
        results = await asyncio.gather(*(worker.run_once() for _ in range(8)))
        assert results.count("silence") == 1
        assert results.count("idle") == 7
        assert len(model.candidates) == 1
        assert platform.sent == []
        assert await worker.run_once() == "idle"
        assert (await incoming.receive(frame())).status == "duplicate"
        assert await worker.run_once() == "idle"
    finally:
        await engine.dispose()


async def test_default_disabled_and_historical_inputs_never_call_model(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        incoming, worker, model, platform = setup(engine, policy=CandidatePolicy())
        await incoming.receive(frame(message_id=1))
        assert await worker.run_once() == "idle"
        enabled, _, _, _ = setup(engine)
        await enabled.receive(frame(message_id=2, time=int(clock().timestamp()) - 1800))
        assert await worker.run_once() == "idle"
        assert model.candidates == []
        assert platform.sent == []
    finally:
        await engine.dispose()


async def test_rebuilt_worker_consumes_pending_but_does_not_repeat_finished_turn(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        incoming, _, _, _ = setup(engine)
        await incoming.receive(frame())
    finally:
        await engine.dispose()
    rebuilt = create_async_engine(database_url, hide_parameters=True)
    try:
        _, worker, model, platform = setup(rebuilt)
        assert await worker.run_once() == "confirmed"
        assert len(platform.sent) == 1
        assert model.candidates[0].generation_epoch == 1
    finally:
        await rebuilt.dispose()
    third = create_async_engine(database_url, hide_parameters=True)
    try:
        _, worker, model, platform = setup(third)
        assert await worker.run_once() == "idle"
        assert model.candidates == []
        assert platform.sent == []
    finally:
        await third.dispose()


async def test_sigkill_recovery_expires_old_turn_and_allows_only_new_candidate(database_url):
    import asyncio
    import json
    import os
    import signal
    import sys

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "tests/helpers/crash_worker.py",
        env={
            "PATH": os.defpath,
            "PYTHONPATH": "src",
            "LANGSMITH_TRACING": "false",
            "XIAOLV_TEST_DATABASE_URL": database_url,
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert process.returncode == -signal.SIGKILL, stderr.decode()
    claimed = json.loads(stdout)
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        incoming, worker, model, platform = setup(engine)
        await incoming.receive(frame(message_id=901, content="重启后的新消息"))
        assert await worker.run_once() == "idle"
        remaining = (datetime.fromisoformat(claimed["expires"]) - clock()).total_seconds()
        await asyncio.sleep(max(0, remaining) + 0.05)
        assert await worker.recover() == 1
        assert await worker.turn_status(claimed["turn"]) == "expired"
        assert await worker.recover() == 0
        assert await worker.run_once() == "confirmed"
        assert [candidate.text for candidate in model.candidates] == ["重启后的新消息"]
        assert model.candidates[0].generation_epoch == 2
        assert len(platform.sent) == 1
        assert await worker.run_once() == "idle"
    finally:
        await engine.dispose()


async def test_late_old_worker_cannot_release_new_workers_lease(database_url):
    import asyncio
    from datetime import timedelta

    class HeldModel(Model):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def reply(self, candidate):
            self.entered.set()
            await self.release.wait()
            return "仍有效的回复"

    engine = create_async_engine(database_url, hide_parameters=True)
    old_model, new_model = HeldModel(), HeldModel()
    tasks = []
    try:
        old_policy = CandidatePolicy(
            frozenset({CONVERSATION}), merge_seconds=0, ttl_seconds=0.3, queue_age_seconds=0.2
        )
        old_incoming, _, _, old_platform = setup(engine, policy=old_policy)
        old_delivery = DeliveryService(old_platform, ledger=PostgresDeliveryLedger(engine))
        # Simulate an old worker whose local clock is behind PostgreSQL's authority.
        old_worker = ChatWorker(
            PostgresTurns(engine),
            TextRuntime(old_model, old_delivery, lambda: clock() - timedelta(seconds=30)),
        )
        await old_incoming.receive(frame(message_id=1, time=int(clock().timestamp()) + 10))
        old_task = asyncio.create_task(old_worker.run_once())
        tasks.append(old_task)
        await asyncio.wait_for(old_model.entered.wait(), 2)
        remaining = (old_model.candidates[0].expires_at - clock()).total_seconds()
        await asyncio.sleep(max(0, remaining) + 0.02)
        incoming, worker, _, platform = setup(engine, new_model)
        await incoming.receive(frame(message_id=2))
        new_task = asyncio.create_task(worker.run_once())
        tasks.append(new_task)
        await asyncio.wait_for(new_model.entered.wait(), 2)
        assert await worker.recover() == 1
        old_model.release.set()
        assert await old_task == "expired"
        assert await worker.turn_status(old_model.candidates[0].event_id) == "expired"
        await incoming.receive(frame(message_id=3))
        assert await worker.run_once() == "idle"
        assert old_platform.sent == []
        new_model.release.set()
        assert await new_task == "confirmed"
        assert await worker.run_once() == "confirmed"
        assert len(platform.sent) == 2
    finally:
        old_model.release.set()
        new_model.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()
