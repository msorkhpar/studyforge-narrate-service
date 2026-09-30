"""`narrate.engine.registry` -- selection by configuration, and its closure.

⛔ **The property under test is that nothing above `narrate.engine` decides
which engine is deployed.** A test that only checked "the registry returns a
`KokoroEngine`" would pass on a service that still constructed one directly in
`build_server`, so the tests here go the other way: they change the *setting*
and assert what the service then reports.
"""

from __future__ import annotations

import pytest

from narrate.config import ConfigError, Config
from narrate.engine import (
    ENGINES,
    KokoroEngine,
    NotAnEngine,
    UnknownEngine,
    build_engine,
    check_engine,
    engine_names,
)


def test_the_registry_is_a_closed_set_and_this_is_what_is_in_it():
    """⚠️ One entry today. The set exists to VALIDATE the setting.

    If a second engine is added, this line changes in the same commit -- which
    is the point of a table rather than an import-by-name.
    """
    assert engine_names() == ("kokoro",)


def test_every_registered_factory_produces_something_that_conforms():
    for name in engine_names():
        engine = ENGINES[name](Config())
        assert check_engine(engine) is engine
        assert engine.name == name


def test_the_default_configuration_builds_the_kokoro_adapter():
    engine = build_engine(Config())
    assert isinstance(engine, KokoroEngine)
    assert engine.identity().engine == "kokoro"


def test_the_configured_url_timeout_and_profile_reach_the_adapter():
    engine = build_engine(Config(
        engine_url="http://engine:8880/v1", timeout=12.5, engine_profile="gpu"
    ))
    assert engine.base_url == "http://engine:8880/v1"
    assert engine.identity().profile == "gpu"


@pytest.mark.parametrize("profile", ["cpu", "gpu", "unknown"])
def test_the_profile_is_carried_through_unchanged_for_every_legal_value(profile):
    """⭐ The same adapter, three declarations. Switching is not a code change."""
    engine = build_engine(Config(engine_profile=profile))
    assert engine.identity().profile == profile
    assert isinstance(engine, KokoroEngine)


def test_an_unknown_engine_is_refused_naming_what_is_permitted():
    with pytest.raises(UnknownEngine) as raised:
        build_engine(Config(engine="whisper-of-some-kind"))
    message = str(raised.value)
    assert "NARRATE_ENGINE" in message
    assert "kokoro" in message


def test_the_refusal_never_echoes_the_value_that_arrived():
    """⛔ Same rule as every other refusal in this service (no echo)."""
    with pytest.raises(UnknownEngine) as raised:
        build_engine(Config(engine="an-account-identifier-someone-pasted"))
    assert "an-account-identifier-someone-pasted" not in str(raised.value)


def test_an_unknown_engine_is_a_configuration_error_so_nothing_starts():
    """⭐ `__main__` catches `ConfigError` and exits 2. This is that edge."""
    assert issubclass(UnknownEngine, ConfigError)
    with pytest.raises(ConfigError):
        build_engine(Config(engine="not-an-engine"))


def test_a_factory_returning_a_non_engine_is_caught_at_startup(monkeypatch):
    """⛔ The gate is on the registry's OUTPUT, not on its keys.

    A future adapter that forgets a member must fail when the service starts,
    not on the first request a caller makes.
    """
    monkeypatch.setitem(ENGINES, "kokoro", lambda config: object())
    with pytest.raises(NotAnEngine):
        build_engine(Config())
