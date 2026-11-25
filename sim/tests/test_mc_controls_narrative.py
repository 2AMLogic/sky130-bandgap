#!/usr/bin/env python3
"""Coverage for the shared Monte Carlo control/seed/convergence narrative (#691).

The three Monte Carlo mismatch runners (`pnp-mismatch`, `error-amp-offset-mc`,
and `monte-carlo-untrimmed`) and their shared `sim_common` helpers must derive
control, seed-stability, sibling-N comparability, and convergence prose from
each run's actual measurements and checks, so a failing or smoke-sized run
never writes a self-contradicting record.
"""

from __future__ import annotations

import copy
import inspect
import json
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR.parent / "scripts" / "ci"))

import batch_sim  # noqa: E402
import sim_common  # noqa: E402
from script_module import load_script_module  # noqa: E402

PNP = load_script_module(SIM_DIR / "pnp-mismatch" / "run_pnp_mismatch.py", "run_pnp_mismatch")
AMP = load_script_module(
    SIM_DIR / "error-amp-offset-mc" / "run_amp_offset_mc.py", "run_amp_offset_mc"
)
UNTRIMMED = load_script_module(
    SIM_DIR / "monte-carlo-untrimmed" / "run_mc_untrimmed.py", "run_mc_untrimmed"
)

PNP_PASS_RECORD = SIM_DIR / "pnp-mismatch" / "records" / "20260731-232801-ab27f82.json"
AMP_LOCAL_RECORD = SIM_DIR / "error-amp-offset-mc" / "records" / "20260803-084950-e599e30.json"
AMP_BATCH_RECORD = SIM_DIR / "error-amp-offset-mc" / "records" / "20261113-140022-64c42cad.json"
UNTRIMMED_PASS_RECORD = (
    SIM_DIR / "monte-carlo-untrimmed" / "records" / "20260817-121131-d7d85b6.json"
)
UNTRIMMED_DRIFT_FAIL_RECORD = (
    SIM_DIR / "monte-carlo-untrimmed" / "records" / "20261104-192509-4193f7c5.json"
)
UNTRIMMED_SINGLE_CONV_RECORD = (
    SIM_DIR / "monte-carlo-untrimmed" / "records" / "20261105-061037-ef9df345.json"
)

RUNNERS = (
    ("pnp-mismatch", PNP, PNP_PASS_RECORD),
    ("error-amp-offset-mc", AMP, AMP_LOCAL_RECORD),
    ("monte-carlo-untrimmed", UNTRIMMED, UNTRIMMED_PASS_RECORD),
)


def _load(path: Path) -> dict:
    return copy.deepcopy(json.loads(path.read_text()))


def _controls_section(md: str) -> str:
    marker = "## Controls"
    idx = md.index(marker)
    rest = md[idx + len(marker) :]
    nxt = rest.find("\n## ")
    return marker + (rest if nxt == -1 else rest[:nxt])


class SeedStabilityChecksTests(unittest.TestCase):
    """`sim_common.seed_stability_checks` must not claim an identical draw changed."""

    def test_differing_worst_sample_keeps_pass_detail(self):
        a = {"stats": {"vout": {"sigma": 0.008, "max_abs": 0.020, "max": 1.220}}}
        b = {"stats": {"vout": {"sigma": 0.0082, "max_abs": 0.022, "max": 1.222}}}
        default_checks = sim_common.seed_stability_checks(a, b, "vout", 101, 102, 0.25)
        self.assertTrue(default_checks[1]["pass"])
        self.assertEqual(default_checks[1]["name"], "seed_sample_differs[vout]")
        self.assertIn(
            "worst-sample magnitude differs between the two seeds "
            "(20.0000 mV vs 22.0000 mV), i.e. the draw really did change",
            default_checks[1]["detail"],
        )

    def test_equal_worst_sample_fails_without_claiming_draw_changed(self):
        pt = {"stats": {"vout": {"sigma": 0.008, "max_abs": 0.020, "max": 1.215}}}
        checks = sim_common.seed_stability_checks(
            pt,
            copy.deepcopy(pt),
            "vout",
            20260803,
            20260804,
            0.25,
            sample_field="max",
            sample_label="VOUT",
            sample_unit="V",
            sample_scale=1.0,
            sample_precision=6,
        )
        sample_check = checks[1]
        self.assertEqual(sample_check["name"], "seed_sample_differs[vout]")
        self.assertFalse(sample_check["pass"])
        self.assertIn("did not change", sample_check["detail"])
        self.assertIn("1.215000 V vs 1.215000 V", sample_check["detail"])
        self.assertNotIn("differs", sample_check["detail"])
        self.assertNotIn("the draw really did change", sample_check["detail"])


