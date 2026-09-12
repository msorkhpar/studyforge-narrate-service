"""`narrate.jobs` -- the manifest, idempotence, and what a partial failure says.

⛔ **Every idempotence assertion here counts ENGINE CALLS**, never merely
compares ids. Two runs returning the same address prove nothing about whether
the second one synthesised: that is exactly the failure §8.2 records from
CodeSignal's runner, which decided a clip was current by whether a file existed
and reported *"0 synthesised"* while 619 clips went on speaking the old wording.
⭐ **The property is that the engine was NOT CALLED, so that is what is asserted.**
"""

from __future__ import annotations

import json

import pytest

from narrate import PROVIDES
from narrate.artifacts import ArtifactStore, address_for
from narrate.config import FORMAT_MEDIA_TYPES
from narrate.engine import EngineFailed, EngineUnavailable
from narrate.jobs import (
    FAILURE_REASONS,
    MAX_SEGMENTS,
    SEGMENT_STATUSES,
    InvalidJob,
    parse_job,
    run_job,
)
from tests.support import FakeEngine, mpeg_bytes


def submit(segments, tmp_path, engine=None, voice=None, fmt=None, store=None):
    """Parse and run one job. Returns `(manifest, engine, store)`."""
    request = {"segments": segments}
    if voice is not None:
        request["voice"] = voice
    if fmt is not None:
        request["format"] = fmt
    engine = engine if engine is not None else FakeEngine()
    store = store if store is not None else ArtifactStore(tmp_path)
    job = parse_job(request, default_voice="am_liam")
    manifest = run_job(job, engine=engine, store=store, chunk_chars=1800,
                       media_types=FORMAT_MEDIA_TYPES, provides=PROVIDES)
    return manifest, engine, store


def entries(manifest):
    return {entry["id"]: entry for entry in manifest["segments"]}


FOUR = [
    {"id": "u01-s001", "text": "The first speech unit."},
    {"id": "u01-s002", "text": "The second speech unit."},
    {"id": "u01-s003", "text": "The third speech unit."},
    {"id": "u01-s004", "text": "The fourth speech unit."},
]


class TestAJobOfManySegments:
    """⭐ *A job of many segments returns one artifact per id plus a manifest.*"""

    def test_every_id_gets_an_artifact_and_they_are_all_different(self, tmp_path):
        manifest, engine, store = submit(FOUR, tmp_path)
        assert manifest["counts"] == {
            "total": 4, "synthesised": 4, "cached": 0, "failed": 0, "skipped": 0,
        }
        assert manifest["ok"] is True
        assert len(engine.calls) == 4
        addresses = {entry["artifact_id"] for entry in manifest["segments"]}
        assert len(addresses) == 4
        for address in addresses:
            assert store.read(address)

    def test_the_manifest_is_in_submission_order(self, tmp_path):
        manifest, _, _ = submit(FOUR, tmp_path)
        assert [entry["id"] for entry in manifest["segments"]] == [
            "u01-s001", "u01-s002", "u01-s003", "u01-s004"
        ]

    def test_each_entry_carries_the_address_and_the_url_to_fetch_it(self, tmp_path):
        manifest, _, _ = submit(FOUR, tmp_path)
        entry = entries(manifest)["u01-s002"]
        assert entry["status"] == "synthesised"
        assert entry["url"] == f"/v1/artifacts/{entry['artifact_id']}"
        assert entry["media_type"] == "audio/mpeg"
        assert entry["engine"] == "fake"

    def test_the_manifest_never_carries_the_audio(self, tmp_path):
        """⛔ A corpus-sized manifest carrying bytes is a gigabyte response."""
        manifest, _, _ = submit(FOUR, tmp_path)
        for entry in manifest["segments"]:
            assert "audio" not in entry
            assert entry["bytes"] > 0

    def test_the_manifest_never_carries_the_text(self, tmp_path):
        """R7's shape at the response boundary, for the batch route too."""
        identifier = "profile-9876543210"
        manifest, _, _ = submit(
            [{"id": "s1", "text": f"Visit {identifier} for details."}], tmp_path
        )
        assert identifier not in json.dumps(manifest)

    def test_the_manifest_declares_the_promise_that_produced_it(self, tmp_path):
        """⛔ Ruling 330(b): a wire shape is versioned by `provides`."""
        manifest, _, _ = submit(FOUR, tmp_path)
        assert manifest["provides"] == PROVIDES

    def test_the_manifest_publishes_how_to_recompute_an_address(self, tmp_path):
        """⭐ So an incremental consumer decides what to send BEFORE sending it."""
        manifest, _, _ = submit(FOUR, tmp_path)
        addressing = manifest["addressing"]
        assert addressing["hash"] == "sha256"
        assert addressing["over"] == ["format", "voice", "text"]
        recomputed = address_for("The first speech unit.", "am_liam", "mp3")
        assert entries(manifest)["u01-s001"]["artifact_id"] == recomputed

    def test_the_voice_and_format_are_job_wide_and_reach_every_segment(self, tmp_path):
        manifest, engine, _ = submit(FOUR, tmp_path, voice="af_bella")
        assert manifest["voice"] == "af_bella"
        assert {call["voice"] for call in engine.calls} == {"af_bella"}
        assert {entry["voice"] for entry in manifest["segments"]} == {"af_bella"}


