#!/usr/bin/env python3
"""Unit coverage for `sim/signoff-envelopes/emit_klt_sim_envelopes.py` (issue #434)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_path = REPO_ROOT / "sim" / "signoff-envelopes" / "emit_klt_sim_envelopes.py"
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))
from script_module import load_script_module  # noqa: E402

emit = load_script_module(_path, "emit_klt_sim_envelopes")


class EmitTest(unittest.TestCase):
    def test_committed_envelopes_are_fresh(self) -> None:
        for path, text in emit.build().items():
            self.assertEqual(path.read_text(), text, emit.rel(path))

    def test_every_ratified_row_is_covered_or_gapped(self) -> None:
        rows = json.loads(emit.MANIFEST.read_text())["spec_rows"]["5"]
        declared = {r["id"] for r in rows}
        covered = {
            m["spec_row"]
            for p in emit.ENVELOPE_DIR.glob("*.klt-sim.json")
            for m in json.loads(p.read_text())["measurements"]
        }
        gaps = {r["id"] for r in rows if r.get("gap")}
        self.assertEqual(declared, covered | gaps)
        self.assertFalse(covered & gaps)

    def test_limits_equal_ratified_bounds(self) -> None:
        for p in emit.ENVELOPE_DIR.glob("*.klt-sim.json"):
            for m in json.loads(p.read_text())["measurements"]:
                if m["name"] == "tc_ppm":
                    self.assertEqual(m["limits"], emit.TC_MAX)
                if m["name"] == "iq":
                    self.assertEqual(m["limits"]["max"], emit.IQ_MAX)

    def test_failing_row_does_not_drag_sibling_row(self) -> None:
        tc = json.loads((emit.ENVELOPE_DIR / "output-voltage-tc.3a.klt-sim.json").read_text())
        vref = json.loads((emit.ENVELOPE_DIR / "output-voltage-tc.1a.klt-sim.json").read_text())
        self.assertEqual(tc["status"], "fail")
        self.assertEqual(vref["status"], "pass")

    def test_drifted_limit_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            emit.check_bound("b", "m", {"max": 60.0}, {"max": 50.0})

    def test_pin_is_netlist_snapshot_hash(self) -> None:
        for p in emit.ENVELOPE_DIR.glob("*.klt-sim.json"):
            e = json.loads(p.read_text())
            digest = emit.sha256_file(REPO_ROOT / e["netlist"])
            self.assertEqual(e["provenance"]["input"]["content_hash"], f"sha256:{digest}")

    def test_margin_handles_missing_value_and_empty_limits(self) -> None:
        self.assertIsNone(emit.margin(None, {"max": 1e-3}))
        self.assertIsNone(emit.margin(None, {"min": 1.0, "max": 2.0}))
        self.assertIsNone(emit.margin(0.5, {}))
        self.assertAlmostEqual(emit.margin(0.2e-3, {"max": 1e-3}), 0.8e-3)

    def test_worst_point_ranks_missing_value_worse_than_finite_margin(self) -> None:
        mixed = [
            (0.9e-3, 0.1e-3, "tt_27c_3.30v", True, ""),
            (None, None, "tt_125c_2.97v", False, "measurement not found in ngspice output"),
            (-0.2e-3, 1.2e-3, "ss_125c_2.97v", False, "above max 0.001"),
        ]
        self.assertEqual(
            emit.worst_point(mixed),
            {
                "corner_id": "tt_125c_2.97v",
                "value": None,
                "margin": None,
                "reason": "measurement not found in ngspice output",
            },
        )
        all_missing = [
            (None, None, "c1", False, "missing 1"),
            (None, None, "c2", False, "missing 2"),
        ]
        self.assertEqual(
            emit.worst_point(all_missing),
            {"corner_id": "c1", "value": None, "margin": None, "reason": "missing 1"},
        )
        all_numeric = [
            (0.8e-3, 0.2e-3, "c1", True, ""),
            (0.4e-3, 0.6e-3, "c2", True, ""),
        ]
        self.assertEqual(
            emit.worst_point(all_numeric),
            {"corner_id": "c2", "value": 0.6e-3, "margin": 0.4e-3},
        )

    def test_mint_preserves_missing_value_corner_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "design" / "netlist").mkdir(parents=True)
            bench_dir = root / "sim" / "dummy-bench"
            (bench_dir / "records").mkdir(parents=True)
            (bench_dir / "netlist-snapshots").mkdir(parents=True)
            snap = "sim/dummy-bench/netlist-snapshots/r1.spice"
            (root / snap).write_text("* empty\n")
            record = {
                "matrix": {"n_points": 2},
                "links": {"netlist_snapshot": snap},
                "corners": [
                    {
                        "corner_id": "tt_27c_3.30v",
                        "process": "tt",
                        "supply_v": 3.3,
                        "temperature_c": 27.0,
                        "measurements": [
                            {
                                "name": "t_start_s",
                                "unit": "s",
                                "min": None,
                                "max": 1e-3,
                                "value": 1e-4,
                                "pass": True,
                                "reason": "",
                            }
                        ],
                    },
                    {
                        "corner_id": "tt_125c_2.97v",
                        "process": "tt",
                        "supply_v": 2.97,
                        "temperature_c": 125.0,
                        "measurements": [
                            {
                                "name": "t_start_s",
                                "unit": "s",
                                "min": None,
                                "max": 1e-3,
                                "value": None,
                                "pass": False,
                                "reason": "measurement not found in ngspice output",
                            }
                        ],
                    },
                ],
            }
            (bench_dir / "records" / "20261124-000000-test.json").write_text(json.dumps(record))
            saved_root = emit.REPO_ROOT
            saved_file = emit.__file__
            emit.REPO_ROOT = root
            emit.__file__ = str(root / "sim" / "signoff-envelopes" / "emit_klt_sim_envelopes.py")
            try:
                _name, env = emit.mint(
                    {
                        "bench": "dummy-bench",
                        "row": "8d",
                        "all_mapped": {"t_start_s"},
                        "measurements": {"t_start_s": ("8d", {"max": 1e-3})},
                    }
                )
            finally:
                emit.REPO_ROOT = saved_root
                emit.__file__ = saved_file

            self.assertEqual(env["status"], "fail")
            self.assertEqual(env["corner_count"], 2)
            self.assertEqual(env["passed"], 1)
            self.assertEqual(env["failed"], 1)
            failed_corner = next(c for c in env["corners"] if c["corner_id"] == "tt_125c_2.97v")
            self.assertEqual(failed_corner["status"], "fail")
            self.assertEqual(
                failed_corner["measurements"][0],
                {
                    "name": "t_start_s",
                    "unit": "s",
                    "value": None,
                    "status": "fail",
                    "margin": None,
                    "reason": "measurement not found in ngspice output",
                },
            )
            self.assertEqual(env["measurements"][0]["status"], "fail")
            self.assertEqual(
                env["measurements"][0]["worst_case"],
                {
                    "corner_id": "tt_125c_2.97v",
                    "value": None,
                    "margin": None,
                    "reason": "measurement not found in ngspice output",
                },
            )


if __name__ == "__main__":
    unittest.main()
