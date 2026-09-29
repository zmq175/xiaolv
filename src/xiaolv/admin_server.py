"""Local management service and explicit password-file provisioning."""

import argparse
import asyncio
import getpass
import logging
import os
import signal
import stat
import sys
from pathlib import Path

import uvicorn
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from sqlalchemy import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.admin import AdminConfig, create_admin_app
from xiaolv.observability.logging_setup import configure_logging, shutdown_logging
from xiaolv.storage.schema import schema_is_current


class AdminRuntimeError(RuntimeError):
    """Only fixed, non-sensitive diagnostic codes."""


class _ServerLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = "管理HTTP服务错误"
        record.args = ()
        record.event = "admin_http_error"
        return True


def _load() -> tuple[str, int, AdminConfig]:
    port = int(os.environ.get("XIAOLV_ADMIN_PORT", "8081"))
    if not 1 <= port <= 65535:
        raise ValueError("invalid_admin_port")
    url = os.environ["XIAOLV_ADMIN_DATABASE_URL"]
    try:
        driver = make_url(url).drivername
    except SQLAlchemyError:
        raise ValueError("invalid_admin_database") from None
    if driver != "postgresql+psycopg":
        raise ValueError("invalid_admin_database")
    path = os.environ["XIAOLV_ADMIN_PASSWORD_HASH_FILE"]
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "r", encoding="utf-8") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise ValueError("unsafe_password_file")
        password_hash = source.read(4097).strip()
    if len(password_hash) > 4096:
        raise ValueError("invalid_password_file")
    PasswordHash.recommended().verify("", password_hash)
    return (
        url,
        port,
        AdminConfig(
            password_hash=password_hash,
            origin=os.environ.get("XIAOLV_ADMIN_ORIGIN", f"http://127.0.0.1:{port}"),
        ),
    )


def _initialize(output: Path, password_stdin: bool) -> None:
    if password_stdin:
        password = sys.stdin.readline(4097).removesuffix("\n").removesuffix("\r")
    else:
        if not sys.stdin.isatty():
            raise ValueError("terminal_required")
        password = getpass.getpass("管理员密码: ")
        if password != getpass.getpass("再次输入密码: "):
            raise ValueError("password_mismatch")
    if not 12 <= len(password) <= 1024:
        raise ValueError("invalid_password_length")
    hashed = PasswordHash.recommended().hash(password)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
        destination.write(hashed + "\n")


async def _serve() -> None:
    url, port, config = _load()
    engine = create_async_engine(url, hide_parameters=True)
    logger = logging.getLogger("xiaolv.admin")
    try:
        async with asyncio.timeout(10):
            if not await schema_is_current(engine):
                raise AdminRuntimeError("database_schema_mismatch")
        server = uvicorn.Server(
            uvicorn.Config(
                create_admin_app(engine, config),
                host="127.0.0.1",
                port=port,
                log_config=None,
                access_log=False,
                proxy_headers=False,
            )
        )
        logger.info("管理服务启动", extra={"event": "admin_started"})
        # Uvicorn owns signal handling while serving; its final SIGTERM replay
        # returns here so database cleanup and the final lifecycle log can run.
        previous = signal.signal(signal.SIGTERM, lambda *_: None)
        try:
            await server.serve()
        finally:
            signal.signal(signal.SIGTERM, previous)
    finally:
        await engine.dispose()
        logger.info("管理服务停止", extra={"event": "admin_stopped"})


def main() -> int:
    parser = argparse.ArgumentParser(description="机器人管理服务")
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init-password")
    initialize.add_argument("--output", type=Path, required=True)
    initialize.add_argument("--password-stdin", action="store_true")
    commands.add_parser("serve")
    args = parser.parse_args()
    configure_logging()
    server_log = logging.getLogger("uvicorn.error")
    server_log.handlers = list(logging.getLogger("xiaolv").handlers)
    server_log.propagate = False
    server_log.setLevel(logging.WARNING)
    server_log.addFilter(_ServerLogFilter())
    try:
        if args.command == "init-password":
            _initialize(args.output, args.password_stdin)
            print("password_file_created")
        else:
            asyncio.run(_serve())
        return 0
    except TimeoutError:
        print("admin_runtime_failed", file=sys.stderr)
        return 1
    except (KeyError, ValueError, OSError, PwdlibError):
        print("invalid_admin_configuration", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("admin_runtime_failed", file=sys.stderr)
        return 1
    except AdminRuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        shutdown_logging()


if __name__ == "__main__":
    raise SystemExit(main())
