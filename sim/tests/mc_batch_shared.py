#!/usr/bin/env python3
"""The bench-independent half of the two Monte Carlo batch test files (#536).

`batch_sim` has held the ONE collector both MC runners drive since PR #532
(#522); until #536 its tests lived as two per-bench copies that drifted --
amp-offset's `_report` grew `unlaunched`/`lost` and the `dropped_without_values`
sidecar check, and the untrimmed copies of neither landed. Each guarantee of
the shared collector gets one assertion site here; the subclasses in
`test_amp_offset_mc_batch.py` / `test_mc_untrimmed_batch.py` keep only what
reads their own bench's constants, driving their own `R.collect_batch(...)`
call path (the same shape `test_psrr_injector_shared.py` uses one layer up).

The filename deliberately does not match `test_*.py`, and the classes below
are plain-object mixins, NOT `unittest.TestCase`: discovery must not collect
them standalone, because every assertion reads class attributes (runner
module, bench directory, `LOCAL_TIMEOUT_S`, report fixture) that only a bench
subclass supplies. Import mechanics: `unittest discover --start-directory
sim/tests` puts this directory on `sys.path`, but `python3 -m unittest
sim.tests.<module>` does not -- each bench file inserts this directory before
importing this module, and this module does the same for `sim/bin`.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR.parent / "scripts" / "ci"))

import batch_sim  # noqa: E402
import mc_common  # noqa: E402
import sim_common  # noqa: E402
from script_module import load_script_module  # noqa: E402

cr = sim_common.load_corner_run()


def _load_runner(path, name):
    """Import one bench's runner under its own module name."""
    return load_script_module(path, name)


def _shard_ids(point, shards):
    return [f"job-{point.corner_id}-s{i}" for i in range(shards)]


def _report(point, measurements, step_size, *, n=None, lib_sha="abc", drop=(),
            shuffle=False, spread=True, unlaunched=0, lost=0, shards=0):
    """A stubbed klt report: one `corners[]` entry per Monte Carlo draw, with
    `measurements(k, step)` building draw `k`'s list and `step` = `k *
    step_size` when `spread` is set and 0 otherwise.

    `spread=False` gives every draw identical values -- the MC-off control
    point's shape, where every sigma must come out exactly 0. `unlaunched` /
    `lost` reproduce a shard-losing request so the short-report refusal can
    name the loss. `shards=N` is the shape klt returns for a sharded request
    (issue #523): a `fleet` list of per-shard entries and NO top-level
    `job_id`."""
    n = point.samples if n is None else n
    corners = []
    for k in range(n):
        step = (k * step_size) if spread else 0.0
        ms = [] if k in drop else measurements(k, step)
        diags = [{"code": "lost_shard"}] if k < lost else []
        corners.append({"process": point.section, "temperature_c": point.temp_c, "status": "pass",
                        "monte_carlo": {"sample_index": k}, "measurements": ms,
                        "diagnostics": diags})
    if shuffle:
        corners.reverse()
    remote = ({"fleet": [{"job_id": j} for j in _shard_ids(point, shards)]} if shards
              else {"job_id": f"job-{point.corner_id}"})
    if unlaunched:
        remote["unlaunched_shards"] = unlaunched
    return {"corner_count": n, "corners": corners, "status": "pass",
            "environment": {"models_lib_sha256": lib_sha, "engine_version": "45",
                            "remote": remote}}


