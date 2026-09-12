"""What an artifact is called, and why it lands in one step.

⭐ **The property this module exists for**: an artifact appears at its final
name **complete or not at all**. Bytes are written to a temporary sibling in the
same directory and `os.replace`d onto the destination -- one atomic rename
within one filesystem -- so an interrupted or failed run never leaves a
truncated file that looks finished. A partial audio file is the worst kind of
failure this service could have: it is *playable*, so nothing downstream
notices, and it simply stops mid-sentence.

The temporary lands in the same directory on purpose. `os.replace` is atomic
only within a filesystem, and a system temporary directory is routinely a
different one; staging there and moving across would be a copy, which is exactly
the non-atomic write this module removes.

## ⭐ The id is a CONTENT ADDRESS, and this module is the one place it is minted

⛔ **`address_for(text, voice, fmt, chunk_chars)` replaced a random `mint_id()`, and the
change is the whole of this store's contribution to idempotence.** Two requests
that would produce the same audio produce the same id, so the second finds the
first already stored and synthesises nothing (`narrate.synthesis`).

⚠️ **Synthesised audio is NOT byte-for-byte reproducible** -- a speech model may
emit different bytes for identical input -- so the address is emphatically *not*
a digest of the audio. A digest of the output would change on every
re-synthesis, which is a cache that never hits. ⭐ **The address is a digest of
the REQUEST**: the inputs that decide what is said and how.

### ⛔ What the address is computed over, and what it deliberately is not

| in the address | |
|---|---|
| the scheme's own name and version | so a future change to what is hashed cannot collide with today's addresses |
| `format` | different formats are different bytes, and the store keeps one file per address |
| `voice` | changing a corpus's voice must invalidate that corpus's audio, and only that corpus's |
| `chunk_chars` | ⛔ **the budget decides WHERE the text is cut, each chunk is a separate engine request, and the pieces are concatenated — so a different budget is different bytes at every join** |
| `text` | ⭐ **exactly as submitted. No normalisation. See below** |

⛔ **THE ENGINE IS NOT IN THE ADDRESS**, and that is a decision rather than an
omission. Putting it there would invalidate every cached artifact the moment a
deployment moved between the CPU and GPU profiles of the *same* model -- a
redeployment would re-synthesise a whole corpus. What is owed instead is
honesty about what actually made a cached artifact, and that is what the record
beside the bytes is for: a cache hit reports **the engine that produced it**,
never the engine deployed now.

⛔ **The text is hashed exactly as submitted, and the alternative was
considered.** `narrate.chunking` strips its input, so `" Hello "` and `"Hello"`
do produce identical audio, and an address that stripped would spare one
synthesis. It does not strip, because a normalisation here is a second rule
that must agree with the chunker **forever**: if the two ever disagree, two
different texts share an address and the store serves the wrong audio for one
of them. ⭐ **The chosen error direction is to synthesise something twice, never
to speak the wrong words.**

⭐ **Each field is LENGTH-PREFIXED before it is hashed.** Plain concatenation
would give `voice="a", text="bc"` and `voice="ab", text="c"` the same address.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path

#: The addressing scheme's own name, hashed first and before anything else. ⛔ A
#: change to WHAT is hashed, or to HOW it is encoded, bumps the number here --
#: which is what stops a new scheme's address colliding with an old one's over
#: different inputs. It is also published, so a caller can recompute an address
#: itself and decide what to submit (`narrate.jobs`, and the manifest).
ADDRESS_SCHEME = "narrate-address-2"

#: The request fields the address covers, in the order they are hashed.
#:
#: ⛔ **`chunk_chars` is here and its absence was a real defect** (`CTO-69/9`).
#: The budget decides where the text is cut; each chunk is a SEPARATE engine
#: request and the pieces are concatenated, so a different budget is a
#: different byte-stream at every join. Two deployments sharing a store served
#: audio that did not match the request, under an address asserting that it
#: did. ⚠️ **The scheme number above moved with it**, per this module's own
#: rule: a change to WHAT is hashed bumps it, so no address minted under the
#: incomplete set can be mistaken for one minted under this one.
ADDRESS_FIELDS = ("format", "voice", "chunk_chars", "text")

#: `hashlib.sha256().hexdigest()` is 64 lowercase hexadecimal characters.
ADDRESS_HEX_CHARS = 64

#: The version of the record written beside each artifact. ⚠️ Internal to this
#: component: nothing outside it reads the store directory, which is why this is
#: not a published contract. A consumer reads `GET /v1/artifacts/<id>`.
RECORD_VERSION = 1

#: Every key a record must carry to be usable. A record missing one is treated
#: as no record at all, so the artifact is synthesised again rather than
#: described from a half-written file.
RECORD_FIELDS = (
    "record", "format", "voice", "bytes", "chunks",
    "frames", "seconds", "sample_rate",
    "engine", "engine_profile", "engine_model",
)

#: ⛔ A closed set. An id arrives from a URL path in `GET /v1/artifacts/<id>`,
#: and this pattern is what stops `..`, a separator or an absolute path from
#: ever reaching the filesystem.
#:
#: ⭐ **64 hex is what `address_for` mints. 32 hex is still admitted**, and
#: deliberately: a store written by version 0.1.0 holds randomly minted 32-hex
#: artifacts, and widening the pattern is what keeps them fetchable by the ids
#: their callers already recorded. ⚠️ **Nothing mints a 32-hex id any more**, and
#: such an artifact carries no record, so it is never a cache hit.
_ID_PATTERN = re.compile(r"\A(?:[0-9a-f]{32}|[0-9a-f]{64})\Z")


class UnknownArtifact(KeyError):
    """No artifact by that id. Nothing was read."""


def address_for(text, voice, fmt, chunk_chars):
    """The content address of the artifact these inputs would produce.

    Deterministic, and a pure function of its arguments: the same four values
    always give the same 64-character address, on any host and in any process.

    ⚠️ **`chunk_chars` is included even though it changes nothing for a text
    shorter than the budget**, which is most segments. Retuning it therefore
    re-synthesises a store that would have been byte-identical. ⭐ **The
    alternative — addressing the CHUNK LIST rather than the text and the budget
    — is exactly correct and was rejected**: it makes the address impossible to
    recompute without reimplementing the chunker, and `consuming.json`
    publishes the recipe precisely so an incremental build need not. ⛔ **The
    error direction is the one this module chose for whitespace too:
    synthesise twice, never speak the wrong words.**
    """
    digest = hashlib.sha256()
    for field in (ADDRESS_SCHEME, fmt, voice, str(chunk_chars), text):
        encoded = field.encode("utf-8")
        # ⛔ Length-prefixed, so no choice of field values can be re-cut into a
        # different tuple with the same digest.
        digest.update(f"{len(encoded)}:".encode("ascii"))
        digest.update(encoded)
    return digest.hexdigest()


def is_artifact_id(value):
    """Whether `value` is a well-formed id this store could hold."""
    return isinstance(value, str) and _ID_PATTERN.match(value) is not None


class ArtifactStore:
    """A directory of finished artifacts, addressed by content.

    Each artifact is two files: the audio, and a small JSON **record** beside
    it saying what made it. ⭐ **The record is what makes a cache hit honest** --
    a hit reports the engine, the duration and the chunk count of the artifact
    that is actually on disk, rather than of the engine that happens to be
    deployed at the moment somebody asks.

    ⛔ **A cache hit reads the record and NOT the audio.** That is the point: a
    job of three thousand cached segments must cost three thousand small reads,
    never three thousand multi-megabyte ones.
    """

    #: ⛔ Publish locks, STRIPED rather than one per address. A dict keyed by
    #: address would grow without bound in a long-running service; 64 stripes
    #: is a fixed cost, and two unrelated addresses colliding on one stripe
    #: merely serialises two writes, which is harmless.
    _STRIPES = 64

    def __init__(self, directory, suffix="mp3"):
        self._directory = Path(directory)
        self._suffix = suffix
        self._publish_locks = [threading.Lock() for _ in range(self._STRIPES)]

    def _publish_lock(self, artifact_id):
        """The lock guarding `artifact_id`'s two-file publish."""
        return self._publish_locks[int(artifact_id[:8], 16) % self._STRIPES]

    @property
    def directory(self):
        return self._directory

    def path_for(self, artifact_id):
        """Filesystem path of `artifact_id`, whether or not it exists.

        Raises `UnknownArtifact` for an id this store could not hold. The check
        is what keeps a caller-supplied path component from resolving anywhere
        but inside the store.
        """
        if not is_artifact_id(artifact_id):
            raise UnknownArtifact(
                "artifact ids are 32 or 64 lowercase hexadecimal characters"
            )
        return self._directory / f"{artifact_id}.{self._suffix}"

    def record_path_for(self, artifact_id):
        """Path of the JSON record beside `artifact_id`'s audio."""
        return self.path_for(artifact_id).with_suffix(".json")

    def read(self, artifact_id):
        """Bytes of a finished artifact.

        Raises `UnknownArtifact` if it is not there. Because the write is
        atomic, anything readable here is complete.
        """
        path = self.path_for(artifact_id)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise UnknownArtifact("no artifact with that id") from None

    def lookup(self, artifact_id):
        """The record of a **complete** stored artifact, or `None`.

        ⛔ This is the cache predicate, and it is deliberately strict: it
        answers with a record only when the audio exists *and* a record beside
        it parses *and* carries every field of `RECORD_FIELDS` at the current
        version. Anything else -- no record, a truncated one, one from an older
        scheme -- reads as a **miss**, so the segment is synthesised again and
        both files are rewritten. ⭐ **A miss costs one synthesis; a half-read
        record would cost a manifest that describes an artifact wrongly.**
        """
        try:
            audio_path = self.path_for(artifact_id)
        except UnknownArtifact:
            return None
        if not audio_path.exists():
            return None
        try:
            raw = self.record_path_for(artifact_id).read_text(encoding="utf-8")
            record = json.loads(raw)
        except (OSError, ValueError):
            return None
        if not isinstance(record, dict):
            return None
        if record.get("record") != RECORD_VERSION:
            return None
        if any(field not in record for field in RECORD_FIELDS):
            return None
        return record

    def put(self, artifact_id, data, record):
        """Write `data` and its `record`, each atomically. Returns the path.

        ⭐ **The audio goes first and the record second, so the RECORD is the
        commit point.** `lookup` requires both, so a crash between the two
        leaves a miss rather than a hit that cannot be described -- and the
        next attempt overwrites both.

        ⛔ **The pair is published under a lock, and that is about CONCURRENCY
        rather than about crashes.** The server is a `ThreadingHTTPServer`, and
        content addressing makes same-address concurrency the EXPECTED case:
        two callers sending identical prose both miss the cache and both
        synthesise. Without the lock, one writer's audio can be published
        beside the other writer's record -- two complete artifacts, but a
        `seconds` a caller uses for highlight sync that belongs to the twin.

        ⚠️ **The lock is in-process, which is the concurrency this service
        actually creates** (one serving process per deployment). Two PROCESSES
        sharing one store can still cross a record with its twin's audio; both
        halves are complete and valid and only the byte and duration figures
        can belong to the sibling synthesis. ⭐ **Named rather than implied: the
        unique temporary below is what makes even that case safe from a
        TRUNCATED file, which is the failure that matters.**
        """
        if not data:
            raise ValueError("refusing to store an empty artifact")
        destination = self.path_for(artifact_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._publish_lock(artifact_id):
            _atomic_write(destination, data)
            _atomic_write(
                self.record_path_for(artifact_id),
                json.dumps(dict(record, record=RECORD_VERSION),
                           sort_keys=True).encode("utf-8"),
            )
        return destination


def _atomic_write(destination, data):
    """`data` at `destination`, via a UNIQUE temporary sibling and one rename.

    ⛔ **The temporary is unique per call, and a name derived from the
    destination was a real defect** (`CTO-69/7`, `CTO-69/8`). Every writer of
    one address shared one staging path, so one writer's `write_bytes`
    truncated another's staged bytes and the first rename published the
    mixture under a valid content address -- ⚠️ **precisely the truncated-file
    failure this module opens by claiming to have eliminated, and a truncated
    mp3 plays.** The shared name also made the `finally` below delete a
    temporary another writer was still using, so its rename raised.

    ⭐ **`mkstemp` in the destination's own directory keeps both carried
    properties**: the staging file is a sibling, so `os.replace` is still one
    atomic rename within one filesystem, and the temporary is still removed on
    every failure path.
    """
    handle, staged = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(staged)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, destination)
    finally:
        # `os.replace` consumed the temporary on the happy path; this is for
        # every other path, and it is why an interrupted run leaves neither a
        # truncated file nor a stray temporary behind. ⭐ It can now only ever
        # remove THIS call's own staging file.
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
