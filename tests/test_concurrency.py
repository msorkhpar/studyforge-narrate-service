"""⛔ The store under the concurrency its own server enables.

`narrate/server.py`'s `NarrateServer` is a `ThreadingHTTPServer` with
`daemon_threads = True`, so two requests are served in two threads. ⭐ **Content
addressing makes SAME-ADDRESS concurrency the expected case rather than the
exotic one**: two callers submitting identical prose both miss the cache, both
synthesise, and both write the same destination.

⚠️ **And the two synthesise DIFFERENT BYTES** -- `narrate/artifacts.py`'s own
docstring says a speech model may not emit identical bytes for identical input,
which is why the address is over the request. So the two writers do not merely
duplicate work; they race with different content.

⛔ **The failure this module exists to catch is the one that module opens by
claiming to have eliminated**: a partial file published under a valid content
address. A truncated mp3 *plays*. Nothing downstream notices.

⭐ **Every test here is sequenced by `threading.Event`, never by a sleep**, so it
is deterministic rather than a race that usually comes out one way.
"""

from __future__ import annotations

import os
import threading

import pytest

from narrate.artifacts import ArtifactStore, address_for

RECORD = {
    "format": "mp3", "voice": "am_liam", "bytes": 0, "chunks": 1,
    "frames": 1, "seconds": 0.026, "sample_rate": 44100,
    "engine": "fake", "engine_profile": "unknown", "engine_model": "fake-1",
}

#: Long enough that a truncation is unambiguous in the assertion's message.
BIG = b"A" * 40_000
SMALL = b"B" * 400

TIMEOUT = 10


def an_address():
    return address_for("Identical prose, sent twice.", "am_liam", "mp3", 1800,
                       "fake-1")


