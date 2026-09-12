"""Where a synthesised artifact lands, and why it lands there in one step.

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

⛔ **The id is minted at random, and that is a deliberate non-decision.** It is
*not* a content address: this service does not deduplicate, does not cache, and
re-synthesising the same text twice produces two artifacts. Content addressing
and the cache it enables are a separate piece of work, and a half-built address
here -- one callers could start to rely on for idempotence it does not have --
would be worse than an id that is obviously opaque.
"""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

#: 128 bits as lowercase hex. Long enough that a collision is not a thing that
#: happens, short enough to read back in a log line.
_ID_BYTES = 16

#: ⛔ A closed set. An id arrives from a URL path in `GET /v1/artifacts/<id>`,
#: and this pattern is what stops `..`, a separator or an absolute path from
#: ever reaching the filesystem. It admits exactly what `mint_id` produces.
_ID_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")


class UnknownArtifact(KeyError):
    """No artifact by that id. Nothing was read."""


def mint_id():
    """A fresh opaque artifact id."""
    return secrets.token_hex(_ID_BYTES)


def is_artifact_id(value):
    """Whether `value` is a well-formed id this store could have minted."""
    return isinstance(value, str) and _ID_PATTERN.match(value) is not None


class ArtifactStore:
    """A directory of finished artifacts, addressed by opaque id."""

    def __init__(self, directory, suffix="mp3"):
        self._directory = Path(directory)
        self._suffix = suffix

    @property
    def directory(self):
        return self._directory

    def path_for(self, artifact_id):
        """Filesystem path of `artifact_id`, whether or not it exists.

        Raises `UnknownArtifact` for an id this store could not have minted.
        The check is what keeps a caller-supplied path component from
        resolving anywhere but inside the store.
        """
        if not is_artifact_id(artifact_id):
            raise UnknownArtifact("artifact ids are 32 lowercase hexadecimal characters")
        return self._directory / f"{artifact_id}.{self._suffix}"

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

    def put(self, artifact_id, data):
        """Write `data` as `artifact_id`, atomically. Returns the path.

        The temporary is removed on every failure path, so a crashed or refused
        synthesis leaves the directory exactly as it found it.
        """
        if not data:
            raise ValueError("refusing to store an empty artifact")
        destination = self.path_for(artifact_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{destination.name}.tmp"
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        finally:
            # `os.replace` consumed the temporary on the happy path; this is
            # for every other path, and it is why an interrupted run leaves
            # neither a truncated artifact nor a stray temporary behind.
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return destination
