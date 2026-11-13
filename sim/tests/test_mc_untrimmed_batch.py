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
from unittest import mock

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

    def test_max_concurrent_jobs_is_off_by_default_and_passed_through(self):
        for g in self.groups:
            self.assertNotIn("max_concurrent_jobs", g.request["batch"])
        args = SimpleNamespace(**vars(ARGS), batch_max_concurrent_jobs=20)
        with tempfile.TemporaryDirectory() as tmp:
            groups = R.build_batch_groups(PIN, BODY, self.points, SPICEINIT, Path(tmp), args)
            for g in groups:
                self.assertEqual(g.request["batch"]["max_concurrent_jobs"], 20)
                self.assertEqual(json.loads(g.request_path.read_text()), g.request)

    def test_resume_is_off_by_default_and_reaches_the_klt_command_line(self):
        self.assertFalse(any(g.resume for g in self.groups))
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
        # `shard_loss`/`samples_from_report` moved into batch_sim (issue #514)
        # so both MC runners read a klt report through one implementation.
        self.assertFalse(hasattr(R, "shard_loss"))
        self.assertFalse(hasattr(R, "samples_from_report"))
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

    def test_sharding_is_sized_by_sample_count(self):
        self.assertEqual(self.groups[0].request["remote"]["hosts"], 300)


def _shard_ids(point, shards):
    return [f"job-{point.corner_id}-s{i}" for i in range(shards)]


def _report(point, n=None, lib_sha="abc", drop=(), shuffle=False, shards=0):
    """A stubbed klt report: one `corners[]` entry per Monte Carlo draw.

    `shards=N` is the shape klt returns for a *sharded* request (issue #523):
    `environment.remote` carries a `fleet` list and no top-level `job_id`."""
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
    remote = ({"fleet": [{"job_id": j} for j in _shard_ids(point, shards)]} if shards
              else {"job_id": f"job-{point.corner_id}"})
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

    def test_sharded_request_records_every_fleet_job_id(self):
        _, execution = self._run(lambda p: _report(p, lib_sha=self.sha, shards=3))
        for job, point in zip(execution["jobs"], self.points):
            with self.subTest(point=point.corner_id):
                self.assertIsNone(job["job_id"])
                self.assertEqual(job["job_ids"], _shard_ids(point, 3))

    def test_samples_sidecar_carries_the_shard_ids(self):
        self._run(lambda p: _report(p, lib_sha=self.sha, shards=3))
        point = self.points[0]
        written = json.loads(R.samples_path(self.corners_dir, point.corner_id).read_text())
        self.assertIsNone(written["job_id"])
        self.assertEqual(written["job_ids"], _shard_ids(point, 3))

    def test_samples_sidecar_is_unchanged_for_an_unsharded_request(self):
        self._run(lambda p: _report(p, lib_sha=self.sha))
        point = self.points[0]
        written = json.loads(R.samples_path(self.corners_dir, point.corner_id).read_text())
        self.assertEqual(written["job_id"], f"job-{point.corner_id}")
        self.assertEqual(written["job_ids"], [f"job-{point.corner_id}"])

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
                    R.seed_mechanism(execution),
                    f"`setseed {R.SEED_A}` (second-seed point uses {R.SEED_B})")
                self.assertEqual(R.seed_label(execution, R.SEED_B), f"`setseed {R.SEED_B}`")
                self.assertEqual(R.seed_convention(execution), f"fixed setseed {R.SEED_A}")
                self.assertEqual(
                    R.convergence_sequence_note(execution),
                    "ngspice draws sequentially per `setseed`, so the first K samples of "
                    "the full run are identical to what a standalone K-sample run would "
                    "produce \u2014 this is a real convergence trend, not a re-simulation "
                    "at each row")

    def test_batch_seed_prose_never_says_setseed(self):
        for text in (R.seed_mechanism(self.BATCH), R.seed_label(self.BATCH, R.SEED_B),
                     R.seed_convention(self.BATCH), R.convergence_sequence_note(self.BATCH)):
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


class CommittedRecordsAreNotRewritten(unittest.TestCase):
    def test_rendering_a_committed_record_writes_nothing(self):
        before = {p: p.stat().st_mtime_ns for p in BENCH_DIR.glob("records/*")}
        for path in sorted(BENCH_DIR.glob("records/*.json")):
            r = json.loads(path.read_text())
            if "points" in r:
                R.render_record(r)
        self.assertEqual({p: p.stat().st_mtime_ns for p in BENCH_DIR.glob("records/*")}, before)


if __name__ == "__main__":
    unittest.main()
