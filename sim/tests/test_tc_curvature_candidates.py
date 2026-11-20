"""The TC screen must measure a real circuit edit on each requested bench."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SIM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM / "tc-curvature-candidates"))
import run_candidates as screen


class CandidateTests(unittest.TestCase):
    def test_each_snapshot_receives_the_same_electrical_edit(self):
        for bench in screen.SNAPSHOTS:
            base = screen.cr.netlist_body(screen.snapshot(bench))
            for variant in screen.VARIANTS:
                with self.subTest(bench=bench, variant=variant):
                    lines = screen.variant_body(base, variant)
                    self.assertNotEqual(lines, base)
                    self.assertIn(
                        "XQ1 VSS VSS VA "
                        + screen.SMALL
                        + " m='n_pnp_ctat' mult='n_pnp_ctat'",
                        lines,
                    )
                    if variant == "unit-pair":
                        self.assertIn(
                            "XQ2 VSS VSS VBQ " + screen.SMALL + " m=80 mult=80", lines
                        )
                    elif variant == "mixed-r1":
                        self.assertIn(".param n_r1=3", lines)
                        self.assertTrue(
                            any(line.startswith("XTC_R1 MIX VB VSS ") for line in lines)
                        )
                    else:
                        self.assertIn(
                            "XTC_Q VSS VA TC_E " + screen.SMALL + " m=1 mult=1", lines
                        )

    def test_batch_request_covers_full_grid_and_stops_at_strict_limits(self):
        exp, matrix = screen.experiment("output-voltage-tc")
        body = screen.variant_body(
            screen.cr.netlist_body(screen.snapshot(exp.slug)), "unit-pair"
        )
        with tempfile.TemporaryDirectory() as tmp:
            groups = screen.requests(exp, matrix, body, Path(tmp))
            self.assertEqual([len(g.corners) for g in groups], [15, 15, 15])
            self.assertEqual(len({c.id for g in groups for c in g.corners}), 45)
            for group in groups:
                self.assertEqual(group.request["batch"]["capacity_wait_s"], 600)
                step = group.request["analysis_steps"][0]
                names = {m["name"] for m in step["measurements"]}
                self.assertTrue(
                    {
                        "n_temp_points",
                        "iq_peak_ua",
                        "vref_min",
                        "vref_max",
                        "tc_ppm",
                        "vref_27",
                    }
                    <= names
                )
            with patch.object(
                screen.batch_sim.subprocess, "run", side_effect=OSError
            ) as run:
                screen.submit(groups[0])
                cmd = run.call_args.args[0]
                self.assertEqual(cmd[cmd.index("--wait-for-capacity") + 1], "600")
        checks, _ = screen.cr.evaluate_measurements(
            exp, {"iq_peak_ua": 50, "tc_ppm": 50}
        )
        self.assertFalse(any(c["pass"] for c in checks))

    def test_current_delta_uses_the_matching_temperature_and_baseline_corner(self):
        results = [
            {
                "corner_id": "tt_-40c_3.30v",
                "temperature_c": -40,
                "measurements": [
                    {"name": "iq_cold_ua", "value": 22.5},
                    {"name": "iq_peak_ua", "value": 33},
                ],
            },
            {
                "corner_id": "ss_125c_2.97v",
                "temperature_c": 125,
                "measurements": [{"name": "iq_hot_ua", "value": None}],
            },
        ]
        baseline = {"tt_-40c_3.30v": 20.5, "ss_125c_2.97v": 32}
        screen.add_current_delta(results, baseline)
        self.assertEqual(results[0]["measurements"][-1]["value"], 2)
        self.assertIsNone(results[1]["measurements"][-1]["value"])

    def test_regression_subsets_are_binding_corners_only(self):
        _, psrr = screen.experiment("psrr-dc")
        _, startup = screen.experiment("startup-stability")
        self.assertEqual([c.id for c in psrr], ["sf_-40c_2.97v"])
        self.assertEqual({c.id for c in startup}, {"ss_125c_2.97v", "ff_125c_3.63v"})


if __name__ == "__main__":
    unittest.main()
