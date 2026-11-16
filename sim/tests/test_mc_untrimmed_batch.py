#!/usr/bin/env python3
"""Coverage for `sim/monte-carlo-untrimmed/run_mc_untrimmed.py --backend batch`
(issue #398): each `Point` becomes one `klt sim` Monte Carlo request instead of
a `setseed` / `reset` / `dowhile` ngspice loop, and the `config` axis (which
mismatch coefficients are zeroed) rides in the request's netlist.

The bench-independent half of this coverage -- the request-shape, budget and
collector tests of the ONE `batch_sim` collector both MC benches drive --
lives in `mc_batch_shared.py` (issue #536); only what reads this bench's own
constants stays here.

No ngspice, no fleet: the tests build requests from the committed netlist
snapshot and read them back.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR / "tests"))
sys.path.insert(0, str(SIM_DIR / "monte-carlo-untrimmed"))

import batch_sim  # noqa: E402
import mc_batch_shared  # noqa: E402
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
PIN = json.loads((SIM_DIR / "pdk.json").read_text())
SPICEINIT = (SIM_DIR / "spiceinit").read_text()

R = mc_batch_shared._load_runner(SIM_DIR / "monte-carlo-untrimmed" / "run_mc_untrimmed.py",
                                 "mc_untrimmed")
SNAPSHOT = sorted((SIM_DIR / "monte-carlo-untrimmed" / "netlist-snapshots").glob("*.spice"))[-1]
BODY = cr.netlist_body(SNAPSHOT)
ARGS = SimpleNamespace(timeout=batch_sim.MC_BATCH_TIMEOUT_S, batch_capacity_wait_s=60.0,
                       batch_runner_version_check="enforce")


class _UntrimmedBench:
    """What the shared mixins read: this bench's runner and deck constants."""

    R = R
    PIN = PIN
    BODY = BODY
    SPICEINIT = SPICEINIT
    ARGS = ARGS


class BatchRequests(_UntrimmedBench, mc_batch_shared.BatchRequestsShared, unittest.TestCase):
    def test_max_concurrent_jobs_is_passed_through(self):
        # The default-off half lives in the shared fixture (issue #577); only
        # this bench's argparse defines the flag, so the pass-through half
        # stays bench-local.
        args = SimpleNamespace(**vars(ARGS), batch_max_concurrent_jobs=20)
        with tempfile.TemporaryDirectory() as tmp:
            groups = R.build_batch_groups(PIN, BODY, self.points, SPICEINIT, Path(tmp), args)
            for g in groups:
                self.assertEqual(g.request["batch"]["max_concurrent_jobs"], 20)
                self.assertEqual(json.loads(g.request_path.read_text()), g.request)

    def test_resume_reaches_the_klt_command_line(self):
        # The default-off half lives in the shared fixture (issue #577); only
        # this bench's argparse defines the flag, so the pass-through half
        # stays bench-local.
        args = SimpleNamespace(**vars(ARGS), batch_resume=True)
        with tempfile.TemporaryDirectory() as tmp:
            groups = R.build_batch_groups(PIN, BODY, self.points[:1], SPICEINIT, Path(tmp), args)
            self.assertTrue(groups[0].resume)
            self.assertEqual(json.loads(groups[0].request_path.read_text()), groups[0].request)
            for group, expect in ((groups[0], True), (self.groups[0], False)):
                with mock.patch.object(batch_sim.subprocess, "run") as run:
                    run.return_value = SimpleNamespace(returncode=2, stdout="", stderr="")
                    batch_sim.run_klt(group, klt="klt")
                self.assertEqual("--resume" in run.call_args.args[0], expect)

    def test_resume_is_rejected_for_non_batch_backends(self):
        with self.assertRaises(cr.HarnessError):
            R.check_batch_only_flags(SimpleNamespace(backend="local", batch_resume=True))
        R.check_batch_only_flags(SimpleNamespace(backend="batch", batch_resume=True))
        R.check_batch_only_flags(SimpleNamespace(backend="local", batch_resume=False))

    def test_shard_loss_names_unlaunched_and_lost_counts(self):
        # `shard_loss`/`samples_from_report` moved into batch_sim (issue #514),
        # then `record_tools`/`samples_path` and the collector itself (#522), and
        # then the seed-contract predicates (#533), so both MC runners read a klt
        # report -- and describe how their draws were seeded -- through one
        # implementation.
        for name in ("shard_loss", "samples_from_report", "record_tools", "samples_path",
                     "collect_mc_batch",
                     "is_batch", "seed_label", "seed_convention", "seed_mechanism"):
            self.assertFalse(hasattr(R, name), f"{name} should come from batch_sim")
            self.assertTrue(callable(getattr(batch_sim, name)))
        # the pre-#533 private name must not come back either
        self.assertFalse(hasattr(R, "_is_batch"), "_is_batch should come from batch_sim")
        report = {
            "environment": {"remote": {"unlaunched_shards": 11}},
            "corners": [{"diagnostics": [{"code": "lost_shard"}]}, {"diagnostics": []}],
        }
        msg = batch_sim.shard_loss(report)
        self.assertIn("11 unlaunched_shards", msg)
        self.assertIn("1 lost_shard", msg)
        self.assertEqual(batch_sim.shard_loss({"corners": []}), "")

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


