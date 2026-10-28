#!/usr/bin/env python3
"""Unit coverage for the record selector of emit_klt_sim_envelopes.py (issue #456).

The minter must never pick a record whose netlist snapshot simulated a different
design from `design/netlist/*` (a candidate-branch experiment is newer than the
shipped design's record, so recency alone selects it).

Run directly (`python3 sim/signoff-envelopes/test_emit_klt_sim_envelopes.py`).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("emit", HERE / "emit_klt_sim_envelopes.py")
emit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emit)

DESIGN = """**.subckt startup_injector GDRV VSENSE VDD VSS
XMPC1 NC1 NC1 GDRV VDD pfet L=20
XMPC2 NG NG NC1 VDD pfet L=20
+ m=1
**.ends
"""
TWO_HIGH = """.subckt startup_injector GDRV VSENSE VDD VSS
* comment
XMPC2   NG NG NC1 VDD pfet L=20 m=1
XMPC1 NC1 NC1 GDRV VDD pfet L=20
.ends
"""
THREE_HIGH = """.subckt startup_injector GDRV VSENSE VDD VSS
XMPC1 NC1 NC1 GDRV VDD pfet L=20
XMPC2 NC2 NC2 NC1 VDD pfet L=20 m=1
XMPC3 NG NG NC2 VDD pfet L=20
.ends
"""


class SelectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        (root / "design" / "netlist").mkdir(parents=True)
        (root / "design" / "netlist" / "startup_injector.spice").write_text(DESIGN)
        self.root = root
        self._saved = emit.REPO_ROOT
        emit.REPO_ROOT = root
        self.addCleanup(lambda: setattr(emit, "REPO_ROOT", self._saved))

    def record(self, name: str, netlist: str) -> None:
        bench = self.root / "sim" / "bench"
        (bench / "records").mkdir(parents=True, exist_ok=True)
        (bench / "snapshots").mkdir(exist_ok=True)
        snap = f"sim/bench/snapshots/{name}.spice"
        (self.root / snap).write_text(netlist)
        (bench / "records" / f"{name}.json").write_text(
            json.dumps({"matrix": {"n_points": 45}, "links": {"netlist_snapshot": snap}})
        )

    def test_equivalent_netlist_matches_despite_formatting(self) -> None:
        self.assertEqual(emit.subckt_bodies(DESIGN), emit.subckt_bodies(TWO_HIGH))

    def test_newer_candidate_record_is_not_selected_by_recency(self) -> None:
        self.record("20260909-main", TWO_HIGH)
        self.record("20261015-candidate", THREE_HIGH)
        chosen = emit.newest_record("bench")
        self.assertEqual(chosen.stem, "20260909-main")

    def test_no_matching_record_is_refused_naming_bench_and_mismatch(self) -> None:
        self.record("20261015-candidate", THREE_HIGH)
        with self.assertRaises(SystemExit) as ctx:
            emit.newest_record("bench")
        message = str(ctx.exception)
        self.assertIn("bench", message)
        self.assertIn("startup_injector differs", message)

    def test_skipped_subckt_is_not_compared(self) -> None:
        snap = self.root / "s.spice"
        snap.write_text(THREE_HIGH)
        design = emit.current_design_subckts()
        self.assertIsNotNone(emit.snapshot_mismatch("s.spice", design))
        self.assertIsNone(emit.snapshot_mismatch("s.spice", design, frozenset({"startup_injector"})))


if __name__ == "__main__":
    unittest.main()
