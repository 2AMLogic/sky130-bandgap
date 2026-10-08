#!/usr/bin/env python3
"""Coverage for `sim/trim-lsb-chained/run_trim_lsb_chained.py` (issue #327).

No fleet, ngspice or PDK needed: schematic parameter extraction, request
coverage, core-body verification and the DR-002 grading logic are exercised
on synthetic fixtures.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

_spec = importlib.util.spec_from_file_location(
    "run_trim_lsb_chained", SIM_DIR / "trim-lsb-chained" / "run_trim_lsb_chained.py"
)
rt = importlib.util.module_from_spec(_spec)
sys.modules["run_trim_lsb_chained"] = rt
_spec.loader.exec_module(rt)

PIN = {"variant": "sky130A", "ngspice_lib": "sky130.lib.spice"}


def synthetic(lsb_mv=2.4, mutate=None, drop=()):
    """results dict for every (config, proc, supply, code); linear VREF in code."""
    res = {}
    for cfg, codes in (("chained", rt.CHAINED_CODES), ("lumped", rt.LUMPED_CODES)):
        for p in rt.PROCESSES:
            for v in rt.SUPPLIES:
                for c in codes:
                    v27 = 1.2 + c * lsb_mv / 1000
                    res[(cfg, p, v, c)] = {"vref_27": v27, "vref_min": v27 - 0.01, "vref_max": v27 + 0.01, "tc_ppm": 50.0}
    if mutate:
        mutate(res)
    for k in drop:
        res.pop(k)
    return res


def by_name(checks):
    return {c["name"]: c for c in checks}


class SizingTests(unittest.TestCase):
    def test_default_sizing_is_current_schematic(self) -> None:
        s = rt.read_design_sizing()
        self.assertEqual(s["n_r1"], 7)
        self.assertEqual(s["n_r2"], 51)
        self.assertEqual(s["r_lseg_trim"], 0.5)
        self.assertEqual(s["n_r2_fine"], 20)

    def test_missing_param_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.sch"
            p.write_text(".param n_r1=7\n.param r_w=1\n")
            with self.assertRaises(rt.cr.HarnessError):
                rt.read_design_sizing(p)

    def test_unparseable_value_is_an_error_not_a_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.sch"
            text = Path(rt.DESIGN_SCH).read_text().replace(".param n_r2=51", ".param n_r2=abc")
            p.write_text(text)
            with self.assertRaises(rt.cr.HarnessError):
                rt.read_design_sizing(p)


class RequestCoverageTests(unittest.TestCase):
    def test_every_supply_and_code_requested_with_all_processes(self) -> None:
        jobs = rt.build_jobs()
        chained = {(j.supply_v, j.code) for j in jobs if j.config == "chained"}
        self.assertEqual(chained, {(v, c) for v in (2.97, 3.30, 3.63) for c in range(0, -17, -1)})
        self.assertEqual(len(jobs), 3 * 17 + 3 * 3)
        req = rt.build_request(jobs[0], PIN, 100)
        self.assertEqual(req["backend"], "batch")
        self.assertEqual(req["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(req["analysis"]["args"], "temp -40 125 11")


class CoreBodyTests(unittest.TestCase):
    BODY = [
        ".subckt bandgap_core VOUT GDRV VDD VSS",
        *(f"{n} a b c d sky130" for n in rt.expected_netlist_devices()["bandgap_core"]),
        "XR1_HD a b c sky130", ".ends",
        ".subckt error_amp A B C D E F",
        *(f"{n} a b c d sky130" for n in rt.expected_netlist_devices()["error_amp"]),
        ".ends",
    ]

    def test_matching_body_verifies(self) -> None:
        out = rt.verify_core_body(self.BODY)
        self.assertIn("XAMP", out["bandgap_core"])
        self.assertIn("XMCC", out["error_amp"])

    def test_missing_device_is_rejected(self) -> None:
        body = [l for l in self.BODY if not l.startswith("XMPAMP")]
        with self.assertRaises(rt.cr.HarnessError):
            rt.verify_core_body(body)

    def test_extra_device_is_rejected(self) -> None:
        body = self.BODY[:1] + ["XSTRAY a b c d sky130"] + self.BODY[1:]
        with self.assertRaises(rt.cr.HarnessError):
            rt.verify_core_body(body)


class GradingTests(unittest.TestCase):
    def test_clean_run_passes(self) -> None:
        checks = rt.evaluate(synthetic())
        self.assertTrue(all(c["pass"] for c in checks), [c for c in checks if not c["pass"]][:2])

    def test_nonmonotonic_intermediate_code_fails(self) -> None:
        def bump(res):
            res[("chained", "tt", 3.30, -7)]["vref_27"] += 0.01  # endpoints untouched
        c = by_name(rt.evaluate(synthetic(mutate=bump)))
        self.assertFalse(c["monotonic[chained_tt_3.30v]"]["pass"])
        self.assertTrue(c["monotonic[chained_ss_3.30v]"]["pass"])
        self.assertTrue(c["lsb_comfortable[chained_tt_3.30v]"]["pass"])  # endpoint LSB unchanged

    def test_oversized_lsb_fails_endpoint_average(self) -> None:
        c = by_name(rt.evaluate(synthetic(lsb_mv=3.2)))
        self.assertFalse(c["lsb_comfortable[chained_tt_3.30v]"]["pass"])
        self.assertIn("3.2000 mV/code", c["lsb_comfortable[chained_tt_3.30v]"]["detail"])

    def test_insufficient_span_fails(self) -> None:
        c = by_name(rt.evaluate(synthetic(lsb_mv=1.0)))  # 16 mV span: < 22.04*1.5 and < 15.62*1.5
        self.assertFalse(c["range_covers_mc_spread[chained_tt_3.30v]"]["pass"])
        self.assertFalse(c["range_covers_current_mc_spread[chained_tt_3.30v]"]["pass"])

    def test_missing_point_is_reported_not_skipped(self) -> None:
        key = ("chained", "ff", 2.97, -5)
        res = synthetic(drop=[key])
        c = by_name(rt.evaluate(res, {key: "error: nonconvergent"}))
        for n in ("monotonic", "lsb_comfortable", "collapse_free"):
            self.assertFalse(c[f"{n}[chained_ff_2.97v]"]["pass"])
        self.assertIn("nonconvergent", c["monotonic[chained_ff_2.97v]"]["detail"])
        self.assertTrue(c["monotonic[chained_tt_2.97v]"]["pass"])
        self.assertIsNone(rt.corner_summary(res, "chained", "ff", 2.97))

    def test_collapsed_point_fails(self) -> None:
        def collapse(res):
            res[("chained", "fs", 2.97, -3)]["vref_max"] = 2.85
        c = by_name(rt.evaluate(synthetic(mutate=collapse)))
        self.assertFalse(c["collapse_free[chained_fs_2.97v]"]["pass"])

    def test_missing_lumped_point_fails_crosscheck(self) -> None:
        c = by_name(rt.evaluate(synthetic(drop=[("lumped", "tt", 3.30, -8)])))
        self.assertFalse(c["lumped_crosscheck_complete"]["pass"])

    def test_record_renders_with_missing_points(self) -> None:
        key = ("chained", "ff", 2.97, -5)
        res = synthetic(drop=[key])
        checks = rt.evaluate(res, {key: "x"})
        text = rt.build_determination(res, checks, rt.read_design_sizing())
        self.assertIn("INCOMPLETE", text)

class Dr005QualificationTests(unittest.TestCase):
    """Issue #333: the literal DR-005 Trim row is graded apart from DR-002."""

    SOURCE = SIM_DIR / "trim-lsb-chained" / "records" / "20261008-163545-ffa415c.json"

    def test_engineering_pass_is_not_a_dr005_pass(self) -> None:
        res = synthetic(lsb_mv=2.4)  # 38.4 mV downward-only: DR-002 clean
        self.assertTrue(all(c["pass"] for c in rt.evaluate(res)))
        q = rt.qualify_dr005(res)
        r = q["requirements"]
        self.assertEqual(q["overall"], "FAIL")
        self.assertEqual(r["range_up"]["verdict"], "FAIL")
        self.assertEqual(r["range_up"]["worst_mv"], 0.0)
        self.assertEqual(r["range_down"]["verdict"], "FAIL")
        self.assertAlmostEqual(r["range_down"]["worst_mv"], 38.4, places=6)
        self.assertEqual(r["resolution"]["verdict"], "PASS")
        self.assertEqual(r["code_coverage"]["verdict"], "FAIL")
        self.assertEqual(r["code_coverage"]["worst_codes"], 17)
        self.assertAlmostEqual(r["code_coverage"]["worst_bits"], 4.087, places=3)

    def test_range_is_relative_to_1v20_not_measured_vref(self) -> None:
        # 3.75 mV/code over 16 codes = 60 mV down; up still 0
        q = rt.qualify_dr005(synthetic(lsb_mv=3.75))
        self.assertEqual(q["requirements"]["range_down"]["verdict"], "PASS")
        self.assertEqual(q["requirements"]["range_up"]["verdict"], "FAIL")
        self.assertAlmostEqual(q["requirements"]["range_down"]["worst_pct"], 5.0, places=6)

    def test_range_just_below_requirement_fails(self) -> None:
        q = rt.qualify_dr005(synthetic(lsb_mv=3.74))
        self.assertEqual(q["requirements"]["range_down"]["verdict"], "FAIL")

    def test_resolution_boundary(self) -> None:
        self.assertEqual(rt.qualify_dr005(synthetic(lsb_mv=3.0))["requirements"]["resolution"]["verdict"], "PASS")
        self.assertEqual(rt.qualify_dr005(synthetic(lsb_mv=3.001))["requirements"]["resolution"]["verdict"], "FAIL")
        self.assertEqual(rt.qualify_dr005(synthetic(lsb_mv=2.999))["requirements"]["resolution"]["verdict"], "PASS")

    def test_resolution_uses_worst_adjacent_step_not_average(self) -> None:
        def widen(res):
            res[("chained", "ss", 3.30, -4)]["vref_27"] -= 0.002  # one 4.4 mV step, average still 2.4+
        r = rt.qualify_dr005(synthetic(lsb_mv=2.4, mutate=widen))["requirements"]["resolution"]
        self.assertEqual(r["verdict"], "FAIL")

    def test_nonmonotonic_levels_reduce_effective_coverage(self) -> None:
        def flat(res):
            res[("chained", "tt", 3.30, -7)]["vref_27"] = res[("chained", "tt", 3.30, -6)]["vref_27"]
        c = rt.qualify_dr005(synthetic(mutate=flat))["corners"]["tt_3.30v"]
        self.assertLess(c["effective_codes"], 17)

    def test_enough_codes_pass_coverage(self) -> None:
        codes = tuple(range(0, -32, -1))
        res = {("chained", p, v, c): {"vref_27": 1.2 + c * 0.0025} for p in rt.PROCESSES for v in rt.SUPPLIES
               for c in codes}
        q = rt.qualify_dr005(res, codes=codes)
        self.assertEqual(q["requirements"]["code_coverage"]["verdict"], "PASS")  # exactly 32 = 5.0 bits
        res = {k: v for k, v in res.items() if k[3] != -31}
        codes31 = codes[:-1]
        q = rt.qualify_dr005(res, codes=codes31)
        self.assertEqual(q["requirements"]["code_coverage"]["verdict"], "FAIL")

    def test_missing_values_are_insufficient_not_pass(self) -> None:
        key = ("chained", "ff", 2.97, -5)
        res = synthetic(lsb_mv=3.0, drop=[key])  # 48 mV down: range fails regardless
        q = rt.qualify_dr005(res)
        self.assertEqual(q["n_incomplete_corners"], 1)
        self.assertFalse(q["corners"]["ff_2.97v"]["complete"])
        self.assertEqual(q["requirements"]["resolution"]["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(q["requirements"]["range_down"]["verdict"], "FAIL")  # fail dominates
        self.assertEqual(q["overall"], "FAIL")

    def test_none_value_counts_as_missing_and_all_missing_is_insufficient(self) -> None:
        res = synthetic()
        res[("chained", "tt", 3.30, 0)]["vref_27"] = None
        self.assertFalse(rt.qualify_dr005(res)["corners"]["tt_3.30v"]["complete"])
        q = rt.qualify_dr005({})
        for name in rt.DR005_REQUIREMENTS:
            self.assertEqual(q["requirements"][name]["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(q["overall"], "INSUFFICIENT_EVIDENCE")

    def test_committed_record_recomputes_to_documented_numbers(self) -> None:
        src = json.loads(self.SOURCE.read_text())
        q = rt.qualify_dr005(rt.parse_results_json(src["results"]))
        r = q["requirements"]
        self.assertEqual(q["overall"], "FAIL")
        self.assertEqual(q["n_incomplete_corners"], 0)
        self.assertAlmostEqual(r["range_down"]["worst_mv"], 38.46, places=2)
        self.assertEqual(r["range_up"]["worst_mv"], 0.0)
        self.assertEqual(r["resolution"]["verdict"], "PASS")
        self.assertLess(r["resolution"]["worst_pct"], 0.25)
        self.assertEqual(r["code_coverage"]["worst_codes"], 17)
        self.assertTrue(src["overall_pass"])  # DR-002 engineering verdict preserved

    def test_derived_record_mint_is_append_only_and_leaves_source_alone(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            # a copy of the committed source inside the repo tree is required by the repo-relative
            # provenance rule, so only exercise the refusal path on a tmp copy
            dst = Path(d) / self.SOURCE.name
            dst.write_bytes(self.SOURCE.read_bytes())
            dst.with_suffix(".md").write_bytes(self.SOURCE.with_suffix(".md").read_bytes())
            (Path(d) / f"{json.loads(dst.read_text())['record_id']}-{rt.DR005_RECORD_SUFFIX}.json").write_text("{}")
            with self.assertRaises(rt.cr.HarnessError):
                rt.mint_dr005_record(dst)

    def test_section_renders_verdicts_and_magnitude_only_note(self) -> None:
        text = "\n".join(rt.render_dr005_section(rt.qualify_dr005(synthetic())))
        self.assertIn("DR-005 verdict: FAIL", text)
        self.assertIn("NARROW OPERATOR QUESTION", text)
        self.assertIn("INSUFFICIENT", "\n".join(rt.render_dr005_section(rt.qualify_dr005({}))))


if __name__ == "__main__":
    unittest.main()
