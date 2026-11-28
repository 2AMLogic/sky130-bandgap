#!/usr/bin/env python3
"""`render_record()` in `run_psrr_injector_candidates.py` states only what the
run supports (issue #709).

`parse_args()` and `verify()` accept any registered variant (`VARIANTS` +
`EXTRA_VARIANTS`), but the renderer used to assume the default four: it
dropped every `EXTRA_VARIANTS` entry from the tables (and crashed on an
`EXTRA_VARIANTS`-only run), and wrote "no device is resized", "they are
different corners" and "`v(NG)` collapsing to a few mV" whether or not the run
had measured any of that. These tests render records built from the bench's
committed measurements and pin the prose to the variants in `r["variants"]`
and the verdicts in `r["checks"]`.
"""

from __future__ import annotations

import copy
import inspect
import json
import re
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR.parent / "scripts" / "ci"))

from script_module import load_script_module  # noqa: E402

R = load_script_module(
    SIM_DIR / "psrr-injector-candidates" / "run_psrr_injector_candidates.py",
    "psrr_candidates_narrative",
)

#: A committed record with the default four variants x 45 corners, run on the batch fleet.
COMMITTED = SIM_DIR / "psrr-injector-candidates" / "records" / "20261113-052755-9402fb82.json"
#: An older committed record that ran without `ngclamp`, with its own checks.
THREE_VARIANT = SIM_DIR / "psrr-injector-candidates" / "records" / "20261002-200944-fe334b1.json"
DEFAULT = ("base", "ref3", "ngclamp", "ref3_ngclamp")
HOT = "ff_125c_3.63v"
COLD = "sf_-40c_3.63v"
#: A committed variant whose measurements stand in for one `COMMITTED` did not run.
DONOR = {"mpc2_vs": "base", "ng_mref0p5": "ngclamp", "ng_mref0p25": "ngclamp",
         "ng_mpnp16": "ngclamp"}
#: Lifting `ref3_ngclamp` here is what turns the committed record into an all-PASS one.
CEILING_FIX = {"sf_125c_3.30v": 67.0, "sf_125c_3.63v": 67.0}
SCREEN_CAVEAT = ("says nothing about startup margin", "DR-012",
                 "re-running `sim/startup-stability/` + `sim/startup-ramp/` for the regression")
FROZEN_PROSE = (
    "they are different corners",
    "collapsing to a few mV",
    "removes that floor",
    "which is the whole reason a stack-height-only fix is not enough",
    "shown[-1]",
)


def _committed(path: Path) -> tuple[dict, dict]:
    src = json.loads(path.read_text())
    results = {(p["variant"], p["corner_id"]): p for p in src.pop("points")}
    return src, results


def record(variants=DEFAULT, mutate=None) -> dict:
    """A renderable record for `variants`: the committed measurements (variants
    `COMMITTED` did not run copy their `DONOR`), with `checks` / `overall_pass`
    produced by the real `evaluate()`."""
    src, committed = _committed(COMMITTED)
    results = {}
    for name in variants:
        donor = name if name in src["variants"] else DONOR[name]
        for (v, cid), p in committed.items():
            if v == donor:
                q = copy.deepcopy(p)
                q["variant"] = name
                results[(name, cid)] = q
    if mutate is not None:
        mutate(results)
    points = R.matrix()
    r = {k: v for k, v in src.items() if k != "checks"}
    r["variants"] = list(variants)
    r["_results"] = results
    r["_points"] = points
    r["checks"] = R.evaluate(results, points, [R.VARIANTS_BY_NAME[n] for n in variants])
    r["overall_pass"] = all(c["pass"] for c in r["checks"])
    return r


def lift_candidate_to_the_ceiling(results):
    for cid, x in CEILING_FIX.items():
        results[("ref3_ngclamp", cid)]["measurements"]["psrr_band_min"] = x


def stick_ng(results, only=None):
    """`ref3_ngclamp`'s `v(NG)` no longer collapses (0.45 V > `NG_OFF_V`)."""
    for (v, cid), p in results.items():
        if v == "ref3_ngclamp" and (only is None or cid in only):
            p["measurements"]["v_ng"] = 0.45


