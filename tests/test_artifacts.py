"""`narrate.artifacts` -- the address, and *complete or not at all*."""

from __future__ import annotations

import json

import pytest

from narrate.artifacts import (
    ADDRESS_HEX_CHARS,
    ADDRESS_SCHEME,
    RECORD_FIELDS,
    RECORD_VERSION,
    ArtifactStore,
    UnknownArtifact,
    address_for,
    is_artifact_id,
)

RECORD = {
    "format": "mp3", "voice": "am_liam", "bytes": 11, "chunks": 1,
    "frames": 1, "seconds": 0.026, "sample_rate": 44100,
    "engine": "fake", "engine_profile": "unknown", "engine_model": "fake-1",
}


def an_address(text="Some prose.", voice="am_liam", fmt="mp3", chunk_chars=1800,
               engine_model="kokoro"):
    return address_for(text, voice, fmt, chunk_chars, engine_model)


class TestTheAddressIsAFunctionOfTheRequest:
    def test_it_is_sixty_four_lowercase_hex_and_the_pattern_admits_it(self):
        address = an_address()
        assert len(address) == ADDRESS_HEX_CHARS
        assert address == address.lower()
        assert is_artifact_id(address)

    def test_the_same_request_always_gives_the_same_address(self):
        assert an_address() == an_address()

    @pytest.mark.parametrize("changed", [
        {"text": "Other prose."},
        {"voice": "af_bella"},
        # ⛔ NS-04: the model decides how a voice sounds, so it is in the
        # address. The engine FAMILY and the hardware PROFILE are not.
        {"engine_model": "some-other-model"},
    ])
    def test_changing_an_input_changes_the_address(self, changed):
        assert an_address() != an_address(**changed)

    def test_the_encoding_is_pinned_to_a_GOLDEN_digest(self):
        """⛔ A concrete value, because *it is deterministic* is unfalsifiable.

        ⚠️ **This replaces a test that was born vacuous** (`CTO-69/10`): it
        asserted that a non-empty string was truthy, under a docstring making a
        real claim about the address. ⭐ A golden digest fails if the scheme
        name, the field ORDER, the length prefixing or the text encoding
        changes -- which is every way the recipe published in `consuming.json`
        could silently stop matching the code.

        ⛔ **If this fails, the address scheme changed and `ADDRESS_SCHEME` must
        be bumped with it** -- see the module docstring's own rule.
        """
        assert address_for("The first speech unit.", "am_liam", "mp3", 1800,
                           "kokoro") == (
            "63d84579ec58153ac099a6002625f0bfa86bc4f8ab3ddc0fb7df8a1361096a80"
        )

    def test_the_fields_are_length_prefixed_so_they_cannot_be_recut(self):
        """⛔ The classic collision, asserted rather than argued.

        ⚠️ **THE INPUTS ARE LOAD-BEARING AND THIS TEST HAS GONE VACUOUS ONCE
        AND BEEN RE-AIMED TWICE.** Its original pair -- `voice="a", text="bc"`
        against `voice="ab", text="c"` -- collided only while `voice` and
        `text` were adjacent in the hashed order. Inserting `chunk_chars`
        between them separated the two and the test then passed with the
        length prefixing REMOVED, which the committed control `p09` caught by
        firing on the wrong tests.

        ⛔ **NS-04 inserted `engine_model` between `chunk_chars` and `text` and
        separated the SECOND pair the same way**, which is precisely what the
        warning above predicted. ⭐ **The pair now collides on the newly
        adjacent fields, `engine_model` and `text`** -- so the assertion tracks
        whichever boundary the current order actually has.

        ⭐ **The collision is ASSERTED rather than assumed**: the first
        assertion pins that these inputs really do share one naive
        concatenation, and it fails loudly if a future field order separates
        them again. Only then does the second assertion mean anything.
        """
        first = {"text": "0bc", "voice": "a", "fmt": "mp3", "chunk_chars": 1800,
                 "engine_model": "m"}
        second = {"text": "bc", "voice": "a", "fmt": "mp3", "chunk_chars": 1800,
                  "engine_model": "m0"}

        def naive(fields):
            """What an unprefixed digest would be fed."""
            return "".join([
                ADDRESS_SCHEME, fields["fmt"], fields["voice"],
                str(fields["chunk_chars"]), fields["engine_model"],
                fields["text"],
            ])

        assert naive(first) == naive(second), (
            "these inputs no longer collide without prefixing, so the "
            "assertion below would hold for a digest that did not prefix; "
            "choose a pair that collides under the current field order"
        )
        assert address_for(**first) != address_for(**second)

    def test_the_text_is_not_normalised_and_that_is_the_safe_direction(self):
        """⚠️ Deliberate: `" Hello "` and `"Hello"` are different addresses.

        A normalisation here would be a second rule that must agree with
        `narrate.chunking` forever; if the two ever disagreed, two different
        texts would share an address and one would be served the other's audio.
        One extra synthesis is the cheaper error.
        """
        assert an_address(text=" Hello ") != an_address(text="Hello")


