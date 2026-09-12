"""`narrate.server` -- every route and every refusal, over a real socket.

The server is started on port 0 and talked to with `http.client`, so these are
end-to-end HTTP assertions rather than handler-method calls: the status line,
the headers and the body are what a caller actually receives. The engine is
faked, so the suite needs no running engine and no GPU.

⚠️ **The `service` fixture is in `tests/conftest.py`** -- `test_server_jobs.py`
needs the same running server, and one definition is what keeps the two
modules' idea of a service identical. `POST /v1/jobs` is tested there.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading

import pytest

from narrate.config import Config
from narrate.engine import (
    EngineFailed,
    EngineUnavailable,
    NotAnEngine,
    UnknownEngine,
)
from narrate.server import MAX_BODY_BYTES, build_server
from tests.support import FakeEngine, mpeg_bytes


@pytest.fixture
def service_address(tmp_path):
    """A running server, yielding only its address. For raw-socket tests."""
    made = {}

    def start():
        config = Config(artifact_dir=tmp_path, bind="127.0.0.1", port=0)
        server = build_server(config, engine=FakeEngine())
        made["server"] = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server.server_address[:2]

    yield start

    server = made.get("server")
    if server is not None:
        server.shutdown()
        server.server_close()


def test_healthz_reports_the_engine(service):
    request = service(FakeEngine())
    response, body = request("GET", "/healthz")
    assert response.status == 200
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["engine"] == "fake"
    assert payload["engine_reachable"] is True
    assert payload["formats"] == ["mp3"]


def test_healthz_reports_an_unreachable_engine_without_failing(service):
    """A health endpoint that fails when the engine is down reports nothing."""
    request = service(FakeEngine(reachable_=False))
    response, body = request("GET", "/healthz")
    assert response.status == 200
    assert json.loads(body)["engine_reachable"] is False


def test_speech_returns_playable_audio_and_names_the_artifact(service):
    request = service(FakeEngine(per_chunk=mpeg_bytes(3)))
    response, body = request("POST", "/v1/speech", {"text": "A sentence."})

    assert response.status == 200
    assert response.getheader("Content-Type") == "audio/mpeg"
    assert body == mpeg_bytes(3)
    assert response.getheader("Narrate-Chunks") == "1"
    artifact_id = response.getheader("Narrate-Artifact-Id")
    # ⭐ 64, not 32: the id is a content address now, not a random token.
    assert len(artifact_id) == 64
    assert response.getheader("Narrate-Artifact-Url") == f"/v1/artifacts/{artifact_id}"


def test_the_artifact_can_be_fetched_again(service):
    request = service(FakeEngine(per_chunk=mpeg_bytes(2)))
    response, body = request("POST", "/v1/speech", {"text": "A sentence."})
    artifact_id = response.getheader("Narrate-Artifact-Id")

    again, fetched = request("GET", f"/v1/artifacts/{artifact_id}")
    assert again.status == 200
    assert again.getheader("Content-Type") == "audio/mpeg"
    assert fetched == body


def test_a_long_text_is_one_request_and_one_artifact(service):
    """The carried-over property, asserted where a caller would see it."""
    engine = FakeEngine()
    request = service(engine, chunk_chars=200)
    text = " ".join(f"Sentence {n} of the corpus." for n in range(400))
    response, body = request("POST", "/v1/speech", {"text": text})

    assert response.status == 200
    chunks = int(response.getheader("Narrate-Chunks"))
    assert chunks > 10
    assert len(engine.calls) == chunks
    assert body == mpeg_bytes(chunks)


def test_the_default_voice_is_used_when_none_is_given(service):
    engine = FakeEngine()
    request = service(engine)
    request("POST", "/v1/speech", {"text": "Prose."})
    assert engine.calls[0]["voice"] == "am_liam"


def test_a_requested_voice_reaches_the_engine(service):
    engine = FakeEngine()
    request = service(engine)
    request("POST", "/v1/speech", {"text": "Prose.", "voice": "af_bella"})
    assert engine.calls[0]["voice"] == "af_bella"


@pytest.mark.parametrize("body,expected", [
    ({"text": ""}, "empty"),
    ({"text": "   "}, "empty"),
    ({"text": 17}, "must be a string"),
    ({}, "must be a string"),
    ({"text": "Prose.", "format": "wav"}, "mp3"),
    ({"text": "Prose.", "voice": 3}, "must be a string"),
])
def test_a_bad_request_is_four_hundred_and_names_what_is_permitted(
    service, body, expected
):
    request = service()
    response, data = request("POST", "/v1/speech", body)
    assert response.status == 400
    assert expected in json.loads(data)["error"]


@pytest.mark.parametrize("raw,expected", [
    (b"this is not json at all", "body must be JSON"),
    (b"[1, 2, 3]", "body must be a JSON object"),
    (b'"a bare string"', "body must be a JSON object"),
    (b"\xff\xfe\x00not-utf-8", "body must be JSON"),
])
def test_a_body_that_is_not_a_json_object_is_four_hundred(service, tmp_path, raw,
                                                          expected):
    request = service()
    response, data = request("POST", "/v1/speech", raw_body=raw)
    assert response.status == 400
    assert json.loads(data)["error"] == expected


def test_an_empty_body_is_four_hundred(service):
    request = service()
    response, data = request("POST", "/v1/speech", raw_body=b"")
    assert response.status == 400
    assert json.loads(data)["error"] == "body must be JSON"


def test_a_post_with_no_content_length_is_four_hundred_and_eleven(service_address):
    """Sent down a raw socket, because `http.client` always supplies a length.

    The branch is reachable from anything that is not `http.client`, so it is
    exercised by something that is not.
    """
    host, port = service_address()
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.sendall(
            b"POST /v1/speech HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: application/json\r\n"
            b"Connection: close\r\n\r\n"
        )
        raw = b""
        while True:
            piece = sock.recv(4096)
            if not piece:
                break
            raw += piece

    head, _, body = raw.partition(b"\r\n\r\n")
    assert b"411" in head.split(b"\r\n")[0]
    assert "Content-Length" in json.loads(body)["error"]


def test_an_oversized_body_is_refused_by_its_declared_length(service):
    """Refused on Content-Length, before the bytes are read into memory."""
    request = service()
    response, data = request(
        "POST", "/v1/speech", None,
        {"Content-Type": "application/json",
         "Content-Length": str(MAX_BODY_BYTES + 1)},
    )
    assert response.status == 413
    assert str(MAX_BODY_BYTES) in json.loads(data)["error"]


def test_an_unreachable_engine_is_five_hundred_and_three(service):
    request = service(FakeEngine(fail_with=EngineUnavailable("engine is down")))
    response, data = request("POST", "/v1/speech", {"text": "Prose."})
    assert response.status == 503
    assert "down" in json.loads(data)["error"]


def test_an_engine_that_refuses_is_five_hundred_and_two(service):
    request = service(FakeEngine(fail_with=EngineFailed("the engine returned HTTP 422")))
    response, data = request("POST", "/v1/speech", {"text": "Prose."})
    assert response.status == 502
    assert "422" in json.loads(data)["error"]


def test_output_that_is_not_audio_is_five_hundred_and_two(service):
    request = service(FakeEngine(per_chunk=b"<html>error</html>"))
    response, data = request("POST", "/v1/speech", {"text": "Prose."})
    assert response.status == 502
    assert "not playable" in json.loads(data)["error"]


@pytest.mark.parametrize("path", [
    "/v1/artifacts/../../etc/passwd",
    "/v1/artifacts/",
    "/v1/artifacts/not-an-id",
    "/v1/artifacts/00000000000000000000000000000000",
])
def test_an_unknown_or_malformed_artifact_is_four_hundred_and_four(service, path):
    request = service()
    response, _ = request("GET", path)
    assert response.status == 404


@pytest.mark.parametrize("method,path", [
    ("GET", "/"),
    ("GET", "/v1/speech"),
    ("GET", "/v1/jobs"),
    ("POST", "/healthz"),
])
def test_an_unknown_route_is_four_hundred_and_four(service, method, path):
    request = service()
    body = {"text": "Prose."} if method == "POST" else None
    response, _ = request(method, path, body)
    assert response.status == 404


def test_the_batch_route_is_at_one_path_and_the_near_misses_are_not_it(service):
    """⭐ The inverse of `NS-01`'s `test_there_is_no_batch_route`.

    That test asserted the absence of `/v1/jobs` so that this task's change
    would be visible rather than silent. It is inverted here rather than
    deleted: `/v1/jobs` now answers, and the spellings a caller might guess
    still do not, because a route that half-exists under three names is how two
    callers end up on two shapes.
    """
    request = service()
    response, _ = request("POST", "/v1/jobs",
                          {"segments": [{"id": "s1", "text": "Prose."}]})
    assert response.status == 200
    for path in ("/v1/batch", "/v1/speech/batch", "/v1/job"):
        response, _ = request("POST", path, {"segments": []})
        assert response.status == 404


def test_the_server_header_does_not_name_the_python_version(service):
    """A banner that names an interpreter version tells a stranger what to look up."""
    request = service()
    response, _ = request("GET", "/healthz")
    banner = response.getheader("Server") or ""
    assert banner.startswith("narrate-service/")
    assert "Python" not in banner


def test_a_response_never_carries_the_text_that_was_sent(service):
    """R7's shape at the response boundary, over the wire."""
    identifier = "profile-9876543210"
    request = service(FakeEngine(fail_with=EngineFailed("the engine returned HTTP 500")))
    response, data = request("POST", "/v1/speech", {"text": f"Visit {identifier}."})
    assert response.status == 502
    assert identifier not in data.decode("utf-8")
    assert identifier not in str(dict(response.getheaders()))


