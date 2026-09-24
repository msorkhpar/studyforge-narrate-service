"""⛔ The negative-control harness, and the anchors it is built on.

⭐ **This module exists because of a near-miss.** A handoff reported that one
plant of twelve failed to apply and produced a green suite, that the run was
discarded, and that the harness now refuses an anchor which does not match
exactly once. ⛔ **The reviewer could confirm the honesty and not the repair,
because the harness was not in the tree.** It is now, and this is where the
repair is checked rather than described.

⚠️ **The most valuable test here is the last one**: every anchor in the
committed catalogue is asserted to resolve **exactly once in the tree today**.
A refactor that moves one turns this suite RED instead of quietly disarming a
control -- which is the whole failure mode, arriving from the other direction.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tools.plant import (
    CONTROLS,
    TERMINATING,
    Control,
    PlantDidNotApply,
    failing_tests,
    plant,
    planted,
    restore,
    run_control,
    run_controls,
)


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "module.py"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    return path


class TestAnAnchorMustMatchExactlyOnce:
    def test_one_match_applies_and_returns_the_original(self, sample):
        original = plant(sample, "beta", "BETA")
        assert original == "alpha\nbeta\ngamma\n"
        assert sample.read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"

    def test_no_match_refuses_and_leaves_the_file_UNTOUCHED(self, sample):
        """⛔ The exact failure that happened: a silent no-op reading green."""
        before = sample.read_text(encoding="utf-8")
        with pytest.raises(PlantDidNotApply, match="matched 0 time"):
            plant(sample, "delta", "DELTA")
        assert sample.read_text(encoding="utf-8") == before

    def test_two_matches_refuse_and_leave_the_file_UNTOUCHED(self, tmp_path):
        """⚠️ The other half: an anchor that armed somewhere unintended."""
        path = tmp_path / "twice.py"
        path.write_text("beta\nbeta\n", encoding="utf-8")
        with pytest.raises(PlantDidNotApply, match="matched 2 time"):
            plant(path, "beta", "BETA")
        assert path.read_text(encoding="utf-8") == "beta\nbeta\n"

    def test_the_refusal_says_no_reading_may_be_reported(self, sample):
        with pytest.raises(PlantDidNotApply) as raised:
            plant(sample, "delta", "DELTA")
        assert "no reading" in str(raised.value)


class TestRestoration:
    def test_restore_puts_the_file_back_byte_for_byte(self, sample):
        before = sample.read_bytes()
        original = plant(sample, "beta", "BETA")
        restore(sample, original)
        assert sample.read_bytes() == before

    def test_the_context_manager_restores_even_when_the_body_RAISES(self, sample):
        before = sample.read_bytes()
        with pytest.raises(ZeroDivisionError):
            with planted(sample, "beta", "BETA"):
                assert sample.read_text(encoding="utf-8") != before.decode()
                1 / 0
        assert sample.read_bytes() == before

    @pytest.mark.parametrize("signum", TERMINATING, ids=lambda s: signal.Signals(s).name)
    def test_a_KILLED_plant_run_restores_the_file(self, sample, signum):
        """⛔ The failure that happened: `timeout` stopped a run and the plant stayed.

        A child process arms a plant and waits; the signal arrives while it is
        armed. The file must be back byte for byte, and the child must still
        exit non-zero, so the kill is never mistaken for a finished run.
        """
        before = sample.read_bytes()
        child = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(f"""
                import sys, time
                from tools.plant import planted
                with planted({str(sample)!r}, "beta", "BETA"):
                    print("armed", flush=True)
                    time.sleep(60)
            """)],
            cwd=str(Path(__file__).resolve().parents[1]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            assert child.stdout.readline().strip() == "armed"
            assert sample.read_text(encoding="utf-8") == "alpha\nBETA\ngamma\n"
            child.send_signal(signum)
            child.wait(timeout=30)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdout.close()
            child.stderr.close()
        assert sample.read_bytes() == before
        assert child.returncode != 0

    def test_the_signal_handlers_are_put_back_after_the_block(self, sample):
        """A handler of the caller's own is what it finds again afterwards."""

        def ours(signum, frame):
            """A sentinel no other test installs."""

        found = {each: signal.signal(each, ours) for each in TERMINATING}
        try:
            with planted(sample, "beta", "BETA"):
                assert all(signal.getsignal(each) is not ours for each in TERMINATING)
            assert all(signal.getsignal(each) is ours for each in TERMINATING)
        finally:
            for each, handler in found.items():
                signal.signal(each, handler)

    def test_a_refused_plant_never_enters_the_block(self, sample):
        entered = []
        with pytest.raises(PlantDidNotApply):
            with planted(sample, "delta", "DELTA"):
                entered.append(True)
        assert entered == []


