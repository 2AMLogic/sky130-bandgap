#!/usr/bin/env python3
"""Coverage for `sim/res-array-head-resistance/run_res_array_head_resistance.py`'s
determination and record rendering (issue #638).

The runner's written confirmation must be derived from the named Phase A
checks, so a failed measurement can never produce a confirmation -- in either
output format (the record `.json`'s `determination` field and the `.md`
rendering). Positive control: the committed readings from the checked-in
record (Phase A checks all pass, Phase B corners fail). Negative control: the
equal-R1 case from issue #638's reproduction (R1's chain equals its single
device), which must fail `r1_chain_exceeds_single_device_model` and
`r1_chain_reproduces_klt_extraction` without any confirmation text.

No fleet, ngspice or PDK needed: `main()` is replayed with canned
measurements substituted for simulator output and record paths redirected to
a temporary directory, exactly the replay method issue #638 used.
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
    SIM_DIR / "res-array-head-resistance" / "run_res_array_head_resistance.py",
    "run_res_array_head_resistance",
)

COMMITTED_RECORD = (
    SIM_DIR / "res-array-head-resistance" / "records" / "20260805-113409-6caa9f8.json"
)

FAKE_PDK = SimpleNamespace(
    dir=Path("/nonexistent-pdk"),
    installed_commit="pinned-commit",
    variant="sky130A",
    matches_pin=True,
    lib_file=Path("/nonexistent-pdk/sky130.lib.spice"),
)


def committed_readings() -> tuple[dict, dict]:
    """(phase_a, phase_b) measurement dicts straight from the committed
    record -- the positive control's substituted simulator output."""
    data = json.loads(COMMITTED_RECORD.read_text())
    phase_b = {}
    for key, values in data["phase_b"].items():
        process, supply = key.split(":")
        phase_b[(process, float(supply))] = dict(values)
    return dict(data["phase_a"]), phase_b


def in_spec_phase_b() -> dict:
    """Synthetic Phase B readings inside the draft spec window at every
    corner -- exercises the all-PASS branch of the Phase B statement."""
    out = {}
    for process, supply in rt.PHASE_B_CORNERS:
        out[(process, supply)] = {
            "vref_27": 1.2,
            "vref_min": 1.19,
            "vref_max": 1.21,
            "tc_ppm": 50.0,
            "n_temp_points": 16,
        }
    return out


