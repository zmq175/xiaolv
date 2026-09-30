"""Composition root for the native text service."""

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from opentelemetry import trace
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from websockets.exceptions import WebSocketException

from xiaolv.application.chat_worker import ChatWorker
from xiaolv.application.delivery import DeliveryService
from xiaolv.application.inbound_images import InboundImages
from xiaolv.application.inbound_speech import InboundSpeech
from xiaolv.application.incoming import IncomingMessages
from xiaolv.application.speech_execution import SpeechExecution
from xiaolv.application.voice_dispatch import VoiceDispatch
from xiaolv.domain.model_budget import BudgetPolicy
from xiaolv.domain.model_usage import ModelCallReport
from xiaolv.domain.speech import SpeechPolicy
from xiaolv.models.chat_completions import ChatCompletionsGateway
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.models.fish_audio import FishAudioProvider
from xiaolv.models.tokenizer import load_tokenizer
from xiaolv.models.vision import ImageDescriber
from xiaolv.orchestration.text_runtime import TextRuntime
from xiaolv.platforms.media_http import MediaDownloader, resolve_public_candidate
from xiaolv.platforms.onebot import OneBotPreparation, OneBotSender, QQTarget
from xiaolv.platforms.onebot_images import OneBotImageInterpreter
from xiaolv.platforms.onebot_ingress import IngressError, OneBotIngress
from xiaolv.platforms.onebot_speech import OneBotSpeechTranscriber
from xiaolv.platforms.onebot_ws import OneBotWebSocket
from xiaolv.settings import ConfigError, Settings, SpeechSettings
from xiaolv.storage.audio_artifacts import LocalAudioArtifacts
from xiaolv.storage.conversation_control import ConversationControl
from xiaolv.storage.media_interpretations import PostgresInterpretations
from xiaolv.storage.postgres_budget import PostgresModelBudget
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger
from xiaolv.storage.postgres_inbox import PostgresInbox
from xiaolv.storage.postgres_model_capacity import PostgresModelCapacity
from xiaolv.storage.postgres_speech import PostgresSpeechLedger
from xiaolv.storage.postgres_turns import CandidatePolicy, PostgresTurns
from xiaolv.storage.published_profile import PublishedProfiles
from xiaolv.storage.schema import schema_is_current
from xiaolv.storage.speech_recovery import recover_speech_calls


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
    settings: Settings,
    stop: asyncio.Event,
    *,
    statistics: LiveSummary | None = None,
    speech_transport: httpx.AsyncBaseTransport | None = None,
    media_transport: httpx.AsyncBaseTransport | None = None,
    media_resolver: Callable[[str, int], Awaitable[tuple[str, ...]]] = resolve_public_candidate,
) -> LiveSummary:
    if settings.mode != "live":
        raise ConfigError("live mode is required")
    try:
        await asyncio.to_thread(load_tokenizer, settings.context_policy.encoding)
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
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
        controls = ConversationControl(engine)
        await controls.register(routes)

        async def authorize(conversation_id: str) -> bool:
            return conversation_id in routes and await controls.allowed(conversation_id)

        budget = PostgresModelBudget(engine, policy)
        capacity = PostgresModelCapacity(engine, "chat-model", settings.model_concurrency)
        try:
            await capacity.initialize()
        except ValueError:
            raise ConfigError("shared model capacity configuration conflict") from None
        async with (
            AsyncExitStack() as resources,
            ChatCompletionsGateway(
                base_url=_required(settings.model_base_url),
                api_key=_required(settings.model_api_key).get_secret_value(),
                model=_required(settings.model_id),
                concurrency=settings.model_concurrency,
                budget=budget,
                shared_capacity=capacity,
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
            inbound_images = None
            if settings.vision is not None:
                vision = settings.vision
                vision_capacity = PostgresModelCapacity(engine, "vision-model", vision.concurrency)
                try:
                    await vision_capacity.initialize()
                except ValueError:
                    raise ConfigError("shared vision capacity configuration conflict") from None
                vision_gateway = await resources.enter_async_context(
                    ChatCompletionsGateway(
                        base_url=vision.base_url,
                        api_key=vision.api_key.get_secret_value(),
                        model=vision.model,
                        concurrency=vision.concurrency,
                        budget=PostgresModelBudget(
                            engine,
                            BudgetPolicy(
                                "external",
                                vision.provider,
                                vision.model,
                                vision.price_version,
                                _required(settings.monthly_external_budget_cny),
                                vision.input_cny_per_million,
                                vision.output_cny_per_million,
                                vision.cached_input_cny_per_million,
                            ),
                        ),
                        shared_capacity=vision_capacity,
                        usage_sink=_log_model_usage,
                    )
                )
                processor = (
                    "vision:v1:"
                    + hashlib.sha256(
                        json.dumps(
                            [
                                vision.base_url,
                                vision.provider,
                                vision.model,
                                vision.processor_version,
                            ]
                        ).encode()
                    ).hexdigest()
                )
                inbound_images = InboundImages(
                    OneBotImageInterpreter(
                        rpc,
                        routes,
                        MediaDownloader(resolver=media_resolver, transport=media_transport),
                        ImageDescriber(
                            vision_gateway,
                            processor=processor,
                            image_tokens=vision.image_tokens,
                            window_tokens=vision.window_tokens,
                        ),
                    ),
                    vision.conversations,
                    store=PostgresInterpretations(engine),
                )
            artifacts = None
            speech_provider = None
            speech_capacity = None
            if settings.speech is not None:
                speech = settings.speech
                artifacts = LocalAudioArtifacts(
                    speech.artifact_root,
                    speech.max_audio_bytes,
                    max_total_bytes=speech.max_total_bytes,
                )
                speech_capacity = PostgresModelCapacity(engine, "speech-model", speech.concurrency)
                try:
                    await speech_capacity.initialize()
                except ValueError:
                    raise ConfigError("shared speech capacity configuration conflict") from None
                speech_provider = await resources.enter_async_context(
                    FishAudioProvider(
                        api_key=speech.api_key.get_secret_value(),
                        model=speech.model,
                        voice_profiles=speech.voices,
                        transport=speech_transport,
                        max_audio_bytes=speech.max_audio_bytes,
                        max_duration_seconds=speech.max_duration_seconds,
                    )
                )
            delivery = DeliveryService(
                OneBotSender(rpc, routes),
                ledger=PostgresDeliveryLedger(engine, policy=settings.delivery_policy),
                prepare=OneBotPreparation(rpc, routes, artifacts=artifacts),
                authorize=authorize,
            )
            voice_delivery = None
            if (
                settings.speech is not None
                and artifacts is not None
                and speech_provider is not None
            ):
                speech = settings.speech
                voice_delivery = SpeechExecution(
                    PostgresSpeechLedger(
                        engine,
                        SpeechPolicy(
                            "external",
                            "fish",
                            speech.model,
                            speech.price_version,
                            speech.voice_binding_version,
                            _required(settings.monthly_external_budget_cny),
                            speech.reservation_cny,
                        ),
                    ),
                    speech_provider,
                    VoiceDispatch(artifacts, delivery),
                    capacity=speech_capacity,
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
                PostgresTurns(engine, history_messages=settings.context_policy.history_messages),
                TextRuntime(
                    ChatCompletionsModel(
                        gateway,
                        profile=settings.bot_profile,
                        context_policy=settings.context_policy,
                        max_reply_chars=settings.max_reply_chars,
                        mention_conversations=[
                            key for key, target in routes.items() if target.kind == "group"
                        ],
                        quote_conversations=list(routes),
                        ordered_conversations=list(routes),
                        voice_profiles=settings.speech.conversations if settings.speech else None,
                    ),
                    delivery,
                    clock,
                    max_chars=settings.max_reply_chars,
                    profile_loader=PublishedProfiles(engine, settings.bot_profile).load,
                    voice_delivery=voice_delivery,
                    inbound_images=inbound_images,
                    inbound_speech=InboundSpeech(
                        OneBotSpeechTranscriber(rpc, routes),
                        settings.native_asr_conversations,
                        store=PostgresInterpretations(engine),
                    )
                    if settings.native_asr_conversations
                    else None,
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
            tasks.append(
                asyncio.create_task(
                    _maintain_speech_calls(engine, settings.speech_recovery_interval_seconds, stop)
                )
            )
            if artifacts is not None and settings.speech is not None:
                tasks.append(asyncio.create_task(_maintain_audio(artifacts, settings.speech, stop)))
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
    try:
        current = await schema_is_current(engine)
    except SQLAlchemyError:
        raise LiveRuntimeError("database_schema_unavailable") from None
    if not current:
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


async def _maintain_audio(
    artifacts: LocalAudioArtifacts, settings: SpeechSettings, stop: asyncio.Event
) -> None:
    while not stop.is_set():
        try:
            removed = await artifacts.cleanup(
                before=datetime.now(UTC) - timedelta(seconds=settings.retention_seconds)
            )
            if removed:
                logging.getLogger(__name__).info(
                    "过期音频已清理",
                    extra={"event": "audio_cleanup", "fields": {"removed": str(removed)}},
                )
        except (OSError, ValueError):
            logging.getLogger(__name__).warning(
                "音频清理失败，容量限制继续生效", extra={"event": "audio_cleanup_failed"}
            )
        try:
            await asyncio.wait_for(stop.wait(), settings.cleanup_interval_seconds)
        except TimeoutError:
            pass


async def _maintain_speech_calls(engine: AsyncEngine, interval: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            count = await recover_speech_calls(engine)
            if count:
                logging.getLogger(__name__).warning(
                    "过期语音调用已标记未知，费用预留保留",
                    extra={"event": "speech_recovered", "fields": {"count": str(count)}},
                )
        except SQLAlchemyError:
            logging.getLogger(__name__).warning(
                "语音审计恢复失败，等待下个周期", extra={"event": "speech_recovery_failed"}
            )
        try:
            await asyncio.wait_for(stop.wait(), interval)
        except TimeoutError:
            pass
