"""`narrate.engine.kokoro` -- the request shape, and every failure branch.

The transport is injected, so the shape of the request the engine receives is
asserted without an engine running. What this cannot prove is that the engine
*accepts* that shape; that is established by a recorded measurement against the
real engine, and the command and its output are in the handoff.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from narrate.engine import EngineFailed, EngineUnavailable, KokoroEngine
from tests.support import mpeg_bytes

BASE = "http://127.0.0.1:8880/v1"


def engine_with(transport, timeout=30.0, probe=None):
    return KokoroEngine(BASE, timeout, transport=transport, probe=probe)


def test_the_request_is_the_openai_speech_shape():
    seen = {}

    def transport(url, body, timeout):
        seen["url"] = url
        seen["body"] = json.loads(body)
        seen["timeout"] = timeout
        return mpeg_bytes(1)

    engine_with(transport).synthesize_chunk("Some prose.", "am_liam", "mp3")

    assert seen["url"] == f"{BASE}/audio/speech"
    assert seen["body"] == {
        "model": "kokoro",
        "input": "Some prose.",
        "voice": "am_liam",
        "response_format": "mp3",
    }
    assert seen["timeout"] == 30.0


def test_a_trailing_slash_in_the_base_url_does_not_double():
    seen = {}

    def transport(url, body, timeout):
        seen["url"] = url
        return mpeg_bytes(1)

    KokoroEngine(f"{BASE}/", 30.0, transport=transport).synthesize_chunk(
        "Prose.", "am_liam", "mp3"
    )
    assert seen["url"] == f"{BASE}/audio/speech"


def test_an_http_error_is_an_engine_failure():
    def transport(url, body, timeout):
        raise urllib.error.HTTPError(url, 422, "Unprocessable", {}, None)

    with pytest.raises(EngineFailed, match="422"):
        engine_with(transport).synthesize_chunk("Prose.", "am_liam", "mp3")


def test_a_refused_connection_is_unavailable():
    def transport(url, body, timeout):
        raise ConnectionRefusedError(111, "Connection refused")

    with pytest.raises(EngineUnavailable, match="cannot reach the engine"):
        engine_with(transport).synthesize_chunk("Prose.", "am_liam", "mp3")


def test_a_timeout_is_unavailable_and_names_the_budget():
    def transport(url, body, timeout):
        raise TimeoutError("timed out")

    with pytest.raises(EngineUnavailable, match="600"):
        engine_with(transport, timeout=600.0).synthesize_chunk(
            "Prose.", "am_liam", "mp3"
        )


def test_an_empty_response_is_an_engine_failure():
    with pytest.raises(EngineFailed, match="no audio"):
        engine_with(lambda url, body, timeout: b"").synthesize_chunk(
            "Prose.", "am_liam", "mp3"
        )


@pytest.mark.parametrize("failure", [
    urllib.error.HTTPError(f"{BASE}/audio/speech", 500, "Server Error", {}, None),
    ConnectionRefusedError(111, "Connection refused"),
    TimeoutError("timed out"),
    OSError("some other socket problem"),
])
def test_no_failure_message_echoes_the_text(failure):
    """⛔ The reason the gate is the caller's is that this service is a third party.

    A refusal that quoted the input would write it into a log, which is the
    same disclosure by a slower route.
    """
    identifier = "profile-1234567890"

    def transport(url, body, timeout):
        raise failure

    with pytest.raises(Exception) as raised:
        engine_with(transport).synthesize_chunk(
            f"Visit {identifier} today.", "am_liam", "mp3"
        )
    assert identifier not in str(raised.value)


def test_reachable_is_true_when_the_probe_answers():
    assert engine_with(None, probe=lambda url, timeout: 200).reachable()


def test_reachable_probes_the_models_endpoint():
    seen = {}

    def probe(url, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return 200

    KokoroEngine(BASE, 600.0, probe=probe).reachable()
    assert seen["url"] == f"{BASE}/models"


def test_the_health_probe_does_not_inherit_the_synthesis_timeout():
    """A `GET /healthz` must not hang for the minutes synthesis is allowed."""
    seen = {}

    def probe(url, timeout):
        seen["timeout"] = timeout
        return 200

    KokoroEngine(BASE, 600.0, probe=probe).reachable()
    assert seen["timeout"] < 60


def test_reachable_is_false_when_the_probe_raises():
    def probe(url, timeout):
        raise ConnectionRefusedError(111, "Connection refused")

    assert engine_with(None, probe=probe).reachable() is False


def test_reachable_never_raises():
    def probe(url, timeout):
        raise RuntimeError("something entirely unexpected")

    assert engine_with(None, probe=probe).reachable() is False
