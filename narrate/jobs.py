"""A batch of keyed segments in, one manifest out. The shape a corpus needs.

⭐ **Why a batch at all.** A corpus is thousands of speech units and the page's
highlight sync needs one clip per unit, so a request per segment makes
per-request overhead the difference between minutes and hours. A job also lets
this service parallelise internally later without any client learning that it
did.

## ⛔ The manifest reports EVERY submitted id, in submission order

⭐ **One entry per submitted id, always**, so `len(manifest["segments"])` equals
the number of segments sent and a caller never has to diff two lists to find
what is missing. A manifest listing only successes is a manifest whose omissions
are silent, which is the shape of failure this project keeps meeting: a check
that can be skipped, and the skip is invisible.

⛔ **The failure report is IN the manifest, not beside it.** A second document
would need its own fetch, its own version and its own way of being forgotten;
the outcome of a segment is a property of that segment, so it is a field on that
segment's entry.

| `status` | |
|---|---|
| `synthesised` | the engine ran and produced it |
| `cached` | ⭐ **the engine was NOT called**; an artifact with this address was already stored |
| `failed` | this segment did not produce an artifact. `reason` and `error` say why |
| `skipped` | ⚠️ not attempted, because the job stopped early. See below |

## ⛔ Two failures, and only one of them stops the job

⭐ **`engine_failed` is per-segment; `engine_unavailable` stops the run.** The
distinction is `narrate.engine.errors`'s own: a bad answer to *this* input says
nothing about the next segment, but *nothing answered at all* predicts the next
three thousand timing out the same way. So a job whose engine has gone away
stops at the first such failure and marks the rest `skipped` -- ⛔ **and every
segment already finished is still in the manifest with its address.** Successful
work is never discarded, which is exactly what the row asks for; what is avoided
is spending an hour rediscovering that a container is down.

⚠️ **The HTTP status of a well-formed job is always `200`**, whatever the mix of
outcomes. The job ran; the per-segment results are data. A caller reads
`counts` -- it has to read the manifest anyway to learn the addresses, so there
is no path on which the outcome is missed. A request that is malformed *as a
job* never runs at all and is a `400`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .artifacts import ADDRESS_FIELDS, ADDRESS_SCHEME
from .config import SUPPORTED_FORMATS
from .engine import EngineError, EngineUnavailable
from .synthesis import UnsupportedFormat, synthesise

#: Every status a segment entry can carry. ⛔ A closed set: `consuming.json`
#: declares it and a test asserts the two are the same list, so a status added
#: here without being published is a failure rather than a surprise.
SEGMENT_STATUSES = ("synthesised", "cached", "failed", "skipped")

#: Why a segment has no artifact. ⛔ Also closed, and also declared.
FAILURE_REASONS = ("engine_unavailable", "engine_failed", "not_synthesisable")

#: How the address a caller can recompute for itself is built. ⭐ Published so
#: an incremental consumer can decide what to submit BEFORE it submits.
ADDRESSING = {
    "scheme": ADDRESS_SCHEME,
    "hash": "sha256",
    "over": list(ADDRESS_FIELDS),
    "encoding": "utf-8, each field length-prefixed as '<bytes>:' before the "
                "bytes; chunk_chars as its decimal digits",
    "order": [ADDRESS_SCHEME, *ADDRESS_FIELDS],
}


def addressing(chunk_chars):
    """`ADDRESSING` plus THIS deployment's chunk budget.

    ⛔ **The budget is part of the address and is a deployment setting**, so a
    caller that wants to recompute an address before submitting needs its
    value and cannot get it from a constant. Publishing the recipe without it
    would be publishing a recipe nobody can follow.
    """
    return dict(ADDRESSING, chunk_chars=chunk_chars)

#: ⛔ A closed pattern for a caller's own segment id. It never reaches the
#: filesystem -- the artifact id does, and that is minted here -- but it is
#: echoed back in the manifest, so it is bounded and printable rather than
#: arbitrary. A framework speech id (`unit-01-s003`) fits comfortably.
_SEGMENT_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

#: ⚠️ A bound on one job, not on a corpus. The body cap
#: (`server.MAX_BODY_BYTES`) bites long before this for real prose; this is here
#: so a pathological body of ten thousand empty segments is refused by a message
#: that names the limit rather than by a timeout.
MAX_SEGMENTS = 5000


class InvalidJob(ValueError):
    """The request is not a well-formed job. ⛔ Nothing was synthesised."""


@dataclass(frozen=True)
class Segment:
    """One keyed unit of text, as the caller sent it."""

    id: str
    text: str


@dataclass(frozen=True)
class Job:
    """A validated job: what to say, in what voice, in what format."""

    segments: tuple
    voice: str
    fmt: str


def parse_job(request, default_voice):
    """A `Job` from a decoded JSON request body, or raise `InvalidJob`.

    ⛔ **Every refusal names what is PERMITTED and never echoes the text.** A
    message quoting a segment's prose would write it into whatever log the
    operator pastes somewhere, which is the disclosure the gate exists to
    prevent -- by a slower route.
    """
    if not isinstance(request, dict):
        raise InvalidJob("body must be a JSON object")

    segments = request.get("segments")
    if not isinstance(segments, list):
        raise InvalidJob("segments must be a list of {id, text} objects")
    if not segments:
        raise InvalidJob("segments must not be empty")
    if len(segments) > MAX_SEGMENTS:
        raise InvalidJob(f"a job carries at most {MAX_SEGMENTS} segments")

    voice = request.get("voice") or default_voice
    if not isinstance(voice, str):
        raise InvalidJob("voice must be a string")
    fmt = request.get("format") or SUPPORTED_FORMATS[0]
    if not isinstance(fmt, str):
        raise InvalidJob("format must be a string")
    if fmt not in SUPPORTED_FORMATS:
        raise InvalidJob(f"format must be one of: {', '.join(SUPPORTED_FORMATS)}")

    return Job(segments=_parse_segments(segments), voice=voice, fmt=fmt)


def _parse_segments(raw):
    """The segment list, validated. ⛔ Ids are unique and never echo text."""
    parsed = []
    seen = set()
    for position, entry in enumerate(raw):
        where = f"segment {position}"
        if not isinstance(entry, dict):
            raise InvalidJob(f"{where} must be an object with id and text")
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not _SEGMENT_ID.match(identifier):
            raise InvalidJob(
                f"{where}: id must be 1-128 characters of "
                "letters, digits, dot, underscore, colon or hyphen, "
                "beginning with a letter or digit"
            )
        if identifier in seen:
            # ⛔ Not a warning. The manifest is keyed by id and cannot report
            # two outcomes under one key without one of them being invisible.
            raise InvalidJob(f"duplicate segment id: {identifier}")
        seen.add(identifier)
        text = entry.get("text")
        if not isinstance(text, str):
            raise InvalidJob(f"{where} ({identifier}): text must be a string")
        parsed.append(Segment(id=identifier, text=text))
    return tuple(parsed)


def run_job(job, engine, store, chunk_chars, media_types, provides):
    """Run every segment and return the manifest as a plain dictionary.

    ⛔ Does not raise for a segment's failure: a failure is an entry in the
    manifest. It raises only what a programming error would raise.
    """
    entries = []
    halted = None
    for segment in job.segments:
        if halted is not None:
            entries.append(_skipped(segment, halted))
            continue
        entry, halted = _run_segment(
            segment, job, engine, store, chunk_chars, media_types
        )
        entries.append(entry)
    return _manifest(job, entries, provides, chunk_chars)


def _run_segment(segment, job, engine, store, chunk_chars, media_types):
    """One segment's manifest entry, and the reason to stop or `None`."""
    try:
        result = synthesise(
            segment.text, job.voice, job.fmt,
            engine=engine, store=store, chunk_chars=chunk_chars,
            media_types=media_types, keep_audio=False,
        )
    except EngineUnavailable as exc:
        # ⛔ Nothing answered. The next segment will not fare better.
        return _failed(segment, "engine_unavailable", exc), "engine_unavailable"
    except EngineError as exc:
        # The engine answered and the answer was unusable. This segment only.
        return _failed(segment, "engine_failed", exc), None
    except (UnsupportedFormat, ValueError) as exc:
        # Empty or unchunkable text. The job's other segments are unaffected.
        return _failed(segment, "not_synthesisable", exc), None
    entry = {"id": segment.id,
             "status": "cached" if result.cached else "synthesised"}
    entry.update(result.summary())
    # `cached` is already said by `status`; two spellings of one fact is one
    # more thing that can disagree.
    entry.pop("cached", None)
    return entry, None


def _failed(segment, reason, exc):
    return {
        "id": segment.id,
        "status": "failed",
        "reason": reason,
        # ⛔ The engine's own message, which by `engine/errors.py`'s contract
        # never interpolates the text that was sent.
        "error": str(exc),
    }


def _skipped(segment, reason):
    return {
        "id": segment.id,
        "status": "skipped",
        "reason": reason,
        "error": "not attempted: the job stopped after an earlier segment",
    }


def _manifest(job, entries, provides, chunk_chars):
    counts = {status: 0 for status in SEGMENT_STATUSES}
    for entry in entries:
        counts[entry["status"]] += 1
    return {
        # ⛔ The manifest is a WIRE SHAPE and takes no contract row of its own:
        # it is versioned by the service's promise, which is `provides` in
        # `consuming.json` (Ruling 330(b)). This echoes that number so a caller
        # holding only a response knows which promise produced it.
        "provides": provides,
        "voice": job.voice,
        "format": job.fmt,
        "addressing": addressing(chunk_chars),
        "counts": dict(counts, total=len(entries)),
        "ok": counts["failed"] == 0 and counts["skipped"] == 0,
        "segments": entries,
    }
