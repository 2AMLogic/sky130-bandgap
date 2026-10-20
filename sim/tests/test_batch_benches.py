#!/usr/bin/env python3
"""Coverage for the pre-layout `corner-run.py` benches enabled for
`--backend batch` by issue #395 (line-regulation, output-voltage-tc, psrr-dc,
quiescent-current, startup-ramp, startup-time), on top of the adapter
`sim/bin/batch_sim.py` (issue #320).

The always-on tests build each bench's real requests from its committed
manifest and newest netlist snapshot (what `corner-run.py --backend batch
--dry-run` prints) and feed fake klt reports through `assemble()`. No xschem,
fleet, AWS credentials or PDK needed.

`KltVsLocal` runs one corner (tt / 27 degC / 3.3 V) of every enabled bench
through `klt sim --backend local` (the same deck generator and measurement
harvesting the fleet runs) and through the local runner's own deck, and
requires identical values. It skips itself without klt, ngspice and the
pinned PDK.
"""

from __future__ import annotations

import json
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
SPICEINIT = (SIM_DIR / "spiceinit").read_text()
LIB_SHA = "a" * 64

#: slug -> (analysis kind, whether the deck carries `meas` commands)
BENCHES = {
    "quiescent-current": ("op", False),
    "psrr-dc": ("ac", False),
    "line-regulation": ("dc", True),
    "output-voltage-tc": ("dc", True),
    "startup-ramp": ("tran", True),
    "startup-time": ("tran", True),
}


def snapshot_body(slug: str) -> list[str]:
    snap = sorted((SIM_DIR / slug / "netlist-snapshots").glob("*.spice"))[-1]
    return sim_common.load_base_body(snap, set())


def matrix(exp, subset=None):
    c = exp.raw["corners"]
    full = [
        cr.Corner(p, float(t), float(v))
        for p in c["process"]
        for t in c["temperature_c"]
        for v in c["supply_v"]
    ]
    return subset or full


def groups_for(slug, tmp, mtx=None, timeout=1800):
    exp = cr.load_experiment(SIM_DIR / slug)
    mtx = mtx or matrix(exp)
    return exp, mtx, batch_sim.build_groups(
        exp, PIN, mtx, snapshot_body(slug), SPICEINIT, tmp, timeout,
        capacity_wait_s=60, runner_version_check="enforce", poll_interval_s=30,
        allow_step_requests=True,
    )


def report_for(group, values, *, qualify=True):
    """A klt-shaped report: every group corner carries `values`, named the way
    klt names them for this request (`main.<name>` inside a single step)."""
    steps = bool(group.request.get("analysis_steps"))
    prefix = f"{batch_sim.STEP_NAME}." if steps and qualify else ""
    corners = [
        {
            "corner_id": f"{c.process}/x/{c.temp_c:g}C",
            "process": c.process,
            "temperature_c": c.temp_c,
            "status": "pass",
            "runtime_s": 5.0,
            "measurements": [
                {"name": prefix + n, "value": v, "status": "pass"} for n, v in values.items()
            ],
            "diagnostics": [],
            "artifacts": {},
        }
        for c in group.corners
    ]
    return {
        "status": "pass",
        "corner_count": len(corners),
        "corners": corners,
        "environment": {
            "engine": "ngspice", "engine_version": "46", "models_lib_sha256": LIB_SHA,
            "remote": {"job_id": f"job-{group.supply_v}", "instance_type": "c7i.4xlarge",
                       "elapsed_seconds": 30, "runner_compatibility": "match"},
        },
        "provenance": {"klt_version": "0.7.1", "pdk": None},
    }


