#!/usr/bin/env python3
"""Coverage for `sim_common.add_batch_args()` -- the shared
`--backend`/`--batch-capacity-wait-s`/`--batch-runner-version-check` flag block
(issue #544).

Six production harnesses (`corner-run.py`, `post_layout_common.py`, both Monte
Carlo runners, both PSRR injector benches) each hand-rolled that block in their
own `parse_args()`. `type`/`default`/`choices` still agreed, but nothing
asserted that they did, and the help text had already drifted into three
wordings for each of the two flags whose meaning is bench-independent -- so
`--help` for the same flag read differently depending on which bench you asked.
#544 folded the block onto one helper; this file is the guard that keeps it
folded, in the same spirit as `test_csv_args.py` for #313's dedup.

Three legs:

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
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

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


class NoHandRolledCopiesTests(unittest.TestCase):
    """The recurrence guard: these flag names live in exactly one place."""

    FLAG_NAMES = ("--batch-capacity-wait-s", "--batch-runner-version-check")
    HOME = SIM_DIR / "bin" / "sim_common.py"

    def test_only_sim_common_names_the_shared_batch_flags(self) -> None:
        offenders: dict[str, list[str]] = {}
        for path in sorted(SIM_DIR.rglob("*.py")):
            if path == self.HOME or path.parent == SIM_DIR / "tests":
                continue
            text = path.read_text()
            hits = [f for f in self.FLAG_NAMES if f in text]
            if hits:
                offenders[str(path.relative_to(SIM_DIR))] = hits
        self.assertEqual(
            offenders, {},
            "these harnesses name a shared batch flag themselves instead of calling "
            "sim_common.add_batch_args() -- that is the copy-paste that drifted into "
            "three help wordings before issue #544",
        )

    def test_the_home_really_is_the_home(self) -> None:
        text = self.HOME.read_text()
        for flag in self.FLAG_NAMES:
            self.assertIn(f'"{flag}"', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