def _section(md: str, heading: str) -> str:
    start = md.index(heading)
    rest = md[start + len(heading):]
    nxt = rest.find("\n## ")
    return heading + (rest if nxt == -1 else rest[:nxt])


def _footer(md: str) -> str:
    return md[md.index("**Overall:"):md.index("Written by")]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split(" | ")]


def _result_header(md: str) -> list[str]:
    line = next(ln for ln in md.splitlines() if ln.startswith("| corner | row 4a ceiling |"))
    return _cells(line)


def _table_rows(section: str) -> list[list[str]]:
    return [_cells(ln) for ln in section.splitlines() if ln.startswith("| `")]


class DefaultFourVariantRecordTests(unittest.TestCase):
    def test_passing_record_states_both_binding_corners_and_the_passing_ng_check(self):
        r = record(mutate=lift_candidate_to_the_ceiling)
        self.assertTrue(all(c["pass"] for c in r["checks"]), "fixture must be all-PASS")
        md = R.render_record(r)
        mech = _section(md, "## Mechanism")
        self.assertIn("## Mechanism -- the operating point at the two binding corners", mech)
        self.assertRegex(
            mech,
            rf"`{HOT}` \([\d.]+ dB\) is `base`'s binding corner and `{COLD}` "
            rf"\([\d.]+ dB\) is `ref3`'s binding corner -- different corners\.",
        )
        self.assertEqual([(row[0], row[1]) for row in _table_rows(mech)], [
            (f"`{HOT}`", f"`{v}`") for v in DEFAULT] + [
            (f"`{COLD}`", f"`{v}`") for v in DEFAULT])
        self.assertIn(
            f"`{R.NG_CHECK}`: PASS at 45/45 corners -- `v(NG)` in `ref3_ngclamp` is at or "
            f"below {R.NG_OFF_V:g} V, and below `ref3`'s, at every corner.",
            mech,
        )
        self.assertIn("**Overall: PASS**", _footer(md))
        self.assertIn(
            "A PASS here means one thing only: on this body, at every one of the 45 corners, "
            "the `ref3_ngclamp` candidate's DC-1 kHz PSRR clears DR-006's floor and sits "
            "within 2 dB of the bare core's own ceiling.",
            _footer(md),
        )
        for phrase in SCREEN_CAVEAT:
            self.assertIn(phrase, _footer(md))

    def test_committed_record_reports_its_own_two_failing_ceiling_checks(self):
        md = R.render_record(record())
        self.assertIn("**Overall: FAIL**", _footer(md))
        self.assertIn(f"`{R.NG_CHECK}`: PASS at 45/45 corners", _section(md, "## Mechanism"))
        self.assertIn("| `candidate_within_bare_core_ceiling[sf_125c_3.63v]` | **FAIL** |", md)

    def test_matching_worst_corners_are_not_called_different(self):
        def mutate(results):
            results[("ref3", HOT)]["measurements"]["psrr_band_min"] = 20.0
            stick_ng(results)

        r = record(mutate=mutate)
        self.assertFalse(r["overall_pass"])
        mech = _section(R.render_record(r), "## Mechanism")
        self.assertIn("## Mechanism -- the operating point at the binding corner", mech)
        self.assertNotIn("two binding corners", mech)
        self.assertRegex(
            mech,
            rf"`{HOT}` \([\d.]+ dB\) is `base`'s binding corner and `{HOT}` "
            rf"\([\d.]+ dB\) is `ref3`'s binding corner -- the same corner\.",
        )
        self.assertNotIn("different corners", mech)
        self.assertEqual(len(_table_rows(mech)), len(DEFAULT))

    def test_elevated_ng_is_a_reported_failure_not_a_claimed_collapse(self):
        r = record(mutate=stick_ng)
        mech = _section(R.render_record(r), "## Mechanism")
        self.assertIn("**Overall: FAIL**", _footer(R.render_record(r)))
        self.assertIn(f"`{R.NG_CHECK}`: FAIL at 45/45 corners (", mech)
        self.assertIn(" and 40 more) -- there `v(NG)` in `ref3_ngclamp` is not at or below "
                      "0.05 V and below `ref3`'s.", mech)
        self.assertNotIn("at every corner", mech)

    def test_ng_check_failures_name_the_failing_corners(self):
        r = record(mutate=lambda res: stick_ng(res, only={HOT}))
        failing = [c["name"] for c in r["checks"]
                   if c["name"].startswith(R.NG_CHECK) and not c["pass"]]
        self.assertEqual(failing, [f"{R.NG_CHECK}[{HOT}]"])
        self.assertIn(f"`{R.NG_CHECK}`: FAIL at 1/45 corners (`{HOT}`) -- there `v(NG)` in "
                      "`ref3_ngclamp` is not at or below 0.05 V and below `ref3`'s.",
                      _section(R.render_record(r), "## Mechanism"))

    def test_long_ng_failure_lists_are_capped(self):
        def mutate(results):
            stick_ng(results, only={cid for (_v, cid) in results if cid.endswith("_3.63v")})

        r = record(mutate=mutate)
        failing = [c["name"].split("[")[1][:-1] for c in r["checks"]
                   if c["name"].startswith(R.NG_CHECK) and not c["pass"]]
        self.assertEqual(len(failing), 15)
        mech = _section(R.render_record(r), "## Mechanism")
        self.assertIn(f"`{R.NG_CHECK}`: FAIL at 15/45 corners ("
                      + ", ".join(f"`{cid}`" for cid in failing[:4])
                      + f", `{failing[4]}` and 10 more) -- there `v(NG)` in", mech)
        listed = re.search(r"FAIL at 15/45 corners \((.*)\) -- there", mech).group(1)
        for cid in failing[5:]:
            self.assertNotIn(f"`{cid}`", listed)


