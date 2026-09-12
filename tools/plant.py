"""Negative controls: plant a defect, prove the suite catches it, restore.

⛔ **A green suite that cannot go red measures nothing**, so every property this
repository claims has a control that breaks it deliberately and names the test
that fires. ⭐ **This module is that harness, and it is IN THE TREE because a
reviewer must be able to confirm the repair rather than only the disclosure**
(`CTO-69/11`).

## ⛔ The failure this module is built around, and it happened

A plant is a text substitution. ⚠️ **If its anchor does not match, the
substitution silently does nothing, the suite passes, and the run is recorded
as a control that fired nothing** -- which converts *nothing was caught* into
*nothing was wrong*. ⛔ **That is the worst failure a control harness has, and
it occurred once during `NS-02`**: one plant of twelve did not apply and
produced a green `292` that was very nearly reported as a reading.

⭐ **Two rules follow, and both are enforced here rather than remembered:**

1. ⛔ **An anchor must match EXACTLY ONCE.** Zero means the plant did not arm;
   more than one means it armed somewhere unintended. Either way `plant()`
   raises `PlantDidNotApply` and the caller must not report a reading.
2. ⛔ **A control whose suite stays GREEN is a FAILED control, not a passed
   one.** `run_controls` marks it `DID NOT FIRE`, which is the outcome a
   reader would otherwise have to notice by counting.

⭐ **Restoration is from a copy taken BEFORE the plant, per file** (`W143`), and
it happens in a `finally`, so an exception mid-run cannot leave a planted tree
behind.

## Running it

```bash
python3 -m tools.plant            # every control in CONTROLS
python3 -m tools.plant p07        # one, by id
```
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PlantDidNotApply(RuntimeError):
    """The anchor did not match exactly once. ⛔ No reading may be reported."""


@dataclass(frozen=True)
class Control:
    """One deliberate defect, and what it must break."""

    id: str
    what: str
    path: str
    anchor: str
    replacement: str
    #: The test whose name states the property. Its presence among the
    #: failures is what makes the control evidence rather than noise.
    expects: str


@dataclass
class Result:
    control: Control
    fired: bool
    failed_tests: tuple
    named_test_failed: bool

    @property
    def ok(self):
        """⛔ A control passes only if it fired AND it fired on its own test."""
        return self.fired and self.named_test_failed


def plant(path, anchor, replacement):
    """Substitute `anchor` in `path`, returning the ORIGINAL text.

    ⛔ Raises `PlantDidNotApply` unless `anchor` occurs exactly once, and in
    that case the file is left untouched.
    """
    target = Path(path)
    original = target.read_text(encoding="utf-8")
    occurrences = original.count(anchor)
    if occurrences != 1:
        raise PlantDidNotApply(
            f"{target}: the anchor matched {occurrences} time(s) and a plant "
            "must match exactly once; the file is unchanged and no reading "
            "may be reported from this run"
        )
    target.write_text(original.replace(anchor, replacement), encoding="utf-8")
    return original


def restore(path, original):
    """Put back the text `plant` returned. ⭐ Byte-for-byte, from before."""
    Path(path).write_text(original, encoding="utf-8")


@contextmanager
def planted(path, anchor, replacement):
    """Plant for the duration of the block, and restore whatever happens."""
    original = plant(path, anchor, replacement)
    try:
        yield
    finally:
        restore(path, original)


def failing_tests(output):
    """The test ids pytest reported as failures, from its own summary lines."""
    return tuple(
        line.split(" ", 1)[1].split(" ")[0]
        for line in output.splitlines()
        if line.startswith("FAILED ")
    )


def _pytest(root):
    """Run the suite and return `(exit_code, output)`. No filter in between."""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-ra"],
        cwd=str(root), capture_output=True, text=True, check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr


def run_control(control, root=ROOT, run=_pytest):
    """Plant, run the suite, restore, and say whether the control fired."""
    with planted(root / control.path, control.anchor, control.replacement):
        code, output = run(root)
    failures = failing_tests(output)
    return Result(
        control=control,
        fired=code != 0,
        failed_tests=failures,
        named_test_failed=any(control.expects in name for name in failures),
    )


def run_controls(controls, root=ROOT, run=_pytest, report=print):
    """Every control in turn. Returns the results; ⛔ a miss is a failure.

    ⛔ **The report names the ANCHOR, the EXPECTED test and the ACTUAL failures,
    per control** — Ruling 342, which holds that a control table reports that
    something fired and never that the *right* thing fired. ⭐ A count cannot
    distinguish those two, so a count is not what this prints.
    """
    results = []
    for control in controls:
        anchor = _anchor_occurrences(root, control)
        result = run_control(control, root=root, run=run)
        results.append(result)
        if result.ok:
            verdict = f"FIRED on the expected test, and on {len(result.failed_tests)} in all"
        elif not result.fired:
            verdict = "⛔ DID NOT FIRE — the suite stayed green"
        else:
            verdict = f"⛔ FIRED ON THE WRONG TESTS — {result.expects_missing()}"
        report(
            f"{control.id}  {control.what}\n"
            f"    anchor    {control.path}, resolved {anchor}x before planting\n"
            f"    expected  {control.expects}\n"
            f"    actual    {_render(result.failed_tests)}\n"
            f"    {verdict}"
        )
    return results


def _anchor_occurrences(root, control):
    """How many times the anchor resolves. ⛔ Anything but 1 and no run is valid."""
    return (Path(root) / control.path).read_text(encoding="utf-8").count(control.anchor)


def _render(failed, limit=6):
    """The failing test ids, short enough to read and never silently truncated."""
    if not failed:
        return "(none)"
    names = [name.rsplit("::", 1)[-1] for name in failed]
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f", +{len(names) - limit} more"


def _expects_missing(self):
    return f"{self.control.expects!r} was not among {self.failed_tests}"


Result.expects_missing = _expects_missing


#: ⛔ The committed catalogue. ⭐ Every anchor is asserted to resolve exactly
#: once in the tree by `tests/test_plant.py`, so a refactor that moves one
#: turns the harness RED instead of quietly disarming it.
CONTROLS = (
    Control(
        id="p01", what="the cache lookup is removed from synthesise()",
        path="narrate/synthesis.py",
        anchor="    record, audio = store.snapshot(artifact_id, with_audio=keep_audio)",
        replacement="    record, audio = None, None",
        expects="test_the_second_run_calls_the_engine_ZERO_times",
    ),
    Control(
        id="p02", what="address_for returns a random token",
        path="narrate/artifacts.py",
        anchor="    digest = hashlib.sha256()",
        replacement="    import secrets\n    return secrets.token_hex(32)\n"
                    "    digest = hashlib.sha256()",
        expects="test_the_same_request_always_gives_the_same_address",
    ),
    Control(
        id="p03", what="EngineUnavailable no longer halts the job",
        path="narrate/jobs.py",
        anchor='return _failed(segment, "engine_unavailable", exc), "engine_unavailable"',
        replacement='return _failed(segment, "engine_unavailable", exc), None',
        expects="test_an_unreachable_engine_HALTS_the_job_and_keeps_what_finished",
    ),
    Control(
        id="p04", what="a per-segment engine failure aborts the whole job",
        path="narrate/jobs.py",
        anchor='        return _failed(segment, "engine_failed", exc), None',
        replacement="        raise",
        expects="test_an_engine_that_answers_badly_fails_ONE_segment",
    ),
    Control(
        id="p05", what="the record beside the audio is never written",
        path="narrate/artifacts.py",
        anchor="            _atomic_write(\n                self.record_path_for(artifact_id),",
        replacement="            return destination\n            _atomic_write(\n"
                    "                self.record_path_for(artifact_id),",
        expects="test_a_stored_artifact_looks_up_to_its_record",
    ),
    Control(
        id="p06", what="a cache hit stamps the CURRENTLY deployed engine",
        path="narrate/synthesis.py",
        anchor="    hit = _from_store(artifact_id, store, media_types, keep_audio)\n"
               "    if hit is not None:\n        return hit",
        replacement="    hit = _from_store(artifact_id, store, media_types, keep_audio)\n"
                    "    if hit is not None:\n        import dataclasses\n"
                    "        return dataclasses.replace(hit, identity=engine.identity())",
        expects="test_a_cached_segment_reports_the_engine_that_MADE_it",
    ),
    Control(
        id="p07", what="/v1/jobs is removed from the router",
        path="narrate/server.py",
        anchor='        if self.path == "/v1/jobs":\n            return self._jobs()',
        replacement="        pass",
        expects="test_every_declared_route_is_a_literal_the_server_matches_on",
    ),
    Control(
        id="p08", what="consuming.json's provides drifts from narrate.PROVIDES",
        path="consuming.json",
        anchor='"provides": 2,',
        replacement='"provides": 1,',
        expects="test_it_carries_both_versions_and_they_are_not_the_same_question",
    ),
    Control(
        id="p09", what="the address drops its length prefixing",
        path="narrate/artifacts.py",
        anchor='        digest.update(f"{len(encoded)}:".encode("ascii"))\n'
               "        digest.update(encoded)",
        replacement="        digest.update(encoded)",
        expects="test_the_fields_are_length_prefixed_so_they_cannot_be_recut",
    ),
    Control(
        id="p10", what="a status is added in code and not in the declaration",
        path="narrate/jobs.py",
        anchor='SEGMENT_STATUSES = ("synthesised", "cached", "failed", "skipped")',
        replacement='SEGMENT_STATUSES = ("synthesised", "cached", "failed", '
                    '"skipped", "partial")',
        expects="test_the_status_closed_set_is_the_one_the_runner_uses",
    ),
    Control(
        id="p11", what="the declared address fields drift from the hashed ones",
        path="consuming.json",
        anchor='"over": [\n        "format",\n        "voice",\n        "chunk_chars",\n        "text"\n      ],',
        replacement='"over": [\n        "format",\n        "voice",\n        "text"\n      ],',
        expects="test_the_declared_addressing_is_what_the_code_actually_hashes",
    ),
    # ⛔ The two below are the controls for `CTO-69/7` and `CTO-69/9`, and they
    # are the reason the catalogue is committed: they are what a reviewer runs
    # to confirm the repair rather than reading a table about it.
    Control(
        id="p12", what="the staging temporary is named from its destination again",
        path="narrate/artifacts.py",
        anchor="    handle, staged = tempfile.mkstemp(\n"
               '        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent\n'
               "    )\n    temporary = Path(staged)",
        replacement='    temporary = destination.parent / f".{destination.name}.tmp"\n'
                    "    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)",
        expects="test_concurrent_writers_to_one_address_use_DIFFERENT_temporaries",
    ),
    # ⛔ `CTO-69/14`: the publish lock was the previous commit's headline
    # addition and NO control planted it. These two are its halves.
    Control(
        id="p14", what="the WRITE-side publish lock is removed",
        path="narrate/artifacts.py",
        anchor="        with self._publish_lock(artifact_id):\n"
               "            _atomic_write(destination, data)",
        replacement="        if True:\n            _atomic_write(destination, data)",
        expects="test_the_audio_and_its_record_are_published_as_ONE_PAIR",
    ),
    Control(
        id="p15", what="the READ-side snapshot lock is removed",
        path="narrate/artifacts.py",
        anchor="        with self._publish_lock(artifact_id):\n"
               "            record = self._lookup_unlocked(artifact_id)",
        replacement="        if True:\n            record = self._lookup_unlocked(artifact_id)",
        expects="test_a_reader_never_pairs_one_writers_record_with_anothers_audio",
    ),
    Control(
        id="p13", what="the chunk budget is dropped from the address",
        path="narrate/artifacts.py",
        anchor="    for field in (ADDRESS_SCHEME, fmt, voice, str(chunk_chars), text):",
        replacement="    for field in (ADDRESS_SCHEME, fmt, voice, text):",
        expects="test_the_CHUNK_BUDGET",
    ),
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", nargs="*", help="control ids; default is all")
    arguments = parser.parse_args(argv)

    chosen = [c for c in CONTROLS if not arguments.ids or c.id in arguments.ids]
    if not chosen:
        parser.error(f"no control matched {arguments.ids}")
    results = run_controls(chosen)
    missed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(missed)} of {len(results)} control(s) fired "
          "on the test that names their property")
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
