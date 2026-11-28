#!/usr/bin/env python3
"""Coverage for `sim_common.add_batch_args()` -- the shared
`--backend`/`--batch-capacity-wait-s`/`--batch-runner-version-check` flag block
(issue #544) -- and for the `-j`/`--jobs` flag and its `--backend batch` guard
that issue #720 folded beside it (`sim_common.add_jobs_arg()` /
`sim_common.reject_batch_jobs()`).

Six production harnesses (`corner-run.py`, `post_layout_common.py`, both Monte
Carlo runners, both PSRR injector benches) each hand-rolled that block in their
own `parse_args()`. `type`/`default`/`choices` still agreed, but nothing
asserted that they did, and the help text had already drifted into three
wordings for each of the two flags whose meaning is bench-independent -- so
`--help` for the same flag read differently depending on which bench you asked.
#544 folded the block onto one helper; this file is the guard that keeps it
folded, in the same spirit as `test_csv_args.py` for #313's dedup.

Five legs:

- `AddBatchArgsTests` pins the helper's own contract (the `type`/`default`/
  `choices` every one of the six had, plus `backend_help` passthrough).
- `RenderedHelpIsCanonicalTests` runs `--help` on every entry point that exposes
  the block and asserts the rendered text carries the canonical wording and none
  of the three pre-#544 ones. This is the operator-facing surface the issue is
  actually about, and it covers the post-layout benches, which reach the block
  through `post_layout_common.parse_post_layout_args()`.
- `NoHandRolledCopiesTests` is the recurrence guard: it fails if any harness
  under `sim/` declares either flag name itself again instead of calling the
  helper. Without it, the next harness copies whichever block it starts from and
  the drift returns -- which is how six copies happened in the first place.
- `AddJobsArgTests` / `RejectBatchJobsTests` pin the #720 helpers' contract.
- `MatrixRunnerDelegationTests` holds the two PVT-matrix runners to the shared
  helpers, and `NoHandRolledCopiesTests` to no private copy of their prose.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import post_layout_common as plc  # noqa: E402
import sim_common  # noqa: E402

#: Every entry point whose `--help` exposes the shared block. The post-layout
#: benches are globbed rather than listed so a new one is covered the day it
#: lands (they all parse through `post_layout_common.parse_post_layout_args()`).
ENTRY_POINTS = [
    SIM_DIR / "bin" / "corner-run.py",
    SIM_DIR / "monte-carlo-untrimmed" / "run_mc_untrimmed.py",
    SIM_DIR / "error-amp-offset-mc" / "run_amp_offset_mc.py",
    SIM_DIR / "psrr-injector-attribution" / "run_psrr_injector_attribution.py",
    SIM_DIR / "psrr-injector-candidates" / "run_psrr_injector_candidates.py",
    *sorted(SIM_DIR.glob("*-post-layout/run_*.py")),
]

#: The two PVT-matrix runners that expose the shared `-j`/`--jobs` flag
#: (issue #720): `corner-run.py`, and the post-layout benches through
#: `post_layout_common.parse_post_layout_args()` (globbed for the same reason
#: as above). The PSRR injector benches' `--jobs` is a different flag
#: (`injector_common.py`: no `-j`, default 2) and is not in this list.
MATRIX_ENTRY_POINTS = [
    SIM_DIR / "bin" / "corner-run.py",
    *sorted(SIM_DIR.glob("*-post-layout/run_*.py")),
]

#: The wordings that existed before #544 canonicalised them. Each must be gone
#: from every `--help`: two of the three are what the sixth copy would be
#: cargo-culted from, and the first two drop the default from the text entirely.
STALE_HELP = (
    "wait this long for Spot capacity per batch submission",
    "klt runner/client version-skew policy for batch jobs",
    "batch only: klt runner/client version-skew policy (default enforce) (default enforce)",
)


def flatten(text: str) -> str:
    """Collapse argparse's column wrapping so a help string can be searched for
    as one line regardless of where argparse broke it."""
    return " ".join(text.split())


def render_help(script: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
        env={"COLUMNS": "100", "PATH": os.environ.get("PATH", "")},
    )
    assert proc.returncode == 0, f"{script.name} --help failed: {proc.stderr}"
    return flatten(proc.stdout)


class AddBatchArgsTests(unittest.TestCase):
    """The flag contract all six hand-rolled copies shared, asserted once."""

    def parser(self, backend_help: str = "where it runs") -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="bench", add_help=False)
        sim_common.add_batch_args(p, backend_help=backend_help)
        return p

    def test_defaults_match_the_pre_dedup_copies(self) -> None:
        args = self.parser().parse_args([])
        self.assertEqual(args.backend, "local")
        self.assertEqual(args.batch_capacity_wait_s, 3600.0)
        self.assertEqual(args.batch_runner_version_check, "enforce")

    def test_capacity_wait_default_comes_from_the_one_constant(self) -> None:
        self.assertEqual(
            self.parser().parse_args([]).batch_capacity_wait_s,
            sim_common.DEFAULT_BATCH_CAPACITY_WAIT_S,
        )

    def test_capacity_wait_is_a_float_not_an_int(self) -> None:
        # batch_sim's request field is a float; an int would change the request.
        args = self.parser().parse_args(["--batch-capacity-wait-s", "600.5"])
        self.assertIsInstance(args.batch_capacity_wait_s, float)
        self.assertEqual(args.batch_capacity_wait_s, 600.5)

    def test_backend_accepts_local_and_batch(self) -> None:
        self.assertEqual(self.parser().parse_args(["--backend", "batch"]).backend, "batch")
        self.assertEqual(self.parser().parse_args(["--backend", "local"]).backend, "local")

    def test_backend_rejects_anything_else(self) -> None:
        with self.assertRaises(SystemExit):
            self.parser().parse_args(["--backend", "remote"])

    def test_runner_version_check_accepts_enforce_and_warn(self) -> None:
        for value in ("enforce", "warn"):
            self.assertEqual(
                self.parser().parse_args(
                    ["--batch-runner-version-check", value]
                ).batch_runner_version_check,
                value,
            )

    def test_runner_version_check_rejects_anything_else(self) -> None:
        with self.assertRaises(SystemExit):
            self.parser().parse_args(["--batch-runner-version-check", "ignore"])

    def test_backend_help_is_the_callers_text(self) -> None:
        # --backend's help names the bench's own enabled slugs / point shape, so
        # it is passed in rather than canonicalised.
        text = flatten(self.parser("bench-specific prose").format_help())
        self.assertIn("bench-specific prose", text)
        self.assertNotIn("bench-specific prose", flatten(self.parser().format_help()))

    def test_backend_help_is_required_and_keyword_only(self) -> None:
        with self.assertRaises(TypeError):
            sim_common.add_batch_args(argparse.ArgumentParser(add_help=False))  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            sim_common.add_batch_args(argparse.ArgumentParser(add_help=False), "positional")  # type: ignore[misc]

    def test_canonical_help_names_the_defaults_once(self) -> None:
        self.assertIn("(default 3600)", sim_common.BATCH_CAPACITY_WAIT_HELP)
        self.assertIn("(default enforce)", sim_common.BATCH_RUNNER_VERSION_CHECK_HELP)


class AddJobsArgTests(unittest.TestCase):
    """The `-j`/`--jobs` contract both matrix runners shared, asserted once."""

    def parser(self) -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(prog="bench", add_help=False)
        sim_common.add_jobs_arg(p)
        return p

    def test_default_is_serial_as_before_the_flag_existed(self) -> None:
        self.assertEqual(self.parser().parse_args([]).jobs, 1)

    def test_short_and_long_forms_agree(self) -> None:
        self.assertEqual(self.parser().parse_args(["-j", "4"]).jobs, 4)
        self.assertEqual(self.parser().parse_args(["--jobs", "4"]).jobs, 4)

    def test_jobs_is_an_int(self) -> None:
        # run_matrix_and_write_record() sizes a ThreadPoolExecutor with it.
        self.assertIsInstance(self.parser().parse_args(["--jobs", "3"]).jobs, int)
        with self.assertRaises(SystemExit):
            self.parser().parse_args(["--jobs", "four"])

    def test_help_is_the_canonical_wording(self) -> None:
        # Rendered wide, as RenderedHelpIsCanonicalTests renders the benches:
        # an 80-column terminal hyphen-breaks "per-process" and the flattened
        # canonical text no longer matches the flattened render.
        with mock.patch.dict(os.environ, COLUMNS="200"):
            text = flatten(self.parser().format_help())
        self.assertIn("-j JOBS, --jobs JOBS", text)
        self.assertIn(flatten(sim_common.JOBS_HELP), text)
        self.assertIn("(default: 1, serial", text)


class RejectBatchJobsTests(unittest.TestCase):
    """`reject_batch_jobs(args, error)`: the guard both matrix runners raised
    from identical private copies until #720."""

    def args(self, backend: str, jobs: int) -> argparse.Namespace:
        return argparse.Namespace(backend=backend, jobs=jobs)

    def test_local_backend_keeps_local_concurrency(self) -> None:
        # AssertionError is the error class, so a refusal would fail the test.
        self.assertIsNone(sim_common.reject_batch_jobs(self.args("local", 8), AssertionError))

    def test_batch_backend_with_the_serial_default_is_accepted(self) -> None:
        self.assertIsNone(sim_common.reject_batch_jobs(self.args("batch", 1), AssertionError))

    def test_batch_backend_with_concurrency_is_refused(self) -> None:
        with self.assertRaises(RuntimeError) as cm:
            sim_common.reject_batch_jobs(self.args("batch", 2), RuntimeError)
        self.assertEqual(str(cm.exception), sim_common.BATCH_JOBS_MESSAGE)
        self.assertEqual(
            sim_common.BATCH_JOBS_MESSAGE,
            "--jobs is a local-concurrency flag; --backend batch ignores it, drop it",
        )

    def test_it_raises_through_the_callers_error_class(self) -> None:
        # Each runner's __main__ handler reports its own HarnessError; the
        # guard must raise that class, never a batch_sim/sim_common one.
        class Error(RuntimeError):
            pass

        with self.assertRaises(Error):
            sim_common.reject_batch_jobs(self.args("batch", 64), Error)


