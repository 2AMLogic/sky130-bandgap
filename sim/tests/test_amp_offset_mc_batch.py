#!/usr/bin/env python3
"""Coverage for `sim/error-amp-offset-mc/run_amp_offset_mc.py --backend batch`
(issues #398, #514): each `MismatchPoint` becomes one `klt sim` Monte Carlo
request instead of a `setseed` / `reset` / `dowhile` ngspice loop, and the
per-sample reports are collected back into the sample list the local path
parses out of an ngspice log.

The bench-independent half of this coverage -- the request-shape, budget and
collector tests of the ONE `batch_sim` collector both MC benches drive --
lives in `mc_batch_shared.py` (issue #536); only what reads this bench's own
constants stays here.

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

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR / "tests"))

import batch_sim  # noqa: E402
import mc_batch_shared  # noqa: E402
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
PIN = json.loads((SIM_DIR / "pdk.json").read_text())
SPICEINIT = (SIM_DIR / "spiceinit").read_text()

R = mc_batch_shared._load_runner(SIM_DIR / "error-amp-offset-mc" / "run_amp_offset_mc.py",
                                 "amp_offset_mc")
SNAPSHOT = sorted((SIM_DIR / "error-amp-offset-mc" / "netlist-snapshots").glob("*.spice"))[-1]
BODY = cr.netlist_body(SNAPSHOT)
ARGS = SimpleNamespace(timeout=batch_sim.MC_BATCH_TIMEOUT_S, batch_capacity_wait_s=60.0,
                       batch_runner_version_check="enforce")


class _AmpBench:
    """What the shared mixins read: this bench's runner and deck constants."""

    R = R
    PIN = PIN
    BODY = BODY
    SPICEINIT = SPICEINIT
    ARGS = ARGS


class BatchRequests(_AmpBench, mc_batch_shared.BatchRequestsShared, unittest.TestCase):
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


class OverCeilingBudgetIsRefused(_AmpBench, mc_batch_shared.OverCeilingBudgetShared,
                                 unittest.TestCase):
    LOCAL_TIMEOUT_S = 7200


class TimeoutDefaultFollowsTheBackend(_AmpBench, mc_batch_shared.TimeoutDefaultShared,
                                      unittest.TestCase):
    LOCAL_TIMEOUT_S = 7200


class BatchCollection(_AmpBench, mc_batch_shared.BatchCollectionShared, unittest.TestCase):
    BENCH_NAME = "error-amp-offset-mc"
    REPORT_STEP = 1e-4

    @staticmethod
    def _report_measurements(k, step):
        return [
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

    def test_control_point_evaluates_to_sigma_zero_from_collected_samples(self):
        by_point, _ = self._run(
            lambda p: self._report(p, lib_sha=self.sha, spread=p.role != "control"))
        control = next(p for p in self.points if p.role == "control")
        samples = by_point[control.corner_id]
        for s in samples:  # the derivation `main()` applies to both backends
            s["rratio"] = s["rra"] / s["rrb"] if s["rrb"] else float("nan")
        res = R.evaluate(control, samples, [], 9.6)
        self.assertTrue(res["pass"], res["checks"])
        zeroed = [c for c in res["checks"] if c["name"].startswith("sigma_zero[")]
        self.assertEqual(len(zeroed), 6)
        self.assertTrue(all(c["pass"] for c in zeroed))


BENCH_DIR = SIM_DIR / "error-amp-offset-mc"


class SeedWording(unittest.TestCase):
    """On the batch path klt derives every sample's own `.options seed=` from
    the request's `monte_carlo.seed`; there is no `setseed` / `reset` loop, so
    a record that says `setseed` names a mechanism that did not run (#523).
    The local wording must stay byte for byte what it was."""

    LOCAL = {"backend": "local"}
    BATCH = {"backend": "batch"}

    def test_local_seed_prose_is_unchanged_byte_for_byte(self):
        for execution in (None, {}, self.LOCAL):
            with self.subTest(execution=execution):
                self.assertEqual(
                    R.seed_mechanism(execution),
                    f"`setseed {R.SEED_A}` (second-seed point uses {R.SEED_B})")
                self.assertEqual(R.seed_label(execution, R.SEED_B), f"`setseed {R.SEED_B}`")
                self.assertEqual(R.seed_convention(execution), f"fixed setseed {R.SEED_A}")

    def test_batch_seed_prose_names_the_monte_carlo_seed_and_never_setseed(self):
        for text in (R.seed_mechanism(self.BATCH), R.seed_label(self.BATCH, R.SEED_B),
                     R.seed_convention(self.BATCH)):
            with self.subTest(text=text):
                self.assertNotIn("setseed", text)
                self.assertIn("monte_carlo", text)
        self.assertIn(str(R.SEED_A), R.seed_mechanism(self.BATCH))
        self.assertIn(str(R.SEED_B), R.seed_label(self.BATCH, R.SEED_B))
        self.assertIn(str(R.SEED_A), R.seed_convention(self.BATCH))

    # The committed records are read-only fixtures here: they are this repo's
    # append-only evidence and are never rewritten (see the issue's scope note).
    def _record(self, backend):
        for path in sorted(BENCH_DIR.glob("records/*.json")):
            r = json.loads(path.read_text())
            if "points" in r and (r.get("execution") or {}).get("backend") == backend:
                return r
        self.skipTest(f"no committed {backend} record for this bench")

    def test_a_batch_record_renders_with_no_setseed_anywhere(self):
        md = R.render_record(self._record("batch"))
        self.assertNotIn("setseed", md)
        self.assertIn(f"Reproducible: klt `monte_carlo` seed {R.SEED_A}", md)
        self.assertIn(f"`monte_carlo` seed {R.SEED_B}", md)

    def test_a_local_record_still_renders_the_setseed_wording(self):
        md = R.render_record(self._record(None))
        self.assertIn(
            f"Reproducible: `setseed {R.SEED_A}` (second-seed point uses {R.SEED_B}). "
            f"N matches", md)
        self.assertIn(f"`setseed {R.SEED_B}`", md)

    def test_statistical_convention_follows_the_backend(self):
        self.assertIn("fixed setseed", R.seed_convention(None))
        self.assertNotIn("setseed", R.seed_convention(self.BATCH))


class CommittedRecordsAreNotRewritten(_AmpBench, mc_batch_shared.CommittedRecordsShared,
                                      unittest.TestCase):
    BENCH_DIR = BENCH_DIR


class SharedHelpers(unittest.TestCase):
    """The report helpers AND the collector that drives them are `batch_sim`'s,
    shared with the sibling MC runner (issues #514, #522), so a collector defect
    -- or a fix -- shows up in one place for both benches."""

    def test_runner_has_no_private_copy_of_the_report_helpers(self):
        for name in ("samples_from_report", "shard_loss", "record_tools", "samples_path",
                     "collect_mc_batch"):
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
