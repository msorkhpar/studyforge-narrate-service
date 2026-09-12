"""`narrate.engine.base` -- the adapter contract, and the gate that enforces it.

⭐ **The gate is what makes the contract a contract rather than a docstring.**
Every test here drives an object that is *almost* an engine, because the failure
this module exists to prevent is a `500` on the first request of a deployment
that started cleanly.
"""

from __future__ import annotations

import pytest

from narrate.engine import (
    ADAPTER_MEMBERS,
    ADAPTER_METHODS,
    EngineIdentity,
    NotAnEngine,
    check_engine,
)
from tests.support import FakeEngine


class _Almost:
    """An engine missing exactly one member, chosen by the caller."""

    def __init__(self, missing=None, not_callable=None):
        if missing != "name":
            self.name = "almost"
        for method in ADAPTER_METHODS:
            if method == missing:
                continue
            setattr(self, method, "not a function" if method == not_callable
                    else (lambda *a, **k: None))


def test_the_contract_is_five_members_and_it_is_written_down():
    """⚠️ **It was four and NS-04 made it five.** `voices()` is an engine-family
    fact, so it belongs behind this seam; the alternative was a server that
    branched on which engine was deployed, which is what `registry.py` exists
    to prevent. ⛔ **The refused POPULATION widened with it**: an object that
    satisfied the four-member contract is refused today.
    """
    assert ADAPTER_MEMBERS == ("name", "synthesize_chunk", "reachable",
                               "identity", "voices")
    assert ADAPTER_METHODS == ("synthesize_chunk", "reachable", "identity",
                               "voices")


def test_a_conforming_engine_is_returned_unchanged():
    engine = FakeEngine()
    assert check_engine(engine) is engine


@pytest.mark.parametrize("missing", ADAPTER_MEMBERS)
def test_every_missing_member_is_refused_and_named(missing):
    with pytest.raises(NotAnEngine) as raised:
        check_engine(_Almost(missing=missing))
    assert missing in str(raised.value)


@pytest.mark.parametrize("method", ADAPTER_METHODS)
def test_a_member_that_is_not_callable_is_refused(method):
    with pytest.raises(NotAnEngine) as raised:
        check_engine(_Almost(not_callable=method))
    assert method in str(raised.value)
    assert "callable" in str(raised.value)


def test_the_refusal_names_the_contract_and_never_the_object():
    """⛔ An engine instance carries a base URL, and a refusal is logged.

    The message is built from the contract's own member names, so there is no
    branch on which a deployment detail could reach it.
    """
    class Carrier:
        name = "carrier"
        base_url = "http://engine.internal:8880/v1"

        def synthesize_chunk(self, text, voice, fmt):  # pragma: no cover
            return b""

        def reachable(self):  # pragma: no cover
            return True

    with pytest.raises(NotAnEngine) as raised:
        check_engine(Carrier())
    message = str(raised.value)
    assert "engine.internal" not in message
    assert "8880" not in message
    assert "identity" in message


def test_a_plain_object_is_not_an_engine():
    with pytest.raises(NotAnEngine):
        check_engine(object())


class TestEngineIdentity:
    def test_the_label_is_family_over_profile(self):
        identity = EngineIdentity(engine="kokoro", profile="cpu", model="kokoro")
        assert identity.label == "kokoro/cpu"

    def test_the_json_shape_is_the_three_fields_healthz_reports(self):
        identity = EngineIdentity(engine="kokoro", profile="gpu", model="kokoro")
        assert identity.as_dict() == {
            "engine": "kokoro",
            "engine_profile": "gpu",
            "engine_model": "kokoro",
        }

    def test_three_fields_are_kept_apart_and_not_flattened(self):
        """⭐ A consumer asks a different question of each; see the docstring.

        Two identities differing only in profile are different identities --
        which is the whole point of recording one beside an artifact.
        """
        cpu = EngineIdentity(engine="kokoro", profile="cpu", model="kokoro")
        gpu = EngineIdentity(engine="kokoro", profile="gpu", model="kokoro")
        assert cpu != gpu
        assert cpu.engine == gpu.engine

    def test_it_is_frozen_so_nothing_can_restamp_an_artifact(self):
        identity = EngineIdentity(engine="kokoro", profile="cpu", model="kokoro")
        with pytest.raises(Exception):
            identity.profile = "gpu"
