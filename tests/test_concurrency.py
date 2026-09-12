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
    return address_for("Identical prose, sent twice.", "am_liam", "mp3", 1800)


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
