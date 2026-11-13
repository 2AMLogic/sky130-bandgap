#!/usr/bin/env python3
"""Coverage for `sim/error-amp-offset-mc/run_amp_offset_mc.py --backend batch`
(issues #398, #514): each `MismatchPoint` becomes one `klt sim` Monte Carlo
request instead of a `setseed` / `reset` / `dowhile` ngspice loop, and the
per-sample reports are collected back into the sample list the local path
parses out of an ngspice log.

No ngspice, no fleet: the tests build requests from the committed netlist
snapshot and read them back, and drive the collector with hand-built klt
reports through a stubbed `batch_sim.collect()`. The report shape those
fixtures use is taken from klt's own documented Monte Carlo report (one
`corners[]` entry per draw carrying `monte_carlo.sample_index`), NOT captured
from a real fleet run -- no real report for this bench is committed anywhere in
this repo, so these tests cannot establish that a live run parses. The first
real fleet run (issue #370) should be a small-N one for that reason.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import batch_sim  # noqa: E402
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
PIN = json.loads((SIM_DIR / "pdk.json").read_text())
SPICEINIT = (SIM_DIR / "spiceinit").read_text()


def _load_runner():
    path = SIM_DIR / "error-amp-offset-mc" / "run_amp_offset_mc.py"
    spec = importlib.util.spec_from_file_location("amp_offset_mc", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["amp_offset_mc"] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load_runner()
SNAPSHOT = sorted((SIM_DIR / "error-amp-offset-mc" / "netlist-snapshots").glob("*.spice"))[-1]
BODY = cr.netlist_body(SNAPSHOT)
ARGS = SimpleNamespace(timeout=7200, batch_capacity_wait_s=60.0, batch_runner_version_check="enforce")


class BatchRequests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.points = R.build_points(300)
        self.groups = R.build_batch_groups(PIN, BODY, self.points, SPICEINIT, Path(self._tmp.name), ARGS)

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

    def test_roles_map_to_sections(self):
        by_role = {}
        for g, p in zip(self.groups, self.points):
            by_role.setdefault(p.role, []).append(g.request)
        self.assertEqual([r["corners"]["process"] for r in by_role["control"]], [["tt"]])
        self.assertEqual(by_role["control"][0]["monte_carlo"]["n"], R.N_CONTROL)
        self.assertEqual(len(by_role["mismatch"]), len(R.TEMPS_C))
        self.assertEqual({r["corners"]["process"][0] for r in by_role["mismatch"]}, {"tt_mm"})
        (seed_b,) = by_role["seed-check"]
        self.assertEqual(seed_b["monte_carlo"]["seed"], R.SEED_B)
        self.assertEqual(by_role["mismatch"][0]["monte_carlo"]["seed"], R.SEED_A)

    def test_measurements_are_the_local_loops_lets(self):
        req = self.groups[0].request
        self.assertEqual([m["name"] for m in req["measurements"]], list(R.VECTORS))
        control = R.control_block(self.points[0])
        for name, expr in R.VECTOR_EXPRS:
            self.assertIn(f"let {name:<5} = {expr}", control)
            self.assertIn({"name": name, "expr": expr}, req["measurements"])

    def test_netlist_carries_supply_and_nodeset_but_no_lib_or_temp(self):
        text = self.groups[0].netlist_path.read_text()
        self.assertIn(f".param vsup={R.SUPPLY_V}", text)
        self.assertIn(".nodeset v(vref)=1.2 v(gdrv)=2.0", text)
        self.assertIn("XBG VREF GDRV VDD 0 bandgap_core", text)
        for banned in (".lib", ".temp", ".control"):
            self.assertNotIn(banned, text)

    def test_sharding_is_sized_by_sample_count(self):
        # 300 samples x 7200 s serial bound is far above the fleet ceiling.
        self.assertEqual(self.groups[0].request["remote"]["hosts"], 300)


def _report(point, n=None, lib_sha="abc", drop=(), shuffle=False, spread=True,
            unlaunched=0, lost=0):
    """A stubbed klt report: one `corners[]` entry per Monte Carlo draw.

    `spread=False` gives every draw identical values -- the MC-off control
    point's shape, where every sigma must come out exactly 0."""
    n = point.samples if n is None else n
    corners = []
    for k in range(n):
        step = (k * 1e-4) if spread else 0.0
        ms = [] if k in drop else [
            {"name": "vos", "value": 1e-3 + step},
            {"name": "vout", "value": 1.21 + step},
            {"name": "dvbe8", "value": 63e-3 + step},
            {"name": "veb8", "value": 0.65 + step},
            {"name": "dvbe1", "value": 63e-3 + step},
            {"name": "nra", "value": 0.0},  # unused by the manifest, must be ignored
            {"name": "rra", "value": 1.0 + step},
            {"name": "rrb", "value": 2.0},
            {"name": "vgdrv", "value": 2.0 + step},
        ]
        diags = [{"code": "lost_shard"}] if k < lost else []
        corners.append({"process": point.section, "temperature_c": point.temp_c, "status": "pass",
                        "monte_carlo": {"sample_index": k}, "measurements": ms,
                        "diagnostics": diags})
    if shuffle:
        corners.reverse()
    remote = {"job_id": f"job-{point.corner_id}"}
    if unlaunched:
        remote["unlaunched_shards"] = unlaunched
    return {"corner_count": n, "corners": corners, "status": "pass",
            "environment": {"models_lib_sha256": lib_sha, "engine_version": "45",
                            "remote": remote}}


