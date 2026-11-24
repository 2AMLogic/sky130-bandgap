#!/usr/bin/env python3
"""Coverage for `sim/res-array-resize/run_res_array_resize.py`'s determination,
control prose and record rendering (issue #642).

The record's narrative must be derived from the checks `evaluate()` produced,
so a failing run can never write a self-contradicting record -- in either
output format (the record `.json`'s `determination` field and the `.md`
rendering). Positive control: the committed readings from the checked-in
record (every check passes, exit 0). Negative controls: the failure readings
from issue #642's reproduction -- AC2 out of spec, a shipped control that is
IN spec, and a too-short / non-monotonic / collapsing downward trim ladder --
each of which must read as FAIL in `checks`, `determination` and Markdown
alike, with no adoption, confirmation or "does not need to widen" text.

No fleet, ngspice or PDK needed: `main()` is replayed with canned
measurements substituted for simulator output and record paths redirected to
a temporary directory, exactly the replay method issue #642 used.
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
    SIM_DIR / "res-array-resize" / "run_res_array_resize.py",
    "run_res_array_resize",
)

COMMITTED_RECORD = (
    SIM_DIR / "res-array-resize" / "records" / "20260805-204809-2c83c7a.json"
)

FAKE_PDK = SimpleNamespace(
    dir=Path("/nonexistent-pdk"),
    installed_commit="pinned-commit",
    variant="sky130A",
    matches_pin=True,
    lib_file=Path("/nonexistent-pdk/sky130.lib.spice"),
)

#: DR-002's coverage target the determination grades the code-0..-16 span
#: against: 1.5 x the worst-case 3-sigma spread (15.62 mV at 125 degC).
SPAN_TARGET_MV = 1.5 * 15.620
ALL_CORNERS = ", ".join(f"{p}/{s:.2f}V" for p, s in rt.CORNERS)
AC2 = "AC2 (resized, untrimmed)"
CONTROL = "DR-003 control (shipped sizing, same code path)"
AC3 = "AC3 (DR-002's downward 0..-16 trim range on the resized baseline)"

#: Prose that was unconditional before #642; a failing run must never carry it.
UNCONDITIONAL_CONFIRMATIONS = (
    "Resize adopted",
    "Control confirms the harness",
    "confirming the harness reproduces",
    "out of spec at all 5 corners and collapses",
    "Layout follow-up",
    "CENTERS the untrimmed operating point",
)


def committed_record() -> dict:
    return json.loads(COMMITTED_RECORD.read_text())


def committed_readings() -> dict[str, dict]:
    """Canned simulator output keyed by the deck name `run_corner_set()`
    builds (`{tag}_{process}_{supply:.2f}v`), from the committed record."""
    out: dict[str, dict] = {}
    for key, values in committed_record()["resized"].items():
        process, supply = key.split(":")
        out[f"resized_{process}_{float(supply):.2f}v"] = dict(values)
    for key, values in committed_record()["shipped"].items():
        process, supply = key.split(":")
        out[f"shipped_{process}_{float(supply):.2f}v"] = dict(values)
    for key, values in committed_record()["resized_trim"].items():
        process, supply, trim = key.split(":")
        out[f"resized_trim{int(trim)}_{process}_{float(supply):.2f}v"] = dict(values)
    return out


def mutate(readings: dict[str, dict], tag: str, **fields) -> None:
    """Overwrite measurement fields of every deck run under `tag`."""
    for name, values in readings.items():
        if name.rsplit("_", 2)[0] == tag:
            values.update(fields)


def ac2_out_of_spec(readings: dict[str, dict]) -> None:
    mutate(readings, "resized", vref_27=1.240)


def shipped_in_spec(readings: dict[str, dict]) -> None:
    mutate(readings, "shipped", vref_27=1.200, vref_max=1.205)


def short_trim_span(readings: dict[str, dict]) -> None:
    """Issue #642's reproduction: the code-0..-16 span collapses to 8.00 mV
    at every corner, still strictly monotonic."""
    for process, supply in rt.CORNERS:
        suffix = f"_{process}_{supply:.2f}v"
        top = readings[f"resized{suffix}"]["vref_27"]
        readings[f"resized_trim-8{suffix}"]["vref_27"] = top - 0.004
        readings[f"resized_trim-16{suffix}"]["vref_27"] = top - 0.008


def non_monotonic_trim(readings: dict[str, dict], process: str, supply: float) -> None:
    readings[f"resized_trim-8_{process}_{supply:.2f}v"]["vref_27"] = (
        readings[f"resized_trim-16_{process}_{supply:.2f}v"]["vref_27"] - 0.001
    )


def collapsing_trim(readings: dict[str, dict], process: str, supply: float) -> None:
    readings[f"resized_trim-16_{process}_{supply:.2f}v"]["vref_max"] = 2.85


def replay_main(readings: dict[str, dict]) -> tuple[int, dict, str]:
    """Run the runner's `main()` with canned measurements and temp-dir
    records; return (exit code, parsed record json, record markdown)."""

    def fake_run_ngspice(run_dir, name, deck, timeout):
        return name, 0, False

    def fake_parse_measurements(raw):
        return dict(readings[raw])

    # The temp tree must sit inside the repo: the record's `links` block and
    # `render_record()` derive repo-relative paths from REPO_ROOT.
    tmp = Path(tempfile.mkdtemp(dir=SIM_DIR.parent, prefix="res-array-resize-determination-"))
    try:
        def fake_setup_record_paths(here, record_id, **_):
            records_dir = tmp / "records"
            corners_dir = tmp / "corners" / record_id
            return (
                records_dir,
                None,
                corners_dir,
                records_dir / f"{record_id}.md",
                records_dir / f"{record_id}.json",
                None,
            )

        with mock.patch.object(rt, "check_pdk_and_ngspice", return_value=FAKE_PDK), \
                mock.patch.object(rt, "run_ngspice", side_effect=fake_run_ngspice), \
                mock.patch.object(rt, "parse_measurements", side_effect=fake_parse_measurements), \
                mock.patch.object(rt, "setup_record_paths", side_effect=fake_setup_record_paths), \
                mock.patch.object(rt, "publish_run_evidence", return_value=None):
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


class DeterminationReplayTests(unittest.TestCase):
    def test_committed_readings_pass_and_confirm_the_control(self) -> None:
        """Positive control: every check passes, the record exits 0, and each
        group reads PASS in both output formats."""
        rc, record, md = replay_main(committed_readings())

        self.assertEqual(rc, 0)
        self.assertTrue(record["overall_pass"])
        self.assertTrue(all(c["pass"] for c in record["checks"]), record["checks"])
        det = record["determination"]
        self.assertIn(f"{AC2}: PASS 5/5 corners", det)
        self.assertIn(f"{CONTROL}: PASS 5/5 corners", det)
        self.assertIn(f"{AC3}: PASS 5/5 corners", det)
        self.assertIn("at least 49.96 mV per corner", det)
        self.assertIn(f"{SPAN_TARGET_MV:.2f} mV", det)
        self.assertIn("does not need to widen", det)
        self.assertIn(det, md)
        details = detail_map(record)
        self.assertIn("OUT of spec, reproducing DR-003", details["shipped_control_out_of_spec[tt_3.30v]"])
        self.assertNotIn("regulation collapsed", details["shipped_control_out_of_spec[tt_3.30v]"])
        self.assertIn(
            "regulation collapsed -- OUT of spec, reproducing DR-003",
            details["shipped_control_out_of_spec[ff_2.97v]"],
        )

    def test_markdown_has_no_unconditional_control_or_handoff_paragraph(self) -> None:
        """The DR-003 control table carries its own verdict columns; nothing
        beneath it may assert an outcome the table did not measure."""
        _, _, md = replay_main(committed_readings())
        for text in UNCONDITIONAL_CONFIRMATIONS:
            self.assertNotIn(text, md)
        self.assertIn("## DR-003 control -- shipped sizing", md)
        self.assertIn("**Overall: PASS**", md)

    def test_issue_reproduction_fails_consistently(self) -> None:
        """Negative control, issue #642's reproduction: AC2 out of spec, an
        IN-spec shipped control and an 8.00 mV trim span together exit 2 with
        10/25 checks failed -- and neither format confirms anything."""
        readings = committed_readings()
        ac2_out_of_spec(readings)
        shipped_in_spec(readings)
        short_trim_span(readings)
        rc, record, md = replay_main(readings)

        self.assertEqual(rc, 2)
        self.assertFalse(record["overall_pass"])
        self.assertEqual(sum(not c["pass"] for c in record["checks"]), 10)
        det = record["determination"]
        self.assertIn(f"{AC2}: FAIL 5/5 corners (failing: {ALL_CORNERS})", det)
        self.assertIn(f"{CONTROL}: FAIL 5/5 corners (failing: {ALL_CORNERS})", det)
        self.assertIn("the range needs widening", det)
        self.assertIn(det, md)
        self.assertIn("**Overall: FAIL** (10 check(s) failed)", md)
        for text in (*UNCONDITIONAL_CONFIRMATIONS, "does not need to widen"):
            self.assertNotIn(text, det)
            self.assertNotIn(text, md)

    def test_ac2_failure_reads_as_not_met(self) -> None:
        """AC2 out of spec at every corner: the determination says so, while
        the control it did reproduce still reads PASS."""
        readings = committed_readings()
        ac2_out_of_spec(readings)
        rc, record, md = replay_main(readings)

        self.assertEqual(rc, 2)
        checks = check_map(record)
        self.assertFalse(checks["resized_vref27_in_spec[tt_3.30v]"])
        self.assertTrue(checks["resized_regulating[tt_3.30v]"])
        self.assertTrue(checks["shipped_control_out_of_spec[tt_3.30v]"])
        det = record["determination"]
        self.assertIn(f"{AC2}: FAIL 5/5 corners (failing: {ALL_CORNERS})", det)
        self.assertIn("needs another iteration", det)
        self.assertIn(f"{CONTROL}: PASS 5/5 corners", det)
        self.assertNotIn(f"{AC2}: PASS", det)
        self.assertNotIn("Resize adopted", det)
        self.assertIn(det, md)

    def test_in_spec_control_detail_and_verdict_follow_the_measurement(self) -> None:
        """The shipped control lands IN spec: its check FAILS, its detail says
        so instead of `reproduces DR-003`, and the determination withdraws the
        harness confirmation -- in the record json and the Markdown alike."""
        readings = committed_readings()
        shipped_in_spec(readings)
        rc, record, md = replay_main(readings)

        self.assertEqual(rc, 2)
        details = detail_map(record)
        checks = check_map(record)
        for process, supply in rt.CORNERS:
            name = f"shipped_control_out_of_spec[{process}_{supply:.2f}v]"
            self.assertFalse(checks[name], name)
            self.assertIn("IN spec -- does NOT reproduce DR-003", details[name])
            self.assertNotIn("reproducing DR-003", details[name])
            self.assertIn(f"FAIL `{name}` — {details[name]}", md)
        det = record["determination"]
        self.assertIn(f"{CONTROL}: FAIL 5/5 corners (failing: {ALL_CORNERS})", det)
        self.assertIn("cannot be attributed to the resize alone", det)
        self.assertNotIn("Control confirms the harness", det)
        self.assertIn(f"{AC2}: PASS 5/5 corners", det)
        self.assertIn(det, md)

    def test_short_trim_span_reads_as_needing_widening(self) -> None:
        """An 8.00 mV code-0..-16 span is not a check, so the record still
        passes overall -- but the determination must ask for a wider range,
        not assert that none is needed."""
        readings = committed_readings()
        short_trim_span(readings)
        rc, record, md = replay_main(readings)

        self.assertEqual(rc, 0)
        self.assertTrue(record["overall_pass"])
        det = record["determination"]
        self.assertIn(f"{AC3}: PASS 5/5 corners", det)
        self.assertIn("at least 8.00 mV per corner, which does NOT clear", det)
        self.assertIn(f"{SPAN_TARGET_MV:.2f} mV", det)
        self.assertIn("the range needs widening", det)
        self.assertNotIn("does not need to widen", det)
        self.assertIn(det, md)
        self.assertNotIn("does not need to widen", md)

    def test_broken_trim_ladder_fails_ac3(self) -> None:
        """Non-monotonic at tt/3.30V and collapsing at fs/2.97V: the AC3
        verdict names exactly those two corners."""
        readings = committed_readings()
        non_monotonic_trim(readings, "tt", 3.30)
        collapsing_trim(readings, "fs", 2.97)
        rc, record, md = replay_main(readings)

        self.assertEqual(rc, 2)
        checks = check_map(record)
        self.assertFalse(checks["resized_trim_monotonic[tt_3.30v]"])
        self.assertFalse(checks["resized_trim_collapse_free[fs_2.97v]"])
        self.assertTrue(checks["resized_trim_monotonic[ss_3.30v]"])
        det = record["determination"]
        self.assertIn(f"{AC3}: FAIL 2/5 corners (failing: tt/3.30V, fs/2.97V)", det)
        self.assertIn(det, md)


class BuildDeterminationUnitTests(unittest.TestCase):
    @staticmethod
    def inputs():
        record = committed_record()
        trim = {}
        for key, values in record["resized_trim"].items():
            process, supply, code = key.split(":")
            trim[(process, float(supply), int(code))] = dict(values)
        names = [c["name"] for c in record["checks"]]
        return names, trim, record["resistances"]

    @classmethod
    def checks(cls, **overrides) -> list[dict]:
        names, _, _ = cls.inputs()
        verdicts = {name: True for name in names}
        verdicts.update(overrides)
        return [{"name": name, "pass": ok, "detail": ""} for name, ok in verdicts.items()]

    def test_missing_group_is_an_error_not_a_silent_pass(self) -> None:
        """A renamed check must not leave its group reading PASS."""
        _, trim, ra = self.inputs()
        with self.assertRaises(rt.cr.HarnessError):
            rt.build_determination(
                [{"name": "resized_vref27_in_spec[tt_3.30v]", "pass": True, "detail": ""}],
                trim,
                ra,
            )

    def test_verdicts_follow_the_checks_not_a_fixed_narrative(self) -> None:
        _, trim, ra = self.inputs()
        det = rt.build_determination(
            self.checks(**{"shipped_control_out_of_spec[tt_3.30v]": False}), trim, ra
        )
        self.assertIn(f"{AC2}: PASS 5/5 corners", det)
        self.assertIn(f"{CONTROL}: FAIL 1/5 corners (failing: tt/3.30V)", det)
        self.assertIn("does NOT reproduce DR-003 there", det)
        self.assertIn(f"{AC3}: PASS 5/5 corners", det)

    def test_span_verdict_follows_the_measurement(self) -> None:
        _, trim, ra = self.inputs()
        for (process, supply, code), values in trim.items():
            if code == -16:
                values["vref_27"] = trim[(process, supply, 0)]["vref_27"] - 0.023
        det = rt.build_determination(self.checks(), trim, ra)
        self.assertIn("the range needs widening", det)
        self.assertNotIn("does not need to widen", det)


if __name__ == "__main__":
    unittest.main()
