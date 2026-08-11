#!/usr/bin/env python3
"""Unit coverage for `layout/bin/measure_mim_overlay_feasibility.py`.

The harness answers a question that decides a *spec* outcome — whether the
amp's compensation cap can be realized as a `cap_mim` overlay (holding the
ratified Area budget) or has to be drawn in-plane (forcing a budget
relaxation). Two of its three answers come straight from `klt`; the third,
"how much plate would a MiM MCC need", is arithmetic this file owns, and a
sign or term error in it would silently move the verdict.

The failure mode worth guarding is specific: dropping the perimeter term
would make every required-area figure *smaller*, i.e. bias the harness
toward reporting "feasible". So the tests below check the two-term law
against the area-only approximation explicitly, rather than just checking
that the function returns a plausible number.

`klayout` is imported lazily inside the harness's two geometry functions, so
this file runs on a plain interpreter with no layout venv and no PDK — same
convention as `test_met2_drc.py`'s import guard, reached differently.

    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))

import measure_mim_overlay_feasibility as mim  # noqa: E402


class TestSquarePlateSizing(unittest.TestCase):
    """`_square_plate_side_um()` inverts the deck's own two-term
    capacitance law, `C = area_cap*A + perim_cap*P`."""

    def _capacitance_of(self, side_um: float) -> float:
        return (
            mim.AREA_CAP_F_UM2 * side_um * side_um
            + mim.PERIM_CAP_F_UM * 4.0 * side_um
        )

    def test_the_solved_side_reproduces_the_target_capacitance(self) -> None:
        for target in (1e-12, mim.CC_MCC_MIN_F, mim.CC_MCC_MAX_F, 1e-10):
            side = mim._square_plate_side_um(target)
            self.assertAlmostEqual(
                self._capacitance_of(side) / target, 1.0, places=9,
                msg=f"round-trip failed at {target} F",
            )

    def test_the_perimeter_term_is_actually_carried(self) -> None:
        """Dropping it would understate the plate a MiM needs — an error
        that biases this harness toward reporting the overlay feasible."""
        target = mim.CC_MCC_MAX_F
        two_term = mim._square_plate_side_um(target)
        area_only = (target / mim.AREA_CAP_F_UM2) ** 0.5
        self.assertLess(
            two_term, area_only,
            "a plate sized with the fringe term must be smaller than one "
            "sized on area alone; got the reverse",
        )
        self.assertGreater(area_only - two_term, 0.05)

    def test_a_larger_target_needs_a_larger_plate(self) -> None:
        self.assertLess(
            mim._square_plate_side_um(mim.CC_MCC_MIN_F),
            mim._square_plate_side_um(mim.CC_MCC_MAX_F),
        )

    def test_the_sizing_target_is_the_measured_capacitance(self) -> None:
        """`design/error_amp.sch` states MCC's capacitance is measured, not
        computed from `Cox*W*L`; `sim/error-amp-loop/` measures 21.04–21.56
        pF across 45 corners. Guarding the constants keeps a future edit
        from quietly reverting to the ~29 pF analytic figure the operator
        ruling used, which would over-size a replacement by ~35%."""
        self.assertAlmostEqual(mim.CC_MCC_MIN_F, 21.0357e-12, places=15)
        self.assertAlmostEqual(mim.CC_MCC_MAX_F, 21.5618e-12, places=15)
        self.assertLess(mim.CC_MCC_MIN_F, mim.CC_MCC_MAX_F)


class TestDeckCoefficients(unittest.TestCase):
    """The coefficients and layer table are transcribed from
    `klayout_tools.decks.sky130.EXTRACTION_DECK`; they are checked here so a
    silent drift shows up as a test failure rather than as a quietly
    different answer in a record."""

    def test_the_capacitance_coefficients_match_the_curated_deck(self) -> None:
        self.assertEqual(mim.AREA_CAP_F_UM2, 2.0e-15)
        self.assertEqual(mim.PERIM_CAP_F_UM, 1.9e-16)

    def test_both_mim_stacks_are_covered_top_and_bottom(self) -> None:
        layers = {label: layer for label, layer, _ in mim.MIM_STACK_LAYERS}
        self.assertEqual(
            layers,
            {
                "70/20": (70, 20),   # met3.drawing  -- cap_mim bottom
                "89/44": (89, 44),   # capm.drawing  -- cap_mim top
                "71/20": (71, 20),   # met4.drawing  -- cap_mim_m4 bottom
                "97/44": (97, 44),   # capm2.drawing -- cap_mim_m4 top
            },
        )

    def test_every_layer_label_matches_its_own_layer_tuple(self) -> None:
        for label, (layer, datatype), _ in mim.MIM_STACK_LAYERS:
            self.assertEqual(label, f"{layer}/{datatype}")


class TestVerdict(unittest.TestCase):
    """`verdict()` is the branch selector between the operator ruling's two
    paths, so both of its inputs have to be able to veto on their own."""

    @staticmethod
    def _verdict(available: float, needed: float, connectable: bool):
        return mim.verdict(
            {"available_overlay_um2": available},
            {"variants": [{"plate_area_um2": needed}]},
            {"cap_terminals_reach_a_labelled_net": connectable},
        )

    def test_feasible_needs_both_area_and_connectivity(self) -> None:
        self.assertTrue(self._verdict(45968.0, 10742.0, True)["feasible"])

    def test_connectivity_alone_vetoes_it(self) -> None:
        v = self._verdict(45968.0, 10742.0, False)
        self.assertTrue(v["overlay_area_sufficient"])
        self.assertFalse(v["feasible"])

    def test_area_alone_vetoes_it(self) -> None:
        v = self._verdict(5000.0, 10742.0, True)
        self.assertTrue(v["mim_terminals_connectable"])
        self.assertFalse(v["feasible"])

    def test_the_worst_case_variant_sets_the_requirement(self) -> None:
        """Sizing to the smallest corner would under-build the replacement,
        so the requirement is the max across variants, not the first."""
        v = mim.verdict(
            {"available_overlay_um2": 11000.0},
            {"variants": [
                {"plate_area_um2": 10479.0},
                {"plate_area_um2": 10742.0},
            ]},
            {"cap_terminals_reach_a_labelled_net": True},
        )
        self.assertEqual(v["required_plate_area_um2"], 10742.0)

    def test_an_exactly_sufficient_area_counts_as_sufficient(self) -> None:
        self.assertTrue(
            self._verdict(10742.0, 10742.0, True)["overlay_area_sufficient"]
        )


if __name__ == "__main__":
    unittest.main()
