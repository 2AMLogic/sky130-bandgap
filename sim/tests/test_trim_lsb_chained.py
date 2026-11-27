#!/usr/bin/env python3
"""Coverage for `sim/trim-lsb-chained/run_trim_lsb_chained.py` (issue #327).

No fleet, ngspice or PDK needed: schematic parameter extraction, request
coverage, core-body verification and the DR-002 grading logic are exercised
on synthetic fixtures.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR.parent / "scripts" / "ci"))

from script_module import load_script_module  # noqa: E402

rt = load_script_module(
    SIM_DIR / "trim-lsb-chained" / "run_trim_lsb_chained.py", "run_trim_lsb_chained"
)

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


def reversed_response(base_v=1.18, lsb_mv=4.0):
    """Results dict whose negative codes push VREF up from a below-nominal code 0
    (issue #696 fixture: a reversed response to the certified downward codes)."""
    return {
        ("chained", p, v, c): {"vref_27": base_v - c * lsb_mv / 1000}
        for p in rt.PROCESSES
        for v in rt.SUPPLIES
        for c in rt.CHAINED_CODES
    }


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

    def test_request_is_built_by_the_shared_batch_builder(self) -> None:
        """The request document comes from `batch_sim.build_adhoc_group()`, not a
        private copy, so it carries `remote.hosts` and `options.ngspice_init` (#525)."""
        job = next(j for j in rt.build_jobs() if j.config == "lumped")
        body = [".save i(v1)", ".param n_r2_trim=0", "XTB vref vdd 0 tb_core"]
        with tempfile.TemporaryDirectory() as d:
            groups, by_dir = rt.write_groups([job], body, {}, 51, PIN, Path(d), 1800)
            self.assertEqual(len(groups), 1)
            g = groups[0]
            self.assertIs(by_dir[g.dir], job)
            self.assertEqual(json.loads(g.request_path.read_text()), g.request)
            self.assertIn(f".param vsup={job.supply_v}", g.netlist_path.read_text())
            self.assertIn(f".param n_r2_trim={job.code}", g.netlist_path.read_text())

        req = g.request
        self.assertEqual(req["backend"], "batch")
        self.assertEqual(req["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(req["corners"]["temperature_c"], [27])
        self.assertEqual(req["analysis"], {"kind": "dc", "args": "temp -40 125 11"})
        self.assertEqual([m["name"] for m in req["measurements"]], ["vref_27", "vref_min", "vref_max"])
        self.assertEqual(req["models"], {"pdk": "sky130A", "lib": "sky130.lib.spice"})
        # the two fields the hand-rolled request had drifted away from
        units = len(rt.PROCESSES)
        self.assertEqual(req["remote"]["hosts"], rt.batch_sim.shard_hosts(units, 1800))
        self.assertGreater(req["remote"]["hosts"], 1, "unsharded: the job bound would exceed the fleet ceiling")
        self.assertLessEqual(
            rt.batch_sim.job_bound_s(units, 1800, req["remote"]["hosts"]),
            rt.batch_sim.FLEET_JOB_CEILING_S,
        )
        expected_init = rt.batch_sim.spiceinit_lines((rt.SIM_DIR / "spiceinit").read_text())
        self.assertTrue(expected_init)
        self.assertEqual(req["options"]["ngspice_init"], expected_init)
        self.assertEqual(req["options"]["timeout_s"], 1800)
        self.assertTrue(req["options"]["keep_artifacts"])

        self.assertEqual(req["batch"], {"poll_interval_s": rt.BATCH_POLL_INTERVAL_S,
                                        "capacity_wait_s": rt.BATCH_CAPACITY_WAIT_S,
                                        "runner_version_check": rt.BATCH_RUNNER_VERSION_CHECK})

    def test_private_request_builder_is_gone(self) -> None:
        self.assertFalse(hasattr(rt, "build_request"),
                         "run_trim_lsb_chained should not re-implement batch_sim.build_request")


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


class FailingCheckDetailTests(unittest.TestCase):
    """A failing check's `detail` may not assert the passing condition
    (issue #694): `collapse_free[*]`/`monotonic[*]` details must state what
    the measurements actually show, not what a passing run would show."""

    def test_collapsed_detail_names_the_out_of_band_codes(self) -> None:
        def collapse(res):
            res[("chained", "fs", 2.97, -3)]["vref_max"] = 2.85
            res[("chained", "fs", 2.97, -4)]["vref_max"] = 0.95
        c = by_name(rt.evaluate(synthetic(mutate=collapse)))["collapse_free[chained_fs_2.97v]"]
        self.assertFalse(c["pass"])
        self.assertIn("code -3", c["detail"])
        self.assertIn("2.850000 V", c["detail"])
        self.assertIn("code -4", c["detail"])
        self.assertIn("left the operating branch", c["detail"])
        self.assertNotIn("stay on the operating branch", c["detail"])

    def test_passing_collapse_detail_keeps_the_pass_wording(self) -> None:
        c = by_name(rt.evaluate(synthetic()))["collapse_free[chained_tt_3.30v]"]
        self.assertTrue(c["pass"])
        self.assertIn("stay on the operating branch", c["detail"])
        self.assertNotIn("left the operating branch", c["detail"])

    def test_nonmonotonic_detail_names_the_offending_transition(self) -> None:
        def bump(res):
            res[("chained", "tt", 3.30, -7)]["vref_27"] += 0.01  # one negative step
        c = by_name(rt.evaluate(synthetic(mutate=bump)))["monotonic[chained_tt_3.30v]"]
        self.assertFalse(c["pass"])
        self.assertIn("NOT strictly increasing", c["detail"])
        self.assertIn("code -7 -> -6 (-7.6000 mV)", c["detail"])
        self.assertNotIn("strictly increasing from code -16 to 0 over all 17 codes", c["detail"])

    def test_passing_monotonic_detail_keeps_the_pass_wording(self) -> None:
        c = by_name(rt.evaluate(synthetic()))["monotonic[chained_tt_3.30v]"]
        self.assertTrue(c["pass"])
        self.assertIn("strictly increasing from code -16 to 0", c["detail"])
        self.assertNotIn("NOT strictly increasing", c["detail"])


class MagnitudeOnlyNoteTests(unittest.TestCase):
    """The 'magnitude only' note's evidence-impact clause follows this run's
    range verdicts (issue #694): it may not claim 'range FAILS under either
    reading' when `range_down` reaches 5 %, where the narrow operator
    question's answer does flip the range verdict."""

    def test_both_directions_fail_keeps_verdict_independent_wording(self) -> None:
        note = rt.qualify_dr005(synthetic())["magnitude_only"]  # down 3.2 %, up 0 mV
        self.assertIn("NARROW OPERATOR QUESTION", note)
        self.assertIn("does not depend on the answer", note)
        self.assertIn("about 3.2 % of 1.20 V", note)
        self.assertIn("range FAILS under either reading", note)

    def test_range_down_pass_makes_the_answer_decisive(self) -> None:
        note = rt.qualify_dr005(synthetic(lsb_mv=3.75))["magnitude_only"]  # down 5.0 %, up 0 mV
        self.assertIn("NARROW OPERATOR QUESTION", note)
        self.assertIn("DOES depend on the answer", note)
        self.assertIn("about 5.0 % of 1.20 V", note)
        self.assertIn("FAIL under the two-sided reading", note)
        self.assertIn("PASS under a one-sided one", note)
        self.assertNotIn("is itself below 5 %", note)
        self.assertNotIn("range FAILS under either reading", note)

    def test_no_evidence_is_insufficient_under_either_reading(self) -> None:
        note = rt.qualify_dr005({})["magnitude_only"]
        self.assertIn("NARROW OPERATOR QUESTION", note)
        self.assertIn("INSUFFICIENT_EVIDENCE under either reading", note)
        self.assertNotIn("is itself below 5 %", note)
        self.assertNotIn("DOES depend on the answer", note)


class MintDr005RecordTests(unittest.TestCase):
    """`mint_dr005_record`'s determination and supersession lines follow the
    source record and this qualification's own verdicts (issue #694)."""

    SOURCE = SIM_DIR / "trim-lsb-chained" / "records" / "20261008-163545-ffa415c.json"

    def mint_from(self, mutate=None, supersedes="") -> tuple[dict, str]:
        # mint computes repo-relative provenance, so the source copy must sit
        # inside the repo tree (records are still untouched: temp dir + cleanup)
        tmp = Path(tempfile.mkdtemp(dir=SIM_DIR.parent, prefix="trim-lsb-dr005-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        src = tmp / self.SOURCE.name
        data = json.loads(self.SOURCE.read_text())
        if mutate:
            mutate(data)
        src.write_text(json.dumps(data))
        src.with_suffix(".md").write_bytes(self.SOURCE.with_suffix(".md").read_bytes())
        out_md, out_json = rt.mint_dr005_record(src, "test author", supersedes)
        return json.loads(out_json.read_text()), out_md.read_text()

    def test_passing_source_determination_follows_the_verdicts(self) -> None:
        rec, md = self.mint_from()
        self.assertIn("DR-002 engineering PASS stands", rec["determination"])
        self.assertIn("range_up FAILS", rec["determination"])
        self.assertIn("code_coverage FAILS", rec["determination"])
        self.assertIn("Only resolution holds", rec["determination"])
        self.assertIn("## Determination", md)
        self.assertIn(rec["determination"], md)
        self.assertNotIn("The DR-002 engineering result is FAIL", md)

    def test_supersedes_is_stamped_and_rendered(self) -> None:
        rec, md = self.mint_from(supersedes="20261112-224417-24a14a1")
        self.assertEqual(rec["supersedes"], "20261112-224417-24a14a1")
        self.assertIn("- **Supersedes**: 20261112-224417-24a14a1", md)
        self.assertNotIn("first DR-005 qualification", md)

    def test_omitted_supersedes_leaves_the_qualification_predecessor_unspecified(self) -> None:
        rec, md = self.mint_from()
        self.assertIsNone(rec["supersedes"])
        self.assertIn("- **Supersedes**: (none specified)", md.splitlines())

    def test_partial_corner_leaves_one_sided_range_and_downward_requirement_unresolved(self) -> None:
        def partial_corner(data):
            src = synthetic_record(results=synthetic(lsb_mv=3.75, drop=[("chained", "tt", 3.3, -1)]))
            for key in ("results", "checks", "overall_pass"):
                data[key] = src[key]

        rec, md = self.mint_from(mutate=partial_corner)
        q = rec["dr005_qualification"]
        self.assertEqual(q["n_incomplete_corners"], 1)
        self.assertEqual(q["requirements"]["range_up"]["verdict"], "FAIL")
        self.assertEqual(q["requirements"]["range_down"]["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertIn("FAIL under the two-sided reading", q["magnitude_only"])
        self.assertIn("INSUFFICIENT_EVIDENCE under a one-sided one", q["magnitude_only"])
        self.assertIn("range_up FAILS", rec["determination"])
        self.assertIn("Insufficient evidence for range_down.", rec["determination"])
        self.assertNotIn("No literal requirement holds", rec["determination"])
        self.assertIn(q["magnitude_only"], md)
        self.assertIn(rec["determination"], md)

    def test_failing_source_determination_reads_as_failing(self) -> None:
        """The issue #694 reproduction: a DR-002-failing source record whose
        range_down reaches 5 % with an oversized step must not be narrated as
        an engineering PASS with range 'below 5 %'."""
        def mutate(data):
            data["overall_pass"] = False
            data["checks"][0]["pass"] = False
            data["results"]["chained|fs|2.97|-3"]["vref_max"] = 2.85
            for key, m in data["results"].items():
                cfg, proc, supply, code = key.split("|")
                if cfg == "chained":
                    m["vref_27"] = round(1.2 + int(code) * 0.00375, 9)
            data["results"]["chained|tt|3.3|-7"]["vref_27"] += 0.002  # one 5.75 mV step

        rec, md = self.mint_from(mutate=mutate)
        self.assertIn("The DR-002 engineering result is FAIL (1 of 76 checks failed", rec["determination"])
        self.assertIn("range_up FAILS", rec["determination"])
        self.assertIn("resolution FAILS", rec["determination"])
        self.assertNotIn("range_down FAILS", rec["determination"])
        self.assertNotIn("DR-002 engineering PASS stands", md)
        q = rec["dr005_qualification"]["requirements"]
        self.assertEqual(q["range_down"]["verdict"], "PASS")
        self.assertEqual(q["resolution"]["verdict"], "FAIL")
        self.assertEqual(rec["dr005_qualification"]["overall"], "FAIL")
        self.assertIn("DOES depend on the answer", rec["dr005_qualification"]["magnitude_only"])
        self.assertIn("about 5.0 % of 1.20 V", md)
        self.assertNotIn("is itself below 5 %", md)
        self.assertIn(rec["determination"], md)

    def test_main_forwards_supersedes(self) -> None:
        with mock.patch.object(rt, "mint_dr005_record",
                               return_value=(SIM_DIR / "a.md", SIM_DIR / "a.json")) as m:
            rc = rt.main(["--qualify-dr005", str(self.SOURCE),
                          "--supersedes", "20261112-224417-24a14a1"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with(self.SOURCE.resolve(), "",
                                  "20261112-224417-24a14a1")


def synthetic_record(**over) -> dict:
    """A minimal but renderable record dict for `render_record` (issue #694):
    checks/determination/DR-005 section are produced by the real functions."""
    res = over.pop("results", synthetic())
    checks = rt.evaluate(res)
    sizing = rt.read_design_sizing()
    r = {
        "record_id": "20261126-000000-test0000",
        "timestamp": "2026-11-26T00:00:00Z",
        "author": "test",
        "supersedes": None,
        "sizing": sizing,
        "pdk": {"variant": "sky130A", "installed_commit": "deadbeef", "matches_pin": True,
                "lib_file": "/nonexistent/sky130.lib.spice"},
        "tools": {"ngspice": "ngspice-46", "xschem": "XSCHEM V3.4.7", "platform": "linux"},
        "klt_version": "klt 0.9.2",
        "local_models_sha256": "x" * 64,
        "models_sha_match": True,
        "git": {"sha": "test0000", "branch": "feature/issue-694", "dirty": False},
        "execution": [{"request": "chained_v3.30_trim0", "job_id": "klt-sim-x", "instance_type": "m6i.4xlarge",
                       "lifecycle": "spot", "fleet_elapsed_s": 24, "wall_s": 80.0, "klt_status": "pass",
                       "engine_version": "46", "models_lib_sha256": "x" * 64}],
        "results": {f"{c}|{p}|{v}|{k}": m for (c, p, v, k), m in res.items()},
        "missing_points": {},
        "provenance": {"schematic_sha256": {"design/bandgap_core.sch": "a" * 64},
                       "netlist_body_sha256": "b" * 64},
        "checks": checks,
        "overall_pass": all(c["pass"] for c in checks),
        "determination": rt.build_determination(res, checks, sizing),
        "dr005_qualification": rt.qualify_dr005(res),
        "links": {"corners_dir": "sim/build/trim-lsb-chained/x/", "json": "sim/build/x.json",
                  "record": "sim/build/x.md", "snapshot": "sim/build/x.spice"},
    }
    r.update(over)
    return r


class RenderRecordSupersessionTests(unittest.TestCase):
    """`render_record` takes supersession from `r["supersedes"]` only (issue
    #694): the hardcoded first-refresh `Replaces the STALE`/`superseded (stale)
    record` lines are gone, so a record can no longer claim two different
    predecessors."""

    def test_supersedes_line_follows_the_record_field(self) -> None:
        md = rt.render_record(synthetic_record(supersedes="20261008-163545-ffa415c"))
        self.assertIn("- **Supersedes**: 20261008-163545-ffa415c", md)

    def test_omitted_supersedes_leaves_the_record_predecessor_unspecified(self) -> None:
        md = rt.render_record(synthetic_record())
        self.assertIn("- **Supersedes**: (none specified)", md.splitlines())

    def test_hardcoded_stale_record_lines_are_gone(self) -> None:
        for sup in (None, "20261008-163545-ffa415c"):
            md = rt.render_record(synthetic_record(supersedes=sup))
            self.assertNotIn("Replaces the STALE", md)
            self.assertNotIn("superseded (stale) record", md)
            self.assertNotIn("20260806-052035-dea0ca5", md)

    def test_results_parse_via_parse_results_json(self) -> None:
        key = ("chained", "ff", 2.97, -5)
        res = synthetic(drop=[key])
        md = rt.render_record(synthetic_record(results=res))
        self.assertIn("INCOMPLETE -- code(s) missing/nonconvergent", md)

class CrosscheckWorstDifferenceTests(unittest.TestCase):
    """Issue #703: the worst lumped-vs-chained line is a maximum over compared
    corners, never a synthetic zero when nothing was compared."""

    PREFIX = "Worst lumped-vs-chained VREF(27 C) difference at the sampled codes:"

    def line(self, res) -> str:
        md = rt.render_record(synthetic_record(results=res))
        return next(l for l in md.splitlines() if l.startswith(self.PREFIX))

    def test_equal_models_report_a_measured_zero(self) -> None:
        self.assertIn("0.0000 mV (15/15 corners compared)", self.line(synthetic()))

    def test_single_complete_corner_reports_its_difference_and_coverage(self) -> None:
        keep = ("tt", 3.30)
        drop = [("lumped", p, v, c) for p in rt.PROCESSES for v in rt.SUPPLIES
                for c in rt.LUMPED_CODES if (p, v) != keep]

        def bump(res):
            res[("lumped", "tt", 3.30, -8)]["vref_27"] += 0.005

        res = synthetic(mutate=bump, drop=drop)
        self.assertIn("5.0000 mV (1/15 corners compared)", self.line(res))

    def test_no_lumped_data_reports_no_numeric_difference(self) -> None:
        drop = [("lumped", p, v, c) for p in rt.PROCESSES for v in rt.SUPPLIES
                for c in rt.LUMPED_CODES]
        line = self.line(synthetic(drop=drop))
        self.assertIn("not available (0/15 corners could be compared)", line)
        self.assertNotIn("0.0000", line)
        self.assertNotRegex(line, r"\d mV")


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

    def test_reversed_response_direction_note_matches_range_rows(self) -> None:
        # issue #696: the Direction note states the available code signs; the measured
        # movement belongs to the range rows, so the note cannot contradict them
        q = rt.qualify_dr005(reversed_response())
        r = q["requirements"]
        self.assertAlmostEqual(r["range_up"]["worst_mv"], 64.0, places=6)
        self.assertAlmostEqual(r["range_up"]["worst_pct"], 64.0 / 12.0, places=6)
        self.assertEqual(r["range_up"]["verdict"], "PASS")
        self.assertEqual(q["direction"]["codes_up"], [0])
        self.assertEqual(q["direction"]["codes_down"], [16])
        note = q["direction"]["note"]
        self.assertIn("downward codes only", note)
        self.assertIn("no upward code exists", note)
        self.assertNotIn("0 mV", note)
        text = "\n".join(rt.render_dr005_section(q))
        self.assertIn(f"- **Direction**: {note}", text)
        self.assertIn("64.000 mV (5.333 %) | **PASS**", text)

    def test_reversed_response_per_corner_table_values(self) -> None:
        # issue #696's documented fixture numbers: at TT, 3.30 V the downward movement
        # from code 0 is 0 mV and the downward reach versus nominal is +20 mV
        q = rt.qualify_dr005(reversed_response())
        c = q["corners"]["tt_3.30v"]
        self.assertAlmostEqual(c["v_code0"], 1.18, places=9)
        self.assertAlmostEqual(c["up_mv"], 64.0, places=6)
        self.assertAlmostEqual(c["down_mv"], 0.0, places=6)
        self.assertAlmostEqual(c["reach_up_mv"], 44.0, places=6)
        self.assertAlmostEqual(c["reach_down_mv"], 20.0, places=6)
        text = "\n".join(rt.render_dr005_section(q))
        self.assertIn("| tt_3.30v | 64.000 | 0.000 | 0.000 | +44.000 / +20.000 |", text)

    def test_range_basis_wording_holds_for_code0_below_at_and_above_nominal(self) -> None:
        # issue #696: the Range basis bullet must not locate code 0 relative to nominal --
        # it names the origin (code 0), the percentage denominator (1.20 V) and the
        # absolute-reach reference (1.20 V) and stays true wherever code 0 actually sits
        bullets = set()
        for base_v in (1.18, 1.20, 1.22):  # below, at, above nominal
            text = "\n".join(rt.render_dr005_section(rt.qualify_dr005(reversed_response(base_v=base_v))))
            bullet = next(l for l in text.splitlines() if l.startswith("- **Range basis**"))
            bullets.add(bullet)
            self.assertIn("code-0 (untrimmed) point", bullet)
            self.assertIn("share of the specified 1.20 V", bullet)
            self.assertIn("Absolute reach versus 1.20 V", bullet)
            # no claim about where code 0 sits: it moves per corner and per fixture
            self.assertNotIn("code 0 sits", bullet)
            self.assertNotIn("smaller", bullet)
        self.assertEqual(len(bullets), 1)  # wording independent of code-0 position
        # ...and independent of corners disagreeing about where code 0 sits
        per_process = {"tt": 1.18, "ss": 1.20, "ff": 1.22, "sf": 1.19, "fs": 1.21}
        res = {("chained", p, v, c): {"vref_27": per_process[p] - 0.004 * c}
               for p in rt.PROCESSES for v in rt.SUPPLIES for c in rt.CHAINED_CODES}
        text = "\n".join(rt.render_dr005_section(rt.qualify_dr005(res)))
        bullet = next(l for l in text.splitlines() if l.startswith("- **Range basis**"))
        self.assertIn(bullet, bullets)


if __name__ == "__main__":
    unittest.main()