class OverCeilingBudgetIsRefused(_UntrimmedBench, mc_batch_shared.OverCeilingBudgetShared,
                                 unittest.TestCase):
    LOCAL_TIMEOUT_S = 3600


class TimeoutDefaultFollowsTheBackend(_UntrimmedBench, mc_batch_shared.TimeoutDefaultShared,
                                      unittest.TestCase):
    LOCAL_TIMEOUT_S = 3600


class BatchCollection(_UntrimmedBench, mc_batch_shared.BatchCollectionShared,
                      unittest.TestCase):
    BENCH_NAME = "monte-carlo-untrimmed"
    REPORT_STEP = 1e-3

    @staticmethod
    def _report_measurements(k, step):
        return [
            {"name": "vout", "value": 1.2 + step}, {"name": "vgdrv", "value": 2.0 + step},
        ]

    def test_samples_sidecar_keeps_this_benchs_config_axis(self):
        """`config` is this bench's extra per-point field; the shared collector
        takes it through `extra_fields` and keeps it in its historical place,
        right after `section` (issue #522)."""
        self._run(lambda p: self._report(p, lib_sha=self.sha))
        point = self.points[0]
        written = json.loads(batch_sim.samples_path(self.corners_dir, point.corner_id).read_text())
        self.assertEqual(written["config"], point.config)
        self.assertEqual(list(written)[:3], ["point", "section", "config"])

    def test_emit_klt_yield_reads_batch_samples_when_no_log(self):
        self._run(lambda p: self._report(p, lib_sha=self.sha, drop={0}))
        import emit_klt_yield as E
        cid = E.corner_id_for(27.0)
        vout = E.load_vout_samples(self.corners_dir / f"{cid}.log")
        self.assertEqual(len(vout), 19)  # the dropped draw is absent, the rest converged


BENCH_DIR = SIM_DIR / "monte-carlo-untrimmed"


