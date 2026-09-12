"""`narrate.synthesis` -- the four steps, and what each failure leaves behind."""

from __future__ import annotations

import json

import pytest

from narrate.artifacts import ArtifactStore
from narrate.config import FORMAT_MEDIA_TYPES
from narrate.engine import EngineFailed, EngineUnavailable
from narrate.synthesis import UnsupportedFormat, synthesise
from tests.support import FakeEngine, mpeg_bytes


def run(text, tmp_path, engine=None, chunk_chars=1800, fmt="mp3", voice="am_liam"):
    store = ArtifactStore(tmp_path)
    return synthesise(
        text, voice, fmt,
        engine=engine if engine is not None else FakeEngine(),
        store=store,
        chunk_chars=chunk_chars,
        media_types=FORMAT_MEDIA_TYPES,
    ), store


def test_a_short_text_is_one_chunk_and_one_artifact(tmp_path):
    engine = FakeEngine()
    result, store = run("A short sentence of study prose.", tmp_path, engine)
    assert result.chunks == 1
    assert len(engine.calls) == 1
    assert store.read(result.artifact_id) == result.audio


def test_a_long_text_is_many_chunks_and_still_one_artifact(tmp_path):
    """⭐ The property: the caller sent one text and got one artifact back."""
    engine = FakeEngine()
    text = " ".join(f"Sentence {n} of the corpus." for n in range(400))
    result, store = run(text, tmp_path, engine, chunk_chars=200)

    assert result.chunks > 10
    assert len(engine.calls) == result.chunks
    assert store.read(result.artifact_id) == result.audio
    assert result.frames == result.chunks


def test_the_chunks_are_sent_in_order(tmp_path):
    engine = FakeEngine()
    text = "\n\n".join(f"Paragraph {n}." for n in range(20))
    run(text, tmp_path, engine, chunk_chars=20)
    assert [call["text"] for call in engine.calls] == [
        f"Paragraph {n}." for n in range(20)
    ]


def test_the_voice_and_format_reach_the_engine(tmp_path):
    engine = FakeEngine()
    run("Some prose.", tmp_path, engine, voice="af_bella")
    assert engine.calls[0]["voice"] == "af_bella"
    assert engine.calls[0]["format"] == "mp3"


def test_the_artifact_is_a_real_mpeg_stream(tmp_path):
    result, _ = run("Prose.", tmp_path, FakeEngine(per_chunk=mpeg_bytes(7)))
    assert result.frames == 7
    assert result.sample_rate == 44100
    assert result.seconds > 0


def test_the_summary_never_carries_the_text(tmp_path):
    """R7's shape at the response boundary."""
    identifier = "profile-9876543210"
    result, _ = run(f"Visit {identifier} for details.", tmp_path)
    assert identifier not in repr(result.summary())


def test_an_unsupported_format_is_refused_and_names_what_is_permitted(tmp_path):
    engine = FakeEngine()
    with pytest.raises(UnsupportedFormat, match="mp3"):
        run("Prose.", tmp_path, engine, fmt="wav")
    assert engine.calls == []
    assert list(tmp_path.iterdir()) == []


def test_empty_text_is_refused_before_the_engine(tmp_path):
    engine = FakeEngine()
    with pytest.raises(ValueError):
        run("   ", tmp_path, engine)
    assert engine.calls == []
    assert list(tmp_path.iterdir()) == []


def test_an_unreachable_engine_leaves_the_store_untouched(tmp_path):
    engine = FakeEngine(fail_with=EngineUnavailable("down"))
    with pytest.raises(EngineUnavailable):
        run("Prose.", tmp_path, engine)
    assert list(tmp_path.iterdir()) == []


def test_output_that_is_not_audio_is_an_engine_failure_and_stores_nothing(tmp_path):
    """The gate in step 3, from the caller's side.

    An engine that answers `200` with an error page must not produce an
    artifact. If it did, the failure would surface as a file that does not
    play, at whatever later point somebody tried.
    """
    engine = FakeEngine(per_chunk=b"<html>gateway error</html>")
    with pytest.raises(EngineFailed, match="not playable"):
        run("Prose.", tmp_path, engine)
    assert list(tmp_path.iterdir()) == []


