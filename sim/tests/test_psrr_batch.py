#!/usr/bin/env python3
"""Coverage for the PSRR injector screen's batch path (issue #361):
`sim/bin/batch_sim.py` enabled for `psrr-dc-with-injector` (AC deck) and
`sim/psrr-injector-candidates/run_psrr_injector_candidates.py --backend batch`.

The always-on tests replace `klt sim` with a fake runner that returns
klt-shaped reports. `KltVsLocal` is the klt-vs-local comparison the issue asks
for: it needs a klt that understands `measurements[].expr`, `ngspice`, the
pinned PDK and (for the value check) a way to run that klt locally, and skips
itself otherwise. To run it against a klayout-tools checkout:

    KLT_SRC=/path/to/klayout-tools/src python3 sim/tests/test_psrr_batch.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
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
EXP = cr.load_experiment(SIM_DIR / "psrr-dc-with-injector")
LIB_SHA = "a" * 64
SPICEINIT = (SIM_DIR / "spiceinit").read_text()


def _load_harness():
    path = SIM_DIR / "psrr-injector-candidates" / "run_psrr_injector_candidates.py"
    spec = importlib.util.spec_from_file_location("psrr_candidates", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["psrr_candidates"] = mod
    spec.loader.exec_module(mod)
    return mod


H = _load_harness()


def full_matrix():
    c = EXP.raw["corners"]
    return [
        cr.Corner(p, float(t), float(v))
        for p in c["process"]
        for t in c["temperature_c"]
        for v in c["supply_v"]
    ]


def klt_corner(process, temp_c, values, *, diags=None):
    return {
        "corner_id": f"{process}/x/{temp_c:g}C",
        "process": process,
        "temperature_c": temp_c,
        "status": "pass",
        "runtime_s": 12.0,
        "measurements": [{"name": n, "value": v, "status": "pass"} for n, v in values.items()],
        "diagnostics": diags or [],
        "artifacts": {},
    }


def fake_report(group, values_for, *, lib_sha=LIB_SHA, drop=None, diags=None):
    corners = [
        klt_corner(c.process, c.temp_c, values_for(group, c), diags=diags)
        for c in group.corners
    ]
    if drop is not None:
        corners = corners[:-drop]
    return {
        "status": "pass",
        "corner_count": len(group.corners),
        "corners": corners,
        "environment": {
            "engine": "ngspice", "engine_version": "46", "models_lib_sha256": lib_sha,
            "remote": {"job_id": f"job-{group.label}", "instance_type": "c7i.4xlarge",
                       "elapsed_seconds": 30, "runner_compatibility": "match"},
        },
        "provenance": {"klt_version": "0.6.0", "pdk": None},
    }


def fake_runner(values_for, **kw):
    def run(group):
        rep = fake_report(group, values_for, **kw)
        path = group.dir / "klt-report.json"
        path.write_text(json.dumps(rep))
        return batch_sim.GroupOutcome(group, "t0", "t1", 40.0, 0, rep, None, "", path)

    return run


def good_values(group, corner):
    """Plausible, guard-clean values keyed off the group's analysis kind."""
    if group.request["analysis"]["kind"] == "ac":
        return {"psrr_dc": 70.0, "f_dc": 0.1, "psrr_1k": 66.0, "f_1k": 1000.0,
                "psrr_band_min": 66.0, "psrr_1m": 20.0, "f_1m": 1e6, "n_ac_points": 71.0}
    return {"v_vref": 1.17, "v_gdrv": 2.0, "i_vdd": -1e-5, "v_ng": 0.01, "v_ne": 0.5, "v_nc1": 1.5}


class PsrrManifestRequest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.body = ["V1 VDD 0 'vsup' ac 1", "XBG VREF GDRV VDD 0 bandgap_core"]
        self.groups = batch_sim.build_groups(
            EXP, PIN, full_matrix(), self.body, SPICEINIT, self.tmp, 1800,
            capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
        )

    def test_slug_is_enabled(self):
        self.assertIn("psrr-dc-with-injector", batch_sim.BATCH_ENABLED_SLUGS)

    def test_three_supply_jobs_carry_the_ac_sweep_and_the_manifests_expressions(self):
        self.assertEqual([g.supply_v for g in self.groups], [2.97, 3.3, 3.63])
        self.assertEqual(sum(len(g.corners) for g in self.groups), 45)
        for g in self.groups:
            req = g.request
            self.assertEqual(req["analysis"], {"kind": "ac", "args": "dec 10 0.1 1meg"})
            self.assertEqual([m["name"] for m in req["measurements"]], [m.name for m in EXP.measurements])
            # AC vector slices pass through verbatim: there is no `let` chain to inline
            self.assertEqual([m["expr"] for m in req["measurements"]], [m.expr for m in EXP.measurements])
            for sent, m in zip(req["measurements"], EXP.measurements):
                self.assertEqual(sent.get("limits", {}).get("min"), m.min)
                self.assertEqual(sent.get("limits", {}).get("max"), m.max)
            self.assertIn(".option reltol=1e-6", g.netlist_path.read_text())
            self.assertIn(f".param vsup={g.supply_v}", g.netlist_path.read_text())


