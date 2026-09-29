import io
import logging
from datetime import timedelta

import pytest

from xiaolv.observability.log_format import parse_log


@pytest.fixture
def output():
    from xiaolv.observability.logging_setup import configure_logging, shutdown_logging

    stream = io.StringIO()
    configure_logging(stream=stream)
    yield stream
    shutdown_logging()


def test_standard_logger_emits_user_format_with_actual_source(output):
    logging.getLogger("xiaolv.test").info(
        "开始执行...", extra={"event": "chat_decision", "fields": {"action": "silence"}}
    )
    entry = parse_log(output.getvalue().strip())
    assert entry.level == "INFO"
    assert entry.event == "chat_decision"
    assert entry.message == "开始执行..."
    assert entry.fields == {"action": "silence"}
    assert entry.timestamp.utcoffset() == timedelta(hours=8)
    assert entry.source.startswith("test_logging.py:")
    assert int(entry.source.split(":")[1]) > 0
    assert entry.traceid == "0" * 32
    assert entry.spanid == "0" * 16


async def test_otel_trace_context_is_isolated_between_concurrent_tasks(output):
    import asyncio

    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")
    barrier = asyncio.Barrier(2)
    expected = {}

    async def emit(name):
        with tracer.start_as_current_span(name) as span:
            context = span.get_span_context()
            expected[name] = (f"{context.trace_id:032x}", f"{context.span_id:016x}")
            await barrier.wait()
            logging.getLogger("xiaolv.test").info(name, extra={"event": "chat_decision"})

    try:
        await asyncio.gather(emit("first"), emit("second"))
        entries = [parse_log(line) for line in output.getvalue().splitlines()]
        assert len(entries) == 2
        assert len({entry.traceid for entry in entries}) == 2
        for entry in entries:
            assert (entry.traceid, entry.spanid) == expected[entry.message]
    finally:
        provider.shutdown()


def test_exception_logs_type_and_stack_without_exception_text_or_source(output):
    logger = logging.getLogger("xiaolv.test")
    try:
        raise ValueError("secret-value-in-exception")
    except ValueError:
        logger.exception(
            "操作失败",
            extra={"event": "service_failed", "fields": {"error_code": "synthetic_failure"}},
        )
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    assert "secret-value-in-exception" not in lines[0]
    entry = parse_log(lines[0])
    assert entry.fields["exception_type"] == "ValueError"
    assert "test_logging.py:" in entry.fields["stack"]
    assert "raise ValueError" not in entry.fields["stack"]
    assert entry.fields["error_code"] == "synthetic_failure"


def test_standard_file_rotation_keeps_bounded_archives_and_parseable_lines(tmp_path, output):
    from xiaolv.observability.logging_setup import configure_logging, shutdown_logging

    target = tmp_path / "application.log"
    configure_logging(stream=output, filename=target, max_bytes=500, backup_count=2)
    logger = logging.getLogger("xiaolv.test")
    for index in range(12):
        logger.info("轮转测试", extra={"event": "test_event", "fields": {"sequence": str(index)}})
    shutdown_logging()
    files = sorted(tmp_path.glob("application.log*"))
    assert [file.name for file in files] == [
        "application.log",
        "application.log.1",
        "application.log.2",
    ]
    for file in files:
        for line in file.read_text().splitlines():
            assert parse_log(line).event == "test_event"
    assert parse_log(target.read_text().splitlines()[-1]).fields["sequence"] == "11"
    assert len(output.getvalue().splitlines()) == 12


def test_reconfiguration_preserves_level_filtering_without_duplicate_lines(output):
    from xiaolv.observability.logging_setup import configure_logging, shutdown_logging

    configure_logging(stream=output)
    configure_logging(stream=output)
    logger = logging.getLogger("xiaolv.test")
    logger.debug("不应出现")
    logger.info("只出现一次")
    configure_logging(stream=output, level="DEBUG")
    logger.debug("调试摘要")
    shutdown_logging()
    assert not output.closed
    entries = [parse_log(line) for line in output.getvalue().splitlines()]
    assert [entry.message for entry in entries] == ["只出现一次", "调试摘要"]