class ExtraVariantRecordTests(unittest.TestCase):
    def test_every_variant_in_the_record_is_in_every_table(self):
        md = R.render_record(record(("base", "mpc2_vs")))
        cands = _section(md, "## Candidates")
        self.assertEqual([row[0] for row in _table_rows(cands)], ["`base`", "`mpc2_vs`"])
        self.assertIn("| `mpc2_vs` | `MPC2`'s gate moved", cands)
        self.assertIn("for each of the 2 variants -- 90 ngspice points", md)
        self.assertEqual(_result_header(md)[3:], ["`base`", "`mpc2_vs`"])
        self.assertEqual([row[0] for row in _table_rows(_section(md, "## Summary per candidate"))],
                         ["`base`", "`mpc2_vs`"])
        self.assertEqual([row[1] for row in _table_rows(_section(md, "## Mechanism"))],
                         ["`base`", "`mpc2_vs`"])

    def test_variant_order_follows_the_record(self):
        header = _result_header(R.render_record(record(("mpc2_vs", "base"))))
        self.assertEqual(header[3:], ["`mpc2_vs`", "`base`"])

    def test_run_without_ref3_attributes_no_binding_corner_to_it(self):
        for other in ("mpc2_vs", "ref3_ngclamp"):
            with self.subTest(other=other):
                mech = _section(R.render_record(record(("base", other))), "## Mechanism")
                self.assertRegex(mech, rf"`{HOT}` \([\d.]+ dB\) is `base`'s binding corner\.")
                self.assertNotIn("`ref3`'s", mech)
                self.assertNotIn("binding corner and", mech)
                self.assertIn(f"`{R.NG_CHECK}` was not evaluated -- it needs both `ref3` and "
                              "`ref3_ngclamp` in the run.", mech)

    def test_extra_variant_only_run_renders_its_own_binding_corner(self):
        md = R.render_record(record(("mpc2_vs",)))
        self.assertIn("for each of the 1 variants -- 45 ngspice points", md)
        mech = _section(md, "## Mechanism")
        self.assertIn("## Mechanism -- the operating point at the binding corner", mech)
        self.assertRegex(mech, rf"`{HOT}` \([\d.]+ dB\) is `mpc2_vs`'s binding corner\.")
        self.assertEqual([(row[0], row[1]) for row in _table_rows(mech)],
                         [(f"`{HOT}`", "`mpc2_vs`")])
        self.assertNotIn("`base`'s", mech)
        self.assertNotIn("`ref3`'s", mech)

    def test_run_without_base_or_ref3_shows_each_variants_own_worst_corner(self):
        mech = _section(R.render_record(record(("ref3_ngclamp", "ngclamp"))), "## Mechanism")
        self.assertIn("## Mechanism -- the operating point at the two binding corners", mech)
        self.assertEqual([(row[0], row[1]) for row in _table_rows(mech)], [
            ("`sf_125c_3.63v`", "`ref3_ngclamp`"), ("`sf_125c_3.63v`", "`ngclamp`"),
            ("`fs_125c_3.63v`", "`ref3_ngclamp`"), ("`fs_125c_3.63v`", "`ngclamp`")])
        self.assertRegex(
            mech,
            r"`sf_125c_3\.63v` \([\d.]+ dB\) is `ref3_ngclamp`'s binding corner and "
            r"`fs_125c_3\.63v` \([\d.]+ dB\) is `ngclamp`'s binding corner -- different corners\.",
        )
        self.assertIn(f"`{R.NG_CHECK}` was not evaluated", mech)

    def test_duplicate_variant_selection_renders_one_column(self):
        md = R.render_record(record(("base", "ref3", "base")))
        self.assertEqual(_result_header(md)[3:], ["`base`", "`ref3`"])
        self.assertIn("for each of the 2 variants -- 90 ngspice points", md)

    def test_variant_without_a_band_measurement_has_no_binding_corner(self):
        def no_band(results):
            for p in results.values():
                p["measurements"].pop("psrr_band_min")

        mech = _section(R.render_record(record(("mpc2_vs",), mutate=no_band)), "## Mechanism")
        self.assertIn("## Mechanism -- no binding corner", mech)
        self.assertIn("no `psrr_band_min` measurement in any variant shown", mech)
        self.assertEqual(_table_rows(mech), [])

    def test_unregistered_variant_name_is_not_rendered(self):
        r = record(("base",))
        r["variants"] = ["base", "no_such_variant"]
        md = R.render_record(r)
        self.assertEqual(_result_header(md)[3:], ["`base`"])
        self.assertNotIn("no_such_variant", md)


