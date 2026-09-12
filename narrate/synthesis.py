"""One text in, one finished artifact out. The service's whole unit of work.

Four steps, in this order, and the order is the design:

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
from .artifacts import mint_id
from .chunking import chunk_text
from .config import SUPPORTED_FORMATS
from .engine import EngineFailed


class UnsupportedFormat(ValueError):
    """The requested audio format is not one this service produces."""


@dataclass(frozen=True)
class Synthesised:
    """A finished artifact, and what is worth saying about it."""

    artifact_id: str
    media_type: str
    fmt: str
    voice: str
    chunks: int
    audio: bytes
    frames: int
    seconds: float
    sample_rate: int

    def summary(self):
        """The JSON body describing this artifact. Never includes the text."""
        return {
            "artifact_id": self.artifact_id,
            "url": f"/v1/artifacts/{self.artifact_id}",
            "format": self.fmt,
            "media_type": self.media_type,
            "voice": self.voice,
            "chunks": self.chunks,
            "bytes": len(self.audio),
            "seconds": self.seconds,
            "sample_rate": self.sample_rate,
        }


def synthesise(text, voice, fmt, engine, store, chunk_chars, media_types):
    """Run the four steps and return a `Synthesised`.

    Raises `UnsupportedFormat`, `ValueError` (empty text), or an
    `EngineError` -- and in every one of those cases the store is untouched.
    """
    if fmt not in SUPPORTED_FORMATS:
        permitted = ", ".join(SUPPORTED_FORMATS)
        raise UnsupportedFormat(f"format must be one of: {permitted}")

    chunks = chunk_text(text, chunk_chars)

    pieces = [engine.synthesize_chunk(chunk, voice, fmt) for chunk in chunks]
    audio = b"".join(pieces)

    try:
        shape = mpeg.describe(audio)
    except mpeg.NotMpegAudio as exc:
        # Deliberately re-raised as an engine failure: from the caller's side
        # the engine produced something that is not audio, and that is a
        # failure of the deployment rather than of the request.
        raise EngineFailed(f"the engine's output is not playable audio: {exc}") from exc

    artifact_id = mint_id()
    store.put(artifact_id, audio)

    return Synthesised(
        artifact_id=artifact_id,
        media_type=media_types[fmt],
        fmt=fmt,
        voice=voice,
        chunks=len(chunks),
        audio=audio,
        frames=shape["frames"],
        seconds=shape["seconds"],
        sample_rate=shape["sample_rate"],
    )
