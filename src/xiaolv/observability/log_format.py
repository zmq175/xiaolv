"""Structured line log wire format."""

import re
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class LogEntry:
    level: str
    timestamp: datetime
    source: str
    event: str
    traceid: str
    spanid: str
    message: str
    fields: dict[str, str] = field(default_factory=dict)


def format_log(entry: LogEntry) -> str:
    _validate(entry)
    timestamp = entry.timestamp.strftime("%Y-%m-%dT%H:%M:%S.")
    timestamp += f"{entry.timestamp.microsecond // 1000:03d}"
    timestamp += entry.timestamp.strftime("%z")
    header = f"[{entry.level}][{timestamp}][{entry.source}] {entry.event}"
    fields = "".join(f"||{key}={_escape(value)}" for key, value in sorted(entry.fields.items()))
    return (
        f"{header}||traceid={entry.traceid}||spanid={entry.spanid}"
        f"||schema_version=1{fields}||__msg={_escape(entry.message)}"
    )


def parse_log(line: str) -> LogEntry:
    if not line.startswith("[") or "\n" in line or "\r" in line:
        raise ValueError("log must be a single line")
    header, *parts = line.split("||")
    if not parts or not parts[-1].startswith("__msg="):
        raise ValueError("message must be last")
    level, timestamp, source_event = header[1:].split("][", 2)
    source, event = source_event.split("] ", 1)
    fields: dict[str, str] = {}
    for part in parts:
        key, value = part.split("=", 1)
        if key in fields:
            raise ValueError("duplicate log field")
        fields[key] = _unescape(value)
    if not _RESERVED <= fields.keys() or fields.pop("schema_version") != "1":
        raise ValueError("missing base fields or unsupported schema")
    entry = LogEntry(
        level=level,
        timestamp=datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f%z"),
        source=source,
        event=event,
        traceid=fields.pop("traceid"),
        spanid=fields.pop("spanid"),
        message=fields.pop("__msg"),
        fields=fields,
    )
    _validate(entry)
    return entry


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("|", r"\u007C")
        .replace("\n", r"\n")
        .replace("\r", r"\r")
    )


def _unescape(value: str) -> str:
    decoded = []
    index = 0
    escapes = {"\\": "\\", "n": "\n", "r": "\r"}
    while index < len(value):
        if value[index] != "\\":
            decoded.append(value[index])
            index += 1
        elif value.startswith(r"\u007C", index):
            decoded.append("|")
            index += 6
        elif index + 1 < len(value) and value[index + 1] in escapes:
            decoded.append(escapes[value[index + 1]])
            index += 2
        else:
            raise ValueError("invalid log escape")
    return "".join(decoded)


_RESERVED = {"traceid", "spanid", "schema_version", "__msg"}


def _validate(entry: LogEntry) -> None:
    if entry.timestamp.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    if entry.level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("invalid log level")
    for name, value, pattern in (
        ("event", entry.event, r"[a-z0-9_]+"),
        ("source", entry.source, r"[^\[\]\r\n|]+:[1-9][0-9]*"),
        ("traceid", entry.traceid, r"[0-9a-f]{32}"),
        ("spanid", entry.spanid, r"[0-9a-f]{16}"),
    ):
        if not re.fullmatch(pattern, value):
            raise ValueError(f"invalid {name}")
    for key in entry.fields:
        if key in _RESERVED or not re.fullmatch(r"[a-z0-9_]+", key):
            raise ValueError("invalid or reserved field name")
