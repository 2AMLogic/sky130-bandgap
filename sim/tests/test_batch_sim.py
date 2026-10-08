#!/usr/bin/env python3
"""Coverage for the Spot-batch execution boundary (`sim/bin/batch_sim.py`,
`corner-run.py --backend batch`, issue #320). No fleet, AWS credentials,
ngspice or PDK needed: `klt sim` is replaced by a fake runner that returns
klt-shaped reports.

Properties pinned (the issue's test plan):

  * ordered aggregation despite shuffled report order;
  * missing / duplicate / unexpected corners block an overall PASS;
  * a simulation error, an engine timeout, an interrupted job and a failed
    submission can never report PASS, and none of them runs a corner locally;
  * the scientific content of the request (251-point sweep, measurement
    expressions, limits, pinned model, PVT axes) is the manifest's, unchanged;
  * a remote model library that is not the pinned one blocks PASS.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import batch_sim  # noqa: E402
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
EXP_DIR = SIM_DIR / "startup-stability"
EXP = cr.load_experiment(EXP_DIR)
PIN = json.loads((SIM_DIR / "pdk.json").read_text())
LIB_SHA = "a" * 64
BODY = ["V1 VDDA 0 'vsup'", "VALPHA ALPHA 0 0"]


def full_matrix():
    c = EXP.raw["corners"]
    return [
        cr.Corner(p, float(t), float(v))
        for p in c["process"]
        for t in c["temperature_c"]
        for v in c["supply_v"]
    ]


def in_limits_values(index: int) -> dict[str, float]:
    """A value inside every limit, varying by corner so spread checks see
    corner sensitivity."""
    vals = {}
    for m in EXP.measurements:
        if m.min is not None and m.max is not None:
            v = (m.min + m.max) / 2
        elif m.min is not None:
            v = m.min * 10
        elif m.max is not None:
            v = m.max / 10
        else:
            v = 1.0
        vals[m.name] = v
    # tighten the ones whose sign conventions the generic rule above can miss
    vals["i_on_su"] = -1e-5
    vals["i_su_standing"] = 1e-7
    vals["vref_dut"] = 1.15 + 0.001 * (index % 30)
    vals["vgdrv_dut"] = 1.2 + 0.05 * (index % 30)
    return vals


def klt_corner(corner, index=0, *, status="pass", diags=None, values=None, runtime=100.0):
    vals = in_limits_values(index) if values is None else values
    return {
        "corner_id": f"{corner.process}/x/{corner.temp_c:g}C",
        "process": corner.process,
        "supply_v": {},
        "temperature_c": corner.temp_c,
        "status": status,
        "runtime_s": runtime,
        "measurements": [
            {"name": n, "value": v, "unit": "", "status": "pass", "margin": 0.0}
            for n, v in vals.items()
        ],
        "diagnostics": diags or [],
        "artifacts": {"log": None, "raw": None, "waveform": None, "deck": None},
        "monte_carlo": None,
    }


def make_report(group, *, lib_sha=LIB_SHA, mutate=None, job="klt-sim-test", elapsed=500):
    corners = [klt_corner(c, i) for i, c in enumerate(group.corners)]
    if mutate:
        corners = mutate(corners, group)
    return {
        "schema_version": 3,
        "status": "pass",
        "corner_count": len(group.corners),
        "corners": corners,
        "environment": {
            "engine": "ngspice",
            "engine_version": "46",
            "models_lib_sha256": lib_sha,
            "netlist_sha256": "b" * 64,
            "remote": {
                "provider": "aws-batch-fleet",
                "job_id": f"{job}-{group.supply_v:.2f}",
                "instance_type": "c7i.4xlarge",
                "ami_id": "ami-1",
                "lifecycle": "spot",
                "elapsed_seconds": elapsed,
                "runner_compatibility": "match",
            },
        },
        "provenance": {"klt_version": "0.6.0", "pdk": None},
    }


def fake_runner(*, mutate=None, lib_sha=LIB_SHA, fail_supply=None, reverse=False):
    def run(group):
        if fail_supply is not None and group.supply_v == fail_supply:
            return batch_sim.GroupOutcome(group, "t0", "t1", 1.0, 1, None, "klt sim exited 1: boom")
        rep = make_report(group, lib_sha=lib_sha, mutate=mutate)
        if reverse:
            rep["corners"].reverse()
        (group.dir / "klt-report.json").write_text(json.dumps(rep))
        return batch_sim.GroupOutcome(group, "t0", "t1", 900.0, 0, rep, None, "", group.dir / "klt-report.json")

    return run


class _Env:
    """Throwaway work tree + a real-manifest batch run through fakes."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup = None

    def execute(self, matrix=None, runner=None, timeout=3600):
        matrix = matrix or full_matrix()
        pdk = SimpleNamespace(lib_file=self.tmp / "sky130.lib.spice")
        pdk.lib_file.write_text("lib")
        sha = batch_sim.sha256_file(pdk.lib_file)
        runner = runner or fake_runner(lib_sha=sha)
        return batch_sim.execute(
            EXP, {**PIN}, pdk, matrix, BODY, (SIM_DIR / "spiceinit").read_text(),
            self.tmp / "work", self.tmp / "corners", self.tmp, timeout,
            cr.evaluate_measurements, {"xschem": "x", "platform": "p", "ngspice": "local"},
            runner=runner,
        ), sha