def test_a_failure_on_a_later_chunk_stores_nothing(tmp_path):
    """Nothing is published until every chunk has been synthesised."""
    calls = {"n": 0}

    def flaky(_text):
        calls["n"] += 1
        if calls["n"] == 3:
            raise EngineUnavailable("engine went away mid-run")
        return mpeg_bytes(1)

    engine = FakeEngine(per_chunk=flaky)
    text = "\n\n".join(f"Paragraph {n}." for n in range(10))
    with pytest.raises(EngineUnavailable):
        run(text, tmp_path, engine, chunk_chars=20)
    assert list(tmp_path.iterdir()) == []


def test_two_identical_requests_are_ONE_artifact_and_one_synthesis(tmp_path):
    """⭐ The inversion of `NS-01`'s `test_two_identical_requests_are_two_artifacts`.

    That test pinned this service's deliberate NON-idempotence so that the
    change would be visible rather than silent. Here is the change: one
    address, one stored artifact, and ⛔ **the second engine is never called at
    all** -- which is the property, rather than merely getting the same id back.
    """
    store = ArtifactStore(tmp_path)
    first_engine, second_engine = FakeEngine(), FakeEngine()
    first = synthesise("Same prose.", "am_liam", "mp3", first_engine, store,
                       1800, FORMAT_MEDIA_TYPES)
    second = synthesise("Same prose.", "am_liam", "mp3", second_engine, store,
                        1800, FORMAT_MEDIA_TYPES)

    assert first.artifact_id == second.artifact_id
    assert len(first_engine.calls) == 1
    assert second_engine.calls == []
    assert first.cached is False
    assert second.cached is True
    # One audio file and one record beside it. Not two of either.
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".json", ".mp3"]
    assert second.audio == first.audio


class TestTheArtifactRecordsWhatMadeIt:
    def test_the_identity_is_read_once_before_the_first_chunk(self):
        """⭐ So every chunk of one artifact is attributed to one engine.

        A `identity()` read per chunk, or after the loop, would let a long
        synthesis be stamped with an engine that only arrived halfway through.
        """
        engine = _CountingIdentity()
        result = synthesise(
            "A sentence. " * 400, "am_liam", "mp3",
            engine=engine, store=_NullStore(), chunk_chars=100,
            media_types=FORMAT_MEDIA_TYPES,
        )
        assert result.chunks > 1
        assert engine.identity_calls == 1
        assert engine.calls_before_first_identity == 0

    def test_the_summary_carries_the_three_fields_and_never_the_text(self):
        engine = FakeEngine(profile="cpu", model="fake-1")
        result = synthesise(
            "A secret sentence.", "am_liam", "mp3",
            engine=engine, store=_NullStore(), chunk_chars=1800,
            media_types=FORMAT_MEDIA_TYPES,
        )
        summary = result.summary()
        assert summary["engine"] == "fake"
        assert summary["engine_profile"] == "cpu"
        assert summary["engine_model"] == "fake-1"
        assert "secret" not in json.dumps(summary)

    def test_the_label_is_what_a_header_carries(self):
        result = synthesise(
            "Prose.", "am_liam", "mp3",
            engine=FakeEngine(profile="gpu"), store=_NullStore(),
            chunk_chars=1800, media_types=FORMAT_MEDIA_TYPES,
        )
        assert result.identity.label == "fake/gpu"


class _NullStore:
    """A store that never holds anything, so every lookup is a miss."""

    def snapshot(self, artifact_id, with_audio=True):
        return None, None

    def lookup(self, artifact_id):
        return None

    def put(self, artifact_id, audio, record):
        return None


class _CountingIdentity(FakeEngine):
    """Records the order of `identity()` against `synthesize_chunk()`."""

    def __init__(self):
        super().__init__()
        self.identity_calls = 0
        self.calls_before_first_identity = None

    def identity(self):
        if self.identity_calls == 0:
            self.calls_before_first_identity = len(self.calls)
        self.identity_calls += 1
        return super().identity()