@pytest.mark.parametrize("bad", [
    "../../etc/passwd",
    "/etc/passwd",
    "..",
    "",
    "ABCDEF0123456789abcdef0123456789",   # uppercase
    "0123456789abcdef0123456789abcde",    # 31 characters
    "0123456789abcdef0123456789abcdef0",  # 33 characters
    "0123456789abcdef0123456789abcde/",
    "0123456789abcdef0123456789abcdez",
    "0" * 63,
    "0" * 65,
    None,
    17,
])
def test_a_bad_id_never_reaches_the_filesystem(bad):
    assert not is_artifact_id(bad)


def test_a_thirty_two_hex_id_is_still_admitted(tmp_path):
    """⭐ A store written by 0.1.0 holds randomly minted 32-hex artifacts.

    Widening the pattern to 64 without keeping 32 would make every id a caller
    already recorded un-fetchable. ⚠️ Nothing mints one any more.
    """
    legacy = "0123456789abcdef0123456789abcdef"
    assert is_artifact_id(legacy)
    store = ArtifactStore(tmp_path)
    store.path_for(legacy).write_bytes(b"older-audio")
    assert store.read(legacy) == b"older-audio"
    # ⛔ ...and it is never a cache hit, because it carries no record.
    assert store.lookup(legacy) is None


