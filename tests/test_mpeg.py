"""`narrate.mpeg` -- the gate that makes *playable* a checked claim."""

from __future__ import annotations

import pytest

from narrate import mpeg
from tests.support import (
    FRAME2_BYTES, FRAME2_SECONDS, FRAME_BYTES, FRAME_SECONDS,
    MEASURED_FRAME2_HEADER, id3_tag, mpeg2_bytes, mpeg_bytes, one_frame,
    one_frame_mpeg2,
)


def test_one_frame_is_described():
    shape = mpeg.describe(mpeg_bytes(1))
    assert shape["frames"] == 1
    assert shape["sample_rate"] == 44100
    assert shape["seconds"] == pytest.approx(FRAME_SECONDS, abs=1e-3)


def test_many_frames_sum_to_their_duration():
    shape = mpeg.describe(mpeg_bytes(100))
    assert shape["frames"] == 100
    assert shape["seconds"] == pytest.approx(100 * FRAME_SECONDS, abs=1e-2)


def test_a_leading_id3_tag_is_skipped():
    shape = mpeg.describe(id3_tag() + mpeg_bytes(3))
    assert shape["frames"] == 3


def test_a_tag_between_two_concatenated_pieces_is_skipped():
    """The shape of a joined multi-chunk synthesis.

    Every piece an encoder returns can carry its own tag. A parser that
    stopped at the first one would under-report the duration of a file that
    plays perfectly well, so the concatenation property has to survive it.
    """
    joined = id3_tag() + mpeg_bytes(4) + id3_tag() + mpeg_bytes(6)
    assert mpeg.describe(joined)["frames"] == 10


def test_html_is_not_audio():
    """The failure this gate exists for: a 200 that is not audio."""
    with pytest.raises(mpeg.NotMpegAudio):
        mpeg.describe(b"<!doctype html><html><body>gateway error</body></html>")


def test_empty_bytes_are_not_audio():
    with pytest.raises(mpeg.NotMpegAudio):
        mpeg.describe(b"")


def test_json_is_not_audio():
    with pytest.raises(mpeg.NotMpegAudio):
        mpeg.describe(b'{"detail": "model not loaded"}')


def test_a_truncated_first_frame_is_not_audio():
    with pytest.raises(mpeg.NotMpegAudio):
        mpeg.describe(one_frame()[:40])


def test_a_free_bitrate_header_is_refused():
    """Bitrate index 0 is 'free'; the frame length is then not computable."""
    header = bytes((0xFF, 0xFB, 0x00, 0x44))
    with pytest.raises(mpeg.NotMpegAudio):
        mpeg.describe(header + b"\x00" * 400)


def test_a_reserved_sample_rate_is_refused():
    header = bytes((0xFF, 0xFB, 0x9C, 0x44))   # sample-rate index 3, reserved
    with pytest.raises(mpeg.NotMpegAudio):
        mpeg.describe(header + b"\x00" * 400)


def test_a_layer_two_frame_is_refused():
    """Layer II is real MPEG audio and still not what this service produces."""
    header = bytes((0xFF, 0xFD, 0x90, 0x44))   # layer bits = 2 -> Layer II
    with pytest.raises(mpeg.NotMpegAudio):
        mpeg.describe(header + b"\x00" * 400)


def test_trailing_junk_after_real_frames_is_tolerated():
    shape = mpeg.describe(mpeg_bytes(5) + b"TAGtrailing-metadata")
    assert shape["frames"] == 5


# -- the arm the deployment actually takes ---------------------------------
#
# ⛔ **Everything above builds MPEG-1 frames; the pinned engine emits MPEG-2.**
# The live reading in `docs/engine-measurement.md` found that `_read_header`'s
# MPEG-2 arm -- a different bitrate table and half the samples per frame -- had
# never been exercised by anything, in a suite of five hundred tests, while
# being the only arm production ever reaches. These close that.


def test_the_builder_reproduces_the_MEASURED_engine_header():
    """⭐ The fixture is derived, and it agrees with the real engine's bytes.

    If this fails, either the derivation is wrong or the engine changed --
    and either way the measurement document is the thing to re-take.
    """
    assert one_frame_mpeg2()[:4] == MEASURED_FRAME2_HEADER


def test_an_MPEG_2_frame_is_described_at_its_own_sample_rate():
    shape = mpeg.describe(mpeg2_bytes(1))
    assert shape["frames"] == 1
    assert shape["sample_rate"] == 24000
    assert shape["seconds"] == pytest.approx(FRAME2_SECONDS, abs=1e-3)


def test_an_MPEG_2_frame_is_384_bytes_not_the_MPEG_1_size():
    """⛔ The size arithmetic is the half that a wrong `samples` gets wrong.

    576 samples, not 1152: a parser that used the MPEG-1 constant here would
    walk off the end of every real frame and read the stream as junk.
    """
    assert FRAME2_BYTES == 384
    assert FRAME2_BYTES != FRAME_BYTES


def test_a_real_length_MPEG_2_stream_sums_to_the_measured_duration():
    """The single-request reading: 123 frames, 2.952 s, and 47276 bytes in all.

    ⭐ Every byte of the real response is accounted for by this arithmetic --
    123 x 384 plus a 44-byte ID3 tag -- which is why the reading is quotable
    rather than merely plausible.
    """
    stream = id3_tag(payload_size=34) + mpeg2_bytes(123)
    assert len(stream) == 47276
    shape = mpeg.describe(stream)
    assert shape["frames"] == 123
    assert shape["sample_rate"] == 24000
    assert shape["seconds"] == pytest.approx(2.952, abs=1e-3)


def test_MPEG_1_and_MPEG_2_frames_in_one_stream_are_REFUSED():
    """⛔ A concatenation of two engines' output is not one artifact.

    The sample rates disagree, so `describe` must refuse rather than report a
    duration for a file that no decoder will play straight through.
    """
    with pytest.raises(mpeg.NotMpegAudio):
        mpeg.describe(mpeg2_bytes(3) + mpeg_bytes(3))
