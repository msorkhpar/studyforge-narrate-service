"""`POST /v1/jobs` over a real socket -- the batch route as a caller sees it.

`tests/test_jobs.py` owns the job runner's behaviour. This module owns the
**wire**: the status line, the body, and the two things a route can get wrong
that the runner cannot -- a refusal that should have been a `400`, and a
manifest that never reaches the caller as JSON.
"""

from __future__ import annotations

import json

import pytest

from narrate import PROVIDES
from narrate.server import MAX_BODY_BYTES
from tests.support import FakeEngine

FOUR = [
    {"id": "u01-s001", "text": "The first speech unit."},
    {"id": "u01-s002", "text": "The second speech unit."},
    {"id": "u01-s003", "text": "The third speech unit."},
    {"id": "u01-s004", "text": "The fourth speech unit."},
]


def manifest_of(response, data):
    assert response.status == 200
    assert response.getheader("Content-Type") == "application/json"
    return json.loads(data)


class TestTheHappyPath:
    def test_a_job_answers_two_hundred_with_a_manifest(self, service):
        request = service()
        manifest = manifest_of(*request("POST", "/v1/jobs", {"segments": FOUR}))
        assert manifest["counts"]["total"] == 4
        assert manifest["counts"]["synthesised"] == 4
        assert manifest["provides"] == PROVIDES

    def test_the_response_is_never_audio(self, service):
        """⛔ The difference between the two synthesis routes.

        A corpus-sized job whose response carried the bytes would be a
        multi-gigabyte body. The manifest carries addresses; the caller fetches
        what it wants.
        """
        request = service()
        response, data = request("POST", "/v1/jobs", {"segments": FOUR})
        assert response.getheader("Content-Type") == "application/json"
        assert b"\xff\xfb" not in data

    def test_each_address_is_fetchable_from_the_artifact_route(self, service):
        request = service()
        manifest = manifest_of(*request("POST", "/v1/jobs", {"segments": FOUR}))
        for entry in manifest["segments"]:
            response, audio = request("GET", entry["url"])
            assert response.status == 200
            assert response.getheader("Content-Type") == "audio/mpeg"
            assert len(audio) == entry["bytes"]

    def test_re_submitting_over_HTTP_synthesises_nothing(self, service):
        """⭐ Idempotence at the wire, counting the engine's calls."""
        engine = FakeEngine()
        request = service(engine=engine)
        first = manifest_of(*request("POST", "/v1/jobs", {"segments": FOUR}))
        calls_after_first = len(engine.calls)
        second = manifest_of(*request("POST", "/v1/jobs", {"segments": FOUR}))

        assert calls_after_first == 4
        assert len(engine.calls) == 4          # ⛔ unchanged by the second job
        assert second["counts"]["cached"] == 4
        assert [e["artifact_id"] for e in first["segments"]] == \
               [e["artifact_id"] for e in second["segments"]]

    def test_the_two_routes_share_one_cache(self, service):
        """⭐ A segment sent to `/v1/speech` is a hit at `/v1/jobs`, and back."""
        engine = FakeEngine()
        request = service(engine=engine)
        speech, _ = request("POST", "/v1/speech", {"text": "Shared prose."})
        assert speech.status == 200
        assert speech.getheader("Narrate-Cached") == "false"

        manifest = manifest_of(*request(
            "POST", "/v1/jobs", {"segments": [{"id": "s1", "text": "Shared prose."}]}
        ))
        assert manifest["segments"][0]["status"] == "cached"
        assert manifest["segments"][0]["artifact_id"] == \
            speech.getheader("Narrate-Artifact-Id")
        assert len(engine.calls) == 1


class TestTheSingleTextRouteGainedIdempotenceToo:
    def test_the_artifact_id_is_now_a_content_address(self, service):
        request = service()
        first, _ = request("POST", "/v1/speech", {"text": "Same words."})
        second, _ = request("POST", "/v1/speech", {"text": "Same words."})
        address = first.getheader("Narrate-Artifact-Id")
        assert len(address) == 64
        assert second.getheader("Narrate-Artifact-Id") == address

    def test_the_cached_header_says_whether_it_cost_a_synthesis(self, service):
        engine = FakeEngine()
        request = service(engine=engine)
        first, _ = request("POST", "/v1/speech", {"text": "Same words."})
        second, second_body = request("POST", "/v1/speech", {"text": "Same words."})

        assert first.getheader("Narrate-Cached") == "false"
        assert second.getheader("Narrate-Cached") == "true"
        assert len(engine.calls) == 1
        assert len(second_body) == int(second.getheader("Content-Length"))

    def test_a_cache_hit_still_returns_the_audio_in_the_body(self, service):
        request = service()
        _, first_body = request("POST", "/v1/speech", {"text": "Same words."})
        _, second_body = request("POST", "/v1/speech", {"text": "Same words."})
        assert second_body == first_body


class TestARefusal:
    @pytest.mark.parametrize("body,fragment", [
        ({}, "segments"),
        ({"segments": []}, "empty"),
        ({"segments": [{"id": "s1"}]}, "text"),
        ({"segments": [{"id": "../x", "text": "y"}]}, "id must be"),
        ({"segments": [{"id": "s1", "text": "y"}], "format": "wav"}, "mp3"),
    ])
    def test_a_malformed_job_is_four_hundred_and_names_what_is_permitted(
        self, service, body, fragment
    ):
        request = service()
        response, data = request("POST", "/v1/jobs", body)
        assert response.status == 400
        assert fragment in json.loads(data)["error"]

    def test_a_body_that_is_not_json_is_four_hundred(self, service):
        request = service()
        response, _ = request("POST", "/v1/jobs", raw_body=b"{not json",
                              headers={"Content-Type": "application/json"})
        assert response.status == 400

    def test_a_body_that_is_a_json_array_is_four_hundred(self, service):
        request = service()
        response, data = request("POST", "/v1/jobs", [1, 2, 3])
        assert response.status == 400
        assert "object" in json.loads(data)["error"]

    def test_no_content_length_is_four_hundred_and_eleven(self, service):
        request = service()
        response, _ = request("POST", "/v1/jobs", raw_body=b"",
                              headers={"Content-Type": "application/json"})
        assert response.status in (400, 411)

    def test_an_oversized_body_is_refused_on_its_declared_length(self, service):
        """⚠️ The one cap both synthesis routes share.

        A corpus larger than this is submitted as several jobs, which costs
        nothing: the addresses are content addresses, so a segment sent twice
        is synthesised once.
        """
        request = service()
        response, _ = request(
            "POST", "/v1/jobs", raw_body=b"x",
            headers={"Content-Type": "application/json",
                     "Content-Length": str(MAX_BODY_BYTES + 1)},
        )
        assert response.status == 413

    def test_a_failing_segment_is_still_a_two_hundred(self, service):
        """⛔ The job ran. A segment's outcome is data, in `counts`."""
        request = service()
        manifest = manifest_of(*request("POST", "/v1/jobs", {"segments": [
            {"id": "good", "text": "Real prose."},
            {"id": "blank", "text": "   "},
        ]}))
        assert manifest["ok"] is False
        assert manifest["counts"]["failed"] == 1
        assert manifest["counts"]["synthesised"] == 1


class TestHealthzCarriesThePromise:
    def test_provides_is_reported_so_a_caller_can_check_before_it_builds(self, service):
        request = service()
        _, data = request("GET", "/healthz")
        payload = json.loads(data)
        assert payload["provides"] == PROVIDES
        # ⚠️ Not the same question as the build's version.
        assert payload["version"] != payload["provides"]