class CandidatesBatchRequests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = H.load_base_body()
        self.pdk = SimpleNamespace(lib_file=self.tmp / "sky130.lib.spice")
        self.pdk.lib_file.write_text("lib")
        self.sha = batch_sim.sha256_file(self.pdk.lib_file)
        self.args = SimpleNamespace(
            batch_capacity_wait_s=60, batch_runner_version_check="enforce", batch_max_jobs=4,
            batch_hosts=1)
        H.BUILD_DIR = self.tmp / "build"

    def run_batch(self, variants, points, runner, corners_dir=None):
        return H.run_all_batch(
            self.pdk, PIN, self.base, [H.VARIANTS_BY_NAME[v] for v in variants], points, 60,
            corners_dir, "rid", self.args, runner=runner)

    def test_netlist_is_the_variant_body_not_the_base(self):
        base = H.batch_netlist(H.VARIANTS_BY_NAME["base"], 3.63, self.base)
        ref3 = H.batch_netlist(H.VARIANTS_BY_NAME["ref3_ngclamp"], 3.63, self.base)
        self.assertNotIn("XMPC3", base)
        self.assertIn("XMPC3", ref3)
        self.assertIn("XMNG", ref3)
        for text in (base, ref3):
            self.assertIn(".param vsup=3.63", text)
            self.assertNotIn(".lib", text)  # klt adds it per process corner

    def test_mpc2_vs_gates_mpc2_on_vsense_and_adds_no_device(self):
        base = H.batch_netlist(H.VARIANTS_BY_NAME["base"], 3.63, self.base)
        vs = H.batch_netlist(H.VARIANTS_BY_NAME["mpc2_vs"], 3.63, self.base)
        mng = H.batch_netlist(H.VARIANTS_BY_NAME["mpc2_vs_mng"], 3.63, self.base)
        card = lambda text: next(ln for ln in text.splitlines() if ln.startswith("XMPC2 "))
        self.assertTrue(card(base).startswith("XMPC2 NG NG NC1 VDD "))
        self.assertTrue(card(vs).startswith("XMPC2 NG VSENSE NC1 VDD "))
        self.assertEqual(base.count("\nX"), vs.count("\nX"))
        self.assertIn("XMNG ", mng)
        self.assertNotIn("XMNG ", vs)

    def test_every_point_becomes_one_ac_and_one_op_request_per_variant_and_supply(self):
        points = H.matrix()
        seen = []

        def spy(group):
            seen.append(group)
            return fake_runner(good_values, lib_sha=self.sha)(group)

        results, blockers, execution = self.run_batch(["base", "ref3"], points, spy)
        self.assertEqual(blockers, [])
        self.assertEqual(len(seen), 2 * 3 * 2)  # variants x supplies x (ac, op)
        self.assertEqual(execution["requests"], 12)
        self.assertEqual(len(results), 2 * 45)
        ac = [g for g in seen if g.request["analysis"]["kind"] == "ac"]
        op = [g for g in seen if g.request["analysis"]["kind"] == "op"]
        self.assertEqual(len(ac), len(op))
        for g in ac:
            self.assertEqual(g.request["analysis"]["args"], "dec 10 0.1 1meg")
            self.assertEqual([(m["name"], m["expr"]) for m in g.request["measurements"]], list(H.AC_MEAS))
            self.assertEqual(len(g.corners), 15)
        for g in op:
            self.assertEqual([(m["name"], m["expr"]) for m in g.request["measurements"]], list(H.OP_ALWAYS))
        # AC and OP values land on the same point, as the local deck's single log does
        m = results[("base", H.corner_id("ff", 125.0, 3.63))]["measurements"]
        self.assertEqual(m["psrr_band_min"], 66.0)
        self.assertEqual(m["v_ng"], 0.01)
        # ... and satisfy the harness's own sweep guards
        checks = H.evaluate(results, points, [H.VARIANTS_BY_NAME["base"], H.VARIANTS_BY_NAME["ref3"]])
        self.assertTrue(all(c["pass"] for c in checks if c["name"].startswith("sweep_guards")))

    def test_batch_hosts_shards_every_request_over_remote_hosts(self):
        points = H.matrix()

        def requests(hosts):
            seen = []

            def spy(group):
                seen.append(group)
                return fake_runner(good_values, lib_sha=self.sha)(group)

            self.args.batch_hosts = hosts
            self.run_batch(["base"], points, spy)
            return [g.request for g in seen]

        default = {r["remote"]["hosts"] for r in requests(1)}
        self.assertNotIn(3, default)  # the budget-derived default, not the override
        sharded = requests(3)
        self.assertEqual(len(sharded), 3 * 2)
        self.assertTrue(all(r["remote"] == {"hosts": 3} for r in sharded))

    def test_request_concurrency_is_the_job_budget_divided_by_shards(self):
        from unittest import mock
        real_collect = batch_sim.collect
        for timeout, max_jobs, expect in ((60, 4, 4), (1800, 8, 1), (1800, 40, 2)):
            self.args.batch_max_jobs = max_jobs
            seen = {}

            def spy(groups, runner, max_workers):
                seen["workers"] = max_workers
                return real_collect(groups, runner, max_workers=max_workers)

            runner = fake_runner(good_values, lib_sha=self.sha)
            with mock.patch.object(batch_sim, "collect", spy):
                H.run_all_batch(
                    self.pdk, PIN, self.base, [H.VARIANTS_BY_NAME["base"]], H.matrix(), timeout,
                    None, "rid", self.args, runner=runner)
            self.assertEqual(seen["workers"], expect)

    def test_remote_library_that_is_not_the_pin_is_a_blocker(self):
        _r, blockers, execution = self.run_batch(
            ["base"], [("ff", 125.0, 3.63)], fake_runner(good_values, lib_sha="b" * 64))
        self.assertTrue(any("model library sha256" in b for b in blockers))
        self.assertFalse(execution["remote_pdk_matches_pin"])

    def test_missing_corner_is_a_blocker_and_a_missing_measurement(self):
        points = [("tt", 27.0, 3.3), ("ss", 27.0, 3.3)]
        results, blockers, _ex = self.run_batch(["base"], points, fake_runner(good_values, lib_sha=self.sha, drop=1))
        self.assertTrue(any("expected 2 corners" in b for b in blockers))
        self.assertTrue(any("no ac result returned" in b for b in blockers))
        self.assertEqual(results[("base", "ss_27c_3.30v")]["measurements"], {})

    def test_error_diagnostic_blocks(self):
        diag = [{"code": "measurement", "severity": "error", "message": "no scalar"}]
        _r, blockers, _ex = self.run_batch(
            ["base"], [("tt", 27.0, 3.3)], fake_runner(good_values, lib_sha=self.sha, diags=diag))
        self.assertTrue(any("no scalar" in b for b in blockers))

    def test_failed_submission_is_an_error_and_never_runs_locally(self):
        def boom(group):
            return batch_sim.GroupOutcome(group, "t0", "t1", 1.0, 1, None, "klt sim exited 1: boom")

        with self.assertRaises(cr.HarnessError) as ctx:
            self.run_batch(["base"], [("tt", 27.0, 3.3)], boom)
        self.assertIn("nothing was run locally", str(ctx.exception))

    def test_non_cross_product_points_are_refused(self):
        with self.assertRaises(cr.HarnessError):
            self.run_batch(["base"], [("tt", 27.0, 3.3), ("ss", -40.0, 3.3), ("tt", -40.0, 3.3)],
                           fake_runner(good_values, lib_sha=self.sha))

    def test_evidence_files_are_written(self):
        out = self.tmp / "corners"
        self.run_batch(["base"], [("tt", 27.0, 3.3)], fake_runner(good_values, lib_sha=self.sha),
                       corners_dir=out)
        self.assertTrue((out / "base__tt_27c_3.30v.log").is_file())
        self.assertTrue((out / "batch-base-ac-v3.30" / "request.json").is_file())
        self.assertTrue((out / "batch-base-op-v3.30" / "klt-report.json").is_file())

    def test_jobs_flag_is_refused_with_batch(self):
        with self.assertRaises(SystemExit):
            H.parse_args(["--backend", "batch", "--jobs", "4"])
        args = H.parse_args(["--backend", "batch"])
        self.assertEqual(args.backend, "batch")
        self.assertEqual(H.parse_args([]).jobs, 2)