class TestAControlThatDoesNotFireIsAFailure:
    """⛔ The meta-property, and it is the one a table of ticks cannot show."""

    CONTROL = Control(id="t", what="a test control", path="module.py",
                      anchor="beta", replacement="BETA",
                      expects="test_the_property")

    def test_a_green_suite_under_a_plant_is_NOT_ok(self, sample):
        result = run_control(self.CONTROL, root=sample.parent,
                             run=lambda root: (0, "1 passed"))
        assert result.fired is False
        assert result.ok is False

    def test_firing_on_the_WRONG_test_is_NOT_ok(self, sample):
        result = run_control(
            self.CONTROL, root=sample.parent,
            run=lambda root: (1, "FAILED tests/test_other.py::test_something_else"),
        )
        assert result.fired is True
        assert result.named_test_failed is False
        assert result.ok is False

    def test_firing_on_its_OWN_test_is_ok(self, sample):
        result = run_control(
            self.CONTROL, root=sample.parent,
            run=lambda root: (1, "FAILED tests/test_x.py::test_the_property - x"),
        )
        assert result.ok is True

    def test_the_report_names_a_control_that_did_not_fire(self, sample):
        lines = []
        run_controls([self.CONTROL], root=sample.parent,
                     run=lambda root: (0, "1 passed"), report=lines.append)
        assert "DID NOT FIRE" in "\n".join(lines)

    def test_the_file_is_restored_after_a_control_runs(self, sample):
        before = sample.read_bytes()
        run_control(self.CONTROL, root=sample.parent,
                    run=lambda root: (1, "FAILED a::test_the_property"))
        assert sample.read_bytes() == before


class TestTheFailureReader:
    def test_it_reads_pytest_own_summary_lines(self):
        output = (
            "collected 3 items\n"
            "FAILED tests/test_a.py::test_one - AssertionError: x\n"
            "FAILED tests/test_b.py::test_two\n"
            "1 passed, 2 failed\n"
        )
        assert failing_tests(output) == (
            "tests/test_a.py::test_one", "tests/test_b.py::test_two",
        )

    def test_a_green_run_reports_no_failures(self):
        assert failing_tests("309 passed in 31.92s\n") == ()


class TestTheCommittedCatalogue:
    """⭐ The test that keeps the harness armed as the tree moves."""

    def test_there_is_at_least_one_control(self):
        assert len(CONTROLS) >= 15

    def test_every_control_id_is_unique(self):
        assert len({control.id for control in CONTROLS}) == len(CONTROLS)

    @pytest.mark.parametrize("control", CONTROLS, ids=lambda c: c.id)
    def test_every_anchor_resolves_EXACTLY_ONCE_in_the_tree(self, control):
        """⛔ The repair a reviewer could not confirm, made confirmable.

        ⚠️ A control whose anchor has drifted is a control that will not arm,
        and the harness would refuse it at run time -- but only if somebody
        ran it. This fails in the ordinary suite instead.
        """
        from tools.plant import ROOT
        text = (ROOT / control.path).read_text(encoding="utf-8")
        assert text.count(control.anchor) == 1, (
            f"{control.id}: anchor matched {text.count(control.anchor)} time(s) "
            f"in {control.path}"
        )

    @pytest.mark.parametrize("control", CONTROLS, ids=lambda c: c.id)
    def test_every_control_actually_changes_the_text(self, control):
        assert control.anchor != control.replacement

    @pytest.mark.parametrize("control", CONTROLS, ids=lambda c: c.id)
    def test_every_control_names_a_test_that_exists(self, control):
        """⛔ A control expecting a test nobody wrote can never be `ok`."""
        from tools.plant import ROOT
        names = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "tests").glob("test_*.py"))
        )
        assert f"def {control.expects}" in names, control.expects
