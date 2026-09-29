from datetime import UTC, datetime, timedelta

import pytest
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import create_async_engine
from test_admin_auth import PASSWORD, client

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.storage.postgres_delivery import PostgresDeliveryLedger


@pytest.fixture(scope="module")
def password_hash():
    return PasswordHash.recommended().hash(PASSWORD)


async def test_admin_disable_survives_registration_and_invalidates_old_turn(
    database_url, password_hash
):
    from xiaolv.storage.conversation_control import ConversationControl

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        control = ConversationControl(engine)
        await control.register(["qq:1:group:2"])
        ledger = PostgresDeliveryLedger(engine)
        old_epoch = await ledger.start_turn("qq:1:group:2")
        async with client(engine, password_hash) as http:
            login = await http.post("/admin/api/login", json={"password": PASSWORD})
            http.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            initial = await http.get("/admin/api/conversations")
            assert initial.status_code == 200
            assert initial.json()["items"] == [
                {"conversation_id": "qq:1:group:2", "enabled": True, "version": 0}
            ]
            body = {"enabled": False, "expected_version": 0}
            headers = {"Idempotency-Key": "disable-1"}
            changed = await http.put(
                "/admin/api/conversations/qq:1:group:2", json=body, headers=headers
            )
            assert changed.status_code == 200
            assert changed.json() == {
                "conversation_id": "qq:1:group:2",
                "enabled": False,
                "version": 1,
            }
            await ConversationControl(engine).register(["qq:1:group:2"])
            assert (await http.get("/admin/api/conversations")).json()["items"] == [changed.json()]
            assert (
                await http.put("/admin/api/conversations/qq:1:group:2", json=body, headers=headers)
            ).json() == changed.json()
            restored = await http.put(
                "/admin/api/conversations/qq:1:group:2",
                json={"enabled": True, "expected_version": 1},
                headers={"Idempotency-Key": "restore-1"},
            )
            assert restored.status_code == 200

        class Platform:
            async def send(self, request):
                raise AssertionError("old reply must not send")

        delivery = DeliveryService(Platform(), ledger=ledger)
        request = DeliveryRequest(
            "old", "qq:1:group:2", datetime.now(UTC) + timedelta(seconds=30), old_epoch, "旧回复"
        )
        assert await delivery.deliver(request) == "superseded"
    finally:
        await engine.dispose()


async def test_disabled_conversation_rejects_new_epoch_at_final_send(database_url, password_hash):
    from xiaolv.storage.conversation_control import ConversationControl

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        await ConversationControl(engine).register(["qq:1:group:2"])
        async with client(engine, password_hash) as http:
            login = await http.post("/admin/api/login", json={"password": PASSWORD})
            http.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            changed = await http.put(
                "/admin/api/conversations/qq:1:group:2",
                json={"enabled": False, "expected_version": 0},
                headers={"Idempotency-Key": "disable"},
            )
            assert changed.status_code == 200

        class Platform:
            def __init__(self):
                self.sent = []

            async def send(self, request):
                self.sent.append(request)
                return "confirmed"

        platform = Platform()
        ledger = PostgresDeliveryLedger(engine)
        epoch = await ledger.start_turn("qq:1:group:2")
        delivery = DeliveryService(platform, ledger=ledger)
        request = DeliveryRequest(
            "new", "qq:1:group:2", datetime.now(UTC) + timedelta(seconds=30), epoch, "新回复"
        )
        assert await delivery.deliver(request) == "not_sent"
        assert platform.sent == []
    finally:
        await engine.dispose()


async def test_control_http_auth_conflicts_and_pagination(database_url, password_hash):
    import asyncio

    from xiaolv.storage.conversation_control import ConversationControl

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        await ConversationControl(engine).register(["qq:1:group:2", "qq:1:group:3"])
        async with client(engine, password_hash) as http:
            assert (await http.get("/admin/api/conversations")).status_code == 401
            login = await http.post("/admin/api/login", json={"password": PASSWORD})
            path = "/admin/api/conversations/qq:1:group:2"
            body = {"enabled": False, "expected_version": 0}
            assert (
                await http.put(path, json=body, headers={"Idempotency-Key": "x"})
            ).status_code == 403
            http.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            assert (await http.put(path, json=body)).status_code == 422
            assert (
                await http.put(
                    path,
                    json=body,
                    headers={"Idempotency-Key": "x", "Origin": "https://evil.example"},
                )
            ).status_code == 403
            results = await asyncio.gather(
                *[http.put(path, json=body, headers={"Idempotency-Key": key}) for key in ("a", "b")]
            )
            assert sorted(r.status_code for r in results) == [200, 409]
            key = "a" if results[0].status_code == 200 else "b"
            assert (
                await http.put(
                    path,
                    json={"enabled": True, "expected_version": 1},
                    headers={"Idempotency-Key": key},
                )
            ).status_code == 409
            assert (
                await http.put(
                    "/admin/api/conversations/unknown",
                    json=body,
                    headers={"Idempotency-Key": "unknown"},
                )
            ).status_code == 404
            assert (
                await http.put(
                    path,
                    json={"enabled": "false", "expected_version": 1},
                    headers={"Idempotency-Key": "bad"},
                )
            ).status_code == 422
            page = (await http.get("/admin/api/conversations?limit=1")).json()
            assert len(page["items"]) == 1
            second = (
                await http.get(
                    "/admin/api/conversations", params={"limit": 1, "after": page["next_after"]}
                )
            ).json()
            assert second["items"][0]["conversation_id"] == "qq:1:group:3"
            assert second["items"][0]["enabled"] is True
            assert second["next_after"] is None
            assert (await http.get("/admin/api/conversations?limit=51")).status_code == 422
    finally:
        await engine.dispose()