class TestResubmittingAnUnchangedJob:
    """⭐ *Re-submitting an unchanged job synthesises nothing and returns the
    same addresses.*"""

    def test_the_second_run_calls_the_engine_ZERO_times(self, tmp_path):
        store = ArtifactStore(tmp_path)
        first, first_engine, _ = submit(FOUR, tmp_path, store=store)
        second, second_engine, _ = submit(FOUR, tmp_path, store=store)

        assert len(first_engine.calls) == 4
        assert second_engine.calls == []
        assert second["counts"]["cached"] == 4
        assert second["counts"]["synthesised"] == 0
        assert second["ok"] is True

    def test_the_addresses_are_the_same_ones(self, tmp_path):
        store = ArtifactStore(tmp_path)
        first, _, _ = submit(FOUR, tmp_path, store=store)
        second, _, _ = submit(FOUR, tmp_path, store=store)
        assert [e["artifact_id"] for e in first["segments"]] == \
               [e["artifact_id"] for e in second["segments"]]

    def test_nothing_new_is_written_to_the_store(self, tmp_path):
        store = ArtifactStore(tmp_path)
        submit(FOUR, tmp_path, store=store)
        before = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
        submit(FOUR, tmp_path, store=store)
        after = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
        assert before == after

    def test_a_cached_segment_reports_the_engine_that_MADE_it(self, tmp_path):
        """⛔ Never the engine deployed now. That would be the first lie here.

        `NS-03` named this exact hazard for this task: a redeployment must not
        make every cached artifact claim it was produced by the new engine.
        """
        store = ArtifactStore(tmp_path)
        submit(FOUR, tmp_path, engine=FakeEngine(profile="gpu", model="first-model"),
               store=store)
        redeployed = FakeEngine(profile="cpu", model="second-model")
        manifest, _, _ = submit(FOUR, tmp_path, engine=redeployed, store=store)

        assert redeployed.calls == []
        for entry in manifest["segments"]:
            assert entry["status"] == "cached"
            assert entry["engine_profile"] == "gpu"
            assert entry["engine_model"] == "first-model"

    def test_two_segments_with_identical_text_share_one_synthesis(self, tmp_path):
        """⭐ Within ONE job: the second is a hit on what the first just stored."""
        manifest, engine, _ = submit([
            {"id": "a", "text": "Repeated prose."},
            {"id": "b", "text": "Repeated prose."},
        ], tmp_path)
        assert len(engine.calls) == 1
        assert manifest["counts"]["synthesised"] == 1
        assert manifest["counts"]["cached"] == 1
        by_id = entries(manifest)
        assert by_id["a"]["artifact_id"] == by_id["b"]["artifact_id"]


class TestChangingOneSegment:
    """⭐ *Changing one segment's text re-synthesises that segment only.*"""

    def test_exactly_one_segment_is_resynthesised(self, tmp_path):
        store = ArtifactStore(tmp_path)
        first, _, _ = submit(FOUR, tmp_path, store=store)

        edited = [dict(entry) for entry in FOUR]
        edited[2]["text"] = "The third speech unit, revised."
        second, engine, _ = submit(edited, tmp_path, store=store)

        assert len(engine.calls) == 1
        assert engine.calls[0]["text"] == "The third speech unit, revised."
        assert second["counts"]["synthesised"] == 1
        assert second["counts"]["cached"] == 3

    def test_only_that_segments_address_moves(self, tmp_path):
        store = ArtifactStore(tmp_path)
        first, _, _ = submit(FOUR, tmp_path, store=store)
        edited = [dict(entry) for entry in FOUR]
        edited[2]["text"] = "The third speech unit, revised."
        second, _, _ = submit(edited, tmp_path, store=store)

        before, after = entries(first), entries(second)
        assert before["u01-s003"]["artifact_id"] != after["u01-s003"]["artifact_id"]
        for other in ("u01-s001", "u01-s002", "u01-s004"):
            assert before[other]["artifact_id"] == after[other]["artifact_id"]

    def test_changing_the_voice_moves_EVERY_address(self, tmp_path):
        """⭐ `NS-04`'s clause, already true: a voice is part of the address."""
        store = ArtifactStore(tmp_path)
        first, _, _ = submit(FOUR, tmp_path, store=store)
        second, engine, _ = submit(FOUR, tmp_path, voice="af_bella", store=store)

        assert len(engine.calls) == 4
        assert second["counts"]["cached"] == 0
        before, after = entries(first), entries(second)
        for key in before:
            assert before[key]["artifact_id"] != after[key]["artifact_id"]

    def test_the_old_artifact_stays_and_is_not_deleted(self, tmp_path):
        """⚠️ Reconciliation is the caller's, not this service's.

        The store is not garbage-collected; an edited segment's previous
        artifact remains addressable. Recorded as a property rather than left
        to be discovered by a disk filling up.
        """
        store = ArtifactStore(tmp_path)
        first, _, _ = submit([FOUR[0]], tmp_path, store=store)
        edited = [{"id": "u01-s001", "text": "Revised."}]
        second, _, _ = submit(edited, tmp_path, store=store)
        assert store.read(first["segments"][0]["artifact_id"])
        assert store.read(second["segments"][0]["artifact_id"])


