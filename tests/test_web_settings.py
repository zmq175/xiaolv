import json

from test_settings import live_environment

from xiaolv.settings import load_settings


def environment(config=None):
    return {
        **live_environment(),
        "XIAOLV_ENABLED_GROUP_IDS": "[20000]",
        "XIAOLV_WEB": json.dumps(
            config
            if config is not None
            else {
                "api_key": "synthetic-web-secret",
                "conversations": ["qq:10000:group:20000"],
            }
        ),
    }


def test_web_tools_are_disabled_by_default_and_explicitly_scoped():
    assert load_settings({}).web is None
    web = load_settings(environment()).web
    assert web.conversations == ("qq:10000:group:20000",)
    assert web.monthly_credit_limit == 900
    assert (web.max_tool_rounds, web.max_tool_calls) == (3, 4)
    assert web.max_search_results == 5 and web.max_page_tokens == 4000
    assert "synthetic-web-secret" not in repr(web)


import pytest


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_key", ""),
        ("api_key", "synthetic-web-secret\n"),
        ("conversations", []),
        ("conversations", ["qq:10000:group:30000"]),
        ("conversations", ["qq:10000:group:20000", "qq:10000:group:20000"]),
        ("monthly_credit_limit", 0),
        ("monthly_credit_limit", 901),
        ("monthly_credit_limit", True),
        ("max_tool_rounds", 4),
        ("max_tool_calls", 5),
        ("max_tool_calls", 1),
        ("max_search_results", 6),
        ("max_page_tokens", 8001),
        ("call_timeout_seconds", float("inf")),
        ("call_timeout_seconds", True),
        ("call_timeout_seconds", 0),
        ("concurrency", 0),
        ("auto_parameters", True),
    ],
)
def test_invalid_web_grants_and_limits_fail_without_exposing_secret(field, value):
    from xiaolv.settings import ConfigError

    config = {"api_key": "synthetic-web-secret", "conversations": ["qq:10000:group:20000"]}
    config[field] = value
    with pytest.raises(ConfigError) as caught:
        load_settings(environment(config))
    assert "synthetic-web-secret" not in str(caught.value)


async def test_unwired_web_configuration_does_not_silently_start_live_service():
    import asyncio

    from xiaolv.live import run_live
    from xiaolv.settings import ConfigError

    configured = load_settings(
        {
            **environment(),
            "XIAOLV_DATABASE_URL": "postgresql+psycopg:///xiaolv_test?host=/tmp/xiaolv-missing-web-test-db",
        }
    )
    with pytest.raises(ConfigError, match="web"):
        await asyncio.wait_for(run_live(configured, asyncio.Event()), 1)