class SharedControlsDeduplicationTests(unittest.TestCase):
    """The `## Controls` heading and MC-off / second-seed bullets live in `sim_common`."""

    TRIPLICATED_PROSE = (
        "## Controls (the reason this record can be believed)",
        "- **MC-off control**",
        "- **Second-seed point**",
        "the individual samples change, σ does not",
    )

    def test_sim_common_exposes_render_mc_controls(self):
        self.assertTrue(callable(getattr(sim_common, "render_mc_controls", None)))

    def test_runners_delegate_controls_without_private_copies(self):
        for name, mod, _ in RUNNERS:
            with self.subTest(runner=name):
                src = inspect.getsource(mod.render_record)
                self.assertIn("render_mc_controls", src)
                for prose in self.TRIPLICATED_PROSE:
                    self.assertNotIn(prose, inspect.getsource(mod))


class ControlsAndComparabilityNarrativeTests(unittest.TestCase):
    """All three runners derive control and comparability prose from measurements/checks."""

    def test_passing_n300_records_render_passing_controls_and_comparability(self):
        for name, mod, path in RUNNERS:
            with self.subTest(runner=name):
                md = mod.render_record(_load(path))
                self.assertIn("\n## Controls\n", md)
                self.assertNotIn("the reason this record can be believed", md)
                controls = _controls_section(md)
                self.assertIn("- **MC-off control**", controls)
                self.assertIn("exactly zero", controls)
                self.assertIn("- **Second-seed point**", controls)
                self.assertIn("individual samples differ", controls)
                self.assertIn("stays within tolerance", controls)
                self.assertIn("N matches", md)

    def test_seed_wording_preserved_on_local_and_batch_amp_records(self):
        local_md = AMP.render_record(_load(AMP_LOCAL_RECORD))
        self.assertIn(f"`setseed {AMP.SEED_B}`", local_md)
        batch_md = AMP.render_record(_load(AMP_BATCH_RECORD))
        self.assertNotIn("setseed", batch_md)
        self.assertIn(batch_sim.seed_label({"backend": "batch"}, AMP.SEED_B), batch_md)

    def test_nonzero_mc_off_sigma_never_claims_exactly_zero(self):
        for name, mod, path in RUNNERS:
            with self.subTest(runner=name):
                r = _load(path)
                ctrl = next(p for p in r["points"] if p["role"] == "control")
                first_vec = next(iter(ctrl["stats"]))
                ctrl["stats"][first_vec]["sigma"] = 0.0042
                for c in ctrl["checks"]:
                    if c["name"] == f"sigma_zero[{first_vec}]":
                        c["pass"] = False
                        c["detail"] = "sigma = 0.0042 V with MC_MM_SWITCH=0 (must be exactly 0)"
                ctrl["pass"] = False
                r["overall_pass"] = False

                controls = _controls_section(mod.render_record(r))
                self.assertIn("0.0042", controls)
                self.assertIn("**FAIL**", controls)
                self.assertIn(f"`sigma_zero[{first_vec}]`", controls)
                self.assertNotIn("exactly zero", controls)
                self.assertNotIn("comes from the mismatch switch", controls)
                self.assertNotIn("is the mismatch switch", controls)

    def test_failing_seed_sigma_stable_never_claims_sigma_stable(self):
        for name, mod, path in RUNNERS:
            with self.subTest(runner=name):
                r = _load(path)
                target = next(
                    c for c in r["cross_point_checks"] if c["name"].startswith("seed_sigma_stable[")
                )
                target["pass"] = False
                r["overall_pass"] = False

                controls = _controls_section(mod.render_record(r))
                self.assertIn("**FAIL**", controls)
                self.assertIn(f"`{target['name']}`", controls)
                self.assertIn("drifted outside", controls)
                self.assertNotIn("σ does not", controls)
                self.assertNotIn("stays within tolerance", controls)

    def test_failing_seed_sample_differs_never_claims_samples_changed(self):
        for name, mod, path in RUNNERS:
            with self.subTest(runner=name):
                r = _load(path)
                target = next(
                    c
                    for c in r["cross_point_checks"]
                    if c["name"].startswith("seed_sample_differs[")
                )
                target["pass"] = False
                r["overall_pass"] = False

                controls = _controls_section(mod.render_record(r))
                self.assertIn("**FAIL**", controls)
                self.assertIn(f"`{target['name']}`", controls)
                self.assertIn("did not change", controls)
                self.assertNotIn("individual samples change", controls)
                self.assertNotIn("individual samples differ", controls)

    def test_both_seed_checks_failing_names_both_without_claiming_either_passed(self):
        for name, mod, path in RUNNERS:
            with self.subTest(runner=name):
                r = _load(path)
                sig_c = next(
                    c for c in r["cross_point_checks"] if c["name"].startswith("seed_sigma_stable[")
                )
                smp_c = next(
                    c
                    for c in r["cross_point_checks"]
                    if c["name"].startswith("seed_sample_differs[")
                )
                sig_c["pass"] = False
                smp_c["pass"] = False
                r["overall_pass"] = False

                controls = _controls_section(mod.render_record(r))
                self.assertIn(f"`{sig_c['name']}`", controls)
                self.assertIn(f"`{smp_c['name']}`", controls)
                self.assertNotIn("individual samples differ", controls)
                self.assertNotIn("stays within tolerance", controls)

    def test_missing_seed_checks_states_not_emitted(self):
        for name, mod, path in RUNNERS:
            with self.subTest(runner=name):
                r = _load(path)
                r["cross_point_checks"] = [
                    c
                    for c in r["cross_point_checks"]
                    if not c["name"].startswith(("seed_sigma_stable[", "seed_sample_differs["))
                ]
                controls = _controls_section(mod.render_record(r))
                self.assertIn("not emitted", controls)
                self.assertNotIn("stays within tolerance", controls)

    def test_sample_count_override_omits_sibling_comparability_claim(self):
        for name, mod, path in RUNNERS:
            with self.subTest(runner=name):
                r = _load(path)
                r["statistics"]["n_samples"] = 20
                md = mod.render_record(r)
                self.assertNotIn("N matches", md)
                self.assertNotIn("directly comparable", md)
                if name == "pnp-mismatch":
                    self.assertNotIn("**N and seed** match gf180-bandgap (N = 300", md)