def replay_main(meas_a: dict, phase_b: dict) -> tuple[int, dict, str]:
    """Run the runner's `main()` with canned measurements and temp-dir
    records; return (exit code, parsed record json, record markdown)."""
    readings = {"phase_a": dict(meas_a)}
    for (process, supply), values in phase_b.items():
        readings[f"phase_b_{process}_{supply:.2f}v"] = dict(values)

    def fake_run_ngspice(run_dir, name, deck, timeout):
        return name, 0, False

    def fake_parse_measurements(raw):
        return dict(readings[raw])

    # The temp tree must sit inside the repo: the record's `links` block and
    # `render_record()` derive repo-relative paths from REPO_ROOT.
    tmp = Path(tempfile.mkdtemp(dir=SIM_DIR.parent, prefix="res-array-determination-"))
    try:
        def fake_setup_record_paths(here, record_id):
            records_dir = tmp / "records"
            corners_dir = tmp / "corners" / record_id
            snapshots_dir = tmp / "netlist-snapshots"
            return (
                records_dir,
                snapshots_dir,
                corners_dir,
                records_dir / f"{record_id}.md",
                records_dir / f"{record_id}.json",
                snapshots_dir / f"{record_id}.spice",
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


def check_map(record: dict) -> dict:
    return {c["name"]: c["pass"] for c in record["checks"]}


class DeterminationReplayTests(unittest.TestCase):
    def test_committed_readings_confirm_phase_a_and_report_phase_b_failures(self) -> None:
        """Positive control: Phase A checks pass, so both statements read
        PASS even though the overall verdict is FAIL (Phase B corners)."""
        meas_a, phase_b = committed_readings()
        rc, record, md = replay_main(meas_a, phase_b)

        self.assertEqual(rc, 2)
        self.assertFalse(record["overall_pass"])
        det = record["determination"]
        self.assertIn("R1 PASS (`r1_chain_exceeds_single_device_model`)", det)
        self.assertIn("R2A/R2B PASS (`r2_chain_exceeds_single_device_model`)", det)
        self.assertIn("R1 PASS (`r1_chain_reproduces_klt_extraction`)", det)
        self.assertIn("R2A/R2B PASS (`r2_chain_reproduces_klt_extraction`)", det)
        self.assertIn("OUTSIDE the draft +/-1% spec window at 5/5 corner points", det)
        self.assertIn(det, md)

    def test_equal_r1_never_reads_as_a_confirmation(self) -> None:
        """Negative control (issue #638's reproduction): R1's chain equals its
        single device, so R1's two Phase A checks fail -- the record must say
        so instead of confirming, in both output formats."""
        meas_a, phase_b = committed_readings()
        meas_a["r1_chain_ohm"] = meas_a["r1_single_ohm"]
        rc, record, md = replay_main(meas_a, phase_b)

        self.assertEqual(rc, 2)
        checks = check_map(record)
        self.assertFalse(checks["r1_chain_exceeds_single_device_model"])
        self.assertFalse(checks["r1_chain_reproduces_klt_extraction"])
        self.assertTrue(checks["r2_chain_exceeds_single_device_model"])
        det = record["determination"]
        self.assertIn("R1 FAIL (`r1_chain_exceeds_single_device_model`)", det)
        self.assertIn("R1 FAIL (`r1_chain_reproduces_klt_extraction`)", det)
        self.assertIn("R2A/R2B PASS (`r2_chain_exceeds_single_device_model`)", det)
        self.assertIn("R2A/R2B PASS (`r2_chain_reproduces_klt_extraction`)", det)
        self.assertNotIn("Reading 2 (a real electrical effect), confirmed.", det)
        self.assertIn(det, md)
        self.assertNotIn("Reading 2 (a real electrical effect), confirmed.", md)

    def test_markdown_has_no_unconditional_agreement_paragraph(self) -> None:
        """The Phase A section must not assert klt-reproduction agreement;
        the numbers live in the check details, the verdict in the checks."""
        meas_a, phase_b = committed_readings()
        _, _, md = replay_main(meas_a, phase_b)
        self.assertNotIn("Reproduction of klt's own extraction", md)
        self.assertNotIn("independently confirms", md)

    def test_in_spec_phase_b_reads_all_pass_and_exits_zero(self) -> None:
        """The Phase B statement tracks the spec checks, not a fixed
        narrative: the all-pass branch reports all corners in spec."""
        meas_a, _ = committed_readings()
        rc, record, md = replay_main(meas_a, in_spec_phase_b())

        self.assertEqual(rc, 0)
        self.assertTrue(record["overall_pass"])
        det = record["determination"]
        self.assertIn(
            "stayed inside the draft +/-1% spec window at all 5 corner points", det
        )
        self.assertIn("R1 PASS (`r1_chain_exceeds_single_device_model`)", det)
        self.assertIn(det, md)


class BuildDeterminationUnitTests(unittest.TestCase):
    @staticmethod
    def checks(**overrides) -> list[dict]:
        base = {
            "r1_chain_exceeds_single_device_model": True,
            "r2_chain_exceeds_single_device_model": True,
            "r1_chain_reproduces_klt_extraction": True,
            "r2_chain_reproduces_klt_extraction": True,
            **{f"chained_vref27_in_spec[{p}_{s:.2f}v]": True for p, s in rt.PHASE_B_CORNERS},
        }
        base.update(overrides)
        return [{"name": name, "pass": ok, "detail": ""} for name, ok in base.items()]

    def test_missing_named_check_is_an_error_not_a_silent_determination(self) -> None:
        with self.assertRaises(rt.cr.HarnessError):
            rt.build_determination(
                [{"name": "r1_chain_exceeds_single_device_model", "pass": True, "detail": ""}]
            )

    def test_statements_follow_the_checks_not_a_fixed_narrative(self) -> None:
        det = rt.build_determination(
            self.checks(
                r1_chain_exceeds_single_device_model=False,
                r1_chain_reproduces_klt_extraction=False,
                **{"chained_vref27_in_spec[tt_3.30v]": False},
            )
        )
        self.assertIn("R1 FAIL (`r1_chain_exceeds_single_device_model`)", det)
        self.assertIn("R1 FAIL (`r1_chain_reproduces_klt_extraction`)", det)
        self.assertIn("tt/3.30V", det)
        self.assertIn("OUTSIDE the draft +/-1% spec window at 1/5 corner points", det)


if __name__ == "__main__":
    unittest.main()