class RenderedHelpIsCanonicalTests(unittest.TestCase):
    """One wording per flag, across every bench that advertises it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.helps = {p: render_help(p) for p in ENTRY_POINTS}

    def test_every_entry_point_exposes_the_shared_block(self) -> None:
        for path, text in self.helps.items():
            with self.subTest(bench=path.name):
                self.assertIn("--backend {local,batch}", text)
                self.assertIn("--batch-capacity-wait-s", text)
                self.assertIn("--batch-runner-version-check {enforce,warn}", text)

    def test_capacity_wait_help_is_the_canonical_wording_everywhere(self) -> None:
        for path, text in self.helps.items():
            with self.subTest(bench=path.name):
                self.assertIn(flatten(sim_common.BATCH_CAPACITY_WAIT_HELP), text)

    def test_runner_version_check_help_is_the_canonical_wording_everywhere(self) -> None:
        for path, text in self.helps.items():
            with self.subTest(bench=path.name):
                self.assertIn(flatten(sim_common.BATCH_RUNNER_VERSION_CHECK_HELP), text)

    def test_no_pre_dedup_wording_survives(self) -> None:
        for path, text in self.helps.items():
            for stale in STALE_HELP:
                with self.subTest(bench=path.name, stale=stale):
                    self.assertNotIn(stale, text)

    def test_the_six_declaring_harnesses_are_all_covered(self) -> None:
        # Guards the ENTRY_POINTS list itself: the post-layout glob must resolve
        # to at least one bench, so a path typo cannot silently empty the sweep.
        self.assertGreaterEqual(len(ENTRY_POINTS), 6)
        self.assertTrue(any("post-layout" in p.parts[-2] for p in ENTRY_POINTS))

    def test_jobs_help_is_the_canonical_wording_on_every_matrix_runner(self) -> None:
        # #720: corner-run.py and every post-layout bench render the one
        # sim_common.JOBS_HELP, under the same -j/--jobs option strings.
        self.assertGreaterEqual(len(MATRIX_ENTRY_POINTS), 2)
        self.assertTrue(set(MATRIX_ENTRY_POINTS) <= set(self.helps))
        for path in MATRIX_ENTRY_POINTS:
            with self.subTest(bench=path.name):
                text = self.helps[path]
                self.assertIn("-j JOBS, --jobs JOBS", text)
                self.assertIn(flatten(sim_common.JOBS_HELP), text)


class MatrixRunnerDelegationTests(unittest.TestCase):
    """The two PVT-matrix runners reach the #720 helpers instead of their own
    copies: `-j`/`--jobs` through `sim_common.add_jobs_arg()`, the batch guard
    through `sim_common.reject_batch_jobs()`, the request preview through
    `batch_sim.print_batch_dry_run()` and the executor through
    `batch_sim.make_matrix_executor()`. `co_names` is the attribute names a
    function body references, so each assertion fails the day a runner spells
    the block out again."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cr = sim_common.load_corner_run()

    def parsers(self):
        return (
            ("corner-run.py", self.cr.parse_args),
            ("post_layout_common.py", plc.parse_post_layout_args),
        )

    def mains(self):
        return (
            ("corner-run.py", self.cr.main),
            ("post_layout_common.py", plc.run_post_layout_experiment),
        )

    def test_both_parsers_register_the_shared_jobs_flag(self) -> None:
        for name, parse in self.parsers():
            with self.subTest(runner=name):
                self.assertIn("add_jobs_arg", parse.__code__.co_names)
                self.assertEqual(parse([]).jobs, 1)
                self.assertEqual(parse(["-j", "3"]).jobs, 3)

    def test_both_mains_guard_batch_jobs_through_the_shared_helper(self) -> None:
        for name, main in self.mains():
            with self.subTest(runner=name):
                self.assertIn("reject_batch_jobs", main.__code__.co_names)

    def test_batch_jobs_are_refused_before_any_work(self) -> None:
        # The guard is the first thing after parsing: it fires before the PDK,
        # the layout inputs or klt are looked at, so the runners can be driven
        # with nonexistent inputs here.
        with self.assertRaises(self.cr.HarnessError) as cm:
            self.cr.main(["--backend", "batch", "-j", "2", "sim/does-not-exist"])
        self.assertEqual(str(cm.exception), sim_common.BATCH_JOBS_MESSAGE)
        with self.assertRaises(self.cr.HarnessError) as cm:
            plc.run_post_layout_experiment(
                self.cr,
                here=SIM_DIR / "does-not-exist-post-layout",
                slug="does-not-exist-post-layout",
                wrapped_experiment="does-not-exist",
                wrapped_schematic="sim/does-not-exist/testbench/tb.sch",
                claim_tail=None,
                argv=["--backend", "batch", "--jobs", "2"],
            )
        self.assertEqual(str(cm.exception), sim_common.BATCH_JOBS_MESSAGE)

    def test_both_batch_dry_runs_print_through_the_shared_printer(self) -> None:
        for name, main in self.mains():
            with self.subTest(runner=name):
                self.assertIn("print_batch_dry_run", main.__code__.co_names)

    def test_both_batch_executors_come_from_the_shared_builder(self) -> None:
        for name, main in self.mains():
            with self.subTest(runner=name):
                self.assertIn("make_matrix_executor", main.__code__.co_names)


