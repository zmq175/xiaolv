import asyncio
import os
import signal
import socket
import sys
from pathlib import Path

import httpx2 as httpx
import pytest

PASSWORD = "synthetic-admin-password"


def environment(**settings):
    env = {key: value for key, value in os.environ.items() if not key.startswith("XIAOLV_")}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    env.update(settings)
    return env


async def command(*args, env=None, stdin=None):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "xiaolv.admin_server",
        *args,
        env=env or environment(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, error = await asyncio.wait_for(process.communicate(stdin), 3)
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()
    return process.returncode, output.decode(), error.decode()


async def test_initialized_password_logs_in_to_standalone_server(database_url, tmp_path):
    secret = tmp_path / "admin.hash"
    code, output, error = await command(
        "init-password",
        "--output",
        str(secret),
        "--password-stdin",
        stdin=(PASSWORD + "\n").encode(),
    )
    assert code == 0, error
    assert PASSWORD not in output + error
    assert secret.stat().st_mode & 0o777 == 0o600
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "xiaolv.admin_server",
        "serve",
        env=environment(
            XIAOLV_ADMIN_DATABASE_URL=database_url,
            XIAOLV_ADMIN_PASSWORD_HASH_FILE=str(secret),
            XIAOLV_ADMIN_PORT=str(port),
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with httpx.AsyncClient(base_url=origin, trust_env=False) as browser:
            async with asyncio.timeout(10):
                while True:
                    assert process.returncode is None, "admin server exited before listening"
                    try:
                        response = await browser.get("/admin/api/session")
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.05)
            assert response.status_code == 401
            login = await browser.post(
                "/admin/api/login", json={"password": PASSWORD}, headers={"Origin": origin}
            )
            assert login.status_code == 200
        process.send_signal(signal.SIGTERM)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
        assert process.returncode == 0
        logs = (stdout + stderr).decode()
        assert PASSWORD not in logs and secret.read_text().strip() not in logs
        assert "admin_started" in logs and "admin_stopped" in logs
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


@pytest.mark.parametrize("fault", ["missing", "hash", "permissions", "port", "dsn"])
async def test_bad_admin_configuration_exits_without_echoing_secrets(database_url, tmp_path, fault):
    secret = tmp_path / "admin.hash"
    code, _, _ = await command(
        "init-password",
        "--output",
        str(secret),
        "--password-stdin",
        stdin=(PASSWORD + "\n").encode(),
    )
    assert code == 0
    env = environment(
        XIAOLV_ADMIN_DATABASE_URL=database_url, XIAOLV_ADMIN_PASSWORD_HASH_FILE=str(secret)
    )
    if fault == "missing":
        env.pop("XIAOLV_ADMIN_DATABASE_URL")
    elif fault == "hash":
        secret.write_text("broken-secret-hash")
    elif fault == "permissions":
        secret.chmod(0o644)
    elif fault == "port":
        env["XIAOLV_ADMIN_PORT"] = "0"
    else:
        env["XIAOLV_ADMIN_DATABASE_URL"] = "sqlite:///sensitive-path"
    code, output, error = await command("serve", env=env)
    assert code == 2
    assert "invalid_admin_configuration" in error
    assert PASSWORD not in output + error
    assert "broken-secret-hash" not in output + error
    assert "sensitive-path" not in output + error


async def test_old_schema_refuses_startup(database_url, tmp_path):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    secret = tmp_path / "admin.hash"
    assert (
        await command(
            "init-password",
            "--output",
            str(secret),
            "--password-stdin",
            stdin=(PASSWORD + "\n").encode(),
        )
    )[0] == 0
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE alembic_version SET version_num = '0009_ordered_text'")
            )
    finally:
        await engine.dispose()
    code, _, error = await command(
        "serve",
        env=environment(
            XIAOLV_ADMIN_DATABASE_URL=database_url, XIAOLV_ADMIN_PASSWORD_HASH_FILE=str(secret)
        ),
    )
    assert code == 1
    assert "database_schema_mismatch" in error


async def test_password_initialization_refuses_overwrite_and_short_password(tmp_path):
    secret = tmp_path / "admin.hash"
    secret.write_text("existing-file")
    code, output, error = await command(
        "init-password",
        "--output",
        str(secret),
        "--password-stdin",
        stdin=(PASSWORD + "\n").encode(),
    )
    assert code == 2
    assert secret.read_text() == "existing-file"
    other = tmp_path / "short.hash"
    assert (
        await command("init-password", "--output", str(other), "--password-stdin", stdin=b"short\n")
    )[0] == 2
    assert not other.exists()
    assert PASSWORD not in output + error


async def test_piped_password_requires_explicit_stdin_mode(tmp_path):
    destination = tmp_path / "admin.hash"
    code, output, error = await command(
        "init-password",
        "--output",
        str(destination),
        stdin=(PASSWORD + "\n" + PASSWORD + "\n").encode(),
    )
    assert code == 2
    assert not destination.exists()
    assert PASSWORD not in output + error


async def test_unavailable_database_exits_before_listening(tmp_path):
    secret = tmp_path / "admin.hash"
    assert (
        await command(
            "init-password",
            "--output",
            str(secret),
            "--password-stdin",
            stdin=(PASSWORD + "\n").encode(),
        )
    )[0] == 0
    missing_socket = tmp_path / "missing-postgres"
    url = f"postgresql+psycopg:///xiaolv_test?host={missing_socket}&port=55432"
    code, output, error = await command(
        "serve",
        env=environment(XIAOLV_ADMIN_DATABASE_URL=url, XIAOLV_ADMIN_PASSWORD_HASH_FILE=str(secret)),
    )
    assert code == 1
    assert "admin_runtime_failed" in error
    assert "admin_started" not in output + error
    assert str(missing_socket) not in output + error
