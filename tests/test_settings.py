import pytest

from xiaolv.settings import load_settings


def test_empty_environment_defaults_to_local_replay():
    settings = load_settings({})
    assert settings.mode == "replay"
    assert settings.chat_ttl_seconds == 45
    assert settings.queue_max_age_seconds == 10
    assert settings.model_concurrency == 2
    assert settings.max_reply_chars == 200


def test_environment_can_override_runtime_limits():
    settings = load_settings({"XIAOLV_CHAT_TTL_SECONDS": "90", "XIAOLV_MODEL_CONCURRENCY": "3"})
    assert settings.chat_ttl_seconds == 90
    assert settings.model_concurrency == 3


@pytest.mark.parametrize(
    "key,value",
    [
        ("CHAT_TTL_SECONDS", "0"),
        ("CHAT_TTL_SECONDS", "nan"),
        ("CHAT_TTL_SECONDS", "inf"),
        ("MODEL_CONCURRENCY", "-1"),
        ("MAX_REPLY_CHARS", "oops"),
        ("QUEUE_MAX_AGE_SECONDS", "46"),
    ],
)
def test_invalid_limits_are_rejected_without_echoing_values(key, value):
    from xiaolv.settings import ConfigError

    with pytest.raises(ConfigError):
        load_settings({f"XIAOLV_{key}": value})


def test_live_mode_requires_explicit_services():
    from xiaolv.settings import ConfigError

    with pytest.raises(ConfigError):
        load_settings({"XIAOLV_MODE": "live"})


def live_environment():
    return {
        "XIAOLV_MODE": "live",
        "XIAOLV_DATABASE_URL": "postgresql+psycopg://tester:fake-db-password@localhost/xiaolv_test",
        "XIAOLV_MODEL_BASE_URL": "https://model.example.test/v1",
        "XIAOLV_MODEL_API_KEY": "fake-model-key",
        "XIAOLV_MODEL_ID": "configured-model",
        "XIAOLV_ONEBOT_URL": "ws://localhost:3001",
        "XIAOLV_ONEBOT_TOKEN": "fake-onebot-token",
    }


def test_explicit_live_config_redacts_secrets():
    settings = load_settings(live_environment())
    assert settings.mode == "live"
    assert settings.model_api_key.get_secret_value() == "fake-model-key"
    output = repr(settings) + settings.model_dump_json()
    for secret in ("fake-db-password", "fake-model-key", "fake-onebot-token"):
        assert secret not in output


@pytest.mark.parametrize("field", ["DATABASE_URL", "MODEL_BASE_URL", "ONEBOT_URL"])
def test_invalid_service_url_does_not_leak_credentials(field):
    from xiaolv.settings import ConfigError

    env = live_environment()
    env[f"XIAOLV_{field}"] = "invalid://user:do-not-log-this@example.test/path"
    with pytest.raises(ConfigError) as raised:
        load_settings(env)
    assert "do-not-log-this" not in str(raised.value)


def test_unknown_prefixed_key_is_rejected_but_other_environment_is_ignored():
    from xiaolv.settings import ConfigError

    assert load_settings({"UNRELATED_SECRET": "not-used"}).mode == "replay"
    with pytest.raises(ConfigError):
        load_settings({"XIAOLV_MODLE_ID": "typo"})
