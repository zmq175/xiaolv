"""Management HTTP application, separate from the chat runtime."""

import hashlib
import math
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import RequestResponseEndpoint


@dataclass(frozen=True)
class AdminConfig:
    password_hash: str = field(repr=False)
    origin: str
    session_seconds: float = 28800

    def __post_init__(self) -> None:
        try:
            origin = urlsplit(self.origin)
            valid = (
                origin.scheme in ("http", "https")
                and bool(origin.hostname)
                and origin.username is None
                and origin.password is None
                and not origin.path
                and not origin.query
                and not origin.fragment
                and not any(char.isspace() for char in self.origin)
                and (
                    origin.scheme == "https" or origin.hostname in ("localhost", "127.0.0.1", "::1")
                )
            )
            _ = origin.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("invalid admin origin")
        if not math.isfinite(self.session_seconds) or not 0 < self.session_seconds <= 86400:
            raise ValueError("invalid session lifetime")


class _Login(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    password: SecretStr = Field(min_length=1, max_length=1024)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_admin_app(engine: AsyncEngine, config: AdminConfig) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    hasher = PasswordHash.recommended()
    password_slots = anyio.CapacityLimiter(2)
    credential_version = _digest(config.password_hash)

    @app.middleware("http")
    async def management_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response: Response
        if request.method not in ("GET", "HEAD") and request.headers.get("origin") != config.origin:
            response = JSONResponse({"detail": "origin_rejected"}, status_code=403)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        # FastAPI's default validation response includes submitted input, even secrets.
        return JSONResponse({"detail": "invalid_request"}, status_code=422)

    async def session(request: Request) -> dict[str, str]:
        token = request.cookies.get("xiaolv_admin", "")
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                SELECT csrf_token FROM admin.sessions WHERE token_hash = :token
                  AND credential_version = :version AND expires_at > clock_timestamp()
            """),
                        {"token": _digest(token), "version": credential_version},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise HTTPException(401, "authentication_required")
        return {"csrf_token": row["csrf_token"]}

    @app.post("/admin/api/login")
    async def login(body: _Login) -> JSONResponse:
        async with engine.begin() as connection:
            admitted = (
                await connection.execute(
                    text("""
                INSERT INTO admin.login_window(id, began_at, attempts)
                VALUES (1, clock_timestamp(), 1)
                ON CONFLICT (id) DO UPDATE SET
                    attempts = CASE WHEN admin.login_window.began_at <= clock_timestamp() - interval '60 seconds'
                                    THEN 1 ELSE admin.login_window.attempts + 1 END,
                    began_at = CASE WHEN admin.login_window.began_at <= clock_timestamp() - interval '60 seconds'
                                    THEN clock_timestamp() ELSE admin.login_window.began_at END
                WHERE admin.login_window.attempts < 5
                   OR admin.login_window.began_at <= clock_timestamp() - interval '60 seconds'
                RETURNING id
            """)
                )
            ).scalar_one_or_none()
        if admitted is None:
            raise HTTPException(429, "login_rate_limited", headers={"Retry-After": "60"})
        valid = await anyio.to_thread.run_sync(
            hasher.verify,
            body.password.get_secret_value(),
            config.password_hash,
            limiter=password_slots,
        )
        if not valid:
            raise HTTPException(401, "invalid_credentials")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                INSERT INTO admin.sessions(token_hash, csrf_token, credential_version, expires_at)
                VALUES (:token, :csrf, :version, clock_timestamp() + :ttl * interval '1 second')
            """),
                {
                    "token": _digest(token),
                    "csrf": csrf,
                    "version": credential_version,
                    "ttl": config.session_seconds,
                },
            )
        response = JSONResponse({"authenticated": True, "csrf_token": csrf})
        response.set_cookie(
            "xiaolv_admin",
            token,
            max_age=int(config.session_seconds),
            httponly=True,
            secure=config.origin.startswith("https://"),
            samesite="strict",
            path="/admin",
        )
        return response

    @app.get("/admin/api/session")
    async def current_session(request: Request) -> dict[str, object]:
        return {"authenticated": True, **await session(request)}

    @app.post("/admin/api/logout")
    async def logout(request: Request) -> Response:
        active = await session(request)
        if not secrets.compare_digest(
            request.headers.get("x-csrf-token", ""), active["csrf_token"]
        ):
            raise HTTPException(403, "csrf_required")
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM admin.sessions WHERE token_hash = :token"),
                {"token": _digest(request.cookies.get("xiaolv_admin", ""))},
            )
        response = Response(status_code=204)
        response.delete_cookie(
            "xiaolv_admin",
            path="/admin",
            httponly=True,
            secure=config.origin.startswith("https://"),
            samesite="strict",
        )
        return response

    return app