def test_concurrent_writers_to_one_address_use_DIFFERENT_temporaries(tmp_path):
    """⛔ The property, stated as the thing that is directly observable.

    A temporary named from the destination is the SAME path for every writer of
    one address. This captures the source of every `os.replace` and asserts
    they are all distinct -- deterministic, and it does not depend on winning a
    race to demonstrate the bug.
    """
    store = ArtifactStore(tmp_path)
    address = an_address()
    seen = []
    lock = threading.Lock()

    import narrate.artifacts as module
    real_replace = module.os.replace

    def watch(source, destination):
        with lock:
            seen.append(str(source))
        return real_replace(source, destination)

    module.os.replace = watch
    try:
        threads = [
            threading.Thread(target=store.put, args=(address, BIG, RECORD))
            for _ in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(TIMEOUT)
    finally:
        module.os.replace = real_replace

    assert all(not thread.is_alive() for thread in threads)
    # 8 writers x (one audio, one record).
    assert len(seen) == 16, seen
    assert len(set(seen)) == len(seen), (
        f"{len(seen)} writes shared {len(set(seen))} temporary path(s); "
        "a temporary named from its destination is one path for every writer "
        "of one address"
    )


def test_a_writer_never_publishes_ANOTHER_writers_bytes(tmp_path):
    """⛔ The corrupt publish, reproduced deterministically.

    ⚠️ **The interleaving is the whole test and an earlier version of it got
    this wrong** -- pausing only one writer let the other commit first, which
    reproduces `CTO-69/8`'s exception and NOT the corruption. The order that
    corrupts is: A stages, B stages **over A's staged bytes**, A renames, B
    renames. Both writers are therefore held at their rename and released by
    this test in that order.

    With one shared temporary, A's rename publishes **B's** content while A
    goes on to write **A's** record beside it. ⭐ Asserted against the record as
    well as the bytes, because the dangerous form is the one where the file and
    what describes it disagree.
    """
    store = ArtifactStore(tmp_path)
    address = an_address()

    at_rename = {"A": threading.Event(), "B": threading.Event()}
    release = {"A": threading.Event(), "B": threading.Event()}
    failures = []

    import narrate.artifacts as module
    real_replace = module.os.replace

    def watch(source, destination):
        name = threading.current_thread().name
        if name in at_rename and str(destination).endswith(".mp3"):
            at_rename[name].set()
            release[name].wait(TIMEOUT)
        return real_replace(source, destination)

    def put(payload, record):
        try:
            store.put(address, payload, record)
        except Exception as exc:              # noqa: BLE001 - recorded, not raised
            failures.append(f"{type(exc).__name__}: {exc}")

    module.os.replace = watch
    try:
        writer_a = threading.Thread(
            target=put, args=(BIG, dict(RECORD, bytes=len(BIG))), name="A")
        writer_a.start()
        assert at_rename["A"].wait(TIMEOUT), "writer A never staged"

        writer_b = threading.Thread(
            target=put, args=(SMALL, dict(RECORD, bytes=len(SMALL))), name="B")
        writer_b.start()
        # ⚠️ NOT asserted, and deliberately: with the publish lock in place B
        # blocks before it ever reaches a rename, and requiring it to stage
        # would deadlock the test against the FIXED code. Whether B gets that
        # far is the implementation's business; the invariant below is not.
        at_rename["B"].wait(2)

        # ⛔ A renames and RUNS TO COMPLETION -- including writing A's record --
        # and only then is B released. ⚠️ Setting both events back to back does
        # NOT order them, and an earlier version of this test did exactly that
        # and passed against the defect it exists to catch.
        release["A"].set()
        writer_a.join(TIMEOUT)
        assert not writer_a.is_alive(), "writer A never finished"
        release["B"].set()
        writer_b.join(TIMEOUT)
    finally:
        module.os.replace = real_replace
        for event in release.values():
            event.set()

    published = store.read(address)
    assert published in (BIG, SMALL), (
        f"published {len(published)} bytes, which is neither writer's content "
        f"({len(BIG)} or {len(SMALL)}); a partial mp3 plays"
    )
    record = store.lookup(address)
    assert record is not None
    assert record["bytes"] == len(published), (
        f"the record says {record['bytes']} bytes and the audio on disk is "
        f"{len(published)}; the record describes a different artifact"
    )


def test_neither_writer_fails_because_the_other_tidied_up(tmp_path):
    """⛔ `CTO-69/8`: the unconditional `finally` unlink, with a shared name.

    The writer whose rename already consumed its own temporary deletes the
    temporary another writer is still using, and that writer's rename raises
    out of `put`. ⭐ Recorded separately from the corruption because the
    `finally` reads as correct in isolation -- only the shared NAME makes it
    wrong.
    """
    store = ArtifactStore(tmp_path)
    address = an_address()
    failures = []
    barrier = threading.Barrier(6, timeout=TIMEOUT)

    def put(n):
        try:
            barrier.wait()
            store.put(address, b"C" * (1000 + n), dict(RECORD, bytes=1000 + n))
        except Exception as exc:              # noqa: BLE001 - recorded, not raised
            failures.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=put, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(TIMEOUT)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == [], f"{len(failures)} of 6 concurrent writers raised: {failures}"


def test_no_temporary_survives_a_burst_of_concurrent_writers(tmp_path):
    """The store is left tidy: one audio, one record, and nothing staged."""
    store = ArtifactStore(tmp_path)
    address = an_address()
    threads = [
        threading.Thread(target=store.put, args=(address, b"D" * 900, RECORD))
        for _ in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(TIMEOUT)

    names = sorted(p.name for p in tmp_path.iterdir())
    assert [n for n in names if ".tmp" in n] == [], names
    assert len(names) == 2, names


@pytest.mark.parametrize("payload", [b"", b"x"])
def test_the_temporary_is_still_a_sibling_and_still_cleaned_up(tmp_path, payload):
    """⚠️ Whatever the fix to the NAME, the two carried properties must hold."""
    store = ArtifactStore(tmp_path)
    address = an_address()
    if not payload:
        with pytest.raises(ValueError):
            store.put(address, payload, RECORD)
        assert list(tmp_path.iterdir()) == []
        return

    seen = []
    import narrate.artifacts as module
    real_replace = module.os.replace

    def watch(source, destination):
        seen.append((os.path.dirname(str(source)), os.path.dirname(str(destination))))
        return real_replace(source, destination)

    module.os.replace = watch
    try:
        store.put(address, payload, RECORD)
    finally:
        module.os.replace = real_replace

    assert len(seen) == 2
    for source_parent, destination_parent in seen:
        assert source_parent == destination_parent == str(tmp_path)
    assert [p.name for p in tmp_path.iterdir() if ".tmp" in p.name] == []


# ---------------------------------------------------------------------------
# ⛔ The PUBLISH LOCK, which `CTO-69/14` correctly charged as proved by nothing.
#
# ⚠️ **The unique temporary and the lock are two different properties and the
# tests above only reach the first.** A reviewer nulled the lock on a clean
# extract and the whole suite stayed green -- in the commit that shipped a
# thirteen-control harness. Everything below fails without it, and controls
# `p14` and `p15` plant its two halves.
# ---------------------------------------------------------------------------


def test_the_audio_and_its_record_are_published_as_ONE_PAIR(tmp_path):
    """⛔ `CTO-69/14`: what the write-side lock buys, and nothing else did.

    Unique temporaries guarantee each published FILE is one complete write.
    They say nothing about the two files belonging to the same writer. Ordered
    so that A publishes its audio, B publishes both of its files, and A then
    publishes its record: without the lock the store ends up holding **B's
    audio beside A's record**, and a caller reads a duration that belongs to a
    synthesis it does not have.
    """
    store = ArtifactStore(tmp_path)
    address = an_address()
    at_record = threading.Event()
    release = threading.Event()
    failures = []

    import narrate.artifacts as module
    real_replace = module.os.replace

    def watch(source, destination):
        if (threading.current_thread().name == "A"
                and str(destination).endswith(".json")):
            at_record.set()
            release.wait(TIMEOUT)
        return real_replace(source, destination)

    def put(name, payload):
        try:
            store.put(address, payload, dict(RECORD, bytes=len(payload)))
        except Exception as exc:              # noqa: BLE001 - recorded
            failures.append(f"{name}: {type(exc).__name__}: {exc}")

    module.os.replace = watch
    try:
        writer_a = threading.Thread(target=put, args=("A", BIG), name="A")
        writer_a.start()
        assert at_record.wait(TIMEOUT), "writer A never reached its record"

        writer_b = threading.Thread(target=put, args=("B", SMALL), name="B")
        writer_b.start()
        # ⚠️ Not asserted: WITH the lock B blocks here and never gets this far.
        writer_b.join(2)

        release.set()
        writer_a.join(TIMEOUT)
        writer_b.join(TIMEOUT)
    finally:
        module.os.replace = real_replace
        release.set()

    assert failures == [], failures
    record = store.lookup(address)
    audio = store.read(address)
    assert record is not None
    assert record["bytes"] == len(audio), (
        f"the record says {record['bytes']} bytes and the audio is "
        f"{len(audio)}; one writer's record is beside another's audio"
    )


def test_a_reader_never_pairs_one_writers_record_with_anothers_audio(tmp_path):
    """⛔ `CTO-69/15`: the write-side lock alone leaves the READER crossing.

    `lookup` then `read` is two unlocked reads. A writer landing between them
    hands back the previous record beside the new audio -- **one process, not
    two**, and in the case this module calls expected.
    """
    store = ArtifactStore(tmp_path)
    address = an_address()
    store.put(address, SMALL, dict(RECORD, bytes=len(SMALL)))

    writers = []
    real_read = store.read

    def read_with_a_writer_landing_first(artifact_id):
        if not writers:
            writer = threading.Thread(
                target=store.put,
                args=(address, BIG, dict(RECORD, bytes=len(BIG))),
            )
            writers.append(writer)
            writer.start()
            # ⭐ WITHOUT the lock the writer lands inside this wait. WITH it,
            # the writer blocks on the stripe this snapshot is holding.
            writer.join(2)
        return real_read(artifact_id)

    store.read = read_with_a_writer_landing_first
    try:
        record, audio = store.snapshot(address)
    finally:
        store.read = real_read
        for writer in writers:
            writer.join(TIMEOUT)

    assert record is not None and audio is not None
    assert record["bytes"] == len(audio), (
        f"the snapshot's record says {record['bytes']} bytes and its audio is "
        f"{len(audio)}; the pair was taken across a write"
    )


def test_a_record_only_snapshot_takes_the_lock_too(tmp_path):
    """⛔ The batch path reads no audio, and it crosses just the same.

    ⚠️ An old record describing new audio is the same defect with the evidence
    removed, so `with_audio=False` must wait for a writer mid-pair as well.
    """
    store = ArtifactStore(tmp_path)
    address = an_address()
    store.put(address, SMALL, dict(RECORD, bytes=len(SMALL)))

    at_record = threading.Event()
    release = threading.Event()
    observed = []

    import narrate.artifacts as module
    real_replace = module.os.replace

    def watch(source, destination):
        if (threading.current_thread().name == "W"
                and str(destination).endswith(".json")):
            at_record.set()
            release.wait(TIMEOUT)
        return real_replace(source, destination)

    module.os.replace = watch
    try:
        writer = threading.Thread(
            target=store.put,
            args=(address, BIG, dict(RECORD, bytes=len(BIG))), name="W")
        writer.start()
        assert at_record.wait(TIMEOUT), "the writer never reached its record"

        reader = threading.Thread(
            target=lambda: observed.append(store.snapshot(address, with_audio=False)))
        reader.start()
        reader.join(2)
        # ⛔ With the lock the reader is still blocked; without it, it has
        # already answered with the OLD record while new audio is on disk.
        answered_early = not reader.is_alive()

        release.set()
        writer.join(TIMEOUT)
        reader.join(TIMEOUT)
    finally:
        module.os.replace = real_replace
        release.set()

    assert not answered_early, (
        "a record-only snapshot answered while a writer was between its two "
        "renames, so it described audio that is no longer on disk"
    )
    record = observed[0][0]
    assert record["bytes"] == len(store.read(address))