class UntrimmedConvergenceNarrativeTests(unittest.TestCase):
    """`run_mc_untrimmed.render_record` derives convergence prose from checkpoints/tolerance."""

    def test_passing_n300_convergence_includes_sufficiency_and_sibling_note(self):
        md = UNTRIMMED.render_record(_load(UNTRIMMED_PASS_RECORD))
        self.assertIn(
            "N=300 (matching the two sibling MC experiments in this repo) is treated as sufficient",
            md,
        )

    def test_passing_n20_convergence_omits_sibling_parenthetical(self):
        r = _load(UNTRIMMED_PASS_RECORD)
        r["statistics"]["n_samples"] = 20
        md = UNTRIMMED.render_record(r)
        self.assertIn("N=20 is treated as sufficient", md)
        self.assertNotIn("matching the two sibling MC experiments", md)

    def test_committed_drift_failure_record_contradicts_neither_seed_nor_convergence_checks(self):
        md = UNTRIMMED.render_record(_load(UNTRIMMED_DRIFT_FAIL_RECORD))
        self.assertNotIn("setseed", md)
        self.assertNotIn("N matches", md)
        self.assertNotIn("matching the two sibling MC experiments", md)
        self.assertNotIn("is treated as sufficient", md)
        self.assertIn("not established as sufficient", md)
        self.assertIn("N=5 -> N=10: σ changed by 23.1%", md)
        controls = _controls_section(md)
        self.assertIn("`seed_sigma_stable[vout]`", controls)
        self.assertNotIn("σ does not", controls)
        self.assertNotIn("stays within tolerance", controls)

    def test_committed_single_checkpoint_record_never_compares_checkpoint_with_itself(self):
        md = UNTRIMMED.render_record(_load(UNTRIMMED_SINGLE_CONV_RECORD))
        self.assertNotIn("setseed", md)
        self.assertNotIn("N=5 -> N=5", md)
        self.assertNotIn("is treated as sufficient", md)
        self.assertNotIn("matching the two sibling MC experiments", md)
        self.assertIn("Fewer than two convergence checkpoints had converged draws", md)
        self.assertIn("`sample_count_sufficient` was not emitted", md)

    def test_zero_checkpoints_states_insufficient_checkpoints(self):
        r = _load(UNTRIMMED_SINGLE_CONV_RECORD)
        for p in r["points"]:
            if "convergence" in p:
                p["convergence"] = []
        md = UNTRIMMED.render_record(r)
        self.assertIn("Fewer than two convergence checkpoints had converged draws", md)
        self.assertNotIn("is treated as sufficient", md)