class RequestFidelity(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.groups = batch_sim.build_groups(
            EXP, PIN, full_matrix(), BODY, (SIM_DIR / "spiceinit").read_text(), self.tmp, 7200,
            capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
        )

    def test_three_supply_jobs_cover_the_full_45_corner_matrix_in_order(self):
        self.assertEqual([g.supply_v for g in self.groups], [2.97, 3.3, 3.63])
        self.assertEqual(sum(len(g.corners) for g in self.groups), 45)
        for g in self.groups:
            req = g.request
            self.assertEqual(req["corners"]["process"], EXP.raw["corners"]["process"])
            self.assertEqual(req["corners"]["temperature_c"], EXP.raw["corners"]["temperature_c"])
            self.assertNotIn("supply_v", req["corners"])  # vsup is a .param, pinned in the netlist
            self.assertIn(f".param vsup={g.supply_v}", g.netlist_path.read_text())

    def test_sweep_measurements_limits_and_model_pin_are_the_manifests(self):
        req = self.groups[0].request
        # the 251-point sweep is passed through verbatim, never shortened
        self.assertEqual(req["analysis"], {"kind": "dc", "args": "valpha 0 1 0.004"})
        self.assertEqual(req["backend"], "batch")
        self.assertEqual(req["engine"], "ngspice")
        self.assertEqual(req["models"], {"pdk": PIN["variant"], "lib": PIN["ngspice_lib"]})
        self.assertEqual([m["name"] for m in req["measurements"]], [m.name for m in EXP.measurements])
        for sent, m in zip(req["measurements"], EXP.measurements):
            self.assertEqual(sent.get("limits", {}).get("min"), m.min)
            self.assertEqual(sent.get("limits", {}).get("max"), m.max)
            # no intermediate vectors survive inlining
            for name in ("ifsu", "ifbare", "ssu", "sbare"):
                self.assertNotRegex(sent["expr"], rf"(?<![\w.]){name}(?![\w(])")
        self.assertTrue(req["options"]["keep_artifacts"])
        self.assertEqual(req["options"]["timeout_s"], 7200)
        init = req["options"]["ngspice_init"]
        self.assertIn("set ngbehavior=hsa", init)
        self.assertIn("option klu", init)
        self.assertTrue(all(";" not in line and not line.startswith("*") for line in init))

    def test_netlist_preamble_matches_the_local_decks_preamble(self):
        local = cr.build_deck(EXP, SimpleNamespace(lib_file=Path("/pdk/lib")), cr.Corner("tt", 27.0, 3.3), BODY)
        batch = self.groups[1].netlist_path.read_text()
        for line in local.splitlines():
            if line.startswith((".param", ".option")):
                self.assertIn(line, batch.splitlines())
        for line in BODY:
            self.assertIn(line, batch.splitlines())

    def test_inlined_expressions_compute_like_the_local_let_chain(self):
        ngspice = shutil.which("ngspice")
        if not ngspice:
            self.skipTest("ngspice not installed")
        analyses = EXP.raw["deck"]["analyses"]
        analysis, lets = batch_sim.split_analyses(analyses)
        # Stand-in circuit with the same probe sources and the same 251-point
        # sweep; only the circuit differs, the expressions are the manifest's.
        lines = [
            "inline-equivalence",
            "VALPHA c 0 0",
            "R1 c a 1k", "VPSW a 0 0",
            "R2 c b 2k", "VPSN b 0 0",
            "R3 c d 3k", "VPSU d 0 0",
            ".control", *analyses,
        ]
        probe_only = re.compile(r"^(?:[^v]|v(?!\())*$")  # no node voltages
        picked = [
            m for m in EXP.measurements
            if probe_only.match(m.expr) and not re.search(r"i\(v[12]\)", m.expr)
        ]
        self.assertGreaterEqual(len(picked), 8)  # every probe-current measurement, not a sample
        for m in picked:
            lines.append(f"let a_{m.name} = {m.expr}")
            lines.append(f"let b_{m.name} = {batch_sim.inline_lets(m.expr, lets)}")
            lines.append(f"print a_{m.name}")
            lines.append(f"print b_{m.name}")
        lines += ["quit", ".endc", ".end"]
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "d.spice").write_text("\n".join(lines))
        out = subprocess.run([ngspice, "-b", "d.spice"], cwd=tmp, capture_output=True, text=True).stdout
        self.assertIn("No. of Data Rows : 251", out)
        for m in picked:
            a = [ln for ln in out.splitlines() if ln.startswith(f"a_{m.name} =")]
            b = [ln for ln in out.splitlines() if ln.startswith(f"b_{m.name} =")]
            self.assertTrue(a and b, out[-800:])
            self.assertEqual(a[0].split("=")[1], b[0].split("=")[1], m.name)

    def test_klt_generated_deck_matches_the_local_deck(self):
        """Deck fidelity for one PVT corner: generate klt's own per-corner deck
        (its private `_write_corner_deck`, through the interpreter `klt` is
        installed in) and compare it with `corner-run.py::build_deck()`.
        Allowed differences: `.lib` quoting, `.temp` float formatting, the
        measurement `let`/`print` naming/inlining, and block order."""
        klt = shutil.which("klt")
        if not klt:
            self.skipTest("klt not installed")
        py = Path(klt).read_text(errors="replace").splitlines()[0].removeprefix("#!").strip()
        script = f"""
import json, sys
from pathlib import Path
from klayout_tools import sim
req = json.load(open({str(self.groups[0].request_path)!r}))
lib = '/PDK/' + req['models']['lib']
pt = sim.CornerPoint('ss', {{}}, -40.0)
sim._write_corner_deck(deck_path={str(self.tmp / 'klt.deck')!r}, netlist_path={str(self.groups[0].netlist_path)!r},
    models_lib=lib, point=pt, analysis=req['analysis'], measurements_spec=req['measurements'], raw_path=None)
"""
        proc = subprocess.run([py, "-c", script], capture_output=True, text=True)
        if proc.returncode != 0:
            self.skipTest(f"klt private deck writer unavailable: {proc.stderr[-200:]}")
        klt_deck = (self.tmp / "klt.deck").read_text().replace(
            f".include {self.groups[0].netlist_path}", self.groups[0].netlist_path.read_text()
        )
        corner = cr.Corner("ss", -40.0, 2.97)
        local = cr.build_deck(EXP, SimpleNamespace(lib_file=Path("/PDK/" + PIN["ngspice_lib"])), corner, BODY)
        self.assertEqual(
            [ln for ln in klt_deck.splitlines() if "valpha" in ln.lower() and ln.lower().startswith("dc")],
            [ln for ln in local.splitlines() if ln.lower().startswith("dc")],
        )

        def structural(text):
            out = set()
            for ln in text.splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("*") or ln.startswith(("let ", "print ", ".end", ".control")):
                    continue
                ln = ln.replace('"', "").replace(".temp -40.0", ".temp -40")
                out.add(ln)
            return out

        self.assertEqual(structural(local), structural(klt_deck))
        self.assertIn("save all", klt_deck)
        self.assertIn("save all", local)
        _, lets = batch_sim.split_analyses(EXP.raw["deck"]["analyses"])
        for m in EXP.measurements:
            self.assertIn(f"let {m.name} = {batch_sim.inline_lets(m.expr, lets)}", klt_deck.splitlines())
            self.assertIn(f"let meas_{m.name} = {m.expr}", local.splitlines())

    def test_not_enabled_for_other_experiments(self):
        other = SimpleNamespace(slug="line-regulation", raw={}, measurements=[])
        with self.assertRaises(batch_sim.BatchError):
            batch_sim.build_groups(other, PIN, full_matrix(), BODY, "", self.tmp / "o", 1,
                                   capacity_wait_s=0, runner_version_check="enforce", poll_interval_s=30)

    def test_non_cross_product_subset_is_refused_not_widened(self):
        m = [cr.Corner("tt", 27.0, 3.3), cr.Corner("ss", -40.0, 3.3), cr.Corner("tt", -40.0, 3.3)]
        with self.assertRaises(batch_sim.BatchError):
            batch_sim.build_groups(EXP, PIN, m, BODY, "", self.tmp / "s", 1,
                                   capacity_wait_s=0, runner_version_check="enforce", poll_interval_s=30)


