#!/usr/bin/env python3
"""Coverage for `sim/error-amp-offset-mc/run_amp_offset_mc.py --backend batch`
(issue #398): each `MismatchPoint` becomes one `klt sim` Monte Carlo request
instead of a `setseed` / `reset` / `dowhile` ngspice loop.

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


class RealRunRefused(unittest.TestCase):
    def test_batch_without_dry_run_is_refused_before_any_work(self):
        with self.assertRaises(cr.HarnessError) as cm:
            R.main(["--backend", "batch"])
        self.assertIn("dry-run only", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
