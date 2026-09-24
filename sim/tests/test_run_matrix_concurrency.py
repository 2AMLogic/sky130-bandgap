#!/usr/bin/env python3
"""Unit coverage for `sim_common.py::run_matrix_and_write_record()`'s `-j`/
`--jobs` concurrency support (issue #308).

`corner-run.py` and `post_layout_common.py` route every corner-matrix run
through this one function, so its serial-vs-concurrent branch is the load-
bearing piece of #308: a mistake here would silently reorder or drop corner
results in every PVT-matrix record the repo writes. Exercised here against a
fake `cr` module (no real `ngspice`/PDK needed -- `run_corner()` is the one
call that would need either) so this test runs headlessly in CI.

Deliberately synchronization-based rather than wall-clock-based: an earlier
draft of this file proved concurrency by comparing elapsed time against the
sum of artificial per-corner delays, which was flaky under sandboxed/loaded
CI runners where `time.sleep()` overhead dwarfs short delays. `threading.Event`
rendezvous points give the same proof deterministically -- "all N corner
workers were in flight at once" and "they completed in a chosen non-matrix
order" are both asserted structurally, not inferred from timing.

Three properties are checked, matching #308's own acceptance criteria:

1. `jobs=1` runs strictly serially (corners complete in matrix order) and the
   written record's `jobs` field says so.
2. `jobs>1` genuinely runs corners concurrently (all N workers are
   simultaneously in flight, proven via an `Event` barrier) AND still writes
   corners into the record in **matrix order**, even when this test
   deliberately releases them to complete in a different, explicit order --
   proving the ordering comes from the index-keyed `results` list, not from
   luck.
3. Each `run_corner()` call receives the caller's full, unmodified
   `--timeout` regardless of `jobs` -- i.e. concurrency never divides a
   per-corner timeout into a shared global budget.

A fourth check (`jobs` larger than the corner count) is folded into #1's
serial-path helper since it is otherwise the same code path with a larger
`max_workers` and no ordering claim to prove beyond what #2 already covers.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import sim_common  # noqa: E402


@dataclass
class FakeCorner:
    """Duck-types `corner-run.py::Corner` (process/temp_c/supply_v + `.id`)
    without importing the real module, so this test needs no PDK/xschem."""

    process: str
    temp_c: float
    supply_v: float

    @property
    def id(self) -> str:
        return f"{self.process}_{self.temp_c:g}c_{self.supply_v:.2f}v"


_MATRIX = [
    FakeCorner("tt", -40, 2.97),
    FakeCorner("tt", 27, 3.30),
    FakeCorner("ss", 27, 3.30),
    FakeCorner("ff", 125, 3.63),
]


class _Harness:
    """One throwaway tmp-tree + fake `cr` per test, wired the way
    `run_matrix_and_write_record()` expects (issue #277's shared contract).

    When `synchronize=True`, each fake `run_corner()` call signals its own
    `started` event and then blocks on its own `release` event, letting the
    test control exactly when each corner "finishes" -- independent of any
    real wall-clock timing.
    """

    def __init__(self, *, synchronize: bool = False) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.completion_order: list[str] = []
        self.seen_timeouts: list[int] = []
        self._lock = threading.Lock()
        self.synchronize = synchronize
        self.started = {c.id: threading.Event() for c in _MATRIX}
        self.release = {c.id: threading.Event() for c in _MATRIX}
        self.finished = {c.id: threading.Event() for c in _MATRIX}

        def fake_run_corner(exp, pdk, corner, body, run_dir, log_path, timeout):
            if self.synchronize:
                self.started[corner.id].set()
                released = self.release[corner.id].wait(timeout=5.0)
                if not released:
                    raise TimeoutError(
                        f"{corner.id} was never released -- corners are not "
                        "running concurrently"
                    )
            with self._lock:
                self.completion_order.append(corner.id)
                self.seen_timeouts.append(timeout)
            self.finished[corner.id].set()
            return {
                "corner_id": corner.id,
                "process": corner.process,
                "temperature_c": corner.temp_c,
                "supply_v": corner.supply_v,
                "ngspice_exit": 0,
                "timed_out": False,
                "killed_by_signal": None,
                "killed_by_signal_name": None,
                "elapsed_s": 0.0,
                "timeout_s": timeout,
                "measurements": [],
                "pass": True,
                "log": str(log_path),
            }

        self.cr = SimpleNamespace(
            REPO_ROOT=self.tmp,
            run_corner=fake_run_corner,
            spread_checks=lambda exp, results: [],
            tool_versions=lambda: {
                "ngspice": "fake",
                "xschem": "fake",
                "platform": "fake",
                "python": "fake",
            },
            default_author=lambda: "test-author",
            render_record=lambda record: "# fake record\n",
            unique_in_order=lambda values: list(dict.fromkeys(values)),
        )

    def run_async(self, *, jobs: int, timeout: int = 5) -> threading.Thread:
        """Run `run_matrix_and_write_record()` on a background thread and
        stash `(record, overall)` on `self.result` once it returns -- needed
        for `synchronize=True` runs, where the calling test thread must stay
        free to release corners one at a time."""
        self.result: tuple[dict, bool] | None = None
        self.error: BaseException | None = None

        def target() -> None:
            try:
                self.result = self._run(jobs=jobs, timeout=timeout)
            except BaseException as exc:  # noqa: BLE001 - surfaced via join()
                self.error = exc

        t = threading.Thread(target=target)
        t.start()
        return t

    def run(self, *, jobs: int, timeout: int = 5) -> tuple[dict, bool]:
        """Synchronous convenience wrapper for `synchronize=False` runs."""
        return self._run(jobs=jobs, timeout=timeout)

    def _run(self, *, jobs: int, timeout: int) -> tuple[dict, bool]:
        exp_dir = self.tmp / "sim" / "dummy"
        args = SimpleNamespace(timeout=timeout, author="", supersedes="", jobs=jobs)
        return sim_common.run_matrix_and_write_record(
            self.cr,
            exp=SimpleNamespace(raw={}),
            matrix=_MATRIX,
            is_subset=False,
            subset_reason="",
            pdk=SimpleNamespace(
                root=self.tmp / "pdk",
                variant="sky130A",
                installed_commit="deadbeef",
                matches_pin=True,
                lib_file=self.tmp / "pdk" / "dummy.lib",
            ),
            pin={"open_pdks_commit": "deadbeef"},
            body=["* dummy deck"],
            run_dir=self.tmp / "build",
            corners_dir=exp_dir / "corners" / "test-record",
            records_dir=exp_dir / "records",
            record_md=exp_dir / "records" / "test-record.md",
            record_json=exp_dir / "records" / "test-record.json",
            snapshot=exp_dir / "netlist-snapshots" / "test-record.spice",
            record_id="test-record",
            git_info={"sha": "abc1234", "branch": "main", "dirty": False},
            now=datetime.now(timezone.utc),
            args=args,
            experiment_fields={
                "slug": "dummy",
                "title": "Dummy",
                "claim": "test claim",
                "provenance": "schematic",
                "provenance_source": "design/dummy.sch",
                "statistical_convention": "N/A",
            },
            links={"testbench": "design/dummy.sch", "manifest": "sim/dummy/experiment.json"},
        )


class TestRunMatrixAndWriteRecordConcurrency(unittest.TestCase):
    def test_jobs_1_runs_serially_and_records_the_jobs_field(self) -> None:
        h = _Harness()
        record, overall = h.run(jobs=1)

        self.assertTrue(overall)
        self.assertEqual(record["jobs"], 1)
        # Serial: corners must complete in the exact order they were started.
        self.assertEqual(h.completion_order, [c.id for c in _MATRIX])
        self.assertEqual([c["corner_id"] for c in record["corners"]], [c.id for c in _MATRIX])

    def test_jobs_larger_than_corner_count_matches_serial_result(self) -> None:
        h = _Harness()
        record, overall = h.run(jobs=100)

        self.assertTrue(overall)
        self.assertEqual(record["jobs"], 100)
        self.assertEqual(len(record["corners"]), len(_MATRIX))
        self.assertEqual([c["corner_id"] for c in record["corners"]], [c.id for c in _MATRIX])

    def test_jobs_greater_than_1_runs_concurrently_but_writes_matrix_order(self) -> None:
        h = _Harness(synchronize=True)
        thread = h.run_async(jobs=len(_MATRIX), timeout=42)

        # All four corner workers must be in flight SIMULTANEOUSLY -- if
        # jobs>1 silently fell back to running one corner at a time, only one
        # `started` event would ever be set while the others waited their
        # turn, and this would time out.
        for corner in _MATRIX:
            in_flight = h.started[corner.id].wait(timeout=5.0)
            self.assertTrue(in_flight, f"{corner.id} never started -- jobs>1 is not concurrent")

        # Release them ONE AT A TIME, in a DELIBERATE order that is NOT
        # matrix order, waiting for each to actually finish before releasing
        # the next -- this pins `completion_order` to exactly this sequence
        # (rather than racing two just-released workers against each other),
        # so the assertion below proves the written record's order comes from
        # the index-keyed `results` list, not from completion order.
        release_order = [_MATRIX[3], _MATRIX[1], _MATRIX[2], _MATRIX[0]]
        for corner in release_order:
            h.release[corner.id].set()
            finished = h.finished[corner.id].wait(timeout=5.0)
            self.assertTrue(finished, f"{corner.id} never finished after being released")

        thread.join(timeout=5.0)
        self.assertFalse(thread.is_alive(), "run_matrix_and_write_record() did not finish")
        self.assertIsNone(h.error)
        record, overall = h.result

        self.assertTrue(overall)
        self.assertEqual(record["jobs"], len(_MATRIX))
        self.assertEqual(h.completion_order, [c.id for c in release_order])
        self.assertNotEqual(h.completion_order, [c.id for c in _MATRIX])

        # ... yet the WRITTEN record is still in matrix order, regardless.
        self.assertEqual([c["corner_id"] for c in record["corners"]], [c.id for c in _MATRIX])

    def test_timeout_is_per_corner_not_a_shared_global_budget(self) -> None:
        """Every `run_corner()` call must see the caller's own `--timeout`
        value unchanged, whether run serially or alongside N-1 siblings --
        concurrency must never divide one budget across the pool."""
        for jobs in (1, 4):
            with self.subTest(jobs=jobs):
                h = _Harness()
                h.run(jobs=jobs, timeout=42)
                self.assertEqual(h.seen_timeouts, [42] * len(_MATRIX))


if __name__ == "__main__":
    unittest.main()