class Requests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_enabled_set_is_exactly_what_ran_on_the_fleet(self):
        """Scalar-analysis benches were compared live on the fleet (issue #395);
        the step-form ones are held back until the runner's klt supports
        `analysis_steps`, and `corner-run.py` must refuse them with that reason."""
        self.assertLessEqual({"psrr-dc", "quiescent-current"}, batch_sim.BATCH_ENABLED_SLUGS)
        for slug, (_kind, has_meas) in BENCHES.items():
            self.assertEqual(has_meas, slug in batch_sim.STEP_REQUEST_SLUGS, slug)
            self.assertEqual(has_meas, slug not in batch_sim.BATCH_ENABLED_SLUGS, slug)
            if has_meas:
                exp = cr.load_experiment(SIM_DIR / slug)
                with self.assertRaises(batch_sim.BatchError) as ctx:
                    batch_sim.build_groups(
                        exp, PIN, matrix(exp), snapshot_body(slug), SPICEINIT, self.tmp / slug, 60,
                        capacity_wait_s=0, runner_version_check="enforce", poll_interval_s=30)
                self.assertIn("batch_runner_feature_unsupported", str(ctx.exception))
        self.assertNotIn("error-amp-loop", batch_sim.BATCH_ENABLED_SLUGS)
        self.assertIn("error-amp-loop", batch_sim.BATCH_UNSUPPORTED_REASONS)

    def test_three_supply_jobs_cover_the_full_matrix_with_the_manifests_content(self):
        for slug, (kind, has_meas) in BENCHES.items():
            with self.subTest(slug):
                exp, mtx, groups = groups_for(slug, self.tmp / slug)
                self.assertEqual(len(mtx), 45)
                self.assertEqual([g.supply_v for g in groups], [2.97, 3.3, 3.63])
                self.assertEqual(sum(len(g.corners) for g in groups), 45)
                for g in groups:
                    req = g.request
                    self.assertEqual(req["backend"], "batch")
                    self.assertEqual(req["models"], {"pdk": PIN["variant"], "lib": PIN["ngspice_lib"]})
                    if has_meas:
                        self.assertNotIn("analysis", req)
                        (step,) = req["analysis_steps"]
                        self.assertEqual(step["analysis"]["kind"], kind)
                        sent = step["measurements"]
                    else:
                        self.assertNotIn("analysis_steps", req)
                        self.assertEqual(req["analysis"]["kind"], kind)
                        sent = req["measurements"]
                    by_name = {m["name"]: m for m in sent}
                    for m in exp.measurements:  # name, unit and limits are the manifest's
                        self.assertIn(m.name, by_name)
                        lim = by_name[m.name].get("limits", {})
                        self.assertEqual(lim.get("min"), m.min)
                        self.assertEqual(lim.get("max"), m.max)
                    self.assertIn(f".param vsup={g.supply_v}", g.netlist_path.read_text())

    def test_analysis_card_is_the_manifests_verbatim(self):
        for slug in BENCHES:
            with self.subTest(slug):
                exp, _m, (g, *_rest) = groups_for(slug, self.tmp / slug)
                head = exp.raw["deck"]["analyses"][0].split(" ", 1)
                req = g.request
                analysis = req["analysis_steps"][0]["analysis"] if "analysis_steps" in req else req["analysis"]
                self.assertEqual(analysis["kind"], head[0])
                self.assertEqual(analysis["args"], head[1] if len(head) > 1 else "")

    def test_meas_commands_become_limitless_spice_cards_of_the_same_analysis_type(self):
        for slug, (kind, has_meas) in BENCHES.items():
            if not has_meas:
                continue
            with self.subTest(slug):
                exp, _m, (g, *_rest) = groups_for(slug, self.tmp / slug)
                cmds = [a for a in exp.raw["deck"]["analyses"] if a.startswith("meas ")]
                cards = [m for m in g.request["analysis_steps"][0]["measurements"] if "spice" in m]
                self.assertEqual(len(cards), len(cmds))
                for cmd, card in zip(cmds, cards):
                    self.assertEqual(card["spice"], "." + cmd)
                    self.assertTrue(card["spice"].startswith(f".meas {kind} "))
                    self.assertNotIn("limits", card)
                    self.assertNotIn("expr", card)

    def test_let_chains_are_inlined_into_expressions(self):
        exp, _m, (g, *_rest) = groups_for("startup-time", self.tmp)
        sent = {m["name"]: m for m in g.request["analysis_steps"][0]["measurements"]}
        expr = sent["t_start_ms"]["expr"]
        self.assertNotRegex(expr, r"\btcand\b|\bup\b")
        self.assertIn("v(vref) gt 1.08", expr)
        exp, _m, (g, *_rest) = groups_for("output-voltage-tc", self.tmp / "tc")
        sent = {m["name"]: m for m in g.request["analysis_steps"][0]["measurements"]}
        self.assertIn("(165)", sent["tc_ppm"]["expr"])  # `let vspan = 165`
        self.assertIn("vref27", sent["tc_ppm"]["expr"])  # the meas result stays a name

    def test_options_params_and_spiceinit_reach_the_request(self):
        exp, _m, (g, *_rest) = groups_for("startup-ramp", self.tmp)
        text = g.netlist_path.read_text()
        self.assertIn(".param t_slow=1e-3", text)
        self.assertIn(".option wnflag=1", text)
        self.assertEqual(g.request["options"]["ngspice_init"], batch_sim.spiceinit_lines(SPICEINIT))

    def test_error_amp_loop_is_refused_with_its_reason(self):
        exp = cr.load_experiment(SIM_DIR / "error-amp-loop")
        with self.assertRaises(batch_sim.BatchError) as ctx:
            batch_sim.build_groups(
                exp, PIN, matrix(exp), [], SPICEINIT, self.tmp, 60,
                capacity_wait_s=0, runner_version_check="enforce", poll_interval_s=30)
        self.assertIn("keeps the local runner", str(ctx.exception))
        self.assertIn("analysis_steps", str(ctx.exception))

    def test_second_analysis_or_alter_is_refused_by_split_analyses(self):
        for entry in ("ac dec 10 1 1k", "alter @v1[acmag]=0"):
            with self.assertRaises(batch_sim.BatchError):
                batch_sim.split_analyses(["op", entry])

    def test_meas_name_that_clashes_with_a_manifest_measurement_is_refused(self):
        exp = cr.load_experiment(SIM_DIR / "line-regulation")
        exp.raw["deck"]["analyses"] = ["dc v1 2.97 3.63 0.022", "meas dc vref_nom FIND v(vref) AT=3.3"]
        with self.assertRaises(batch_sim.BatchError):
            batch_sim.build_groups(
                exp, PIN, matrix(exp), snapshot_body("line-regulation"), SPICEINIT, self.tmp, 60,
                capacity_wait_s=0, runner_version_check="enforce", poll_interval_s=30,
                allow_step_requests=True)

    def test_meas_parsing(self):
        analysis, lets, cards = batch_sim.split_analyses(
            ["tran 1u 2m 0 5u", "let a = 1", "meas tran x FIND v(o) AT=1m", "MEASURE tran y when v(o)=1 rise=1"])
        self.assertEqual(analysis, {"kind": "tran", "args": "1u 2m 0 5u"})
        self.assertEqual(lets, {"a": "1"})
        self.assertEqual(
            cards,
            [{"name": "x", "spice": ".meas tran x FIND v(o) AT=1m"},
             {"name": "y", "spice": ".meas tran y when v(o)=1 rise=1"}])