class KltVsLocal(unittest.TestCase):
    """One corner (tt / 27 C / 3.3 V) of `psrr-dc-with-injector`, every
    measurement: klt's generated deck and klt's results against the local
    runner's, on the committed netlist snapshot of that bench."""

    SNAPSHOT = SIM_DIR / "psrr-dc-with-injector" / "netlist-snapshots" / "20260923-124813-af9ff1e.spice"

    @classmethod
    def setUpClass(cls):
        klt = shutil.which("klt")
        if not klt:
            raise unittest.SkipTest("klt not installed")
        cls.py = Path(klt).read_text(errors="replace").splitlines()[0].removeprefix("#!").strip()
        cls.env = dict(os.environ)
        if os.environ.get("KLT_SRC"):
            cls.env["PYTHONPATH"] = os.environ["KLT_SRC"]
        probe = subprocess.run(
            [cls.py, "-c", "from klayout_tools import sim; sim._write_corner_deck"],
            capture_output=True, text=True, env=cls.env)
        if probe.returncode != 0:
            raise unittest.SkipTest("klt private deck writer unavailable")
        if not cls.SNAPSHOT.is_file():
            raise unittest.SkipTest("netlist snapshot missing")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.corner = cr.Corner("tt", 27.0, 3.3)
        body = sim_common.load_base_body(self.SNAPSHOT, set())
        self.body = body
        (g,) = batch_sim.build_groups(
            EXP, PIN, [self.corner], body, SPICEINIT, self.tmp / "b", 1800,
            capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30)
        self.group = g

    def klt(self, code):
        return subprocess.run([self.py, "-c", code], capture_output=True, text=True,
                              env=self.env, cwd=self.group.dir)

    def test_klt_deck_carries_the_local_analysis_and_every_expression(self):
        deck_path = self.tmp / "klt.deck"
        proc = self.klt(f"""
import json
from klayout_tools import sim
req = json.load(open({str(self.group.request_path)!r}))
pt = sim.CornerPoint('tt', {{}}, 27.0)
sim._write_corner_deck(deck_path={str(deck_path)!r}, netlist_path={str(self.group.netlist_path)!r},
    models_lib='/PDK/' + req['models']['lib'], point=pt, analysis=req['analysis'],
    measurements_spec=req['measurements'], raw_path=None)
""")
        if proc.returncode != 0:
            self.skipTest(f"klt cannot build an expr deck: {proc.stderr[-200:]}")
        klt_lines = deck_path.read_text().splitlines()
        local = cr.build_deck(EXP, SimpleNamespace(lib_file=Path("/PDK/" + PIN["ngspice_lib"])),
                              self.corner, self.body).splitlines()
        self.assertIn("ac dec 10 0.1 1meg", [ln.lower() for ln in klt_lines])
        self.assertIn("ac dec 10 0.1 1meg", [ln.lower() for ln in local])
        for m in EXP.measurements:
            self.assertIn(f"let {m.name} = {m.expr}", klt_lines)
            self.assertIn(f"let meas_{m.name} = {m.expr}", local)

    def test_klt_values_equal_the_local_runner_on_every_measurement(self):
        try:
            pdk = cr.resolve_pdk(PIN)
        except cr.HarnessError as exc:
            self.skipTest(f"no pinned PDK on this host: {exc}")
        if not shutil.which("ngspice"):
            self.skipTest("ngspice not installed")
        local_dir = self.tmp / "local"
        deck = cr.build_deck(EXP, pdk, self.corner, self.body)
        raw, _rc, timed_out = sim_common.run_ngspice(local_dir, "c", deck, 600)
        self.assertFalse(timed_out)
        local = sim_common.parse_measurements(raw)
        self.assertEqual(set(local), {m.name for m in EXP.measurements})
        proc = self.klt(
            "import sys; from klayout_tools.cli import main; sys.exit(main(['sim', "
            f"{str(self.group.request_path)!r}, '--backend', 'local', '--format', 'json', "
            f"'-o', {str(self.tmp / 'out')!r}]))")
        if "requires 'name' and 'spice'" in proc.stdout + proc.stderr:
            self.skipTest("installed klt predates measurements[].expr; set KLT_SRC")
        self.assertIn(proc.returncode, (0, 3), proc.stderr[-500:])
        (kc,) = json.loads(proc.stdout)["corners"]
        got = {m["name"]: m["value"] for m in kc["measurements"]}
        self.assertEqual(set(got), set(local))
        for name, want in local.items():
            # klt prints with ngspice's default digits; the local harness does too
            self.assertAlmostEqual(got[name], want, delta=max(abs(want) * 1e-4, 1e-4), msg=name)


if __name__ == "__main__":
    unittest.main()
