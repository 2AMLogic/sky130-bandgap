"""Shared helpers deduplicated out of the two psrr-injector scripts (issue #379)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import sim_common  # noqa: E402


class SharedHelpersTest(unittest.TestCase):
    def test_corner_id_and_matrix(self):
        self.assertEqual(sim_common.corner_id("tt", 27, 1.8), "tt_27c_1.80v")
        self.assertEqual(
            sim_common.matrix(["tt", "ss"], [-40, 27], [1.7]),
            [("tt", -40, 1.7), ("tt", 27, 1.7), ("ss", -40, 1.7), ("ss", 27, 1.7)],
        )

    def test_band_min_by_corner(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            rec = tmp / "r.json"
            rec.write_text(json.dumps({"corners": [
                {"corner_id": "a", "measurements": [{"name": "psrr_band_min", "value": -41.5}]},
                {"corner_id": "b", "measurements": [{"name": "psrr_band_min", "value": None}]},
            ]}))
            self.assertEqual(sim_common.band_min_by_corner(rec, "rec"), {"a": -41.5})
            with self.assertRaises(sim_common._cr().HarnessError):
                sim_common.band_min_by_corner(tmp / "missing.json", "rec")

    def test_run_all_variants(self):
        def fake(v, p, t, s):
            cid = sim_common.corner_id(p, t, s)
            return {"variant": v, "corner_id": cid, "ngspice_exit": 0, "timed_out": False,
                    "measurements": {"psrr_band_min": -40.0} if v == "x" else {}}

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = sim_common.run_all_variants(fake, ["x", "y"], [("tt", 27, 1.8)], 2, 5)
        self.assertEqual(set(res), {("x", "tt_27c_1.80v"), ("y", "tt_27c_1.80v")})
        out = buf.getvalue()
        self.assertIn("[  1/2] x     tt_27c_1.80v", out)
        self.assertIn("NO MEASUREMENT (rc=0, timeout=False)", out)

    def test_write_batch_log_and_artifact_text(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            deck = tmp / "deck.cir"
            deck.write_text("R1 a b 1k\n")
            kcs = {"ac": {"artifacts": {"deck": str(deck)}, "diagnostics": []}}
            self.assertIsNone(sim_common.artifact_text(None, "deck"))
            self.assertEqual(sim_common.artifact_text(kcs["ac"], "deck"), "R1 a b 1k\n")
            sim_common.write_batch_log(tmp / "logs", "v__c", "rid", kcs)
            text = (tmp / "logs" / "v__c.log").read_text()
            self.assertIn("| R1 a b 1k", text)
            self.assertIn("(not retrieved)", text)  # no ngspice log artifact


if __name__ == "__main__":
    unittest.main()