class Aggregation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def values(self, exp):
        """In-limit value for every manifest measurement, plus a deck `meas` result."""
        out = {}
        for m in exp.measurements:
            lo = m.min if m.min is not None else (m.max - 1 if m.max is not None else 0.0)
            hi = m.max if m.max is not None else lo + 1
            out[m.name] = (lo + hi) / 2
        return out

    def test_single_step_names_are_unqualified_and_hidden_meas_results_are_ignored(self):
        exp, mtx, groups = groups_for("line-regulation", self.tmp)
        vals = {**self.values(exp), "vrefnom": 1.2}  # `vrefnom` is the deck's meas card
        outcomes = []
        for g in groups:
            rep = report_for(g, vals)
            outcomes.append(batch_sim.GroupOutcome(g, "t0", "t1", 1.0, 0, rep, None, "", None))
        results, blockers, _extra = batch_sim.assemble(
            exp, mtx, outcomes, 1800, cr.evaluate_measurements, local_lib_sha256=LIB_SHA, pin=PIN)
        self.assertEqual(blockers, [])
        self.assertEqual(len(results), 45)
        self.assertTrue(all(r["pass"] for r in results))
        self.assertEqual(
            [c["name"] for c in results[0]["measurements"]], [m.name for m in exp.measurements])
        self.assertTrue(all(c["value"] is not None for c in results[0]["measurements"]))

    def test_unqualified_names_would_not_be_found_so_a_klt_naming_change_fails_loudly(self):
        exp, mtx, groups = groups_for("line-regulation", self.tmp)
        outcomes = [
            batch_sim.GroupOutcome(g, "t0", "t1", 1.0, 0, report_for(g, self.values(exp), qualify=False),
                                   None, "", None)
            for g in groups
        ]
        # names without the `main.` prefix are still accepted (plain_name is a no-op on them) ...
        results, blockers, _x = batch_sim.assemble(
            exp, mtx, outcomes, 1800, cr.evaluate_measurements, local_lib_sha256=LIB_SHA, pin=PIN)
        self.assertEqual(blockers, [])
        # ... but a missing measurement is a failing corner, never silently passing
        for g, o in zip(groups, outcomes):
            for kc in o.report["corners"]:
                kc["measurements"] = kc["measurements"][1:]
        results, _b, _x = batch_sim.assemble(
            exp, mtx, outcomes, 1800, cr.evaluate_measurements, local_lib_sha256=LIB_SHA, pin=PIN)
        self.assertFalse(any(r["pass"] for r in results))

    def test_scalar_analysis_names_are_untouched(self):
        exp, mtx, groups = groups_for("quiescent-current", self.tmp)
        outcomes = [
            batch_sim.GroupOutcome(g, "t0", "t1", 1.0, 0, report_for(g, self.values(exp)), None, "", None)
            for g in groups
        ]
        results, blockers, _x = batch_sim.assemble(
            exp, mtx, outcomes, 1800, cr.evaluate_measurements, local_lib_sha256=LIB_SHA, pin=PIN)
        self.assertEqual(blockers, [])
        self.assertTrue(all(r["pass"] for r in results))

    def test_plain_name_only_strips_inside_a_single_step_request(self):
        self.assertEqual(batch_sim.plain_name("main.x", {"analysis_steps": [{}]}), "x")
        self.assertEqual(batch_sim.plain_name("main.x", {"analysis": {}}), "main.x")
        self.assertEqual(batch_sim.plain_name("other.x", {"analysis_steps": [{}]}), "other.x")