class EvaluateToRenderIntegrationTests(unittest.TestCase):
    """End-to-end `evaluate()` / `seed_stability()` / `convergence_check()` -> `render_record()`."""

    def test_evaluate_nonzero_control_spread_flows_into_failing_control_bullet(self):
        pnp_ctrl_pt = next(p for p in PNP.build_points(20) if p.role == "control")
        pnp_samples = [
            {v: 0.70 + (0.0042 if k % 2 else 0.0) for v in PNP.ALL_VECTORS}
            for k in range(pnp_ctrl_pt.samples)
        ]
        pnp_ctrl = PNP.evaluate(pnp_ctrl_pt, pnp_samples)
        self.assertFalse(pnp_ctrl["pass"])
        r_pnp = _load(PNP_PASS_RECORD)
        r_pnp["points"] = [pnp_ctrl if p["role"] == "control" else p for p in r_pnp["points"]]
        controls_pnp = _controls_section(PNP.render_record(r_pnp))
        self.assertIn("**FAIL**", controls_pnp)
        self.assertNotIn("exactly zero", controls_pnp)

        amp_ctrl_pt = next(p for p in AMP.build_points(20) if p.role == "control")
        amp_samples = [
            {
                "vos": 0.0 + (0.001 if k % 2 else 0.0),
                "vout": 1.20 + (0.0042 if k % 2 else 0.0),
                "dvbe8": 0.062,
                "veb8": 0.731,
                "dvbe1": 0.063,
                "rra": 109.03e3,
                "rrb": 14.027e3,
                "rratio": 7.5,
                "vgdrv": 2.0,
            }
            for k in range(amp_ctrl_pt.samples)
        ]
        amp_ctrl = AMP.evaluate(amp_ctrl_pt, amp_samples, [], 9.65)
        self.assertFalse(amp_ctrl["pass"])
        r_amp = _load(AMP_LOCAL_RECORD)
        r_amp["points"] = [amp_ctrl if p["role"] == "control" else p for p in r_amp["points"]]
        controls_amp = _controls_section(AMP.render_record(r_amp))
        self.assertIn("**FAIL**", controls_amp)
        self.assertIn("`sigma_zero[vos]`", controls_amp)
        self.assertIn("`sigma_zero[vout]`", controls_amp)
        self.assertNotIn("exactly zero", controls_amp)

        unt_ctrl_pt = next(p for p in UNTRIMMED.build_points(20) if p.role == "control")
        unt_samples = [
            {"vout": 1.20 + (0.0042 if k % 2 else 0.0), "vgdrv": 2.0}
            for k in range(unt_ctrl_pt.samples)
        ]
        unt_ctrl = UNTRIMMED.evaluate(unt_ctrl_pt, unt_samples, [])
        self.assertFalse(unt_ctrl["pass"])
        r_unt = _load(UNTRIMMED_PASS_RECORD)
        r_unt["points"] = [unt_ctrl if p["role"] == "control" else p for p in r_unt["points"]]
        controls_unt = _controls_section(UNTRIMMED.render_record(r_unt))
        self.assertIn("**FAIL**", controls_unt)
        self.assertIn("`sigma_zero[vout]`", controls_unt)
        self.assertNotIn("exactly zero", controls_unt)

    def test_seed_stability_equal_samples_flows_into_both_checks_and_controls(self):
        for name, mod, path in RUNNERS:
            with self.subTest(runner=name):
                r = _load(path)
                seed_b = next(p for p in r["points"] if p["role"] == "seed-check")
                seed_a_id = seed_b["corner_id"].removesuffix("_seed-b")
                seed_a = next(p for p in r["points"] if p["corner_id"] == seed_a_id)
                seed_b["stats"] = copy.deepcopy(seed_a["stats"])
                by_id = {seed_a_id: seed_a, seed_b["corner_id"]: seed_b}
                cross = mod.seed_stability(by_id)
                self.assertTrue(cross)
                sample_checks = [
                    c for c in cross if c["name"].startswith("seed_sample_differs[")
                ]
                self.assertTrue(all(not c["pass"] for c in sample_checks))
                for c in sample_checks:
                    self.assertIn("did not change", c["detail"])
                    self.assertNotIn("the draw really did change", c["detail"])
                r["cross_point_checks"] = cross
                md = mod.render_record(r)
                self.assertNotIn("the draw really did change", md)
                self.assertNotIn("individual samples differ", _controls_section(md))

    def test_untrimmed_evaluate_single_checkpoint_and_unconverged_series(self):
        all_27_pt = next(
            p
            for p in UNTRIMMED.build_points(20)
            if p.role == "mismatch" and p.config == "all" and p.temp_c == 27.0
        )
        # 7 converged samples -> only N=5 checkpoint reached (len(conv) == 1)
        samples_1 = [{"vout": 1.20 + 0.002 * (k % 2), "vgdrv": 2.0} for k in range(7)]
        eval_1 = UNTRIMMED.evaluate(all_27_pt, samples_1, [])
        self.assertEqual(len(eval_1["convergence"]), 1)
        self.assertEqual(UNTRIMMED.convergence_check(eval_1), [])
        r_1 = _load(UNTRIMMED_SINGLE_CONV_RECORD)
        r_1["points"] = [
            eval_1 if p["corner_id"] == all_27_pt.corner_id else p for p in r_1["points"]
        ]
        r_1["cross_point_checks"] = [
            c for c in r_1["cross_point_checks"] if c["name"] != "sample_count_sufficient"
        ]
        md_1 = UNTRIMMED.render_record(r_1)
        self.assertNotIn("N=5 -> N=5", md_1)
        self.assertNotIn("is treated as sufficient", md_1)

        # 10 converged samples with >20% jump between N=5 and N=10
        samples_jump = [
            {"vout": 1.20 + (0.001 if k < 5 else 0.020) * (1 if k % 2 else -1), "vgdrv": 2.0}
            for k in range(10)
        ]
        eval_jump = UNTRIMMED.evaluate(all_27_pt, samples_jump, [])
        conv_checks = UNTRIMMED.convergence_check(eval_jump)
        self.assertEqual(len(conv_checks), 1)
        self.assertFalse(conv_checks[0]["pass"])
        r_jump = _load(UNTRIMMED_DRIFT_FAIL_RECORD)
        r_jump["points"] = [
            eval_jump if p["corner_id"] == all_27_pt.corner_id else p
            for p in r_jump["points"]
        ]
        r_jump["cross_point_checks"] = [
            c for c in r_jump["cross_point_checks"] if c["name"] != "sample_count_sufficient"
        ] + conv_checks
        md_jump = UNTRIMMED.render_record(r_jump)
        self.assertNotIn("is treated as sufficient", md_jump)
        self.assertIn("not established as sufficient", md_jump)


if __name__ == "__main__":
    unittest.main()
