"""Management HTTP application, separate from the chat runtime."""

import hashlib
import math
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import RequestResponseEndpoint
from starlette.staticfiles import StaticFiles

from xiaolv.domain.bot_profile import BotProfile
from xiaolv.storage.profile_publication import ProfilePublication, PublicationError


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


class _ProfileWrite(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    expected_version: int = Field(ge=0)


class _DraftWrite(_ProfileWrite):
    profile: BotProfile


class _RollbackWrite(_ProfileWrite):
    release_version: int = Field(gt=0)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_admin_app(
    engine: AsyncEngine, config: AdminConfig, *, frontend_dir: Path | None = None
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    hasher = PasswordHash.recommended()
    password_slots = anyio.CapacityLimiter(2)
    credential_version = _digest(config.password_hash)
    profiles = ProfilePublication(engine)

    @app.exception_handler(PublicationError)
    async def publication_error(request: Request, error: PublicationError) -> JSONResponse:
        return JSONResponse({"detail": error.code}, status_code=error.status)

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
        if request.url.path.startswith("/admin/api/profile"):
            fields = {
                "body",
                "path",
                "profile",
                "expected_version",
                "release_version",
                "version",
                *BotProfile.model_fields,
            }
            errors = [
                {
                    "loc": [
                        part if isinstance(part, int) or part in fields else "unknown_field"
                        for part in issue["loc"]
                    ],
                    "type": issue["type"],
                }
                for issue in error.errors()
            ]
            return JSONResponse({"detail": "invalid_request", "errors": errors}, status_code=422)
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

    async def require_write(request: Request) -> str:
        active = await session(request)
        if not secrets.compare_digest(
            request.headers.get("x-csrf-token", ""), active["csrf_token"]
        ):
            raise HTTPException(403, "csrf_required")
        key = request.headers.get("idempotency-key", "")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key) is None:
            raise HTTPException(422, "invalid_idempotency_key")
        return key

    @app.get("/admin/api/profile")
    async def current_profile(request: Request) -> JSONResponse:
        await session(request)
        return JSONResponse(await profiles.current())

    @app.put("/admin/api/profile/draft")
    async def save_profile(body: _DraftWrite, request: Request) -> JSONResponse:
        key = await require_write(request)
        return JSONResponse(
            await profiles.change("draft", body.profile, body.expected_version, key)
        )

    @app.post("/admin/api/profile/publish")
    async def publish_profile(body: _ProfileWrite, request: Request) -> JSONResponse:
        key = await require_write(request)
        return JSONResponse(await profiles.change("publish", None, body.expected_version, key))

    @app.post("/admin/api/profile/rollback")
    async def rollback_profile(body: _RollbackWrite, request: Request) -> JSONResponse:
        key = await require_write(request)
        return JSONResponse(
            await profiles.change(
                "rollback", None, body.expected_version, key, body.release_version
            )
        )

    @app.get("/admin/api/profile/releases")
    async def profile_history(
        request: Request,
        limit: int = Query(default=20, ge=1, le=50),
        before: int | None = Query(default=None, gt=0, le=9223372036854775807),
    ) -> JSONResponse:
        await session(request)
        return JSONResponse(await profiles.history(limit, before))

    @app.get("/admin/api/profile/releases/{version}")
    async def profile_release(version: int, request: Request) -> JSONResponse:
        await session(request)
        return JSONResponse(await profiles.release(version))

    frontend = (
        frontend_dir
        if frontend_dir is not None
        else Path(__file__).resolve().parents[2] / "dashboard" / "dist"
    )
    if (frontend / "index.html").is_file():
        app.mount("/admin", StaticFiles(directory=frontend, html=True), name="admin-ui")
    else:

        @app.get("/admin/")
        async def missing_frontend() -> Response:
            return Response(
                "管理页面未构建，请先构建 dashboard。", status_code=503, media_type="text/plain"
            )

    return app
