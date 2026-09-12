"""Walk an MPEG audio elementary stream and say whether it is really one.

⭐ **Why the service owns this rather than leaving it to the caller.** The
acceptance this repository was built against is *a playable artifact*, and the
only way to keep that honest without a decoder is to check the thing that makes
an artifact playable: that it is a run of well-formed MPEG audio frames, each
one's header agreeing with the next about sample rate and layer.

⛔ **It is a gate, not a statistic.** An engine that returns an HTML error page
with a 200, or 300 bytes of a truncated response, produces something a naive
byte-count check calls a success. Here it fails to parse, the artifact is never
renamed into place, and the caller gets an error instead of a file that will
not play.

It also yields the artifact's duration for free, summed from the frames, which
is what the service reports back.

Standard library only, and no third-party parser: the header is four bytes and
fully specified, and vendoring a dependency to read four bytes would be the
larger cost.
"""

from __future__ import annotations

#: Bitrate table for MPEG-1 Layer III, in kbit/s, indexed by the header's four
#: bitrate bits. Index 0 is "free" and index 15 is invalid; both are rejected.
_BITRATES_V1_L3 = (
    None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, None,
)
#: MPEG-2 and MPEG-2.5, Layer III.
_BITRATES_V2_L3 = (
    None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None,
)
#: Sample rates in Hz, indexed by the header's two sampling bits, per version.
_SAMPLE_RATES = {
    3: (44100, 48000, 32000, None),   # MPEG-1
    2: (22050, 24000, 16000, None),   # MPEG-2
    0: (11025, 12000, 8000, None),    # MPEG-2.5
}
#: Samples per frame for Layer III, per version. MPEG-2 and 2.5 halve it.
_SAMPLES_PER_FRAME = {3: 1152, 2: 576, 0: 576}

_LAYER_III = 1  # the header's two layer bits, for Layer III


class NotMpegAudio(ValueError):
    """The bytes are not a decodable MPEG audio stream."""


def describe(data):
    """Return `{"frames": int, "seconds": float, "sample_rate": int}` for `data`.

    Raises `NotMpegAudio` if the stream carries no frames, or if what follows a
    frame is neither another frame nor recognised trailing metadata.
    """
    offset = _skip_id3(data)
    frames = 0
    seconds = 0.0
    sample_rate = None

    while offset < len(data):
        header = _read_header(data, offset)
        if header is None:
            # An ID3 tag between frames. This is the normal shape of a stream
            # made by concatenating what an encoder returned for each chunk:
            # every piece carries its own tag, and a decoder skips them. Skip
            # it here too rather than stopping and under-reporting the
            # duration of a file that plays perfectly well.
            skipped = _skip_id3(data[offset:])
            if skipped:
                offset += skipped
                continue
            # Trailing bytes that are neither a frame nor a tag. Tolerated only
            # once we have real audio: with no frames yet, it is a failure.
            break
        size, rate, duration = header
        if sample_rate is None:
            sample_rate = rate
        elif rate != sample_rate:
            raise NotMpegAudio(
                "frames disagree about sample rate; the stream is not one piece"
            )
        frames += 1
        seconds += duration
        offset += size

    if frames == 0:
        raise NotMpegAudio("no MPEG audio frame found")
    return {"frames": frames, "seconds": round(seconds, 3), "sample_rate": sample_rate}


def _skip_id3(data):
    """Return the offset past a leading ID3v2 tag, or 0 if there is none."""
    if len(data) >= 10 and data[:3] == b"ID3":
        # Synchsafe integer: seven bits per byte.
        size = 0
        for byte in data[6:10]:
            size = (size << 7) | (byte & 0x7F)
        return 10 + size
    return 0


def _read_header(data, offset):
    """Parse the frame header at `offset`.

    Returns `(frame_bytes, sample_rate, seconds)`, or `None` if `offset` does
    not begin a valid Layer III frame.
    """
    if offset + 4 > len(data):
        return None
    b0, b1, b2, _b3 = data[offset:offset + 4]
    if b0 != 0xFF or (b1 & 0xE0) != 0xE0:
        return None

    version = (b1 >> 3) & 0x03
    layer = (b1 >> 1) & 0x03
    if version == 1 or layer != _LAYER_III:
        return None

    bitrate_index = (b2 >> 4) & 0x0F
    rate_index = (b2 >> 2) & 0x03
    padding = (b2 >> 1) & 0x01

    table = _BITRATES_V1_L3 if version == 3 else _BITRATES_V2_L3
    bitrate = table[bitrate_index]
    sample_rate = _SAMPLE_RATES[version][rate_index]
    if bitrate is None or sample_rate is None:
        return None

    samples = _SAMPLES_PER_FRAME[version]
    size = (samples // 8) * bitrate * 1000 // sample_rate + padding
    if size <= 4 or offset + size > len(data):
        return None
    return size, sample_rate, samples / sample_rate
