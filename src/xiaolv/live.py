"""Composition root for the native text service."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from opentelemetry import trace
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from websockets.exceptions import WebSocketException

from xiaolv.application.chat_worker import ChatWorker
from xiaolv.application.delivery import DeliveryService
from xiaolv.application.incoming import IncomingMessages
from xiaolv.domain.model_budget import BudgetPolicy
from xiaolv.domain.model_usage import ModelCallReport
from xiaolv.models.chat_completions import ChatCompletionsGateway
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.orchestration.text_runtime import TextRuntime
from xiaolv.platforms.onebot import OneBotSender, QQTarget
from xiaolv.platforms.onebot_ingress import IngressError, OneBotIngress
from xiaolv.platforms.onebot_ws import OneBotWebSocket
from xiaolv.settings import ConfigError, Settings
from xiaolv.storage.postgres_budget import PostgresModelBudget
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger
from xiaolv.storage.postgres_inbox import PostgresInbox
from xiaolv.storage.postgres_turns import CandidatePolicy, PostgresTurns


class LiveRuntimeError(RuntimeError):
    """Service failed; message contains a stable error code, not input data."""


@dataclass
class LiveSummary:
    stored: int = 0
    duplicate: int = 0
    ignored: int = 0
    invalid: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)


def _required[T](value: T | None) -> T:
    if value is None:
        raise ConfigError("live service configuration is incomplete")
    return value


async def run_live(
    settings: Settings, stop: asyncio.Event, *, statistics: LiveSummary | None = None
) -> LiveSummary:
    if settings.mode != "live":
        raise ConfigError("live mode is required")
    self_id = _required(settings.qq_self_id)
    policy = BudgetPolicy(
        "external",
        _required(settings.model_provider),
        _required(settings.model_id),
        _required(settings.model_price_version),
        _required(settings.monthly_external_budget_cny),
        _required(settings.model_input_cny_per_million),
        _required(settings.model_output_cny_per_million),
        settings.model_cached_input_cny_per_million,
    )
    routes = {
        f"qq:{self_id}:group:{group}": QQTarget("group", group)
        for group in settings.enabled_group_ids
    }
    routes.update(
        {
            f"qq:{self_id}:private:{user}": QQTarget("private", user)
            for user in settings.enabled_private_ids
        }
    )
    engine = create_async_engine(
        _required(settings.database_url).get_secret_value(), hide_parameters=True
    )
    summary = statistics if statistics is not None else LiveSummary()
    clock = lambda: datetime.now(UTC)
    try:
        await _check_schema(engine)
        budget = PostgresModelBudget(engine, policy)
        async with (
            ChatCompletionsGateway(
                base_url=_required(settings.model_base_url),
                api_key=_required(settings.model_api_key).get_secret_value(),
                model=_required(settings.model_id),
                concurrency=settings.model_concurrency,
                budget=budget,
                usage_sink=_log_model_usage,
            ) as gateway,
            OneBotWebSocket(
                _required(settings.onebot_url), _required(settings.onebot_token).get_secret_value()
            ) as rpc,
        ):
            login = await rpc.call("get_login_info", {})
            data = login.get("data")
            if (
                login.get("status") != "ok"
                or type(login.get("retcode")) is not int
                or login["retcode"] != 0
                or not isinstance(data, dict)
                or type(data.get("user_id")) is not int
            ):
                raise LiveRuntimeError("onebot_login_invalid")
            if data["user_id"] != self_id:
                raise LiveRuntimeError("onebot_account_mismatch")
            delivery = DeliveryService(
                OneBotSender(rpc, routes), ledger=PostgresDeliveryLedger(engine)
            )
            incoming = IncomingMessages(
                OneBotIngress(self_id, settings.queue_max_age_seconds),
                PostgresInbox(
                    engine,
                    candidate_policy=CandidatePolicy(
                        frozenset(routes),
                        ttl_seconds=settings.chat_ttl_seconds,
                        queue_age_seconds=settings.queue_max_age_seconds,
                    ),
                ),
                clock,
            )
            worker = ChatWorker(
                PostgresTurns(engine),
                TextRuntime(
                    ChatCompletionsModel(
                        gateway,
                        profile=settings.bot_profile,
                        max_reply_chars=settings.max_reply_chars,
                    ),
                    delivery,
                    clock,
                    max_chars=settings.max_reply_chars,
                ),
            )
            await delivery.recover()
            while await worker.recover():
                if stop.is_set():
                    return summary
            with trace.get_tracer(__name__).start_as_current_span("service_ready"):
                logging.getLogger(__name__).info("服务准备完成", extra={"event": "service_ready"})
            tasks = [asyncio.create_task(_receive(rpc, incoming, summary))]
            workers = [
                asyncio.create_task(_work(worker, summary, stop))
                for _ in range(settings.model_concurrency)
            ]
            tasks.extend(workers)
            stopping = asyncio.create_task(stop.wait())
            try:
                done, _ = await asyncio.wait(
                    [*tasks, stopping], return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    if task is not stopping:
                        task.result()
                tasks[0].cancel()
                await asyncio.gather(tasks[0], return_exceptions=True)
                try:
                    await asyncio.wait_for(asyncio.gather(*workers), 5)
                except TimeoutError:
                    pass
            finally:
                stopping.cancel()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(stopping, *tasks, return_exceptions=True)
    except SQLAlchemyError:
        raise LiveRuntimeError("database_unavailable") from None
    except (OSError, WebSocketException):
        raise LiveRuntimeError("platform_connection_failed") from None
    finally:
        await engine.dispose()
    return summary


async def _check_schema(engine: AsyncEngine) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    expected = ScriptDirectory.from_config(config).get_current_head()
    try:
        async with engine.connect() as connection:
            revisions: list[str] = list(
                (await connection.execute(text("SELECT version_num FROM alembic_version")))
                .scalars()
                .all()
            )
    except SQLAlchemyError:
        raise LiveRuntimeError("database_schema_unavailable") from None
    if revisions != [expected]:
        raise LiveRuntimeError("database_schema_mismatch")


async def _receive(rpc: OneBotWebSocket, incoming: IncomingMessages, summary: LiveSummary) -> None:
    while True:
        frame = await rpc.next_event()
        try:
            with trace.get_tracer(__name__).start_as_current_span(
                "event_receive", record_exception=False, set_status_on_exception=False
            ):
                result = await incoming.receive(frame)
                logging.getLogger(__name__).info(
                    "入站事件处理完成",
                    extra={"event": "event_received", "fields": {"status": result.status}},
                )
        except IngressError:
            summary.invalid += 1
            continue
        setattr(summary, result.status, getattr(summary, result.status) + 1)


async def _work(worker: ChatWorker, summary: LiveSummary, stop: asyncio.Event) -> None:
    while not stop.is_set():
        outcome = await worker.run_once()
        if outcome == "idle":
            await asyncio.sleep(0.1)
        else:
            summary.outcomes[outcome] = summary.outcomes.get(outcome, 0) + 1


async def _log_model_usage(report: ModelCallReport) -> None:
    fields = {
        "call_id": report.call_id,
        "status": report.status,
        "usage_known": str(report.usage is not None).lower(),
    }
    if report.usage is not None:
        fields.update(
            input_tokens=str(report.usage.input_tokens),
            output_tokens=str(report.usage.output_tokens),
        )
    logging.getLogger(__name__).info(
        "模型调用已记账", extra={"event": "model_call", "fields": fields}
    )
