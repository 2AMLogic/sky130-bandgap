#!/usr/bin/env python3
"""Coverage for `sim/trim-range-monotonicity/run_trim_sweep.py`'s check
details and record narrative (issue #687).

The record's narrative must follow the measurements a run actually took, so
a failing run can never write a self-contradicting record: check `detail`
strings may not assert sanity, bracketing or non-monotonicity the
measurements refute, the positive-direction table's `+0` row may not hardcode
`yes`, the experiment title / corner-matrix description / Claim / Scope
limits may not state run 1's historical outcome, and the `-16` TC-delta range
in Scope limits must be derived from `results` (matching
`tc_delta_reported[*]`). Positive control: the committed readings from the
checked-in record (exit 0, all 58 checks pass). Negative controls: the
failure readings from issue #687's reproduction -- a collapsed trim=0
baseline, every positive code regulating, a collapsed `+3`, a clean all-
collapsed threshold, and a shifted `-16` TC delta -- each of which must read
as FAIL in `checks` and Markdown alike, with none of the unconditional
run-1 prose appearing.

No fleet, ngspice or PDK needed: `main()` is replayed with canned
measurements substituted for simulator output and record paths redirected to
a temporary directory, exactly the replay method issue #687 used.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(SIM_DIR.parent / "scripts" / "ci"))

from script_module import load_script_module  # noqa: E402

rt = load_script_module(
    SIM_DIR / "trim-range-monotonicity" / "run_trim_sweep.py",
    "run_trim_sweep",
)

COMMITTED_RECORD = (
    SIM_DIR / "trim-range-monotonicity" / "records" / "20260803-170704-b976d0f.json"
)

FAKE_PDK = SimpleNamespace(
    dir=Path("/nonexistent-pdk"),
    installed_commit="pinned-commit",
    variant="sky130A",
    matches_pin=True,
    lib_file=Path("/nonexistent-pdk/sky130.lib.spice"),
)

#: Prose that was unconditional before #687; no rendered record, passing or
#: failing, may carry it.
UNCONDITIONAL_PROSE = (
    "Read the ff row across codes",
    "collapsed, collapsed, sane, sane, collapsed",
    "## Controls",
    "reproduces the pre-existing untrimmed record",
    "The override-that-didn't-work IS the negative control",
    "replicates issue #46's finding",
    "both lose the ff/2.97 V and fs/2.97 V operating point",
    "1.199721 V / 163.389 ppm/°C",
    "+79 to +86 ppm/°C",
    "demonstrating non-monotonic collapse",
    "a substantial, disclosed cost",
    "certified usable by this record",
    "confirms the same collapse mechanism is not ff-specific",
    "DOWNWARD-ONLY range, positive direction rejected",
    "Headline finding: the positive (VOUT-increasing) direction is REJECTED",
    "the positive direction was tested",
    "and found unsafe",
    "bracketed by codes that collapse",
)

POSITIVE_REGULATING = (
    "ff_trimp1_2.97v",
    "ff_trimp2_2.97v",
    "ff_trimp3_2.97v",
    "ff_trimp4_2.97v",
    "ff_trimp5_2.97v",
    "ff_trimp15_2.97v",
    "fs_trimp15_2.97v",
)


def committed_record() -> dict:
    return json.loads(COMMITTED_RECORD.read_text())


def committed_readings() -> dict[str, dict]:
    """Canned simulator output keyed by the corner id `main()` runs
    (`Point.corner_id`), from the committed record."""
    out: dict[str, dict] = {}
    for key, values in committed_record()["results"].items():
        process, supply, code = key.split(":")
        point = rt.Point(process, float(supply), int(code), "positive_rejected")
        out[point.corner_id] = dict(values)
    return out


def issue_reproduction(readings: dict[str, dict]) -> None:
    """Issue #687's failure readings: a tt trim=0 baseline driven out of the
    sanity band, a collapsed ff trim=0 baseline, every positive code
    regulating, and the tt -16 TC delta shifted to +12.0 ppm/°C."""
    readings["tt_trimp0_3.30v"].update(vref_27=1.350, tc_ppm=240.0)
    readings["ff_trimp0_2.97v"]["vref_max"] = 2.850
    for name in POSITIVE_REGULATING:
        readings[name].update(vref_27=1.200, vref_max=1.205)
    readings["tt_trimn16_3.30v"]["tc_ppm"] = readings["tt_trimp0_3.30v"]["tc_ppm"] + 12.0


def tc_delta_range(readings: dict[str, dict]) -> str:
    """The Scope-limits TC-delta range the runner must render, computed the
    same way from the same floats."""
    deltas = [
        readings[f"{process}_trimn16_{supply:.2f}v"]["tc_ppm"]
        - readings[f"{process}_trimp0_{supply:.2f}v"]["tc_ppm"]
        for process, supply in rt.NEGATIVE_CORNERS
    ]
    return f"{min(deltas):+.3f} to {max(deltas):+.3f} ppm/°C"


def replay_main(readings: dict[str, dict]) -> tuple[int, dict, str]:
    """Run the runner's `main()` with canned measurements and temp-dir
    records; return (exit code, parsed record json, record markdown)."""

    def fake_run_ngspice(run_dir, name, deck, timeout):
        return name, 0, False

    def fake_parse_measurements(raw):
        return dict(readings[raw])

    # The temp tree must sit inside the repo: the record's `links` block and
    # `render_record()` derive repo-relative paths from REPO_ROOT.
    tmp = Path(tempfile.mkdtemp(dir=SIM_DIR.parent, prefix="trim-range-narrative-"))
    try:
        def fake_setup_record_paths(here, record_id, **_):
            records_dir = tmp / "records"
            snapshots_dir = tmp / "netlist-snapshots"
            return (
                records_dir,
                snapshots_dir,
                tmp / "corners" / record_id,
                records_dir / f"{record_id}.md",
                records_dir / f"{record_id}.json",
                snapshots_dir / f"{record_id}.spice",
            )

        with mock.patch.object(rt, "check_pdk_and_ngspice", return_value=FAKE_PDK), \
                mock.patch.object(rt, "run_ngspice", side_effect=fake_run_ngspice), \
                mock.patch.object(rt, "parse_measurements", side_effect=fake_parse_measurements), \
                mock.patch.object(rt, "setup_record_paths", side_effect=fake_setup_record_paths), \
                mock.patch.object(rt, "publish_run_evidence", return_value=None), \
                mock.patch.object(rt.cr, "netlist_with_xschem", return_value=["netlisted"]), \
                mock.patch.object(rt.cr, "netlist_body", return_value=[".param n_r2_trim=0"]):
            rc = rt.main([])

        record_json = next((tmp / "records").glob("*.json"))
        record_md = next((tmp / "records").glob("*.md"))
        return rc, json.loads(record_json.read_text()), record_md.read_text()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_map(record: dict) -> dict[str, bool]:
    return {c["name"]: c["pass"] for c in record["checks"]}


def detail_map(record: dict) -> dict[str, str]:
    return {c["name"]: c["detail"] for c in record["checks"]}


class NarrativeReplayTests(unittest.TestCase):
    def test_committed_readings_pass(self) -> None:
        """Positive control: the committed record's readings exit 0 with all
        58 checks passing, and the derived narratives state the measured
        outcome (the committed +77.582..+79.537 ppm/°C TC cost DR-002
        cites, the +3/+4 bracketing at its measured +2/+5 neighbours)."""
        rc, record, md = replay_main(committed_readings())

        self.assertEqual(rc, 0)
        self.assertTrue(record["overall_pass"])
        self.assertEqual(len(record["checks"]), 58)
        self.assertTrue(all(c["pass"] for c in record["checks"]), record["checks"])
        self.assertIn("**Overall: PASS** (0 check(s) failed)", md)
        self.assertIn("measures a signed TC change of +77.582 to +79.537 ppm/°C", md)
        self.assertIn("- **Experiment**: `trim-range-monotonicity` — " + rt.TITLE, md)
        self.assertIn("**Positive direction (rejection test)**", md)
        details = detail_map(record)
        self.assertIn(
            "sane on this grid, but bracketed by collapsed codes (+2 below, +5 above)",
            details["positive_code_sane_but_not_safe[ff_trimp3_2.97v]"],
        )
        self.assertIn(
            "sane on this grid, but bracketed by collapsed codes (+2 below, +5 above)",
            details["positive_code_sane_but_not_safe[ff_trimp4_2.97v]"],
        )
        self.assertIn(
            "regulation is lost and regained along increasing code",
            details["positive_direction_nonmonotonic[ff]"],
        )

    def test_markdown_has_no_unconditional_prose(self) -> None:
        """No rendered record, passing or failing, carries the removed
        run-1 prose: the fixed collapse paragraph, the Controls section, the
        hardcoded title outcome and the hardcoded TC-delta range."""
        for readings in (committed_readings(),):
            _, _, md = replay_main(readings)
            for text in UNCONDITIONAL_PROSE:
                self.assertNotIn(text, md, text)
        self.assertNotIn("rejected", rt.TITLE)

    def test_issue_reproduction_fails_consistently(self) -> None:
        """Negative control, issue #687's reproduction: a collapsed ff
        trim=0 baseline, every positive code regulating and a +12.0 ppm/°C
        tt -16 delta exit 2 with 8/58 checks failed, and the record agrees
        with itself -- the +0 row reads collapsed, the non-monotonicity
        detail withdraws its claim, and Scope limits quotes the measured
        TC range, not run 1's."""
        readings = committed_readings()
        issue_reproduction(readings)
        rc, record, md = replay_main(readings)

        self.assertEqual(rc, 2)
        self.assertFalse(record["overall_pass"])
        self.assertEqual(sum(not c["pass"] for c in record["checks"]), 8)
        self.assertIn("**Overall: FAIL** (8 check(s) failed)", md)

        # The +0 baseline row follows is_regulating(m0), not a hardcoded yes.
        self.assertIn(
            "| ff | 2.97 | +0 | 1.199468 | 2.850000 | 162.298 | **NO — collapsed** |",
            md,
        )
        self.assertNotIn("| ff | 2.97 | +0 | 1.199468 | 2.850000 | 162.298 | yes |", md)

        details = detail_map(record)
        checks = check_map(record)
        self.assertFalse(checks["positive_direction_nonmonotonic[ff]"])
        self.assertIn(
            "every probed positive code stayed on the operating branch",
            details["positive_direction_nonmonotonic[ff]"],
        )
        self.assertNotIn(
            "genuine mix", details["positive_direction_nonmonotonic[ff]"]
        )
        for name in POSITIVE_REGULATING:
            if name == "ff_trimp3_2.97v" or name == "ff_trimp4_2.97v":
                continue
            self.assertFalse(checks[f"regulation_loss_confirmed[{name}]"], name)
            self.assertIn("UNEXPECTED", details[f"regulation_loss_confirmed[{name}]"])

        # Scope limits derives the -16 TC-delta span from this run's results.
        self.assertIn(f"measures a signed TC change of {tc_delta_range(readings)}", md)

        # Title and corner-matrix description state the test, not the
        # historical outcome.
        self.assertIn("- **Experiment**: `trim-range-monotonicity` — " + rt.TITLE, md)
        self.assertIn("probing for non-monotonic collapse", md)
        for text in UNCONDITIONAL_PROSE:
            self.assertNotIn(text, md, text)

    def test_collapsed_sane_code_reads_as_unexpected(self) -> None:
        """A collapsed +3 fails positive_code_sane_but_not_safe with an
        UNEXPECTED detail instead of claiming sanity, while the still-sane
        +4's bracketing follows its now-collapsed +3 neighbour."""
        readings = committed_readings()
        readings["ff_trimp3_2.97v"]["vref_max"] = 2.850
        rc, record, md = replay_main(readings)

        self.assertEqual(rc, 2)
        self.assertEqual(sum(not c["pass"] for c in record["checks"]), 1)
        checks = check_map(record)
        details = detail_map(record)
        self.assertFalse(checks["positive_code_sane_but_not_safe[ff_trimp3_2.97v]"])
        self.assertIn(
            "UNEXPECTED: this code was expected to stay sane on this grid",
            details["positive_code_sane_but_not_safe[ff_trimp3_2.97v]"],
        )
        self.assertNotIn(
            "sane on this grid, but",
            details["positive_code_sane_but_not_safe[ff_trimp3_2.97v]"],
        )
        self.assertTrue(checks["positive_code_sane_but_not_safe[ff_trimp4_2.97v]"])
        self.assertIn(
            "bracketed by collapsed codes (+3 below, +5 above)",
            details["positive_code_sane_but_not_safe[ff_trimp4_2.97v]"],
        )
        self.assertTrue(checks["positive_direction_nonmonotonic[ff]"])
        self.assertIn(
            "FAIL `positive_code_sane_but_not_safe[ff_trimp3_2.97v]` — "
            "vref_27=1.204653, vref_max=2.85 -- UNEXPECTED",
            md,
        )

    def test_clean_threshold_fails_the_nonmonotonic_check(self) -> None:
        """+3 and +4 collapsed too: every probed ff code left the operating
        branch, so the non-monotonicity check fails as a clean threshold
        rather than asserting the mix it looks for."""
        readings = committed_readings()
        readings["ff_trimp3_2.97v"]["vref_max"] = 2.850
        readings["ff_trimp4_2.97v"]["vref_max"] = 2.850
        rc, record, md = replay_main(readings)

        self.assertEqual(rc, 2)
        self.assertEqual(sum(not c["pass"] for c in record["checks"]), 3)
        checks = check_map(record)
        details = detail_map(record)
        self.assertFalse(checks["positive_direction_nonmonotonic[ff]"])
        self.assertIn(
            "every probed positive code collapsed",
            details["positive_direction_nonmonotonic[ff]"],
        )
        self.assertIn("no threshold is inferred", details["positive_direction_nonmonotonic[ff]"])
        self.assertNotIn("regained", details["positive_direction_nonmonotonic[ff]"])
        self.assertIn("every probed positive code collapsed", md)

    def test_single_collapse_threshold_is_not_nonmonotonic(self) -> None:
        """One transition (ff regulating at +1..+4, collapsed at +5 and +15)
        is a clean threshold, not a reversal: the check fails and the detail
        says so."""
        readings = committed_readings()
        for code in (1, 2, 3, 4):
            readings[f"ff_trimp{code}_2.97v"].update(vref_27=1.2, vref_max=1.205)
        rc, record, md = replay_main(readings)

        self.assertEqual(rc, 2)
        checks = check_map(record)
        detail = detail_map(record)["positive_direction_nonmonotonic[ff]"]
        self.assertFalse(checks["positive_direction_nonmonotonic[ff]"])
        self.assertIn("single transition", detail)
        self.assertNotIn("regained", detail)
        self.assertIn("FAIL `positive_direction_nonmonotonic[ff]`", md)
        self.assertIn("did NOT show a reversal", md)
        self.assertNotIn("PASS `positive_direction_nonmonotonic[ff]`", md)

    def test_failed_run_does_not_certify_downward_range(self) -> None:
        """A failed negative-range check withdraws the downward-range claim
        and the full-temperature-coverage claim."""
        readings = committed_readings()
        readings["tt_trimp0_3.30v"].update(vref_27=1.350, tc_ppm=240.0)
        _, record, md = replay_main(readings)

        self.assertFalse(check_map(record)["sanity[tt_trimp0_3.30v]"])
        self.assertIn("does NOT support the downward range as usable", md)
        self.assertNotIn("certified usable", md)
        self.assertNotIn("full temperature coverage", md)
        self.assertNotIn("usable)", md)

    def test_tc_improvement_is_reported_neutrally(self) -> None:
        """Every -16 TC set to trim=0 minus 5 ppm/°C, with a trim=0 TC of 45
        (below 50): reported as a signed -5 improvement, not a cost, and the
        per-corner detail does not claim the baseline exceeds 50."""
        readings = committed_readings()
        for process, supply in rt.NEGATIVE_CORNERS:
            base = f"{process}_trimp0_{supply:.2f}v"
            readings[base]["tc_ppm"] = 45.0
            readings[f"{process}_trimn16_{supply:.2f}v"]["tc_ppm"] = 40.0
        rc, record, md = replay_main(readings)

        self.assertEqual(rc, 0)
        self.assertIn("signed TC change of -5.000 to -5.000 ppm/°C", md)
        self.assertIn("a decrease at every corner, i.e. an improvement, not a cost", md)
        self.assertNotIn("substantial, disclosed cost", md)
        for name, detail in detail_map(record).items():
            if name.startswith("tc_delta_reported["):
                self.assertIn("does not exceed the 50", detail)
                self.assertNotIn("baseline itself already exceeds", detail)


if __name__ == "__main__":
    unittest.main()
