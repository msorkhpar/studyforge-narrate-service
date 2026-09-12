"""`narrate.config` -- defaults, overrides, and refusals that quote nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from narrate.config import ConfigError, from_environment


def test_the_defaults_are_loopback_and_a_relative_artifact_directory():
    config = from_environment({})
    assert config.bind == "127.0.0.1"
    assert config.port == 8870
    assert config.artifact_dir == Path("artifacts")
    assert config.voice == "am_liam"
    assert config.chunk_chars == 1800


def test_the_default_binds_loopback_and_not_every_interface():
    """⛔ The service has no authentication of its own.

    Publishing it on every interface is a decision a deployment makes
    explicitly. It must never be what happens by leaving a setting alone.
    """
    assert from_environment({}).bind == "127.0.0.1"
    assert from_environment({}).bind != "0.0.0.0"


def test_every_setting_can_be_overridden():
    config = from_environment({
        "NARRATE_ENGINE_URL": "http://engine:8880/v1/",
        "NARRATE_ARTIFACT_DIR": "/var/lib/narrate/artifacts",
        "NARRATE_BIND": "0.0.0.0",
        "NARRATE_PORT": "9000",
        "NARRATE_VOICE": "af_bella",
        "NARRATE_CHUNK_CHARS": "500",
        "NARRATE_TIMEOUT_SECONDS": "42.5",
    })
    assert config.engine_url == "http://engine:8880/v1"
    assert config.artifact_dir == Path("/var/lib/narrate/artifacts")
    assert config.bind == "0.0.0.0"
    assert config.port == 9000
    assert config.voice == "af_bella"
    assert config.chunk_chars == 500
    assert config.timeout == 42.5


def test_an_empty_value_falls_back_to_the_default():
    config = from_environment({"NARRATE_PORT": "", "NARRATE_VOICE": ""})
    assert config.port == 8870
    assert config.voice == "am_liam"


@pytest.mark.parametrize("name,value", [
    ("NARRATE_PORT", "not-a-number"),
    ("NARRATE_PORT", "0"),
    ("NARRATE_PORT", "-1"),
    ("NARRATE_PORT", "70000"),
    ("NARRATE_CHUNK_CHARS", "12"),
    ("NARRATE_CHUNK_CHARS", "nonsense"),
    ("NARRATE_TIMEOUT_SECONDS", "0"),
    ("NARRATE_TIMEOUT_SECONDS", "-5"),
    ("NARRATE_TIMEOUT_SECONDS", "soon"),
])
def test_an_unusable_setting_is_refused(name, value):
    with pytest.raises(ConfigError):
        from_environment({name: value})


@pytest.mark.parametrize("name", [
    "NARRATE_PORT", "NARRATE_CHUNK_CHARS", "NARRATE_TIMEOUT_SECONDS",
])
def test_a_refusal_names_the_variable_and_never_its_value(name):
    """⛔ An environment variable is exactly where an identifier turns up.

    A refusal that echoed the value would copy it into the log an operator
    then pastes somewhere. The message names the variable and what is
    permitted; the value never appears.
    """
    poison = "profile-1234567890-home-dir"
    with pytest.raises(ConfigError) as raised:
        from_environment({name: poison})
    message = str(raised.value)
    assert name in message
    assert poison not in message
    assert "1234567890" not in message
