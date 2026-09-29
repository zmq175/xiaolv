from datetime import datetime

import pytest

from xiaolv.observability.log_format import LogEntry, format_log


def entry(**changes):
    values = {
        "level": "INFO",
        "timestamp": datetime.fromisoformat("2026-09-29T16:20:00.123+08:00"),
        "source": "participation.py:120",
        "event": "chat_decision",
        "traceid": "0123456789abcdef0123456789abcdef",
        "spanid": "0123456789abcdef",
        "message": "开始执行...",
        "fields": {},
    }
    values.update(changes)
    return LogEntry(**values)


EXAMPLE = (
    "[INFO][2026-09-29T16:20:00.123+0800][participation.py:120] chat_decision"
    "||traceid=0123456789abcdef0123456789abcdef||spanid=0123456789abcdef"
    "||schema_version=1||__msg=开始执行..."
)


def test_user_log_format_uses_single_equals_for_message():
    assert format_log(entry()) == EXAMPLE


def test_fields_are_sorted_before_message():
    assert format_log(entry(fields={"turn_id": "a=b", "action": "silence"})) == EXAMPLE.replace(
        "||__msg=", "||action=silence||turn_id=a=b||__msg="
    )


def test_parse_recovers_entry_and_equals_in_values():
    from xiaolv.observability.log_format import parse_log

    line = EXAMPLE.replace("||__msg=", "||turn_id=a=b||__msg=")
    assert parse_log(line) == entry(fields={"turn_id": "a=b"})


def test_escaping_is_single_pass_and_keeps_one_line():
    from xiaolv.observability.log_format import parse_log

    message = "第一行\n第二行\r|\\n\\u007C"
    original = entry(message=message, fields={"value": "x||y=z\\"})
    line = format_log(original)
    assert "\n" not in line and "\r" not in line
    assert line.endswith(r"||__msg=第一行\n第二行\r\u007C\\n\\u007C")
    assert parse_log(line) == original


@pytest.mark.parametrize(
    "changes",
    [
        {"fields": {"traceid": "override"}},
        {"fields": {"bad||name": "value"}},
        {"event": "event\nforged"},
        {"source": "file.py:1] forged"},
        {"level": "INFO][forged"},
        {"traceid": "bad"},
        {"spanid": "bad"},
        {"timestamp": datetime(2026, 9, 29)},  # noqa: DTZ001 - deliberate invalid input
    ],
)
def test_invalid_metadata_is_rejected_before_encoding(changes):
    with pytest.raises(ValueError):
        format_log(entry(**changes))


@pytest.mark.parametrize(
    "line",
    [
        EXAMPLE.replace("schema_version=1", "schema_version=2"),
        EXAMPLE + "||traceid=duplicate",
        EXAMPLE.replace("||spanid=0123456789abcdef", ""),
        EXAMPLE + r"\q",
        EXAMPLE + "||extra=after_message",
        EXAMPLE + "\nforged",
        EXAMPLE.replace("chat_decision", "chat decision"),
    ],
)
def test_malformed_lines_are_rejected(line):
    from xiaolv.observability.log_format import parse_log

    with pytest.raises(ValueError):
        parse_log(line)


@pytest.mark.parametrize(
    "line",
    [
        EXAMPLE.replace("[INFO]", "XINFO]"),
        EXAMPLE.replace("||__msg=", "||spanid=0123456789abcdef||__msg="),
    ],
)
def test_header_prefix_and_duplicate_base_fields_are_rejected(line):
    from xiaolv.observability.log_format import parse_log

    with pytest.raises(ValueError):
        parse_log(line)
