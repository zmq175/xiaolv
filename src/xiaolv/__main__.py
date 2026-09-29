"""Command-line entry point; offline replay by default."""

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import asdict

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from xiaolv.live import LiveRuntimeError, run_live
from xiaolv.observability.logging_setup import configure_logging, shutdown_logging
from xiaolv.replay import main as replay
from xiaolv.settings import ConfigError, Settings, load_settings


async def serve(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
            installed.append(signum)
        summary = await run_live(settings, stop)
        print(json.dumps({"mode": "live", **asdict(summary)}, ensure_ascii=False))
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)


def main() -> int:
    try:
        settings = load_settings(os.environ)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        configure_logging(
            level=settings.log_level,
            filename=settings.log_file,
            max_bytes=settings.log_max_bytes,
            backup_count=settings.log_backup_count,
        )
    except OSError:
        print("invalid logging destination", file=sys.stderr)
        shutdown_logging()
        return 2
    provider = TracerProvider(resource=Resource({"service.name": "xiaolv"}))
    trace.set_tracer_provider(provider)
    tracer = provider.get_tracer("xiaolv.lifecycle")
    logger = logging.getLogger("xiaolv.lifecycle")
    try:
        with tracer.start_as_current_span("service_start"):
            logger.info(
                "开始执行", extra={"event": "service_started", "fields": {"mode": settings.mode}}
            )
        asyncio.run(serve(settings) if settings.mode == "live" else replay())
        with tracer.start_as_current_span("service_stop"):
            logger.info("服务已停止", extra={"event": "service_stopped"})
    except (ConfigError, LiveRuntimeError) as error:
        with tracer.start_as_current_span("service_failure"):
            logger.exception(
                "服务退出", extra={"event": "service_failed", "fields": {"error_code": str(error)}}
            )
        return 2 if isinstance(error, ConfigError) else 1
    finally:
        provider.shutdown()
        shutdown_logging()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