class TestTheEngineIsReported:
    """⛔ `NS-03`: *"the engine in use is reported by the service so a caller
    can record which one produced an artifact."*

    ⭐ **Two places, and both are needed.** `/healthz` answers *what will this
    deployment use*, which a caller reads before it sends anything. The
    artifact's own headers answer *what made THIS file* -- and that question
    cannot be answered by a later `/healthz`, because by then the deployment
    may have been restarted onto the other profile.
    """

    def test_healthz_reports_the_engine_family_profile_and_model(self, service):
        request = service(engine=FakeEngine(profile="cpu", model="fake-1"))
        response, data = request("GET", "/healthz")
        payload = json.loads(data)
        assert payload["engine"] == "fake"
        assert payload["engine_profile"] == "cpu"
        assert payload["engine_model"] == "fake-1"

    def test_a_synthesised_artifact_carries_the_engine_in_its_headers(self, service):
        request = service(engine=FakeEngine(profile="gpu", model="fake-1"))
        response, data = request("POST", "/v1/speech", {"text": "Prose."})
        assert response.status == 200
        assert response.getheader("Narrate-Engine") == "fake/gpu"
        assert response.getheader("Narrate-Engine-Model") == "fake-1"

    def test_the_two_reports_agree_within_one_deployment(self, service):
        request = service(engine=FakeEngine(profile="cpu", model="fake-1"))
        health = json.loads(request("GET", "/healthz")[1])
        response, _ = request("POST", "/v1/speech", {"text": "Prose."})
        assert response.getheader("Narrate-Engine") == (
            f"{health['engine']}/{health['engine_profile']}"
        )
        assert response.getheader("Narrate-Engine-Model") == health["engine_model"]

    def test_the_declared_profile_follows_the_deployment_and_nothing_else(
        self, service, tmp_path
    ):
        """⭐ The same engine class, two profiles, no code path in between.

        ⚠️ **Each profile gets its OWN store**, and that is load-bearing since
        the cache landed: three deployments sharing one store would find each
        other's artifacts, and a cache hit correctly reports the engine that
        MADE it rather than the one now deployed -- so a shared store would
        measure the cache, not the profile plumbing.
        """
        seen = set()
        for profile in ("cpu", "gpu", "unknown"):
            request = service(engine=FakeEngine(profile=profile),
                              artifact_dir=tmp_path / profile)
            response, _ = request("POST", "/v1/speech", {"text": "Prose."})
            seen.add(response.getheader("Narrate-Engine"))
        assert seen == {"fake/cpu", "fake/gpu", "fake/unknown"}

    def test_no_engine_header_names_an_address(self, service):
        """⛔ A caller must not learn the engine's address from an artifact."""
        request = service(engine=FakeEngine())
        response, _ = request("POST", "/v1/speech", {"text": "Prose."})
        for name, value in response.getheaders():
            assert "8880" not in value
            assert "http://" not in value


