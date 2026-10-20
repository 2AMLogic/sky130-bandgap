#!/usr/bin/env python3
"""Coverage for the post-layout benches' `--backend batch` path (issue #396):
`batch_sim.build_groups(..., gate_slug=<post-layout slug>)` and the
`post_layout_common` flag set. Needs no PDK, ngspice, klt or network: the
requests are built from each bench's manifest and a stand-in extracted body.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import batch_sim  # noqa: E402
import post_layout_common as plc  # noqa: E402
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
PIN = json.loads((SIM_DIR / "pdk.json").read_text())
SPICEINIT = (SIM_DIR / "spiceinit").read_text()
BODY = ["V1 VDD 0 'vsup'", "XBG VREF GDRV VDD 0 bandgap_core", ".subckt bandgap_core a b c d", ".ends"]

# slug -> the manifest directory its runner wraps (or owns)
MANIFEST = {
    "psrr-dc-post-layout": "psrr-dc",
    "quiescent-current-post-layout": "quiescent-current",
    "startup-stability-post-layout": "startup-stability-post-layout",
    "startup-ramp-post-layout": "startup-ramp-post-layout",
    "startup-time-post-layout": "startup-time",
    "line-regulation-post-layout": "line-regulation",
    "output-voltage-tc-post-layout": "output-voltage-tc",
}


def matrix(exp):
    c = exp.raw["corners"]
    return [
        cr.Corner(p, float(t), float(v))
        for p in c["process"]
        for t in c["temperature_c"]
        for v in c["supply_v"]
    ]


class PostLayoutBatchRequests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def groups(self, slug):
        exp = cr.load_experiment(SIM_DIR / MANIFEST[slug])
        return exp, batch_sim.build_groups(
            exp, PIN, matrix(exp), BODY, SPICEINIT, self.tmp / slug, 60,
            capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
            gate_slug=slug,
        )

    def test_enabled_benches_build_one_request_per_supply(self):
        for slug in sorted(batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS):
            with self.subTest(slug=slug):
                exp, groups = self.groups(slug)
                self.assertEqual(
                    sorted(g.supply_v for g in groups),
                    sorted({c.supply_v for c in matrix(exp)}),
                )
                self.assertEqual(sum(len(g.corners) for g in groups), len(matrix(exp)))
                for g in groups:
                    self.assertEqual(g.request["backend"], "batch")
                    self.assertEqual(
                        [m["name"] for m in g.request["measurements"]],
                        [m.name for m in exp.measurements],
                    )
                    text = g.netlist_path.read_text()
                    self.assertIn(f".param vsup={g.supply_v}", text)
                    self.assertIn("XBG VREF GDRV VDD 0 bandgap_core", text)
                    self.assertNotIn(".lib", text)  # klt adds it per process corner

    def test_analysis_kinds(self):
        kinds = {
            "psrr-dc-post-layout": "ac",
            "quiescent-current-post-layout": "op",
            "startup-stability-post-layout": "dc",
        }
        for slug, kind in kinds.items():
            with self.subTest(slug=slug):
                _exp, groups = self.groups(slug)
                self.assertEqual(groups[0].request["analysis"]["kind"], kind)

    def test_untranslatable_benches_are_refused_with_a_reason(self):
        for slug in sorted(batch_sim.POST_LAYOUT_BATCH_REFUSALS):
            with self.subTest(slug=slug):
                with self.assertRaises(batch_sim.BatchError) as cm:
                    self.groups(slug)
                self.assertIn(batch_sim.POST_LAYOUT_BATCH_REFUSALS[slug], str(cm.exception))
                self.assertIn("not yet mapped", str(cm.exception))

    def test_every_post_layout_bench_is_enabled_or_refused(self):
        self.assertEqual(
            set(MANIFEST),
            batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS | set(batch_sim.POST_LAYOUT_BATCH_REFUSALS),
        )

    def test_unknown_post_layout_slug_is_refused(self):
        with self.assertRaises(batch_sim.BatchError):
            batch_sim.require_batch_enabled("nope-post-layout", batch_sim.POST_LAYOUT_BATCH_ENABLED_SLUGS)

    def test_gate_slug_none_keeps_the_pre_layout_gate(self):
        exp = cr.load_experiment(SIM_DIR / "quiescent-current")
        with self.assertRaises(batch_sim.BatchError):
            batch_sim.build_groups(
                exp, PIN, matrix(exp), BODY, SPICEINIT, self.tmp / "x", 60,
                capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
            )


class PostLayoutArgs(unittest.TestCase):
    def test_default_backend_is_local_with_300s_timeout(self):
        a = plc.parse_post_layout_args([])
        self.assertEqual((a.backend, a.timeout), ("local", 300))

    def test_batch_backend_defaults_to_the_fleet_timeout(self):
        a = plc.parse_post_layout_args(["--backend", "batch"])
        self.assertEqual(a.timeout, batch_sim.DEFAULT_BATCH_TIMEOUT_S)

    def test_explicit_timeout_wins(self):
        a = plc.parse_post_layout_args(["--backend", "batch", "--timeout", "90"])
        self.assertEqual(a.timeout, 90)


if __name__ == "__main__":
    unittest.main()
