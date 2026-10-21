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


class RealRunRefused(unittest.TestCase):
    def test_batch_without_dry_run_is_refused_before_any_work(self):
        with self.assertRaises(cr.HarnessError) as cm:
            R.main(["--backend", "batch"])
        self.assertIn("dry-run only", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