class Aggregation(unittest.TestCase):
    def setUp(self):
        self.env = _Env()
        self.addCleanup(shutil.rmtree, self.env.tmp, True)

    def test_all_good_is_matrix_ordered_even_when_reports_are_shuffled(self):
        (self.env.tmp / "sky130.lib.spice").write_text("lib")
        (results, blockers, extra), sha = self.env.execute()
        self.assertEqual(blockers, [])
        self.assertEqual([r["corner_id"] for r in results], [c.id for c in full_matrix()])
        self.assertTrue(all(r["pass"] for r in results))
        # shuffled report order
        (results2, blockers2, _), _ = self.env.execute(runner=fake_runner(lib_sha=sha, reverse=True))
        self.assertEqual(blockers2, [])
        self.assertEqual([r["corner_id"] for r in results2], [c.id for c in full_matrix()])
        self.assertEqual(extra["execution"]["backend"], "batch")
        self.assertTrue(extra["execution"]["remote_pdk_matches_pin"])
        self.assertIsNone(extra["jobs"])

    def _run(self, mutate=None, **kw):
        (self.env.tmp / "sky130.lib.spice").write_text("lib")
        sha = batch_sim.sha256_file(self.env.tmp / "sky130.lib.spice")
        (res, blockers, extra), _ = self.env.execute(runner=fake_runner(mutate=mutate, lib_sha=kw.get("lib_sha", sha)))
        return res, blockers, extra

    def test_missing_corner_blocks_pass(self):
        res, blockers, _ = self._run(lambda cs, g: cs[:-1] if g.supply_v == 3.3 else cs)
        self.assertTrue(any("no result returned" in b for b in blockers))
        self.assertEqual(sum(1 for r in res if not r["pass"]), 1)

    def test_duplicate_corner_blocks_pass(self):
        res, blockers, _ = self._run(lambda cs, g: cs + [copy.deepcopy(cs[0])] if g.supply_v == 2.97 else cs)
        self.assertTrue(any("duplicate" in b for b in blockers))
        self.assertTrue(any("corner_count" in b for b in blockers))
        self.assertFalse(res[0]["pass"])

    def test_unexpected_corner_blocks_pass(self):
        def add(cs, g):
            extra = copy.deepcopy(cs[0])
            extra["process"] = "zz"
            return cs + [extra]
        _, blockers, _ = self._run(add)
        self.assertTrue(any("unexpected corner" in b for b in blockers))

    def test_engine_timeout_is_a_timeout_not_a_plain_failure(self):
        def mut(cs, g):
            if g.supply_v == 3.63:
                cs[0] = klt_corner(g.corners[0], values={}, status="error", runtime=3600.0, diags=[
                    {"severity": "error", "code": "timeout", "message": "ngspice did not complete within 3600s, killed"}])
            return cs
        res, _, _ = self._run(mut)
        bad = [r for r in res if not r["pass"]]
        self.assertEqual(len(bad), 1)
        self.assertTrue(bad[0]["timed_out"])
        self.assertIn("TIMEOUT", bad[0]["batch"]["failure"])
        self.assertIsNone(bad[0]["ngspice_exit"])  # not exposed by klt: unknown, never 0

    def test_simulation_error_is_a_failure_not_a_timeout(self):
        def mut(cs, g):
            if g.supply_v == 2.97:
                cs[1] = klt_corner(g.corners[1], values={}, status="error", diags=[
                    {"severity": "error", "code": "nonconvergence", "message": "gmin stepping failed"}])
            return cs
        res, _, _ = self._run(mut)
        bad = [r for r in res if not r["pass"]]
        self.assertEqual(len(bad), 1)
        self.assertFalse(bad[0]["timed_out"])
        self.assertIn("nonconvergence", bad[0]["batch"]["failure"])

    def test_interrupted_or_unobserved_job_never_passes(self):
        def mut(cs, g):
            return [klt_corner(c, values={}, status="error", diags=[
                {"severity": "error", "code": "batch_poll_timeout", "message": "job still running"}])
                for c in g.corners]
        res, _, _ = self._run(mut)
        self.assertFalse(any(r["pass"] for r in res))
        self.assertIn("never observed", res[0]["batch"]["failure"])

    def test_out_of_limit_value_fails_through_the_shared_evaluator(self):
        def mut(cs, g):
            vals = in_limits_values(0)
            vals["ncross_su"] = 3.0  # the very failure this bench exists to catch
            if g.supply_v == 3.3:
                cs[0] = klt_corner(g.corners[0], values=vals)
            return cs
        res, _, _ = self._run(mut)
        bad = [r for r in res if not r["pass"]]
        self.assertEqual(len(bad), 1)
        self.assertEqual([c["name"] for c in bad[0]["measurements"] if not c["pass"]], ["ncross_su"])

    def test_remote_model_library_that_is_not_the_pin_blocks_pass(self):
        _, blockers, extra = self._run(lib_sha="c" * 64)
        self.assertTrue(any("model library sha256" in b for b in blockers))
        self.assertFalse(extra["execution"]["remote_pdk_matches_pin"])

    def test_runner_version_skew_blocks_pass(self):
        (self.env.tmp / "sky130.lib.spice").write_text("lib")
        base = fake_runner(lib_sha=batch_sim.sha256_file(self.env.tmp / "sky130.lib.spice"))

        def skewed(group):
            out = base(group)
            out.report["environment"]["remote"]["runner_compatibility"] = "mismatch"
            return out
        (_, blockers, _), _ = self.env.execute(runner=skewed)
        self.assertTrue(any("runner klt" in b for b in blockers))

    def test_timings_separate_queue_overhead_from_compute(self):
        res, _, extra = self._run()
        job = extra["execution"]["jobs"][0]
        self.assertEqual(job["job_elapsed_s"], 500)
        self.assertEqual(job["queue_provision_and_transfer_s"], 400.0)  # 900 wall - 500 job
        self.assertEqual(extra["execution"]["corner_runtime_sum_s"], 4500.0)  # 45 x 100 s compute
        self.assertEqual(res[0]["elapsed_s"], 100.0)

    def test_evidence_files_are_written(self):
        self._run()
        corners = self.env.tmp / "corners"
        self.assertTrue((corners / "tt_-40c_2.97v.log").is_file())
        for v in ("2.97", "3.30", "3.63"):
            for name in ("request.json", "netlist.cir", "klt-report.json"):
                self.assertTrue((corners / f"batch-v{v}" / name).is_file(), (v, name))