def test_path_for_refuses_a_bad_id(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(UnknownArtifact):
        store.path_for("../../escape")


def test_a_traversal_id_cannot_read_a_neighbouring_file(tmp_path):
    """The behavioural half: a refusal that still read the file is no refusal."""
    secret = tmp_path.parent / "neighbour.txt"
    secret.write_text("not for the store")
    store = ArtifactStore(tmp_path / "store")
    with pytest.raises(UnknownArtifact):
        store.read("../neighbour.txt")


def test_put_then_read_round_trips(tmp_path):
    store = ArtifactStore(tmp_path)
    store.put(an_address(), b"audio-bytes", RECORD)
    assert store.read(an_address()) == b"audio-bytes"


def test_put_creates_the_directory(tmp_path):
    store = ArtifactStore(tmp_path / "deep" / "nested")
    store.put(an_address(), b"x", RECORD)
    assert (tmp_path / "deep" / "nested").is_dir()


def test_an_empty_artifact_is_refused(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="empty"):
        store.put(an_address(), b"", RECORD)
    assert list(tmp_path.iterdir()) == []


def test_reading_an_absent_artifact_raises(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(UnknownArtifact):
        store.read(an_address())


class TestTheRecordIsTheCachePredicate:
    def test_a_stored_artifact_looks_up_to_its_record(self, tmp_path):
        store = ArtifactStore(tmp_path)
        store.put(an_address(), b"audio", RECORD)
        record = store.lookup(an_address())
        assert record["engine"] == "fake"
        assert record["record"] == RECORD_VERSION
        assert all(field in record for field in RECORD_FIELDS)

    def test_an_absent_artifact_looks_up_to_nothing(self, tmp_path):
        assert ArtifactStore(tmp_path).lookup(an_address()) is None

    def test_a_malformed_id_looks_up_to_nothing_rather_than_raising(self, tmp_path):
        """⛔ The predicate must never be the thing that fails a job."""
        assert ArtifactStore(tmp_path).lookup("../../etc/passwd") is None

    def test_audio_without_a_record_is_a_MISS(self, tmp_path):
        """⭐ The crash-between-the-two-writes case, and it reads as a miss."""
        store = ArtifactStore(tmp_path)
        store.path_for(an_address()).write_bytes(b"orphan")
        assert store.lookup(an_address()) is None

    def test_a_record_without_audio_is_a_MISS(self, tmp_path):
        store = ArtifactStore(tmp_path)
        path = store.record_path_for(an_address())
        path.write_text(json.dumps(dict(RECORD, record=RECORD_VERSION)))
        assert store.lookup(an_address()) is None

    @pytest.mark.parametrize("damage", [
        "not json at all",
        "[]",
        '{"record": 1}',
        '"a string"',
    ])
    def test_an_unusable_record_is_a_MISS_and_never_an_error(self, tmp_path, damage):
        store = ArtifactStore(tmp_path)
        store.put(an_address(), b"audio", RECORD)
        store.record_path_for(an_address()).write_text(damage)
        assert store.lookup(an_address()) is None

    def test_a_record_from_another_version_is_a_MISS(self, tmp_path):
        store = ArtifactStore(tmp_path)
        store.put(an_address(), b"audio", RECORD)
        store.record_path_for(an_address()).write_text(
            json.dumps(dict(RECORD, record=RECORD_VERSION + 1))
        )
        assert store.lookup(an_address()) is None

    def test_the_record_version_is_stamped_by_the_store_not_the_caller(self, tmp_path):
        store = ArtifactStore(tmp_path)
        store.put(an_address(), b"audio", dict(RECORD, record="nonsense"))
        assert store.lookup(an_address())["record"] == RECORD_VERSION


def test_an_interrupted_write_leaves_no_artifact_and_no_temporary(tmp_path, monkeypatch):
    """The whole reason this module exists.

    `os.replace` is made to fail, which is the moment between *bytes written*
    and *bytes visible under the final name*. Afterwards the directory must
    hold neither a truncated artifact nor a stray temporary -- a partial audio
    file is the dangerous failure, because it plays.
    """
    store = ArtifactStore(tmp_path)

    def boom(source, destination):
        raise OSError("interrupted")

    monkeypatch.setattr("narrate.artifacts.os.replace", boom)
    with pytest.raises(OSError):
        store.put(an_address(), b"half-an-mp3", RECORD)

    assert list(tmp_path.iterdir()) == []
    assert not store.path_for(an_address()).exists()


def test_the_temporary_is_a_sibling_of_the_destination(tmp_path):
    """Atomicity is only true within one filesystem.

    Staging in a system temporary directory and moving across would be a copy.
    The assertion is that the staged file is in the destination's own
    directory, which is what makes the rename atomic -- for the record as much
    as for the audio.
    """
    store = ArtifactStore(tmp_path)
    seen = []

    import narrate.artifacts as module
    real_replace = module.os.replace

    def watch(source, destination):
        seen.append((str(source).rsplit("/", 1)[0],
                     str(destination).rsplit("/", 1)[0]))
        return real_replace(source, destination)

    module.os.replace = watch
    try:
        store.put(an_address(), b"bytes", RECORD)
    finally:
        module.os.replace = real_replace

    assert len(seen) == 2  # the audio, then the record
    for source_parent, destination_parent in seen:
        assert source_parent == destination_parent == str(tmp_path)


def test_overwriting_an_artifact_is_still_atomic(tmp_path):
    store = ArtifactStore(tmp_path)
    store.put(an_address(), b"first", RECORD)
    store.put(an_address(), b"second-and-longer", dict(RECORD, bytes=17))
    assert store.read(an_address()) == b"second-and-longer"
    assert store.lookup(an_address())["bytes"] == 17
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".json", ".mp3"]