class KltVsLocal(unittest.TestCase):
    """tt / 27 degC / 3.3 V of each enabled bench: `klt sim --backend local`
    (klt's own deck writer and harvesting, as on the fleet) against the local
    runner's deck, on the bench's committed netlist snapshot."""

    @classmethod
    def setUpClass(cls):
        if not (shutil.which("klt") and shutil.which("ngspice")):
            raise unittest.SkipTest("klt and ngspice are required")
        try:
            cls.pdk = cr.resolve_pdk(PIN)
        except Exception as exc:  # no pinned PDK on this machine
            raise unittest.SkipTest(f"pinned PDK unavailable: {exc}")

    def test_values_are_identical(self):
        corner = cr.Corner("tt", 27.0, 3.3)
        for slug in BENCHES:
            with self.subTest(slug):
                tmp = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, tmp, True)
                exp = cr.load_experiment(SIM_DIR / slug)
                body = snapshot_body(slug)
                (g,) = batch_sim.build_groups(
                    exp, PIN, [corner], body, SPICEINIT, tmp / "b", 3000,
                    capacity_wait_s=0, runner_version_check="enforce", poll_interval_s=30,
                    allow_step_requests=True)
                req = json.loads(g.request_path.read_text())
                req.update(backend="local")
                req["models"]["pdk_root"] = str(self.pdk.root)  # pin the root: ~/.volare may also exist
                for key in ("batch", "remote"):
                    req.pop(key, None)
                g.request_path.write_text(json.dumps(req))
                proc = subprocess.run(
                    ["klt", "sim", str(g.request_path), "--backend", "local", "--format", "json",
                     "-o", str(tmp / "o")],
                    capture_output=True, text=True, cwd=tmp)
                self.assertIn(proc.returncode, batch_sim.REPORT_EXIT_CODES, proc.stderr[-500:])
                (kc,) = json.loads(proc.stdout)["corners"]
                klt_vals = {
                    batch_sim.plain_name(m["name"], req): m["value"]
                    for m in kc["measurements"] if m.get("value") is not None
                }
                run = tmp / "local"
                run.mkdir()
                shutil.copy(SIM_DIR / "spiceinit", run / ".spiceinit")
                (run / "d.spice").write_text(cr.build_deck(exp, self.pdk, corner, body))
                out = subprocess.run(["ngspice", "-b", "d.spice"], capture_output=True, text=True, cwd=run)
                local_vals = cr.parse_measurements(out.stdout + "\n" + out.stderr)
                self.assertEqual(set(local_vals), {m.name for m in exp.measurements}, slug)
                for name, value in local_vals.items():
                    self.assertEqual(klt_vals.get(name), value, f"{slug}.{name}")


if __name__ == "__main__":
    unittest.main()
