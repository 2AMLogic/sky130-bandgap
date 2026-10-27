#!/usr/bin/env python3
"""Coverage for `sim/monte-carlo-untrimmed/run_mc_untrimmed.py --backend batch`
(issue #398): each `Point` becomes one `klt sim` Monte Carlo request instead of a
`setseed` / `reset` / `dowhile` ngspice loop, and the `config` axis (which
mismatch coefficients are zeroed) rides in the request's netlist.

No ngspice, no fleet: the tests build requests from the committed netlist
snapshot and read them back.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR / "monte-carlo-untrimmed"))

import batch_sim  # noqa: E402
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
PIN = json.loads((SIM_DIR / "pdk.json").read_text())
SPICEINIT = (SIM_DIR / "spiceinit").read_text()


def _load_runner():
    path = SIM_DIR / "monte-carlo-untrimmed" / "run_mc_untrimmed.py"
    spec = importlib.util.spec_from_file_location("mc_untrimmed", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mc_untrimmed"] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load_runner()
SNAPSHOT = sorted((SIM_DIR / "monte-carlo-untrimmed" / "netlist-snapshots").glob("*.spice"))[-1]
BODY = cr.netlist_body(SNAPSHOT)
ARGS = SimpleNamespace(timeout=3600, batch_capacity_wait_s=60.0, batch_runner_version_check="enforce")


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
        (control,) = by_role["control"]
        self.assertEqual(control["corners"]["process"], ["tt"])
        self.assertEqual(control["monte_carlo"]["n"], R.N_CONTROL)
        self.assertEqual(len(by_role["mismatch"]), len(R.TEMPS_C) * len(R.CONFIGS))
        self.assertEqual({r["corners"]["process"][0] for r in by_role["mismatch"]}, {"tt_mm"})
        (seed_b,) = by_role["seed-check"]
        self.assertEqual(seed_b["monte_carlo"]["seed"], R.SEED_B)

    def test_measurements_are_the_local_loops_lets(self):
        req = self.groups[0].request
        self.assertEqual([m["name"] for m in req["measurements"]], list(R.VECTORS))
        control = R.control_block(self.points[0])
        for name, expr in R.VECTOR_EXPRS:
            self.assertIn(f"let {name} = {expr}", control)
            self.assertIn({"name": name, "expr": expr}, req["measurements"])

    def test_config_axis_zeroes_exactly_that_configs_coefficients(self):
        for g, p in zip(self.groups, self.points):
            with self.subTest(point=p.corner_id):
                overrides = {
                    ln.split("=")[0].split()[1]
                    for ln in g.netlist_path.read_text().splitlines()
                    if ln.startswith(".param sw_mm_") and ln.endswith("=0")
                }
                self.assertEqual(overrides, set(R.CONFIGS[p.config]))

    def test_overrides_follow_the_circuit_body(self):
        # klt writes `.lib <section>` before `.include netlist`, so a trailing
        # `.param <coeff>=0` is the last definition, as in the local deck.
        lines = self.groups[1].netlist_path.read_text().splitlines()  # config=pnp
        first = next(i for i, ln in enumerate(lines) if ln.startswith(".param sw_mm_"))
        self.assertTrue(any(ln.startswith("XBG ") for ln in lines[:first]))

    def test_netlist_drops_save_lib_and_temp(self):
        text = self.groups[0].netlist_path.read_text()
        self.assertIn(f".param vsup={R.SUPPLY_V}", text)
        self.assertIn(".nodeset v(vref)=1.2 v(gdrv)=2.2", text)
        self.assertIn("XBG VREF GDRV VDD 0 bandgap_core", text)
        self.assertIn(".save i(v1)", "\n".join(BODY))  # the snapshot has one to drop
        for banned in (".save", ".lib", ".temp", ".control"):
            self.assertNotIn(banned, text)

    def test_sharding_is_sized_by_sample_count(self):
        self.assertEqual(self.groups[0].request["remote"]["hosts"], 300)


def _report(point, n=None, lib_sha="abc", drop=(), shuffle=False):
    """A stubbed klt report: one `corners[]` entry per Monte Carlo draw."""
    n = point.samples if n is None else n
    corners = []
    for k in range(n):
        ms = [] if k in drop else [
            {"name": "vout", "value": 1.2 + k * 1e-3}, {"name": "vgdrv", "value": 2.0 + k * 1e-3},
        ]
        corners.append({"process": point.section, "temperature_c": point.temp_c, "status": "pass",
                        "monte_carlo": {"sample_index": k}, "measurements": ms, "diagnostics": []})
    if shuffle:
        corners.reverse()
    return {"corner_count": n, "corners": corners, "status": "pass",
            "environment": {"models_lib_sha256": lib_sha, "engine_version": "45",
                            "remote": {"job_id": f"job-{point.corner_id}"}}}


class BatchCollection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.lib = tmp / "sky130.lib.spice"
        self.lib.write_text("lib")
        self.sha = __import__("hashlib").sha256(b"lib").hexdigest()
        self.pdk = SimpleNamespace(lib_file=self.lib)
        self.points = R.build_points(20)
        self.corners_dir = tmp / "corners"
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

    def test_samples_ordered_and_same_shape_as_local_parse(self):
        by_point, execution = self._run(lambda p: _report(p, lib_sha=self.sha, shuffle=True))
        first = by_point[self.points[0].corner_id]
        self.assertEqual(len(first), 20)
        self.assertEqual(set(first[0]), set(R.VECTORS))
        self.assertEqual([s["vout"] for s in first], sorted(s["vout"] for s in first))
        self.assertEqual(execution["backend"], "batch")
        self.assertEqual(execution["jobs"][0]["job_id"], f"job-{self.points[0].corner_id}")

    def test_draws_without_values_are_dropped_and_counted(self):
        by_point, execution = self._run(lambda p: _report(p, lib_sha=self.sha, drop={3, 4}))
        self.assertEqual(len(by_point[self.points[0].corner_id]), 18)
        self.assertEqual(execution["jobs"][0]["samples_dropped"], 2)

    def test_wrong_sample_count_is_refused(self):
        with self.assertRaises(cr.HarnessError) as cm:
            self._run(lambda p: _report(p, n=p.samples - 1, lib_sha=self.sha))
        self.assertIn("requested", str(cm.exception))

    def test_model_library_mismatch_is_refused(self):
        with self.assertRaises(cr.HarnessError) as cm:
            self._run(lambda p: _report(p, lib_sha="deadbeef"))
        self.assertIn("sha256", str(cm.exception))

    def test_submit_failure_is_an_error_not_a_local_run(self):
        def boom(groups, runner=None, max_workers=None):
            raise batch_sim.BatchError("submit failed")
        orig = batch_sim.collect
        batch_sim.collect = boom
        self.addCleanup(setattr, batch_sim, "collect", orig)
        with self.assertRaises(cr.HarnessError) as cm:
            R.collect_batch(PIN, self.pdk, BODY, self.points, ARGS, self.corners_dir)
        self.assertIn("submit failed", str(cm.exception))

    def test_emit_klt_yield_reads_batch_samples_when_no_log(self):
        self._run(lambda p: _report(p, lib_sha=self.sha, drop={0}))
        import emit_klt_yield as E
        cid = E.corner_id_for(27.0)
        vout = E.load_vout_samples(self.corners_dir / f"{cid}.log")
        self.assertEqual(len(vout), 19)  # the dropped draw is absent, the rest converged


if __name__ == "__main__":
    unittest.main()
