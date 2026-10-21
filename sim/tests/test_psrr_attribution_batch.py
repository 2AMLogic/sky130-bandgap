#!/usr/bin/env python3
"""Coverage for `sim/psrr-injector-attribution/run_psrr_injector_attribution.py
--backend batch` (issue #398): the five device-removal variants become `klt sim`
requests (one per variant x supply x analysis), the variant bodies are the same
ones the local deck uses, and `--dry-run` builds the requests without submitting.

No ngspice, no fleet: the tests build requests from the committed netlist
snapshot and read them back; the run path uses a fake klt runner.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
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


def _load_runner():
    path = SIM_DIR / "psrr-injector-attribution" / "run_psrr_injector_attribution.py"
    spec = importlib.util.spec_from_file_location("psrr_attribution", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["psrr_attribution"] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load_runner()
ARGS = SimpleNamespace(
    timeout=1800, batch_capacity_wait_s=60.0, batch_runner_version_check="enforce",
    batch_hosts=1, batch_max_jobs=4, dry_run=True,
)
LIB_SHA = "a" * 64


def klt_corner(process, temp_c, values):
    return {
        "corner_id": f"{process}/x/{temp_c:g}C", "process": process, "temperature_c": temp_c,
        "status": "pass", "runtime_s": 1.0,
        "measurements": [{"name": n, "value": v, "status": "pass"} for n, v in values.items()],
        "diagnostics": [], "artifacts": {},
    }


def fake_runner(group):
    if group.request["analysis"]["kind"] == "ac":
        vals = {n: 1.0 for n, _ in R.AC_MEAS}
        vals["psrr_band_min"] = 55.0
    else:
        vals = {m["name"]: 0.5 for m in group.request["measurements"]}
    rep = {
        "status": "pass", "corner_count": len(group.corners),
        "corners": [klt_corner(c.process, c.temp_c, vals) for c in group.corners],
        "environment": {"engine": "ngspice", "engine_version": "46", "models_lib_sha256": LIB_SHA,
                        "remote": {"job_id": f"job-{group.label}", "instance_type": "c7i.4xlarge",
                                   "elapsed_seconds": 3, "runner_compatibility": "match"}},
        "provenance": {"klt_version": "0.7.1", "pdk": None},
    }
    path = group.dir / "klt-report.json"
    path.write_text(json.dumps(rep))
    return batch_sim.GroupOutcome(group, "t0", "t1", 1.0, 0, rep, None, "", path)


class AttributionBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.base = R.load_base_body()
        self.points = R.matrix()
        self.groups = R.build_batch_groups(
            PIN, self.base, list(R.VARIANTS), self.points, self.tmp, 1800, ARGS)

    def test_one_ac_and_one_op_request_per_variant_and_supply(self):
        self.assertEqual(len(self.groups), len(R.VARIANTS) * 3 * 2)
        by_kind = {"ac": 0, "op": 0}
        for g in self.groups:
            by_kind[g.request["analysis"]["kind"]] += 1
            self.assertEqual(len(g.corners), 15)  # 5 processes x 3 temperatures at one supply
        self.assertEqual(by_kind, {"ac": 15, "op": 15})
        self.assertEqual(sum(len(g.corners) for g in self.groups if g.label.startswith("base-ac")), 45)

    def test_ac_requests_carry_the_manifest_sweep_and_expressions(self):
        for g in self.groups:
            if g.request["analysis"]["kind"] != "ac":
                continue
            self.assertEqual(g.request["analysis"], {"kind": "ac", "args": "dec 10 0.1 1meg"})
            self.assertEqual([(m["name"], m["expr"]) for m in g.request["measurements"]],
                             list(R.AC_MEAS))

    def test_op_measurements_follow_the_variants_op_extra(self):
        ops = {g.label: [m["name"] for m in g.request["measurements"]]
               for g in self.groups if g.request["analysis"]["kind"] == "op"}
        self.assertEqual(ops["core_only-op-v3.63"], ["v_vref", "v_gdrv", "i_vdd"])
        self.assertEqual(ops["ref_open-op-v3.63"],
                         ["v_vref", "v_gdrv", "i_vdd", "v_ng", "v_ne"])
        self.assertEqual(ops["base-op-v3.63"],
                         ["v_vref", "v_gdrv", "i_vdd", "v_ng", "v_ne", "v_nc1"])

    def test_netlists_are_the_variant_bodies_and_carry_no_lib_or_temp(self):
        text = {g.label: g.netlist_path.read_text() for g in self.groups}
        base, core = text["base-ac-v3.63"], text["core_only-ac-v3.63"]
        self.assertTrue(any(ln.startswith("XSU ") for ln in base.splitlines()))
        self.assertFalse(any(ln.startswith("XSU ") for ln in core.splitlines()))
        ref = text["ref_open-ac-v3.63"]
        self.assertNotIn("XMPC1 ", ref)
        self.assertNotIn("XMPC2 ", ref)
        self.assertIn("VNGTIE NG VSS 0", ref)
        self.assertEqual(text["base-ac-v2.97"].count(".param vsup=2.97"), 1)
        for t in text.values():
            self.assertNotIn(".lib", t)  # klt adds it per process corner
            self.assertNotIn(".temp", t)
            self.assertIn(".option reltol=1e-6", t)

    def test_subset_that_is_not_a_cross_product_is_refused(self):
        pts = [("tt", 27.0, 3.3), ("ff", 125.0, 3.3)]
        with self.assertRaises(batch_sim.BatchError):
            R.build_batch_groups(PIN, self.base, list(R.VARIANTS), pts, self.tmp, 1800, ARGS)

    def test_run_all_batch_maps_results_back_to_variant_and_corner(self):
        R.BUILD_DIR = self.tmp / "build"
        lib = self.tmp / "sky130.lib.spice"
        lib.write_text("lib")
        batch_sim_sha = batch_sim.sha256_file(lib)

        def runner(group):
            out = fake_runner(group)
            out.report["environment"]["models_lib_sha256"] = batch_sim_sha
            return out

        pdk = SimpleNamespace(lib_file=lib)
        variants = [R.VARIANTS_BY_NAME["base"], R.VARIANTS_BY_NAME["core_only"]]
        results, blockers, execution = R.run_all_batch(
            pdk, PIN, self.base, variants, self.points, 60, None, "rid", ARGS, runner=runner)
        self.assertEqual(blockers, [])
        self.assertEqual(len(results), 2 * 45)
        res = results[("base", R.corner_id("ff", 125.0, 3.63))]
        self.assertEqual(res["measurements"]["psrr_band_min"], 55.0)
        self.assertEqual(res["measurements"]["v_nc1"], 0.5)
        self.assertNotIn("v_nc1", results[("core_only", R.corner_id("ff", 125.0, 3.63))]["measurements"])
        self.assertEqual(execution["requests"], 2 * 3 * 2)
        self.assertTrue(execution["remote_pdk_matches_pin"])

    def test_dry_run_flag_requires_the_batch_backend(self):
        with self.assertRaises(SystemExit):
            R.parse_args(["--dry-run"])
        args = R.parse_args(["--backend", "batch", "--dry-run"])
        self.assertTrue(args.dry_run)
        with self.assertRaises(SystemExit):
            R.parse_args(["--backend", "batch", "--jobs", "2"])
        self.assertEqual(R.parse_args([]).jobs, 2)


if __name__ == "__main__":
    unittest.main()
