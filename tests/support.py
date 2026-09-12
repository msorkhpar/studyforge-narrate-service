"""Shared test material: a real-shaped MPEG frame, and a fake engine.

⭐ **The frames here are synthesised by arithmetic, not sampled from a real
file.** A committed binary fixture would prove that the parser agrees with one
encoder's output; building the header from the specification proves it agrees
with the specification, and lets a test ask for a stream of an exact known
duration -- which is what makes the duration assertions meaningful rather than
self-confirming.

⚠️ **Known-incomplete, deliberately:** only MPEG-1 Layer III at 44.1 kHz is
built here, because that is what the engine emits. A second sample rate is one
more constant when something needs it.
"""

from __future__ import annotations

#: MPEG-1 Layer III, 128 kbit/s, 44.1 kHz, no padding, joint stereo.
FRAME_SAMPLE_RATE = 44100
FRAME_BITRATE = 128_000
FRAME_SAMPLES = 1152
FRAME_BYTES = (FRAME_SAMPLES // 8) * FRAME_BITRATE // FRAME_SAMPLE_RATE
FRAME_SECONDS = FRAME_SAMPLES / FRAME_SAMPLE_RATE


def one_frame(filler=b"\x00"):
    """One well-formed MPEG-1 Layer III frame, header plus filler."""
    header = bytes((0xFF, 0xFB, 0x90, 0x44))
    return header + filler * (FRAME_BYTES - len(header))


def mpeg_bytes(frames=1):
    """`frames` well-formed frames, concatenated."""
    return one_frame() * frames


def id3_tag(payload_size=16):
    """A minimal ID3v2 tag, the thing an encoder puts in front of its output."""
    size = payload_size
    synchsafe = bytes((
        (size >> 21) & 0x7F, (size >> 14) & 0x7F,
        (size >> 7) & 0x7F, size & 0x7F,
    ))
    return b"ID3" + b"\x04\x00" + b"\x00" + synchsafe + b"\x00" * size


class FakeEngine:
    """An engine that returns known bytes and records what it was asked.

    This is what lets every route, every failure branch and the chunking
    property be tested with no engine running and no GPU present. A suite that
    needed the deployment up is a suite that does not run.
    """

    name = "fake"

    def __init__(self, per_chunk=None, fail_with=None, reachable_=True):
        self._per_chunk = per_chunk if per_chunk is not None else mpeg_bytes(1)
        self._fail_with = fail_with
        self._reachable = reachable_
        self.calls = []

    def synthesize_chunk(self, text, voice, fmt):
        self.calls.append({"text": text, "voice": voice, "format": fmt})
        if self._fail_with is not None:
            raise self._fail_with
        if callable(self._per_chunk):
            return self._per_chunk(text)
        return self._per_chunk

    def reachable(self):
        return self._reachable
