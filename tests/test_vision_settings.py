import json

from test_settings import live_environment

from xiaolv.settings import load_settings


def vision_configuration():
    return {
        "base_url": "https://vision.example/v1",
        "api_key": "synthetic-secret",
        "model": "synthetic-vision",
        "provider": "synthetic-provider",
        "price_version": "test-v1",
        "processor_version": "caption-v1",
        "input_cny_per_million": "1",
        "output_cny_per_million": "2",
        "image_tokens": 2048,
        "window_tokens": 8192,
        "conversations": ["qq:10000:group:20000"],
    }


def environment():
    return {
        **live_environment(),
        "XIAOLV_ENABLED_GROUP_IDS": "[20000]",
        "XIAOLV_VISION": json.dumps(vision_configuration()),
    }


def test_vision_is_opt_in_and_accepts_explicit_scoped_configuration():
    assert load_settings({}).vision is None
    settings = load_settings(environment())
    assert settings.vision.conversations == ("qq:10000:group:20000",)
    assert settings.vision.image_tokens == 2048
    assert settings.vision.concurrency == 1
    assert "synthetic-secret" not in repr(settings)


import pytest


@pytest.mark.parametrize(
    "field,value",
    [
        ("base_url", "http://vision.example/v1"),
        ("base_url", "https://user:synthetic-secret@vision.example/v1"),
        ("base_url", "https://vision.example/v1?key=synthetic-secret"),
        ("base_url", "https://vision.example:0/v1"),
        ("model", " "),
        ("provider", " "),
        ("price_version", " "),
        ("processor_version", " "),
        ("api_key", "synthetic-secret\n"),
        ("conversations", []),
        ("conversations", ["qq:10000:group:99999"]),
        ("conversations", ["qq:10000:group:20000", "qq:10000:group:20000"]),
        ("cached_input_cny_per_million", "2"),
        ("image_tokens", 0),
        ("image_tokens", True),
        ("window_tokens", 1024),
    ],
)
def test_invalid_vision_configuration_is_rejected_without_exposing_credentials(field, value):
    from xiaolv.settings import ConfigError

    config = vision_configuration()
    config[field] = value
    with pytest.raises(ConfigError) as caught:
        load_settings({**environment(), "XIAOLV_VISION": json.dumps(config)})
    assert "synthetic-secret" not in str(caught.value)
