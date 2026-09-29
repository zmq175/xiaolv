# ruff: noqa: F811 -- pytest fixture imported for registration and requested by name
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import create_async_engine
from test_profile_publication import PROFILE, admin  # noqa: F401 - shared HTTP fixture

from xiaolv.application.delivery import DeliveryService
from xiaolv.domain.bot_profile import BotProfile
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime

NOW = datetime(2026, 9, 29, 8, tzinfo=UTC)


def candidate():
    return ConversationCandidate("chat-1", "event-1", "聊什么", NOW + timedelta(seconds=45), 3)


def setup(model, **kwargs):
    class Platform:
        def __init__(self):
            self.sent = []

        async def send(self, request):
            self.sent.append(request)
            return "confirmed"

    platform = Platform()
    clock = lambda: NOW
    delivery = DeliveryService(platform, clock, lambda _: 3)
    return TextRuntime(model, delivery, clock, **kwargs), platform


async def save_publish(http, profile, revision, key):
    saved = await http.put(
        "/admin/api/profile/draft",
        json={"expected_version": revision, "profile": profile},
        headers={"Idempotency-Key": key + "-draft"},
    )
    assert saved.status_code == 200
    published = await http.post(
        "/admin/api/profile/publish",
        json={"expected_version": revision + 1},
        headers={"Idempotency-Key": key + "-publish"},
    )
    assert published.status_code == 200
    return published.json()


async def test_publishing_during_turn_preserves_snapshot_until_next_turn(admin, database_url):
    from xiaolv.storage.published_profile import PublishedProfiles

    await save_publish(admin, PROFILE, 0, "first")
    prompts = []

    class Generator:
        async def generate(self, *, instructions, context, schema, expires_at):
            prompts.append(instructions)
            if "action" in schema["properties"]:
                if len(prompts) == 1:
                    await save_publish(admin, {**PROFILE, "name": "晚晴"}, 2, "second")
                return '{"action":"respond"}'
            return json.dumps({"text": "合成回复"})

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        runtime, platform = setup(
            ChatCompletionsModel(Generator(), profile=BotProfile(name="启动名字")),
            profile_loader=PublishedProfiles(engine, BotProfile(name="启动名字")).load,
        )
        assert await runtime.run(candidate()) == "confirmed"
        assert all('"name": "青禾"' in value for value in prompts)
        assert (
            await runtime.run(replace(candidate(), event_id="next", conversation_id="chat-2"))
            == "confirmed"
        )
        assert all('"name": "晚晴"' in value for value in prompts[2:])
        assert len(platform.sent) == 2
    finally:
        await engine.dispose()


async def test_draft_startup_rollback_and_selected_version_log(admin, database_url, caplog):
    import logging

    from xiaolv.storage.published_profile import PublishedProfiles

    prompts = []

    class Generator:
        async def generate(self, *, instructions, **kwargs):
            prompts.append(instructions)
            return '{"action":"silence"}'

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        runtime, platform = setup(
            ChatCompletionsModel(Generator()),
            profile_loader=PublishedProfiles(engine, BotProfile(name="启动名字")).load,
        )
        caplog.set_level(logging.INFO)
        await admin.put(
            "/admin/api/profile/draft",
            json={"expected_version": 0, "profile": PROFILE},
            headers={"Idempotency-Key": "draft-only"},
        )
        assert await runtime.run(candidate()) == "silence"
        assert '"name": "启动名字"' in prompts[-1]
        await admin.post(
            "/admin/api/profile/publish",
            json={"expected_version": 1},
            headers={"Idempotency-Key": "publish-first"},
        )
        await save_publish(admin, {**PROFILE, "name": "晚晴"}, 2, "second")
        rolled = await admin.post(
            "/admin/api/profile/rollback",
            json={"expected_version": 4, "release_version": 1},
            headers={"Idempotency-Key": "rollback"},
        )
        assert rolled.status_code == 200
        assert await runtime.run(replace(candidate(), event_id="after-rollback")) == "silence"
        assert '"name": "青禾"' in prompts[-1]
        selected = [
            r.fields for r in caplog.records if getattr(r, "event", None) == "profile_selected"
        ]
        assert selected == [
            {"turn_id": "event-1", "profile_source": "startup", "profile_version": "none"},
            {"turn_id": "after-rollback", "profile_source": "published", "profile_version": "3"},
        ]
        from xiaolv.observability.logging_setup import LineFormatter

        lines = [
            LineFormatter().format(r)
            for r in caplog.records
            if getattr(r, "event", None) == "profile_selected"
        ]
        assert "||profile_version=3||" in lines[-1]
        assert PROFILE["personality"] not in caplog.text
        assert platform.sent == []
    finally:
        await engine.dispose()