class BatchCollection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.lib = tmp / "sky130.lib.spice"
        self.lib.write_text("lib")
        self.sha = hashlib.sha256(b"lib").hexdigest()
        self.pdk = SimpleNamespace(lib_file=self.lib)
        self.points = R.build_points(20)
        self.bench = tmp / "error-amp-offset-mc"
        self.corners_dir = self.bench / "corners" / "20260101-000000-abc1234"
        R.BUILD_DIR, self._old = tmp / "build", R.BUILD_DIR
        self.addCleanup(setattr, R, "BUILD_DIR", self._old)

    def _run(self, make_report):
        def fake_collect(groups, runner=None, max_workers=None):
            return [batch_sim.GroupOutcome(g, "t0", "t1", 1.0, 0, make_report(p), None, "", g.request_path)
                    for g, p in zip(groups, self.points)]
        orig = batch_sim.collect
        batch_sim.collect = fake_collect
        self.addCleanup(setattr, batch_sim, "collect", orig)
        return R.collect_batch(PIN, self.pdk, BODY, self.points, ARGS, self.corners_dir)

    def _assert_bench_untouched(self):
        self.assertFalse(self.bench.exists(), f"{self.bench} should not exist after a failure")

    def test_samples_ordered_and_same_shape_as_local_parse(self):
        by_point, execution = self._run(lambda p: _report(p, lib_sha=self.sha, shuffle=True))
        self.assertEqual(sorted(by_point), sorted(p.corner_id for p in self.points))
        first = by_point[self.points[0].corner_id]
        self.assertEqual(len(first), self.points[0].samples)
        # exactly the vectors the local `.control` loop prints -- `nra` is in the
        # report but not in VECTOR_EXPRS, so it must not leak into a sample.
        self.assertEqual(set(first[0]), set(R.VECTORS))
        self.assertEqual([s["vout"] for s in first], sorted(s["vout"] for s in first))

    def test_execution_block_names_the_jobs_and_the_fleet_engine(self):
        _, execution = self._run(lambda p: _report(p, lib_sha=self.sha))
        self.assertEqual(execution["backend"], "batch")
        self.assertEqual(execution["local_pinned_lib_sha256"], self.sha)
        self.assertEqual([j["job_id"] for j in execution["jobs"]],
                         [f"job-{p.corner_id}" for p in self.points])
        self.assertIn("ngspice-45 (remote, batch fleet", R.record_tools(execution)["ngspice"])
        self.assertNotIn("remote", R.record_tools(None)["ngspice"])

    def test_samples_file_and_request_copy_land_next_to_the_record(self):
        by_point, _ = self._run(lambda p: _report(p, lib_sha=self.sha))
        point = self.points[0]
        written = json.loads(R.samples_path(self.corners_dir, point.corner_id).read_text())
        self.assertEqual(written["point"], point.corner_id)
        self.assertEqual(written["section"], point.section)
        self.assertEqual(written["seed"], point.seed)
        self.assertEqual(written["requested"], point.samples)
        self.assertEqual(written["vectors"], list(R.VECTORS))
        self.assertEqual(written["samples"], by_point[point.corner_id])
        copied = json.loads((self.corners_dir / f"{point.corner_id}.request.json").read_text())
        self.assertEqual(copied["monte_carlo"], {"n": point.samples, "seed": point.seed,
                                                 "vary": "mismatch"})

    def test_draws_without_values_are_dropped_and_counted(self):
        by_point, execution = self._run(lambda p: _report(p, lib_sha=self.sha, drop={3, 4}))
        self.assertEqual(len(by_point[self.points[0].corner_id]), self.points[0].samples - 2)
        self.assertEqual(execution["jobs"][0]["samples_dropped"], 2)
        written = json.loads(R.samples_path(self.corners_dir, self.points[0].corner_id).read_text())
        self.assertEqual(written["dropped_without_values"], 2)

    def test_short_report_is_refused_naming_the_point_and_the_shard_loss(self):
        with self.assertRaises(cr.HarnessError) as cm:
            self._run(lambda p: _report(p, n=p.samples - 3, lib_sha=self.sha,
                                        unlaunched=3, lost=2))
        msg = str(cm.exception)
        self.assertIn(self.points[0].corner_id, msg)
        self.assertIn(f"requested {self.points[0].samples} samples, report has "
                      f"{self.points[0].samples - 3}", msg)
        self.assertIn("3 unlaunched_shards", msg)
        self.assertIn("2 lost_shard", msg)
        self.assertIn("nothing was run locally", msg)
        self._assert_bench_untouched()

    def test_model_library_mismatch_is_refused(self):
        with self.assertRaises(cr.HarnessError) as cm:
            self._run(lambda p: _report(p, lib_sha="deadbeef"))
        self.assertIn("sha256", str(cm.exception))
        self._assert_bench_untouched()

    def test_submit_failure_is_an_error_not_a_local_run(self):
        def boom(groups, runner=None, max_workers=None):
            raise batch_sim.BatchError("submit failed")
        orig = batch_sim.collect
        batch_sim.collect = boom
        self.addCleanup(setattr, batch_sim, "collect", orig)
        with self.assertRaises(cr.HarnessError) as cm:
            R.collect_batch(PIN, self.pdk, BODY, self.points, ARGS, self.corners_dir)
        self.assertIn("submit failed", str(cm.exception))
        self._assert_bench_untouched()

    def test_control_point_evaluates_to_sigma_zero_from_collected_samples(self):
        by_point, _ = self._run(lambda p: _report(p, lib_sha=self.sha, spread=p.role != "control"))
        control = next(p for p in self.points if p.role == "control")
        samples = by_point[control.corner_id]
        for s in samples:  # the derivation `main()` applies to both backends
            s["rratio"] = s["rra"] / s["rrb"] if s["rrb"] else float("nan")
        res = R.evaluate(control, samples, [], 9.6)
        self.assertTrue(res["pass"], res["checks"])
        zeroed = [c for c in res["checks"] if c["name"].startswith("sigma_zero[")]
        self.assertEqual(len(zeroed), 6)
        self.assertTrue(all(c["pass"] for c in zeroed))


class SharedHelpers(unittest.TestCase):
    """The report helpers are `batch_sim`'s, shared with the sibling MC runner
    (issue #514), so a collector defect shows up in one place for both."""

    def test_runner_has_no_private_copy_of_the_report_helpers(self):
        for name in ("samples_from_report", "shard_loss"):
            self.assertFalse(hasattr(R, name), f"{name} should come from batch_sim")
            self.assertTrue(callable(getattr(batch_sim, name)))

    def test_shard_loss_names_unlaunched_and_lost_counts(self):
        report = {
            "environment": {"remote": {"unlaunched_shards": 11}},
            "corners": [{"diagnostics": [{"code": "lost_shard"}]}, {"diagnostics": []}],
        }
        msg = batch_sim.shard_loss(report)
        self.assertIn("11 unlaunched_shards", msg)
        self.assertIn("1 lost_shard", msg)
        self.assertEqual(batch_sim.shard_loss({"corners": []}), "")


if __name__ == "__main__":
    unittest.main()