class KnobVariantRecordTests(unittest.TestCase):
    def test_knob_run_names_the_param_line_it_rewrites(self):
        cands = _section(R.render_record(record(("base", "ng_mref0p5"))), "## Candidates")
        self.assertIn("| `ng_mref0p5` | `MNG` clamp with `.param m_ref=0.5`", cands)
        self.assertNotIn("No existing device is resized in any variant", cands)
        self.assertIn("No existing device is resized in `base`: every `W`/`L`/`mult` in the "
                      "body is the shipped value. That is deliberate -- DR-011 closed the "
                      "resize-only path empirically", cands)
        self.assertIn("these bodies do not carry the shipped multiplicities: `ng_mref0p5` "
                      "rewrites `.param m_ref=1` -> `.param m_ref=0.5`.", cands)

    def test_knob_only_run_makes_no_no_resize_claim_at_all(self):
        cands = _section(R.render_record(record(("ng_mpnp16", "ng_mref0p25"))), "## Candidates")
        self.assertNotIn("No existing device is resized", cands)
        self.assertNotIn("DR-011 closed", cands)
        self.assertIn("these bodies do not carry the shipped multiplicities: `ng_mpnp16` "
                      "rewrites `.param m_pnp=8` -> `.param m_pnp=16`; `ng_mref0p25` rewrites "
                      "`.param m_ref=1` -> `.param m_ref=0.25`.", cands)

    def test_default_record_keeps_the_plain_no_resize_note(self):
        cands = _section(R.render_record(record()), "## Candidates")
        self.assertIn("No existing device is resized in any variant: every `W`/`L`/`mult` in "
                      "the body is the shipped value.", cands)
        self.assertNotIn("rewrites", cands)