class TestAPartiallyFailingJob:
    """⭐ *A partially failing job reports which ids failed and still returns
    the rest -- it does not discard successful work.*"""

    def test_one_unsynthesisable_segment_does_not_stop_the_others(self, tmp_path):
        """⛔ The arm that needs no engine failure at all: blank text."""
        manifest, engine, store = submit([
            {"id": "good-1", "text": "Real prose."},
            {"id": "blank", "text": "   "},
            {"id": "good-2", "text": "More real prose."},
        ], tmp_path)

        assert manifest["counts"] == {
            "total": 3, "synthesised": 2, "cached": 0, "failed": 1, "skipped": 0,
        }
        assert manifest["ok"] is False
        by_id = entries(manifest)
        assert by_id["blank"]["status"] == "failed"
        assert by_id["blank"]["reason"] == "not_synthesisable"
        assert "artifact_id" not in by_id["blank"]
        # ⭐ And the successful work is really on disk, not merely reported.
        for good in ("good-1", "good-2"):
            assert store.read(by_id[good]["artifact_id"])

    def test_an_engine_that_answers_badly_fails_ONE_segment(self, tmp_path):
        """`EngineFailed` is about this input, so the job continues."""
        def per_chunk(text):
            if "poison" in text:
                raise EngineFailed("the engine's output is not playable audio")
            return mpeg_bytes(1)

        manifest, engine, _ = submit([
            {"id": "a", "text": "Fine prose."},
            {"id": "b", "text": "A poison segment."},
            {"id": "c", "text": "Also fine prose."},
        ], tmp_path, engine=FakeEngine(per_chunk=per_chunk))

        assert len(engine.calls) == 3
        assert manifest["counts"]["synthesised"] == 2
        assert manifest["counts"]["failed"] == 1
        assert manifest["counts"]["skipped"] == 0
        assert entries(manifest)["b"]["reason"] == "engine_failed"

    def test_an_unreachable_engine_HALTS_the_job_and_keeps_what_finished(self, tmp_path):
        """⭐ The judgement call, stated as a test.

        Nothing answered, so the next three thousand segments will not fare
        better -- and a corpus-sized job must not spend an hour discovering it.
        ⛔ Everything already synthesised is still in the manifest.
        """
        state = {"n": 0}

        def per_chunk(_text):
            state["n"] += 1
            if state["n"] > 2:
                raise EngineUnavailable("the engine could not be reached")
            return mpeg_bytes(1)

        manifest, engine, store = submit([
            {"id": f"s{n}", "text": f"Unit number {n}."} for n in range(6)
        ], tmp_path, engine=FakeEngine(per_chunk=per_chunk))

        assert manifest["counts"] == {
            "total": 6, "synthesised": 2, "cached": 0, "failed": 1, "skipped": 3,
        }
        assert manifest["ok"] is False
        by_id = entries(manifest)
        assert by_id["s2"]["reason"] == "engine_unavailable"
        for skipped in ("s3", "s4", "s5"):
            assert by_id[skipped]["status"] == "skipped"
            assert by_id[skipped]["reason"] == "engine_unavailable"
        # ⛔ Successful work was NOT discarded.
        for done in ("s0", "s1"):
            assert store.read(by_id[done]["artifact_id"])
        # ⭐ And it stopped: three of six were never attempted.
        assert len(engine.calls) == 3

    def test_the_halt_keeps_a_re_run_cheap(self, tmp_path):
        """⭐ The point of halting: the retry pays only for what is left."""
        store = ArtifactStore(tmp_path)
        state = {"n": 0}

        def flaky(_text):
            state["n"] += 1
            if state["n"] > 2:
                raise EngineUnavailable("down")
            return mpeg_bytes(1)

        segments = [{"id": f"s{n}", "text": f"Unit number {n}."} for n in range(6)]
        submit(segments, tmp_path, engine=FakeEngine(per_chunk=flaky), store=store)
        retry, retry_engine, _ = submit(segments, tmp_path, store=store)

        assert retry["ok"] is True
        assert retry["counts"]["cached"] == 2
        assert len(retry_engine.calls) == 4

    def test_a_failed_entry_never_echoes_the_text(self, tmp_path):
        identifier = "profile-9876543210"
        manifest, _, _ = submit(
            [{"id": "s1", "text": "   "},
             {"id": "s2", "text": f"Visit {identifier}."}],
            tmp_path, engine=FakeEngine(fail_with=EngineFailed("unusable audio")),
        )
        assert identifier not in json.dumps(manifest)

    def test_every_status_and_reason_used_is_in_the_closed_set(self, tmp_path):
        def per_chunk(text):
            if "poison" in text:
                raise EngineFailed("unusable")
            if "gone" in text:
                raise EngineUnavailable("down")
            return mpeg_bytes(1)

        manifest, _, _ = submit([
            {"id": "a", "text": "Fine."},
            {"id": "b", "text": "A poison one."},
            {"id": "c", "text": "   "},
            {"id": "d", "text": "Now gone."},
            {"id": "e", "text": "Never attempted."},
        ], tmp_path, engine=FakeEngine(per_chunk=per_chunk))

        for entry in manifest["segments"]:
            assert entry["status"] in SEGMENT_STATUSES
            if "reason" in entry:
                assert entry["reason"] in FAILURE_REASONS
        assert {e["status"] for e in manifest["segments"]} == {
            "synthesised", "failed", "skipped"
        }


