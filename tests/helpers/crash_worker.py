"""Isolated fault fixture: SIGKILL after the durable turn claim commits."""

import asyncio
import json
import os
import signal
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


def clock():
    return datetime.now(UTC)


class CrashingModel:
    async def decide(self, candidate):
        print(
            json.dumps({"turn": candidate.event_id, "expires": candidate.expires_at.isoformat()}),
            flush=True,
        )
        os.kill(os.getpid(), signal.SIGKILL)

    async def reply(self, candidate):
        raise AssertionError("crashed turn must not generate")


class NoPlatform:
    async def send(self, request):
        raise AssertionError("crashed turn must not send")


async def main():
    engine = create_async_engine(os.environ["XIAOLV_TEST_DATABASE_URL"], hide_parameters=True)
    policy = CandidatePolicy(
        frozenset({"qq:10000:group:20000"}), merge_seconds=0, ttl_seconds=2, queue_age_seconds=1
    )
    incoming = IncomingMessages(
        OneBotIngress(10000), PostgresInbox(engine, candidate_policy=policy), clock
    )
    await incoming.receive(
        {
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "self_id": 10000,
            "user_id": 10001,
            "group_id": 20000,
            "message_id": 900,
            "time": int(clock().timestamp()) + 10,
            "message": [{"type": "text", "data": {"text": "崩溃前合成消息"}}],
        }
    )
    delivery = DeliveryService(NoPlatform(), ledger=PostgresDeliveryLedger(engine))
    await ChatWorker(
        PostgresTurns(engine), TextRuntime(CrashingModel(), delivery, clock)
    ).run_once()
    raise AssertionError("fault fixture did not terminate")


asyncio.run(main())