class FooterScopeTests(unittest.TestCase):
    def test_pass_without_the_candidate_does_not_explain_it_by_the_candidate(self):
        r = record(("base", "ref3", "ngclamp"))
        self.assertTrue(r["overall_pass"])
        footer = _footer(R.render_record(r))
        self.assertIn("**Overall: PASS**", footer)
        self.assertNotIn("A PASS here means one thing only", footer)
        self.assertIn("`ref3_ngclamp` is not among this run's variants (`base`, `ref3` and "
                      "`ngclamp`), so no `candidate_clears_floor` / "
                      "`candidate_within_bare_core_ceiling` check was evaluated and this "
                      "record says nothing about whether it clears DR-006. A PASS here means "
                      "only that the checks listed above passed.", footer)
        for phrase in SCREEN_CAVEAT:
            self.assertIn(phrase, footer)

    def test_extra_variant_pass_keeps_the_screen_caveat(self):
        footer = _footer(R.render_record(record(("mpc2_vs",))))
        self.assertIn("**Overall: PASS**", footer)
        self.assertIn("is not among this run's variants (`mpc2_vs`)", footer)
        self.assertIn("landing a candidate means drawing it in `design/startup_injector.sch`, "
                      "re-running `sim/psrr-dc-with-injector` from the schematic", footer)
        for phrase in SCREEN_CAVEAT:
            self.assertIn(phrase, footer)


class CommittedThreeVariantRecordTests(unittest.TestCase):
    def test_ng_verdict_is_read_back_from_the_records_own_checks(self):
        src, results = _committed(THREE_VARIANT)
        self.assertEqual(src["variants"], ["base", "ref3", "ref3_ngclamp"])
        ng = [c for c in src["checks"] if c["name"].startswith(R.NG_CHECK)]
        n_pass = sum(1 for c in ng if c["pass"])
        src["_results"] = results
        src["_points"] = R.matrix()
        mech = _section(R.render_record(src), "## Mechanism")
        self.assertIn(f"`{R.NG_CHECK}`: PASS at {n_pass}/{len(ng)} corners", mech)
        self.assertEqual([row[1] for row in _table_rows(mech)],
                         [f"`{v}`" for v in ("base", "ref3", "ref3_ngclamp")] * 2)

    def test_a_record_without_the_ng_checks_says_so(self):
        r = record()
        r["checks"] = [c for c in r["checks"] if not c["name"].startswith(R.NG_CHECK)]
        self.assertIn(f"`{R.NG_CHECK}`: no such check in this record.",
                      _section(R.render_record(r), "## Mechanism"))


class FrozenProseTests(unittest.TestCase):
    def test_the_four_variant_narrative_is_gone_from_the_renderer(self):
        src = inspect.getsource(R.render_record)
        for phrase in FROZEN_PROSE:
            self.assertNotIn(phrase, src)
        self.assertIn("VARIANTS_BY_NAME", src)
        self.assertNotIn("for v in VARIANTS if", src)
        self.assertIn('for n in dict.fromkeys(r["variants"]) if n in VARIANTS_BY_NAME', src)

    def test_every_registered_variant_is_accepted_by_the_cli(self):
        self.assertGreater(len(R.VARIANTS_BY_NAME), len(R.VARIANTS))
        self.assertEqual(R.parse_args(["--variants", ",".join(R.VARIANTS_BY_NAME)]).variants,
                         list(R.VARIANTS_BY_NAME))
        for name in ("mpc2_vs", "ng_mref0p5"):
            self.assertIn(R.VARIANTS_BY_NAME[name], R.EXTRA_VARIANTS)
            self.assertNotIn(R.VARIANTS_BY_NAME[name], R.VARIANTS)


if __name__ == "__main__":
    unittest.main()