class NoSilentLocalFallback(unittest.TestCase):
    def setUp(self):
        self.env = _Env()
        self.addCleanup(shutil.rmtree, self.env.tmp, True)
        (self.env.tmp / "sky130.lib.spice").write_text("lib")

    def test_failed_submission_raises_and_runs_nothing_locally(self):
        local_calls = []
        orig = sim_common._invoke_ngspice
        sim_common._invoke_ngspice = lambda *a, **k: local_calls.append(a) or ("", "", 0, False)
        orig_run_corner = cr.run_corner
        cr.run_corner = lambda *a, **k: local_calls.append(a)
        self.addCleanup(setattr, sim_common, "_invoke_ngspice", orig)
        self.addCleanup(setattr, cr, "run_corner", orig_run_corner)
        sha = batch_sim.sha256_file(self.env.tmp / "sky130.lib.spice")
        with self.assertRaises(batch_sim.BatchError) as ctx:
            self.env.execute(runner=fake_runner(lib_sha=sha, fail_supply=3.3))
        self.assertIn("nothing was run locally", str(ctx.exception))
        self.assertIn("3.30 V", str(ctx.exception))
        self.assertEqual(local_calls, [])

    def test_unusable_klt_binary_is_an_error(self):
        group = SimpleNamespace(dir=self.env.tmp, request_path=self.env.tmp / "r.json", supply_v=3.3)
        out = batch_sim.run_klt(group, klt="/nonexistent/klt")
        self.assertIsNone(out.report)
        self.assertIn("could not launch klt", out.error)

    def test_klt_error_exit_has_no_report(self):
        fake = self.env.tmp / "klt"
        fake.write_text("#!/bin/sh\necho 'error: no capacity' >&2\nexit 1\n")
        fake.chmod(0o755)
        group = SimpleNamespace(dir=self.env.tmp, request_path=self.env.tmp / "r.json", supply_v=3.3)
        out = batch_sim.run_klt(group, klt=str(fake))
        self.assertIsNone(out.report)
        self.assertIn("no capacity", out.error)

    def test_klt_exit_4_with_report_is_collected(self):
        fake = self.env.tmp / "klt"
        fake.write_text("#!/bin/sh\necho '{\"corners\": [], \"status\": \"error\"}'\nexit 4\n")
        fake.chmod(0o755)
        group = SimpleNamespace(dir=self.env.tmp, request_path=self.env.tmp / "r.json", supply_v=3.3)
        out = batch_sim.run_klt(group, klt=str(fake))
        self.assertEqual(out.rc, 4)
        self.assertEqual(out.report["status"], "error")


