import pytest
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import create_async_engine
from test_admin_auth import PASSWORD, client

PROFILE = {
    "name": "青禾",
    "aliases": ["小青"],
    "personality": "合成测试人设",
    "participation_style": "有合适话题再接话",
    "reply_style": "简短自然",
}


@pytest.fixture
async def admin(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, PasswordHash.recommended().hash(PASSWORD)) as http:
            response = await http.post("/admin/api/login", json={"password": PASSWORD})
            http.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            yield http
    finally:
        await engine.dispose()


async def test_draft_and_publication_are_separate(admin):
    initial = await admin.get("/admin/api/profile")
    assert initial.status_code == 200
    assert initial.json() == {"version": 0, "draft": None, "published": None}
    saved = await admin.put(
        "/admin/api/profile/draft",
        json={"expected_version": 0, "profile": PROFILE},
        headers={"Idempotency-Key": "save-1"},
    )
    assert saved.status_code == 200
    assert saved.json() == {"version": 1, "draft": PROFILE, "published": None}
    published = await admin.post(
        "/admin/api/profile/publish",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "publish-1"},
    )
    assert published.status_code == 200
    assert published.json()["published"] == {"version": 1, "profile": PROFILE}
    changed = {**PROFILE, "name": "晚晴"}
    assert (
        await admin.put(
            "/admin/api/profile/draft",
            json={"expected_version": 2, "profile": changed},
            headers={"Idempotency-Key": "save-2"},
        )
    ).status_code == 200
    current = (await admin.get("/admin/api/profile")).json()
    assert current["draft"]["name"] == "晚晴"
    assert current["published"]["profile"]["name"] == "青禾"


async def test_concurrent_edit_rejects_stale_version(admin):
    import asyncio

    results = await asyncio.gather(
        *[
            admin.put(
                "/admin/api/profile/draft",
                json={"expected_version": 0, "profile": {**PROFILE, "name": name}},
                headers={"Idempotency-Key": name},
            )
            for name in ("first", "second")
        ]
    )
    assert sorted(response.status_code for response in results) == [200, 409]
    winner = next(response.json() for response in results if response.status_code == 200)
    assert (await admin.get("/admin/api/profile")).json() == winner


async def test_idempotent_retry_survives_restart_and_rejects_key_reuse(database_url):
    hashed = PasswordHash.recommended().hash(PASSWORD)
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, hashed) as http:
            login = (await http.post("/admin/api/login", json={"password": PASSWORD})).json()
            token = http.cookies.get("xiaolv_admin")
            headers = {"X-CSRF-Token": login["csrf_token"], "Idempotency-Key": "save-once"}
            body = {"expected_version": 0, "profile": PROFILE}
            saved = await http.put("/admin/api/profile/draft", json=body, headers=headers)
            published = await http.post(
                "/admin/api/profile/publish",
                json={"expected_version": 1},
                headers={**headers, "Idempotency-Key": "publish-once"},
            )
            assert published.status_code == 200
    finally:
        await engine.dispose()
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with client(engine, hashed) as restarted:
            restarted.cookies.set("xiaolv_admin", token)
            replay = await restarted.put("/admin/api/profile/draft", json=body, headers=headers)
            assert replay.status_code == 200
            assert replay.json() == saved.json()
            conflict = await restarted.put(
                "/admin/api/profile/draft",
                json={"expected_version": 2, "profile": {**PROFILE, "name": "different"}},
                headers=headers,
            )
            assert conflict.status_code == 409
            assert conflict.json()["detail"] == "idempotency_conflict"
            assert (await restarted.get("/admin/api/profile")).json() == published.json()
    finally:
        await engine.dispose()


async def test_rollback_creates_new_release_without_changing_history_or_draft(admin):
    await admin.put(
        "/admin/api/profile/draft",
        json={"expected_version": 0, "profile": PROFILE},
        headers={"Idempotency-Key": "draft-a"},
    )
    await admin.post(
        "/admin/api/profile/publish",
        json={"expected_version": 1},
        headers={"Idempotency-Key": "release-a"},
    )
    changed = {**PROFILE, "name": "晚晴"}
    await admin.put(
        "/admin/api/profile/draft",
        json={"expected_version": 2, "profile": changed},
        headers={"Idempotency-Key": "draft-b"},
    )
    await admin.post(
        "/admin/api/profile/publish",
        json={"expected_version": 3},
        headers={"Idempotency-Key": "release-b"},
    )
    rollback = await admin.post(
        "/admin/api/profile/rollback",
        json={"expected_version": 4, "release_version": 1},
        headers={"Idempotency-Key": "rollback-a"},
    )
    assert rollback.status_code == 200
    assert rollback.json() == {
        "version": 5,
        "draft": changed,
        "published": {"version": 3, "profile": PROFILE},
    }
    for version, profile in ((1, PROFILE), (2, changed), (3, PROFILE)):
        response = await admin.get(f"/admin/api/profile/releases/{version}")
        assert response.status_code == 200
        assert response.json() == {"version": version, "profile": profile}


