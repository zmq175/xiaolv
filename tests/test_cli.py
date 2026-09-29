import json
import os
import subprocess
import sys
from pathlib import Path


def invoke(**changes):
    env = {key: value for key, value in os.environ.items() if not key.startswith("XIAOLV_")}
    env.update(changes)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    return subprocess.run(
        [sys.executable, "-m", "xiaolv"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_default_command_runs_offline_replay():
    result = invoke()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "mode": "local_fake_replay",
        "outcomes": ["silence", "confirmed"],
        "sent": ["我也在听，你们继续。"],
    }


def test_invalid_live_configuration_exits_without_secrets_or_traceback():
    result = invoke(XIAOLV_MODE="live", XIAOLV_MODEL_API_KEY="do-not-print-this")
    assert result.returncode == 2
    assert "invalid configuration" in result.stderr
    assert "do-not-print-this" not in result.stderr + result.stdout
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_cli_uses_structured_stderr_logs_and_keeps_stdout_machine_readable():
    from xiaolv.observability.log_format import parse_log

    result = invoke()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mode"] == "local_fake_replay"
    entries = [parse_log(line) for line in result.stderr.splitlines()]
    assert "我也在听" not in result.stderr
    entries = [entry for entry in entries if entry.event.startswith("service_")]
    assert [entry.event for entry in entries] == ["service_started", "service_stopped"]
    assert all(entry.traceid != "0" * 32 for entry in entries)
    assert entries[0].traceid != entries[1].traceid