class SeedWording(unittest.TestCase):
    """On the batch path klt derives every sample's own `.options seed=` from
    the request's `monte_carlo.seed`; there is no `setseed` / `reset` loop, so
    a record that says `setseed` -- including the convergence table's
    "ngspice draws sequentially per `setseed`" claim -- names a mechanism that
    did not run (issue #523). The local wording is unchanged byte for byte."""

    LOCAL = {"backend": "local"}
    BATCH = {"backend": "batch"}

    def test_local_seed_prose_is_unchanged_byte_for_byte(self):
        for execution in (None, {}, self.LOCAL):
            with self.subTest(execution=execution):
                self.assertEqual(
                    batch_sim.seed_mechanism(execution, R.SEED_A, R.SEED_B),
                    f"`setseed {R.SEED_A}` (second-seed point uses {R.SEED_B})")
                self.assertEqual(
                    batch_sim.seed_label(execution, R.SEED_B), f"`setseed {R.SEED_B}`")
                self.assertEqual(
                    batch_sim.seed_convention(execution, R.SEED_A), f"fixed setseed {R.SEED_A}")
                self.assertEqual(
                    R.convergence_sequence_note(execution),
                    "ngspice draws sequentially per `setseed`, so the first K samples of "
                    "the full run are identical to what a standalone K-sample run would "
                    "produce \u2014 this is a real convergence trend, not a re-simulation "
                    "at each row")

    def test_batch_seed_prose_never_says_setseed(self):
        for text in (batch_sim.seed_mechanism(self.BATCH, R.SEED_A, R.SEED_B),
                     batch_sim.seed_label(self.BATCH, R.SEED_B),
                     batch_sim.seed_convention(self.BATCH, R.SEED_A),
                     R.convergence_sequence_note(self.BATCH)):
            with self.subTest(text=text):
                self.assertNotIn("setseed", text)
                self.assertIn("monte_carlo", text)

    def test_batch_convergence_note_claims_only_the_verified_property(self):
        """The rows are prefixes of one `monte_carlo.sample_index`-ordered draw
        sequence -- that much `batch_sim.samples_from_report()` guarantees. That
        a standalone K-sample request reproduces the first K draws of an
        N-sample one is a local `setseed` property this repo has not shown for
        klt's derived per-sample seeds, so the batch wording must not claim it."""
        note = R.convergence_sequence_note(self.BATCH)
        self.assertIn("sample_index", note)
        self.assertIn("not a re-simulation at each row", note)
        self.assertIn("not known to reproduce these same first K draws", note)
        clause = R.convergence_sequence_clause({"backend": "batch"}, 300, 100)
        self.assertNotIn("identical to a standalone", clause)
        self.assertEqual(
            R.convergence_sequence_clause(None, 300, 100),
            "same seed stream, the 300-sample run's first 100 draws are identical "
            "to a standalone 100-sample run")

    def test_sample_count_sufficient_detail_follows_the_backend(self):
        """The check detail is stored in the record JSON, so a committed record
        replays whatever was written at run time; only the generator can be
        fixed, and only for the next record."""
        point = {"convergence": [{"n": 100, "sigma": 0.008, "mean": 1.2},
                                 {"n": 300, "sigma": 0.0081, "mean": 1.2}]}
        local = R.convergence_check(point, None)[0]["detail"]
        batch = R.convergence_check(point, self.BATCH)[0]["detail"]
        self.assertIn("same seed stream, the 300-sample run's first 100 draws are "
                      "identical to a standalone 100-sample run", local)
        self.assertNotIn("identical to a standalone", batch)
        self.assertIn("ordered by sample_index", batch)
        # everything outside the mechanism clause is untouched
        self.assertIn("relative change", batch)
        self.assertIn("Full checkpoint series: N=100", batch)

    # Committed records are read-only fixtures: append-only evidence, never rewritten.
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
        self.assertIn("`monte_carlo.sample_index` fixes the draw order", md)

    def test_a_local_record_still_renders_the_setseed_wording(self):
        md = R.render_record(self._record(None))
        self.assertIn(
            f"Reproducible: `setseed {R.SEED_A}` (second-seed point uses {R.SEED_B}). "
            f"N matches", md)
        self.assertIn(f"`setseed {R.SEED_B}`", md)
        self.assertIn("ngspice draws sequentially per `setseed`", md)


class CommittedRecordsAreNotRewritten(_UntrimmedBench, mc_batch_shared.CommittedRecordsShared,
                                      unittest.TestCase):
    BENCH_DIR = BENCH_DIR


if __name__ == "__main__":
    unittest.main()
