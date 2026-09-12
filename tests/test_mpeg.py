"""`narrate.mpeg` -- the gate that makes *playable* a checked claim."""

from __future__ import annotations

import pytest

from narrate import mpeg
from tests.support import FRAME_SECONDS, id3_tag, mpeg_bytes, one_frame


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