class TestARequestThatIsNotAJobNeverRuns:
    @pytest.mark.parametrize("request_body,expected", [
        ({}, "segments must be a list"),
        ({"segments": {}}, "segments must be a list"),
        ({"segments": []}, "must not be empty"),
        ({"segments": ["not an object"]}, "must be an object"),
        ({"segments": [{"text": "no id"}]}, "id must be"),
        ({"segments": [{"id": "s1"}]}, "text must be a string"),
        ({"segments": [{"id": "s1", "text": 7}]}, "text must be a string"),
        ({"segments": [{"id": "", "text": "x"}]}, "id must be"),
        ({"segments": [{"id": "../escape", "text": "x"}]}, "id must be"),
        ({"segments": [{"id": "a b", "text": "x"}]}, "id must be"),
        ({"segments": [{"id": "s" * 129, "text": "x"}]}, "id must be"),
        ({"segments": [{"id": "s1", "text": "x"}], "voice": 7}, "voice must be"),
        ({"segments": [{"id": "s1", "text": "x"}], "format": "wav"}, "mp3"),
    ])
    def test_a_malformed_job_is_refused_naming_what_is_permitted(
        self, request_body, expected
    ):
        with pytest.raises(InvalidJob, match=expected):
            parse_job(request_body, default_voice="am_liam")

    def test_a_duplicate_id_is_refused_rather_than_reported_twice(self):
        """⛔ A manifest keyed by id cannot carry two outcomes for one key."""
        with pytest.raises(InvalidJob, match="duplicate segment id: s1"):
            parse_job({"segments": [
                {"id": "s1", "text": "one"},
                {"id": "s1", "text": "two"},
            ]}, default_voice="am_liam")

    def test_too_many_segments_is_refused_naming_the_limit(self):
        with pytest.raises(InvalidJob, match=str(MAX_SEGMENTS)):
            parse_job({"segments": [
                {"id": f"s{n}", "text": "x"} for n in range(MAX_SEGMENTS + 1)
            ]}, default_voice="am_liam")

    def test_a_refusal_never_echoes_the_text(self):
        identifier = "profile-9876543210"
        with pytest.raises(InvalidJob) as raised:
            parse_job({"segments": [{"id": "s1", "text": identifier}],
                       "format": "wav"}, default_voice="am_liam")
        assert identifier not in str(raised.value)

    def test_nothing_is_synthesised_when_parsing_fails(self, tmp_path):
        engine = FakeEngine()
        with pytest.raises(InvalidJob):
            parse_job({"segments": []}, default_voice="am_liam")
        assert engine.calls == []
        assert list(tmp_path.iterdir()) == []

    def test_the_default_voice_is_used_when_the_job_names_none(self):
        job = parse_job({"segments": [{"id": "s1", "text": "x"}]},
                        default_voice="am_liam")
        assert job.voice == "am_liam"
        assert job.fmt == "mp3"
