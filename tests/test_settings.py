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
        "XIAOLV_QQ_SELF_ID": "10000",
        "XIAOLV_MODEL_PROVIDER": "synthetic-provider",
        "XIAOLV_MODEL_PRICE_VERSION": "synthetic-v1",
        "XIAOLV_MODEL_INPUT_CNY_PER_MILLION": "1",
        "XIAOLV_MODEL_OUTPUT_CNY_PER_MILLION": "2",
        "XIAOLV_MONTHLY_EXTERNAL_BUDGET_CNY": "60",
        "XIAOLV_MONTHLY_FIXED_COST_CNY": "100",
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


def test_live_configuration_has_no_enabled_conversations_by_default():
    settings = load_settings(live_environment())
    assert settings.qq_self_id == 10000
    assert settings.enabled_group_ids == ()
    assert settings.enabled_private_ids == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"XIAOLV_MODEL_CACHED_INPUT_CNY_PER_MILLION": "2"},
    ],
)
def test_cached_input_price_cannot_exceed_normal_price(changes):
    from xiaolv.settings import ConfigError

    env = live_environment()
    env.update(changes)
    with pytest.raises(ConfigError):
        load_settings(env)


async def test_enabled_conversations_require_explicit_json_integer_ids():
    env = live_environment()
    env.update(
        {"XIAOLV_ENABLED_GROUP_IDS": "[20000,30000]", "XIAOLV_ENABLED_PRIVATE_IDS": "[10001]"}
    )
    settings = load_settings(env)
    assert settings.enabled_group_ids == (20000, 30000)
    assert settings.enabled_private_ids == (10001,)


@pytest.mark.parametrize(
    "value", ["[true]", "[0]", "[1.5]", '["20000"]', '"*"', "[20000,", '{"group":20000}']
)
def test_unsafe_conversation_allowlist_is_rejected(value):
    from xiaolv.settings import ConfigError

    env = live_environment()
    env["XIAOLV_ENABLED_GROUP_IDS"] = value
    with pytest.raises(ConfigError):
        load_settings(env)


@pytest.mark.parametrize(
    "key",
    [
        "QQ_SELF_ID",
        "MODEL_PROVIDER",
        "MODEL_PRICE_VERSION",
        "MODEL_INPUT_CNY_PER_MILLION",
        "MODEL_OUTPUT_CNY_PER_MILLION",
        "MONTHLY_EXTERNAL_BUDGET_CNY",
    ],
)
def test_live_requires_every_identity_and_budget_field(key):
    from xiaolv.settings import ConfigError

    env = live_environment()
    env.pop("XIAOLV_" + key)
    with pytest.raises(ConfigError):
        load_settings(env)


def test_model_budget_is_independent_of_hosting_cost_and_has_no_200_cny_cap():
    from decimal import Decimal

    env = live_environment()
    env["XIAOLV_MONTHLY_EXTERNAL_BUDGET_CNY"] = "1000"
    env["XIAOLV_MONTHLY_FIXED_COST_CNY"] = "250"
    settings = load_settings(env)
    assert settings.monthly_external_budget_cny == Decimal(1000)
    assert settings.monthly_fixed_cost_cny == Decimal(250)


def test_live_startup_does_not_require_hosting_cost_estimate():
    env = live_environment()
    env.pop("XIAOLV_MONTHLY_FIXED_COST_CNY")
    settings = load_settings(env)
    assert settings.mode == "live"
    assert settings.monthly_fixed_cost_cny is None


@pytest.mark.parametrize(
    "profile",
    [
        {"name": "   "},
        {"name": "x" * 65},
        {"aliases": "not-a-list"},
        {"aliases": [""]},
        {"aliases": ["a"] * 33},
        {"personality": "x" * 2001},
        {"reply_style": "x" * 1001},
        {"participation_style": "x" * 1001},
        {"name": "synthetic-private-profile", "permissions": "admin"},
    ],
)
def test_invalid_persona_is_rejected_without_echoing_profile(profile):
    import json

    from xiaolv.settings import ConfigError

    with pytest.raises(ConfigError) as raised:
        load_settings({"XIAOLV_BOT_PROFILE": json.dumps(profile)})
    assert "synthetic-private-profile" not in str(raised.value)
    assert "bot_profile" in str(raised.value)


def test_persona_json_syntax_error_is_sanitized():
    from xiaolv.settings import ConfigError

    with pytest.raises(ConfigError) as raised:
        load_settings({"XIAOLV_BOT_PROFILE": '{"name":"private-profile"'})
    assert "private-profile" not in str(raised.value)


def test_logging_output_and_rotation_are_configurable():
    settings = load_settings(
        {
            "XIAOLV_LOG_LEVEL": "DEBUG",
            "XIAOLV_LOG_FILE": "/tmp/synthetic.log",
            "XIAOLV_LOG_MAX_BYTES": "4096",
            "XIAOLV_LOG_BACKUP_COUNT": "2",
        }
    )
    assert settings.log_level == "DEBUG"
    assert str(settings.log_file) == "/tmp/synthetic.log"
    assert settings.log_max_bytes == 4096
    assert settings.log_backup_count == 2


@pytest.mark.parametrize(
    "key,value",
    [
        ("LOG_LEVEL", "VERBOSE"),
        ("LOG_MAX_BYTES", "0"),
        ("LOG_BACKUP_COUNT", "0"),
        ("LOG_BACKUP_COUNT", "101"),
    ],
)
def test_invalid_log_settings_are_rejected(key, value):
    from xiaolv.settings import ConfigError

    with pytest.raises(ConfigError):
        load_settings({"XIAOLV_" + key: value})