class TestASecondEngineFamilyReachesEveryRouteUnchanged:
    """⛔ *"Adding a different speech engine later must not touch the API."*

    ⚠️ **`FakeEngine` is a test double and is NOT offered as evidence that some
    other speech engine works.** What these assert is the narrow, real thing a
    suite can assert: an adapter of a different family, satisfying the contract
    in `engine/base.py` and nothing else, is served by every route without one
    line of the API, the chunker, the store or the server changing -- because
    nothing above `narrate.engine` imports `KokoroEngine` at all.
    """

    def test_no_module_above_the_engine_package_imports_a_concrete_engine(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "narrate"
        offenders = [
            path.name for path in root.glob("*.py")
            if "KokoroEngine" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []

    def test_every_route_serves_an_adapter_of_another_family(self, service):
        request = service(engine=FakeEngine(profile="cpu", model="other-2"))
        assert json.loads(request("GET", "/healthz")[1])["engine"] == "fake"
        response, audio = request("POST", "/v1/speech", {"text": "Prose."})
        assert response.status == 200
        artifact_id = response.getheader("Narrate-Artifact-Id")
        again, refetched = request("GET", f"/v1/artifacts/{artifact_id}")
        assert again.status == 200
        assert refetched == audio


class TestAnInjectedEngineIsCheckedAtStartup:
    def test_an_object_missing_a_member_refuses_to_start(self, tmp_path):
        """⛔ Not a 500 on the first request. `build_server` is public."""
        class Halfway:
            name = "halfway"

            def reachable(self):  # pragma: no cover
                return True

        config = Config(artifact_dir=tmp_path, bind="127.0.0.1", port=0)
        with pytest.raises(NotAnEngine):
            build_server(config, engine=Halfway())

    def test_an_unknown_engine_name_refuses_to_start(self, tmp_path):
        config = Config(artifact_dir=tmp_path, bind="127.0.0.1", port=0,
                        engine="not-an-engine")
        with pytest.raises(UnknownEngine):
            build_server(config)