async def test_invalid_profile_reports_field_without_echoing_values(admin):
    response = await admin.put(
        "/admin/api/profile/draft",
        json={
            "expected_version": 0,
            "profile": {**PROFILE, "name": "", "personality": "PRIVATE-SENTINEL"},
        },
        headers={"Idempotency-Key": "invalid-draft"},
    )
    assert response.status_code == 422
    assert "PRIVATE-SENTINEL" not in response.text
    assert ["body", "profile", "name"] in [error["loc"] for error in response.json()["errors"]]
    assert (await admin.get("/admin/api/profile")).json()["version"] == 0


async def test_profile_writes_require_session_csrf_and_idempotency_key(admin):
    body = {"expected_version": 0, "profile": PROFILE}
    assert (await admin.put("/admin/api/profile/draft", json=body)).status_code == 422
    admin.headers.pop("X-CSRF-Token")
    assert (
        await admin.put(
            "/admin/api/profile/draft", json=body, headers={"Idempotency-Key": "denied"}
        )
    ).status_code == 403
    assert (await admin.get("/admin/api/profile")).json()["version"] == 0
    admin.cookies.clear()
    assert (
        await admin.put(
            "/admin/api/profile/draft", json=body, headers={"Idempotency-Key": "denied"}
        )
    ).status_code == 401
    assert (await admin.get("/admin/api/profile")).status_code == 401


async def test_missing_draft_or_release_never_changes_state(admin):
    assert (
        await admin.post(
            "/admin/api/profile/publish",
            json={"expected_version": 0},
            headers={"Idempotency-Key": "no-draft"},
        )
    ).status_code == 409
    assert (
        await admin.post(
            "/admin/api/profile/rollback",
            json={"expected_version": 0, "release_version": 999},
            headers={"Idempotency-Key": "no-release"},
        )
    ).status_code == 404
    assert (await admin.get("/admin/api/profile")).json() == {
        "version": 0,
        "draft": None,
        "published": None,
    }


async def test_release_history_is_authenticated_and_cursor_pagination_is_stable(admin):
    empty = await admin.get("/admin/api/profile/releases")
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "next_before": None}
    for version in range(1, 4):
        await admin.put(
            "/admin/api/profile/draft",
            json={
                "expected_version": (version - 1) * 2,
                "profile": {**PROFILE, "name": f"名字{version}"},
            },
            headers={"Idempotency-Key": f"history-draft-{version}"},
        )
        await admin.post(
            "/admin/api/profile/publish",
            json={"expected_version": version * 2 - 1},
            headers={"Idempotency-Key": f"history-publish-{version}"},
        )
    first = (await admin.get("/admin/api/profile/releases?limit=2")).json()
    assert [item["version"] for item in first["items"]] == [3, 2]
    assert first["next_before"] == 2
    assert first["items"][0]["name"] == "名字3"
    assert set(first["items"][0]) == {"version", "name", "created_at"}
    from datetime import datetime

    assert datetime.fromisoformat(first["items"][0]["created_at"]).utcoffset() is not None
    await admin.post(
        "/admin/api/profile/publish",
        json={"expected_version": 6},
        headers={"Idempotency-Key": "new-release-between-pages"},
    )
    second = (await admin.get("/admin/api/profile/releases?limit=2&before=2")).json()
    assert [item["version"] for item in second["items"]] == [1]
    assert second["next_before"] is None
    for query in ("limit=0", "limit=51", "before=0", "before=abc", "before=9223372036854775808"):
        assert (await admin.get("/admin/api/profile/releases?" + query)).status_code == 422
    admin.cookies.clear()
    assert (await admin.get("/admin/api/profile/releases")).status_code == 401
