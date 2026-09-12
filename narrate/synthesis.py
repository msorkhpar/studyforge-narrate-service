"""One text in, one finished artifact out. The service's whole unit of work.

Five steps, in this order, and the order is the design:

0. **Address** the request (`narrate.artifacts.address_for`) and look it up in
   the store. ⭐ **A hit returns immediately and the engine is never called** --
   which is the whole of the idempotence this service promises, and the
   mechanism R10's audio carve-out names.
1. **Split** the text into chunks (`narrate.chunking`), because a caller sends
   one text of any length and never stitches anything.
2. **Synthesise** each chunk at the engine (`narrate.engine`), in order.
3. **Verify** the joined bytes really are an MPEG audio stream
   (`narrate.mpeg`) -- so an engine that answers `200` with an error page, or
   with a truncated response, fails here instead of producing a file that will
   not play.
4. **Store** it atomically (`narrate.artifacts`), which is the step that must
   be last: nothing appears under the artifact's final name until every chunk
   has been synthesised and the result has been checked.

⭐ **Failing before step 4 leaves the store exactly as it was.** That is the
carried-over property stated from the other end: there is no window in which a
partial artifact exists under a name a caller could fetch.

⛔ **A CACHE HIT DOES NOT CLAIM THE ENGINE DEPLOYED NOW.** The artifact on disk
was made by whatever engine ran the first time, which may not be the one
answering today. Its record is read back with it and *that* is what the
response reports. Reporting the current engine for a cached artifact would be
the first lie in this surface.

⛔ **`keep_audio=False` exists for the batch route and it is not an
optimisation.** A job of three thousand segments that held every artifact's
bytes in memory in order to describe them would be measured in gigabytes; a
manifest needs the address and the numbers, never the audio.

⛔ **No gate runs here.** The caller gates its text before the request; see the
package docstring for why a second copy in this service would be a liability
rather than a safety net.

**Why the chunks are joined by concatenation and not by a muxer.** An MPEG
elementary stream is a sequence of independently decodable frames, so joining
two of them yields one playable stream. That is only true of `mp3`, which is
why `config.SUPPORTED_FORMATS` is the closed set it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import mpeg
from .artifacts import address_for
from .chunking import chunk_text
from .config import SUPPORTED_FORMATS
from .engine import EngineFailed, EngineIdentity


class UnsupportedFormat(ValueError):
    """The requested audio format is not one this service produces."""


@dataclass(frozen=True)
class Synthesised:
    """A finished artifact, and what is worth saying about it."""

    artifact_id: str
    media_type: str
    fmt: str
    voice: str
    #: ⭐ Which engine made it, recorded at the moment it was made -- and read
    #: back from the store on a cache hit, so it is always the engine that
    #: actually produced these bytes. See `engine/base.py`.
    identity: EngineIdentity
    chunks: int
    #: ⚠️ `None` when the caller asked not to keep it (`keep_audio=False`).
    #: `byte_count` is the size either way.
    audio: bytes | None
    byte_count: int
    frames: int
    seconds: float
    sample_rate: int
    #: ⭐ Whether this cost a synthesis. `True` means the engine was not called.
    cached: bool

    def summary(self):
        """The JSON body describing this artifact. Never includes the text."""
        return {
            "artifact_id": self.artifact_id,
            "url": f"/v1/artifacts/{self.artifact_id}",
            "format": self.fmt,
            "media_type": self.media_type,
            "voice": self.voice,
            "engine": self.identity.engine,
            "engine_profile": self.identity.profile,
            "engine_model": self.identity.model,
            "chunks": self.chunks,
            "bytes": self.byte_count,
            "seconds": self.seconds,
            "sample_rate": self.sample_rate,
            "cached": self.cached,
        }

    def record(self):
        """What is written beside the audio, for a later run to read back."""
        return {
            "format": self.fmt,
            "voice": self.voice,
            "bytes": self.byte_count,
            "chunks": self.chunks,
            "frames": self.frames,
            "seconds": self.seconds,
            "sample_rate": self.sample_rate,
            "engine": self.identity.engine,
            "engine_profile": self.identity.profile,
            "engine_model": self.identity.model,
        }


def synthesise(text, voice, fmt, engine, store, chunk_chars, media_types,
               keep_audio=True):
    """Run the steps and return a `Synthesised`.

    Raises `UnsupportedFormat`, `ValueError` (empty text), or an
    `EngineError` -- and in every one of those cases the store is untouched.
    """
    if fmt not in SUPPORTED_FORMATS:
        permitted = ", ".join(SUPPORTED_FORMATS)
        raise UnsupportedFormat(f"format must be one of: {permitted}")

    artifact_id = address_for(text, voice, fmt)

    hit = _from_store(artifact_id, store, media_types, keep_audio)
    if hit is not None:
        return hit

    chunks = chunk_text(text, chunk_chars)

    # ⭐ Read BEFORE the first chunk, so every chunk of one artifact is
    # attributed to the engine that actually started it.
    identity = engine.identity()

    pieces = [engine.synthesize_chunk(chunk, voice, fmt) for chunk in chunks]
    audio = b"".join(pieces)

    try:
        shape = mpeg.describe(audio)
    except mpeg.NotMpegAudio as exc:
        # Deliberately re-raised as an engine failure: from the caller's side
        # the engine produced something that is not audio, and that is a
        # failure of the deployment rather than of the request.
        raise EngineFailed(f"the engine's output is not playable audio: {exc}") from exc

    result = Synthesised(
        artifact_id=artifact_id,
        media_type=media_types[fmt],
        fmt=fmt,
        voice=voice,
        identity=identity,
        chunks=len(chunks),
        audio=audio if keep_audio else None,
        byte_count=len(audio),
        frames=shape["frames"],
        seconds=shape["seconds"],
        sample_rate=shape["sample_rate"],
        cached=False,
    )
    store.put(artifact_id, audio, result.record())
    return result


def _from_store(artifact_id, store, media_types, keep_audio):
    """A `Synthesised` describing what is already stored, or `None`.

    ⛔ Everything but the media type comes from the artifact's own record, so a
    hit describes the bytes on disk rather than the request that found them.
    """
    record = store.lookup(artifact_id)
    if record is None:
        return None
    return Synthesised(
        artifact_id=artifact_id,
        media_type=media_types[record["format"]],
        fmt=record["format"],
        voice=record["voice"],
        identity=EngineIdentity(
            engine=record["engine"],
            profile=record["engine_profile"],
            model=record["engine_model"],
        ),
        chunks=record["chunks"],
        audio=store.read(artifact_id) if keep_audio else None,
        byte_count=record["bytes"],
        frames=record["frames"],
        seconds=record["seconds"],
        sample_rate=record["sample_rate"],
        cached=True,
    )
