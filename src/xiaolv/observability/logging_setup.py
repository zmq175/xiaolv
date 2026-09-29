"""Standard logging configuration; the application only supplies its formatter."""

import logging
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO
from zoneinfo import ZoneInfo

from opentelemetry import trace

from xiaolv.observability.log_format import LogEntry, format_log

_HANDLERS: list[logging.Handler] = []


class LineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = trace.get_current_span().get_span_context()
        fields = dict(getattr(record, "fields", {}))
        if record.exc_info and record.exc_info[0] is not None:
            fields["exception_type"] = record.exc_info[0].__name__
            fields["stack"] = " > ".join(
                f"{Path(frame.f_code.co_filename).name}:{line}/{frame.f_code.co_name}"
                for frame, line in traceback.walk_tb(record.exc_info[2])
            )
        return format_log(
            LogEntry(
                level=record.levelname,
                timestamp=datetime.fromtimestamp(record.created, ZoneInfo("Asia/Shanghai")),
                source=f"{record.filename}:{record.lineno}",
                event=getattr(record, "event", "application_log"),
                traceid=f"{context.trace_id:032x}",
                spanid=f"{context.span_id:016x}",
                message=record.getMessage(),
                fields=fields,
            )
        )


def configure_logging(
    *,
    stream: TextIO | None = None,
    level: str = "INFO",
    filename: Path | None = None,
    max_bytes: int = 20 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    shutdown_logging()
    logger = logging.getLogger("xiaolv")
    logger.setLevel(level)
    logger.propagate = False
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(LineFormatter())
    logger.addHandler(handler)
    _HANDLERS.append(handler)
    if filename is not None:
        file_handler = RotatingFileHandler(
            filename, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(LineFormatter())
        logger.addHandler(file_handler)
        _HANDLERS.append(file_handler)


def shutdown_logging() -> None:
    logger = logging.getLogger("xiaolv")
    for handler in _HANDLERS:
        logger.removeHandler(handler)
        handler.close()
    _HANDLERS.clear()
