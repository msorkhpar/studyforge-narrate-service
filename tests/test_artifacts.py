"""`narrate.artifacts` -- the property is *complete or not at all*."""

from __future__ import annotations

import pytest

from narrate.artifacts import ArtifactStore, UnknownArtifact, is_artifact_id, mint_id


def test_a_minted_id_is_accepted_by_the_pattern():
    for _ in range(50):
        assert is_artifact_id(mint_id())


def test_ids_are_not_reused():
    assert len({mint_id() for _ in range(500)}) == 500


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
    None,
    17,
])
def test_a_bad_id_never_reaches_the_filesystem(bad):
    assert not is_artifact_id(bad)


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
    artifact_id = mint_id()
    store.put(artifact_id, b"audio-bytes")
    assert store.read(artifact_id) == b"audio-bytes"


def test_put_creates_the_directory(tmp_path):
    store = ArtifactStore(tmp_path / "deep" / "nested")
    store.put(mint_id(), b"x")
    assert (tmp_path / "deep" / "nested").is_dir()


def test_an_empty_artifact_is_refused(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="empty"):
        store.put(mint_id(), b"")
    assert list(tmp_path.iterdir()) == []


def test_reading_an_absent_artifact_raises(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(UnknownArtifact):
        store.read(mint_id())


def test_an_interrupted_write_leaves_no_artifact_and_no_temporary(tmp_path, monkeypatch):
    """The whole reason this module exists.

    `os.replace` is made to fail, which is the moment between *bytes written*
    and *bytes visible under the final name*. Afterwards the directory must
    hold neither a truncated artifact nor a stray temporary -- a partial audio
    file is the dangerous failure, because it plays.
    """
    store = ArtifactStore(tmp_path)
    artifact_id = mint_id()

    def boom(source, destination):
        raise OSError("interrupted")

    monkeypatch.setattr("narrate.artifacts.os.replace", boom)
    with pytest.raises(OSError):
        store.put(artifact_id, b"half-an-mp3")

    assert list(tmp_path.iterdir()) == []
    assert not store.path_for(artifact_id).exists()


def test_the_temporary_is_a_sibling_of_the_destination(tmp_path):
    """Atomicity is only true within one filesystem.

    Staging in a system temporary directory and moving across would be a copy.
    The assertion is that the staged file is in the destination's own
    directory, which is what makes the rename atomic.
    """
    store = ArtifactStore(tmp_path)
    artifact_id = mint_id()
    seen = {}

    real_replace = __import__("os").replace

    def watch(source, destination):
        seen["source_parent"] = str(source).rsplit("/", 1)[0]
        seen["destination_parent"] = str(destination).rsplit("/", 1)[0]
        return real_replace(source, destination)

    import narrate.artifacts as module
    original = module.os.replace
    module.os.replace = watch
    try:
        store.put(artifact_id, b"bytes")
    finally:
        module.os.replace = original

    assert seen["source_parent"] == seen["destination_parent"] == str(tmp_path)


def test_overwriting_an_artifact_is_still_atomic(tmp_path):
    store = ArtifactStore(tmp_path)
    artifact_id = mint_id()
    store.put(artifact_id, b"first")
    store.put(artifact_id, b"second-and-longer")
    assert store.read(artifact_id) == b"second-and-longer"
    assert len(list(tmp_path.iterdir())) == 1