class NoHandRolledCopiesTests(unittest.TestCase):
    """The recurrence guard: these flag names and these prose strings live in
    exactly one place."""

    FLAG_NAMES = ("--batch-capacity-wait-s", "--batch-runner-version-check")
    HOME = SIM_DIR / "bin" / "sim_common.py"

    #: Prose the two PVT-matrix runners (`corner-run.py`,
    #: `post_layout_common.py`) spelled identically before #720: the `-j`/
    #: `--jobs` help, the batch `--jobs` refusal, the batch request preview
    #: and the `klt --version` tool line. None of it may come back as a
    #: private copy in a runner. The refusal ends at its closing quote on
    #: purpose: the PSRR injector benches' `--jobs` is a different flag
    #: (`injector_common.py`, issue #720 leaves it alone) and keeps its own
    #: longer wording, through `p.error()`.
    MATRIX_PROSE = (
        "run up to N corners concurrently",
        '--backend batch ignores it, drop it"',
        "-- batch requests (one klt sim job per supply voltage) --",
        "nothing submitted, nothing written under sim/<experiment>/)",
        'local_tools["klt"]',
    )

    def offenders(self, needles: tuple[str, ...], homes: tuple[Path, ...]) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for path in sorted(SIM_DIR.rglob("*.py")):
            if path in homes or path.parent == SIM_DIR / "tests":
                continue
            text = path.read_text()
            hits = [needle for needle in needles if needle in text]
            if hits:
                found[str(path.relative_to(SIM_DIR))] = hits
        return found

    def test_only_sim_common_names_the_shared_batch_flags(self) -> None:
        self.assertEqual(
            self.offenders(self.FLAG_NAMES, (self.HOME,)),
            {},
            "these harnesses name a shared batch flag themselves instead of calling "
            "sim_common.add_batch_args() -- that is the copy-paste that drifted into "
            "three help wordings before issue #544",
        )

    def test_the_home_really_is_the_home(self) -> None:
        text = self.HOME.read_text()
        for flag in self.FLAG_NAMES:
            self.assertIn(f'"{flag}"', text)

    def test_only_sim_common_declares_the_short_jobs_flag(self) -> None:
        self.assertEqual(
            self.offenders(('"-j"',), (self.HOME,)),
            {},
            "a harness declares -j itself instead of calling sim_common.add_jobs_arg() "
            "(issue #720)",
        )

    def test_only_the_shared_modules_carry_the_matrix_batch_prose(self) -> None:
        homes = (self.HOME, SIM_DIR / "bin" / "batch_sim.py")
        self.assertEqual(
            self.offenders(self.MATRIX_PROSE, homes),
            {},
            "a PVT-matrix runner spells out a block that sim_common / batch_sim own "
            "(add_jobs_arg, reject_batch_jobs, print_batch_dry_run, "
            "make_matrix_executor -- issue #720)",
        )

    def test_the_matrix_homes_really_are_the_homes(self) -> None:
        # Guards the prose list itself: every entry is live text in a home
        # module, so a renamed helper cannot leave this guard asserting nothing.
        homes = {path: path.read_text() for path in (self.HOME, SIM_DIR / "bin" / "batch_sim.py")}
        self.assertIn('"-j"', homes[self.HOME])
        for prose in self.MATRIX_PROSE:
            with self.subTest(prose=prose):
                self.assertTrue(any(prose in text for text in homes.values()), prose)


if __name__ == "__main__":
    unittest.main(verbosity=2)
