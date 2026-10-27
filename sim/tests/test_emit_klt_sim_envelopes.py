#!/usr/bin/env python3
"""Unit coverage for `sim/signoff-envelopes/emit_klt_sim_envelopes.py` (issue #434)."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_path = REPO_ROOT / "sim" / "signoff-envelopes" / "emit_klt_sim_envelopes.py"
_spec = importlib.util.spec_from_file_location("emit_klt_sim_envelopes", _path)
assert _spec and _spec.loader
emit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emit)


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


if __name__ == "__main__":
    unittest.main()