class RecordIntegration(unittest.TestCase):
    """`run_matrix_and_write_record(execute_matrix=...)`: blockers force FAIL
    even when every corner passed, and the record carries the execution block."""

    def _run(self, blockers):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        matrix = full_matrix()[:3]

        def execute_matrix(m, corners_dir):
            results = [{
                "corner_id": c.id, "process": c.process, "temperature_c": c.temp_c,
                "supply_v": c.supply_v, "ngspice_exit": None, "timed_out": False,
                "killed_by_signal": None, "killed_by_signal_name": None, "elapsed_s": 1.0,
                "timeout_s": 1, "measurements": [], "pass": True, "log": "x",
                "batch": {"failure": None},
            } for c in m]
            return results, blockers, {"execution": {"backend": "batch"}, "jobs": None}

        fake_cr = SimpleNamespace(
            REPO_ROOT=tmp, spread_checks=lambda e, r: [], default_author=lambda: "t",
            tool_versions=lambda: {"ngspice": "n", "xschem": "x", "platform": "p", "python": "3"},
            render_record=lambda r: "# r\n",
            unique_in_order=lambda v: list(dict.fromkeys(v)),
        )
        exp_dir = tmp / "sim" / "d"
        return sim_common.run_matrix_and_write_record(
            fake_cr, exp=SimpleNamespace(raw={}), matrix=matrix, is_subset=True, subset_reason="t",
            pdk=SimpleNamespace(root=tmp, variant="sky130A", installed_commit="d", matches_pin=True,
                                lib_file=tmp / "l"),
            pin={"open_pdks_commit": "d"}, body=["*"], run_dir=tmp / "b",
            corners_dir=exp_dir / "corners" / "r", records_dir=exp_dir / "records",
            record_md=exp_dir / "records" / "r.md", record_json=exp_dir / "records" / "r.json",
            snapshot=exp_dir / "snaps" / "r.spice", record_id="r",
            git_info={"sha": "a", "branch": "b", "dirty": False}, now=datetime.now(timezone.utc),
            args=SimpleNamespace(timeout=1, author="", supersedes="", jobs=1),
            experiment_fields={"slug": "d", "title": "d", "claim": "c", "provenance": "s",
                               "provenance_source": "s", "statistical_convention": "N/A"},
            links={"testbench": "t", "manifest": "m"}, execute_matrix=execute_matrix,
        )

    def test_clean_batch_passes(self):
        record, overall = self._run([])
        self.assertTrue(overall)
        self.assertEqual(record["overall_blockers"], [])
        self.assertEqual(record["execution"]["backend"], "batch")
        self.assertIsNone(record["jobs"])

    def test_blocker_forces_fail_even_if_every_corner_passed(self):
        record, overall = self._run(["x: no result returned"])
        self.assertFalse(overall)
        self.assertFalse(record["overall_pass"])


if __name__ == "__main__":
    unittest.main()
