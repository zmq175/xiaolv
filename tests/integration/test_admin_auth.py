import httpx2 as httpx
import pytest
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import create_async_engine

from xiaolv.admin import AdminConfig, create_admin_app

ORIGIN = "https://admin.example"
PASSWORD = "synthetic-admin-password"


@pytest.fixture(scope="module")
def password_hash():
    return PasswordHash.recommended().hash(PASSWORD)


def client(engine, password_hash, **options):
    app = create_admin_app(
        engine, AdminConfig(password_hash=password_hash, origin=ORIGIN, **options)
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )


async def test_login_cookie_survives_application_recreation(database_url, password_hash):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, password_hash) as browser:
            assert (await browser.get("/admin/api/session")).status_code == 401
            response = await browser.post("/admin/api/login", json={"password": PASSWORD})
            assert response.status_code == 200
            cookie = response.headers["set-cookie"]
            assert "HttpOnly" in cookie and "Secure" in cookie
            assert "SameSite=strict" in cookie and "Path=/admin" in cookie
            token = browser.cookies.get("xiaolv_admin")
        async with client(engine, password_hash) as restarted:
            restarted.cookies.set("xiaolv_admin", token)
            session = await restarted.get("/admin/api/session")
            assert session.status_code == 200
            assert session.json()["authenticated"] is True
            assert session.json()["csrf_token"]
    finally:
        await engine.dispose()


async def test_logout_requires_csrf_and_revokes_stolen_cookie(database_url, password_hash):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, password_hash) as browser:
            login = await browser.post("/admin/api/login", json={"password": PASSWORD})
            token = browser.cookies.get("xiaolv_admin")
            csrf = login.json()["csrf_token"]
            assert (await browser.post("/admin/api/logout")).status_code == 403
            assert (
                await browser.post("/admin/api/logout", headers={"X-CSRF-Token": "wrong"})
            ).status_code == 403
            assert (
                await browser.post("/admin/api/logout", headers={"X-CSRF-Token": csrf})
            ).status_code == 204
        async with client(engine, password_hash) as other:
            other.cookies.set("xiaolv_admin", token)
            assert (await other.get("/admin/api/session")).status_code == 401
    finally:
        await engine.dispose()


@pytest.mark.parametrize("origin", ["", "https://other.example", "null"])
async def test_login_rejects_untrusted_origin(database_url, password_hash, origin):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, password_hash) as browser:
            response = await browser.post(
                "/admin/api/login", json={"password": PASSWORD}, headers={"Origin": origin}
            )
            assert response.status_code == 403
            assert "set-cookie" not in response.headers
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"password": "wrong"}, 401),
        ({"password": [PASSWORD]}, 422),
        ({"password": PASSWORD, "extra": PASSWORD}, 422),
    ],
)
async def test_authentication_errors_do_not_echo_secrets(
    database_url, password_hash, payload, expected
):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, password_hash) as browser:
            response = await browser.post("/admin/api/login", json=payload)
            assert response.status_code == expected
            assert PASSWORD not in response.text
            assert response.headers["cache-control"] == "no-store"
    finally:
        await engine.dispose()


async def test_expired_or_old_credential_session_is_rejected(database_url, password_hash):
    import asyncio

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, password_hash, session_seconds=1) as browser:
            login = await browser.post("/admin/api/login", json={"password": PASSWORD})
            assert login.status_code == 200
            token = browser.cookies.get("xiaolv_admin")
            async with client(engine, PasswordHash.recommended().hash("changed")) as changed:
                changed.cookies.set("xiaolv_admin", token)
                assert (await changed.get("/admin/api/session")).status_code == 401
            await asyncio.sleep(1.05)
            response = await browser.get(
                "/admin/api/session", headers={"Cookie": f"xiaolv_admin={token}"}
            )
            assert response.status_code == 401
    finally:
        await engine.dispose()


async def test_login_limit_is_atomic_and_shared_across_applications(database_url, password_hash):
    import asyncio

    engines = [create_async_engine(database_url, hide_parameters=True) for _ in range(2)]
    try:
        async with (
            client(engines[0], password_hash) as first,
            client(engines[1], password_hash) as second,
        ):
            results = await asyncio.gather(
                *[
                    (first if index % 2 else second).post(
                        "/admin/api/login", json={"password": "wrong"}
                    )
                    for index in range(8)
                ]
            )
            assert sorted(response.status_code for response in results) == [401] * 5 + [429] * 3
        async with client(engines[0], password_hash) as restarted:
            response = await restarted.post("/admin/api/login", json={"password": PASSWORD})
            assert response.status_code == 429
            assert "set-cookie" not in response.headers
    finally:
        for engine in engines:
            await engine.dispose()


@pytest.mark.parametrize(
    "origin",
    [
        "http://public.example",
        "https://admin.example/path",
        "https://user:pass@admin.example",
        "https://admin.example?key=value",
    ],
)
async def test_unsafe_admin_origin_is_rejected_at_configuration(
    database_url, password_hash, origin
):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        with pytest.raises(ValueError, match="origin"):
            create_admin_app(engine, AdminConfig(password_hash=password_hash, origin=origin))
    finally:
        await engine.dispose()