class BatchRequestsShared:
    """`build_batch_groups()` request-shape tests that read no bench constant.

    The subclass supplies `R`, `PIN`, `BODY`, `SPICEINIT` and `ARGS`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.points = self.R.build_points(300)
        self.groups = self.R.build_batch_groups(
            self.PIN, self.BODY, self.points, self.SPICEINIT, Path(self._tmp.name), self.ARGS)

    def test_one_request_per_point_with_its_section_seed_and_samples(self):
        self.assertEqual(len(self.groups), len(self.points))
        for g, p in zip(self.groups, self.points):
            with self.subTest(point=p.corner_id):
                req = g.request
                self.assertEqual(req["backend"], "batch")
                self.assertEqual(req["corners"], {"process": [p.section], "temperature_c": [int(p.temp_c)]})
                self.assertEqual(req["monte_carlo"], {"n": p.samples, "seed": p.seed, "vary": "mismatch"})
                self.assertEqual(req["analysis"], {"kind": "op", "args": ""})
                self.assertEqual(json.loads(g.request_path.read_text()), req)

    def test_sharding_is_sized_by_sample_count(self):
        # At the batch default a 300-sample point packs 14 samples per shard
        # instead of asking for one Spot host per sample (issue #528).
        self.assertEqual(self.points[0].samples, 300)
        self.assertEqual(
            self.groups[0].request["remote"]["hosts"],
            batch_sim.shard_hosts(300, batch_sim.MC_BATCH_TIMEOUT_S),
        )
        self.assertEqual(self.groups[0].request["remote"]["hosts"], 22)

    def test_every_request_fits_the_fleet_job_ceiling_at_the_default(self):
        for g, p in zip(self.groups, self.points):
            with self.subTest(point=p.corner_id):
                hosts = g.request["remote"]["hosts"]
                self.assertLessEqual(hosts, p.samples)  # klt rejects hosts > units
                bound = batch_sim.job_bound_s(
                    p.samples, g.request["options"]["timeout_s"], hosts
                )
                self.assertLessEqual(bound, batch_sim.FLEET_JOB_CEILING_S)

    def test_default_timeout_is_the_batch_default_under_backend_batch(self):
        for g in self.groups:
            self.assertEqual(
                g.request["options"]["timeout_s"], batch_sim.MC_BATCH_TIMEOUT_S
            )

    def test_batch_flags_are_absent_from_a_default_request(self):
        """Neither batch flag is set in the fixture's plain `ARGS`, so no bench's
        default request may carry `batch.max_concurrent_jobs` and no group may
        ask for `--resume`. amp-offset's argparse defines neither flag, so this
        is its only lock on the emitted shape (issue #577)."""
        for g in self.groups:
            with self.subTest(label=g.label):
                self.assertNotIn("max_concurrent_jobs", g.request["batch"])
                self.assertIs(g.resume, False)


class OverCeilingBudgetShared:
    """The bench's former per-point default (`LOCAL_TIMEOUT_S` seconds) is a
    per-SAMPLE budget on the fleet: its single-sample bound already exceeds
    the whole-job ceiling, so no `remote.hosts` split fits and klt would only
    warn (issue #528).

    The subclass supplies `R`, `PIN`, `BODY`, `SPICEINIT` and the literal
    `LOCAL_TIMEOUT_S` -- deliberately NOT `R.LOCAL_TIMEOUT_S`, so the
    assertions stay a byte-value guard on the runner's constant (issue #536)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)
        self.points = self.R.build_points(300)

    def _args(self, timeout):
        return SimpleNamespace(timeout=timeout, batch_capacity_wait_s=60.0,
                               batch_runner_version_check="enforce")

    def test_refused_as_a_harness_error_naming_bound_ceiling_and_a_budget(self):
        with self.assertRaises(cr.HarnessError) as cm:
            self.R.build_batch_groups(
                self.PIN, self.BODY, self.points, self.SPICEINIT, self.out,
                self._args(self.LOCAL_TIMEOUT_S))
        msg = str(cm.exception)
        # an over-ceiling budget gets the finest split (one unit per shard),
        # so the bound named is the budget + the fixed per-job overhead
        self.assertIn(f"{self.LOCAL_TIMEOUT_S + batch_sim.FLEET_JOB_OVERHEAD_S}s", msg)
        self.assertIn(f"{batch_sim.FLEET_JOB_CEILING_S}s", msg)  # the ceiling
        self.assertIn("3480s", msg)  # the largest budget that fits
        self.assertIn(f"{batch_sim.MC_BATCH_TIMEOUT_S}s", msg)  # the MC default
        self.assertNotIn("post-layout", msg)

    def test_nothing_is_written_before_the_refusal(self):
        with self.assertRaises(cr.HarnessError):
            self.R.build_batch_groups(
                self.PIN, self.BODY, self.points, self.SPICEINIT, self.out,
                self._args(self.LOCAL_TIMEOUT_S))
        self.assertEqual(sorted(self.out.rglob("*")), [])

    def test_exactly_at_the_limit_is_accepted_and_one_over_is_refused(self):
        limit = batch_sim.FLEET_JOB_CEILING_S - batch_sim.FLEET_JOB_OVERHEAD_S
        groups = self.R.build_batch_groups(
            self.PIN, self.BODY, self.points, self.SPICEINIT, self.out / "ok", self._args(limit)
        )
        self.assertEqual(groups[0].request["remote"]["hosts"], self.points[0].samples)
        with self.assertRaises(cr.HarnessError):
            self.R.build_batch_groups(
                self.PIN, self.BODY, self.points, self.SPICEINIT, self.out / "no",
                self._args(limit + 1)
            )

    def test_a_small_sample_count_still_shards_at_the_default(self):
        points = self.R.build_points(20)
        groups = self.R.build_batch_groups(
            self.PIN, self.BODY, points, self.SPICEINIT, self.out / "small",
            self._args(batch_sim.MC_BATCH_TIMEOUT_S),
        )
        self.assertEqual(groups[0].request["remote"]["hosts"], 2)


class TimeoutDefaultShared:
    """`--timeout` bounds a whole point locally and one sample on the fleet, so
    one number cannot serve both (issue #528).

    The subclass supplies `R` and the literal `LOCAL_TIMEOUT_S` (see
    `OverCeilingBudgetShared` for why the literal, not `R.LOCAL_TIMEOUT_S`)."""

    def test_batch_default_is_the_mc_batch_budget(self):
        self.assertEqual(
            self.R.parse_args(["--backend", "batch"]).timeout, batch_sim.MC_BATCH_TIMEOUT_S
        )

    def test_local_default_is_unchanged(self):
        self.assertEqual(self.R.parse_args([]).timeout, self.LOCAL_TIMEOUT_S)
        self.assertEqual(self.R.parse_args(["--backend", "local"]).timeout, self.R.LOCAL_TIMEOUT_S)

    def test_an_explicit_timeout_still_wins_on_both_backends(self):
        self.assertEqual(self.R.parse_args(["--timeout", "900"]).timeout, 900)
        self.assertEqual(
            self.R.parse_args(["--backend", "batch", "--timeout", "900"]).timeout, 900
        )


class CliBlockShared:
    """`parse_args()` and the batch `--dry-run` branch are `batch_sim`'s
    (issue #653): the flag block and the backend-dependent `--timeout` default
    through `batch_sim.add_mc_batch_args()` / `batch_sim.parse_mc_args()`, the
    printed requests through `batch_sim.print_mc_batch_dry_run()`. Before #653
    each runner carried its own byte-for-byte copy of both, so #528 and #544
    each had to be landed twice.

    The subclass supplies `R`, the literal `LOCAL_TIMEOUT_S` (see
    `OverCeilingBudgetShared` for why the literal, not `R.LOCAL_TIMEOUT_S`) and
    `BENCH_FLAGS`: the option strings of the flags its own bench adds after the
    shared block, in `--help` order (empty for a bench that adds none)."""

    #: Prose both runners spelled identically before #653. None of it may come
    #: back as a private copy in a runner.
    SHARED_PROSE = (
        "ngspice timeout in seconds. Locally this bounds one point",
        "where the points run (default: local ngspice",
        "-- batch requests (one klt sim Monte Carlo request per point) --",
        "nothing submitted, nothing written under sim/",
    )

    def _runner_parser(self):
        """The parser `R.parse_args()` hands to `batch_sim.parse_mc_args()`,
        and the local `--timeout` default it resolves against."""
        seen = {}
        real = batch_sim.parse_mc_args

        def spy(parser, argv, *, local_timeout_s):
            seen["parser"] = parser
            seen["local_timeout_s"] = local_timeout_s
            return real(parser, argv, local_timeout_s=local_timeout_s)

        with mock.patch.object(batch_sim, "parse_mc_args", spy):
            self.R.parse_args(["--backend", "batch"])
        self.assertTrue(seen, "R.parse_args() does not parse through batch_sim.parse_mc_args()")
        return seen["parser"], seen["local_timeout_s"]

    @staticmethod
    def _shapes(parser):
        """Comparable form of a parser's actions: argparse stores the owning
        parser on each action, so the actions of two parsers never compare
        equal directly."""
        return [
            (a.option_strings, a.dest, a.nargs, a.const, a.default, a.type,
             a.choices, a.required, a.help, a.metavar)
            for a in parser._actions
        ]

    def test_the_shared_block_comes_first_and_only_the_bench_flags_follow(self):
        """Flags are listed in `--help` in the order they are added, so the
        block must be registered verbatim and in full before anything the
        bench adds -- that order is what keeps both `--help` outputs
        byte-identical to their pre-#653 text."""
        parser, local_timeout_s = self._runner_parser()
        self.assertEqual(local_timeout_s, self.LOCAL_TIMEOUT_S)
        reference = argparse.ArgumentParser(prog=parser.prog, add_help=True)
        batch_sim.add_mc_batch_args(
            reference, samples_default=self.R.N_SAMPLES, local_timeout_s=self.LOCAL_TIMEOUT_S
        )
        want, got = self._shapes(reference), self._shapes(parser)
        self.assertEqual(got[:len(want)], want)
        self.assertEqual([shape[0] for shape in got[len(want):]], self.BENCH_FLAGS)

    def test_help_names_this_benchs_local_timeout_default(self):
        # Anchored on the --timeout sentence: --batch-capacity-wait-s also
        # prints a "(default ...)", and its 3600 equals one bench's local
        # default, which would satisfy a bare positive check.
        parser, _ = self._runner_parser()
        text = " ".join(parser.format_help().split())
        named = re.findall(r"over its samples; default (\d+)\)", text)
        self.assertEqual(named, [str(self.LOCAL_TIMEOUT_S)])

    def test_main_prints_the_dry_run_through_the_shared_printer(self):
        # Everything in main() before the dry-run branch needs the PDK, so
        # what can be pinned here is that main() delegates dry-run handling to
        # mc_common.handle_mc_dry_run(), which calls batch_sim's shared printer.
        self.assertIn("handle_mc_dry_run", self.R.main.__code__.co_names)
        self.assertIn("print_mc_batch_dry_run", mc_common.handle_mc_dry_run.__code__.co_names)

    def test_no_private_copy_of_the_shared_prose_survives_in_the_runner(self):
        source = inspect.getsource(self.R)
        for prose in self.SHARED_PROSE:
            with self.subTest(prose=prose):
                self.assertNotIn(prose, source)


class BatchCollectionShared:
    """`collect_batch()` tests: hand-built klt reports driven through a
    stubbed `batch_sim.collect()`, the shared collector's guarantees asserted
    once for every bench.

    The subclass supplies `R`, `PIN`, `BODY`, `ARGS`, `BENCH_NAME` (the
    bench's directory under `sim/`) and the report-fixture halves that ARE
    bench content: `REPORT_STEP` (this bench's per-draw increment) and
    `_report_measurements(k, step)` (this bench's vector names and values)."""

    def _report(self, point, **kwargs):
        return _report(point, self._report_measurements, self.REPORT_STEP, **kwargs)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.lib = tmp / "sky130.lib.spice"
        self.lib.write_text("lib")
        self.sha = hashlib.sha256(b"lib").hexdigest()
        self.pdk = SimpleNamespace(lib_file=self.lib)
        self.points = self.R.build_points(20)
        self.bench = tmp / self.BENCH_NAME
        self.corners_dir = self.bench / "corners" / "20260101-000000-abc1234"
        self.R.BUILD_DIR, self._old = tmp / "build", self.R.BUILD_DIR
        self.addCleanup(setattr, self.R, "BUILD_DIR", self._old)

    def _run(self, make_report):
        def fake_collect(groups, runner=None, max_workers=None):
            return [batch_sim.GroupOutcome(g, "t0", "t1", 1.0, 0, make_report(p), None, "", g.request_path)
                    for g, p in zip(groups, self.points)]
        orig = batch_sim.collect
        batch_sim.collect = fake_collect
        self.addCleanup(setattr, batch_sim, "collect", orig)
        return self.R.collect_batch(
            self.PIN, self.pdk, self.BODY, self.points, self.ARGS, self.corners_dir)

    def _assert_bench_untouched(self):
        """A refused batch leaves no record and no half-populated `corners/`
        directory, so the error's "no record was written" is literally true
        (issue #522). Before the shared collector a bench wrote each point's
        sidecar inside the collection loop, so a refusal left them behind."""
        self.assertFalse(self.bench.exists(), f"{self.bench} should not exist after a failure")

    def test_samples_ordered_and_same_shape_as_local_parse(self):
        by_point, execution = self._run(
            lambda p: self._report(p, lib_sha=self.sha, shuffle=True))
        self.assertEqual(sorted(by_point), sorted(p.corner_id for p in self.points))
        first = by_point[self.points[0].corner_id]
        self.assertEqual(len(first), self.points[0].samples)
        # exactly the vectors the local `.control` loop prints -- a measurement
        # in the report but not in the bench's VECTOR_EXPRS must not leak into
        # a sample.
        self.assertEqual(set(first[0]), set(self.R.VECTORS))
        self.assertEqual([s["vout"] for s in first], sorted(s["vout"] for s in first))
        self.assertEqual(execution["backend"], "batch")
        self.assertEqual(execution["jobs"][0]["job_id"], f"job-{self.points[0].corner_id}")

    def test_execution_block_names_the_jobs_and_the_fleet_engine(self):
        _, execution = self._run(lambda p: self._report(p, lib_sha=self.sha))
        self.assertEqual(execution["backend"], "batch")
        self.assertEqual(execution["local_pinned_lib_sha256"], self.sha)
        self.assertEqual([j["job_id"] for j in execution["jobs"]],
                         [f"job-{p.corner_id}" for p in self.points])
        tools = cr.tool_versions()
        self.assertIn("ngspice-45 (remote, batch fleet",
                      batch_sim.record_tools(tools, execution)["ngspice"])
        self.assertNotIn("remote", batch_sim.record_tools(tools, None)["ngspice"])

    def test_sharded_request_records_every_fleet_job_id(self):
        """klt splits a 300-sample point across shards; the ids live under
        `remote.fleet[]` and there is no top-level `job_id` (issue #523)."""
        _, execution = self._run(lambda p: self._report(p, lib_sha=self.sha, shards=3))
        for job, point in zip(execution["jobs"], self.points):
            with self.subTest(point=point.corner_id):
                self.assertIsNone(job["job_id"])
                self.assertEqual(job["job_ids"], _shard_ids(point, 3))

    def test_samples_sidecar_carries_the_shard_ids(self):
        self._run(lambda p: self._report(p, lib_sha=self.sha, shards=3))
        point = self.points[0]
        written = json.loads(batch_sim.samples_path(self.corners_dir, point.corner_id).read_text())
        self.assertIsNone(written["job_id"])
        self.assertEqual(written["job_ids"], _shard_ids(point, 3))

    def test_samples_sidecar_is_unchanged_for_an_unsharded_request(self):
        self._run(lambda p: self._report(p, lib_sha=self.sha))
        point = self.points[0]
        written = json.loads(batch_sim.samples_path(self.corners_dir, point.corner_id).read_text())
        self.assertEqual(written["job_id"], f"job-{point.corner_id}")
        self.assertEqual(written["job_ids"], [f"job-{point.corner_id}"])

    def test_samples_file_and_request_copy_land_next_to_the_record(self):
        by_point, _ = self._run(lambda p: self._report(p, lib_sha=self.sha))
        point = self.points[0]
        written = json.loads(batch_sim.samples_path(self.corners_dir, point.corner_id).read_text())
        self.assertEqual(written["point"], point.corner_id)
        self.assertEqual(written["section"], point.section)
        self.assertEqual(written["seed"], point.seed)
        self.assertEqual(written["requested"], point.samples)
        self.assertEqual(written["vectors"], list(self.R.VECTORS))
        self.assertEqual(written["samples"], by_point[point.corner_id])
        copied = json.loads((self.corners_dir / f"{point.corner_id}.request.json").read_text())
        self.assertEqual(copied["monte_carlo"], {"n": point.samples, "seed": point.seed,
                                                 "vary": "mismatch"})

    def test_draws_without_values_are_dropped_and_counted(self):
        by_point, execution = self._run(
            lambda p: self._report(p, lib_sha=self.sha, drop={3, 4}))
        self.assertEqual(len(by_point[self.points[0].corner_id]), self.points[0].samples - 2)
        self.assertEqual(execution["jobs"][0]["samples_dropped"], 2)
        written = json.loads(
            batch_sim.samples_path(self.corners_dir, self.points[0].corner_id).read_text())
        self.assertEqual(written["dropped_without_values"], 2)

    def test_short_report_is_refused_naming_the_point_and_the_shard_loss(self):
        with self.assertRaises(cr.HarnessError) as cm:
            self._run(lambda p: self._report(p, n=p.samples - 3, lib_sha=self.sha,
                                             unlaunched=3, lost=2))
        msg = str(cm.exception)
        self.assertIn(self.points[0].corner_id, msg)
        self.assertIn(f"requested {self.points[0].samples} samples, report has "
                      f"{self.points[0].samples - 3}", msg)
        self.assertIn("3 unlaunched_shards", msg)
        self.assertIn("2 lost_shard", msg)
        self.assertIn("nothing was run locally", msg)
        self._assert_bench_untouched()

    def test_model_library_mismatch_is_refused_and_writes_nothing(self):
        with self.assertRaises(cr.HarnessError) as cm:
            self._run(lambda p: self._report(p, lib_sha="deadbeef"))
        self.assertIn("sha256", str(cm.exception))
        self._assert_bench_untouched()

    def test_submit_failure_is_an_error_not_a_local_run(self):
        def boom(groups, runner=None, max_workers=None):
            raise batch_sim.BatchError("submit failed")
        orig = batch_sim.collect
        batch_sim.collect = boom
        self.addCleanup(setattr, batch_sim, "collect", orig)
        with self.assertRaises(cr.HarnessError) as cm:
            self.R.collect_batch(
                self.PIN, self.pdk, self.BODY, self.points, self.ARGS, self.corners_dir)
        self.assertIn("submit failed", str(cm.exception))
        self._assert_bench_untouched()


class CommittedRecordsShared:
    """`sim/` records are append-only evidence: rendering one must not rewrite
    it. The subclass supplies `R` and `BENCH_DIR`."""

    def test_rendering_a_committed_record_writes_nothing(self):
        before = {p: p.stat().st_mtime_ns for p in self.BENCH_DIR.glob("records/*")}
        for path in sorted(self.BENCH_DIR.glob("records/*.json")):
            r = json.loads(path.read_text())
            if "points" in r:
                self.R.render_record(r)
        self.assertEqual({p: p.stat().st_mtime_ns for p in self.BENCH_DIR.glob("records/*")},
                         before)
