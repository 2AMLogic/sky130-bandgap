#!/usr/bin/env python3
"""Unit coverage for `layout/bin/met2_drc.py` (issue #62).

This checker is what closes the last gap between the met2 escape plane and
unchecked geometry: the curated `klt` sky130 deck declares met2 as a
connectivity level (2AMLogic/klayout-tools#508, merged via #511) and now
checks most of its DRC rules too (2AMLogic/klayout-tools#513, merged via
#515: `met2.width.1`, `met2.space.1`, `via.width.1`, `via.space.1`,
`met1.enclosing.via.1`, `met2.enclosing.via.1`) -- but not the met2 min-area
rule (`m2.6`), which #515 deliberately left out (the curated deck's rule
vocabulary has no `area` check primitive). A checker that silently passed
everything, on `m2.6` or on the rules the curated deck already covers, would
look exactly like a clean layout -- which is the false-evidence failure mode
this repo's "verification is the product" rule exists to prevent.

So every rule here is exercised in **both** directions: a compliant shape must
not be reported, and a deliberately non-compliant one must be. The
all-passes-everything failure is not hypothetical -- the first cut of the
`m2.6` area rule had it. `Region.with_area(min, max)` silently resolved to
KLayout's *other* two-argument overload, `with_area(area, inverse)`, so
`with_area(0, threshold)` read as "area exactly 0, inverted" and returned
every polygon; the real layout came back with four area violations it did not
have, and a genuinely-too-small shape would have been indistinguishable.

Skipped (not failed) when `klayout` is not importable, so the suite still runs
on an interpreter without the layout venv. `layout/bin/setup-venv.sh` provides
it; `npm run test:unit` under that venv exercises these.

    python3 -m unittest discover --start-directory layout/tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))

import met2_drc  # noqa: E402  -- resolved from layout/bin, above

try:  # pragma: no cover -- import guard
    import klayout.db as db

    HAVE_KLAYOUT = True
except ImportError:  # pragma: no cover
    db = None
    HAVE_KLAYOUT = False


DBU = 0.005


@unittest.skipUnless(HAVE_KLAYOUT, "klayout not importable (needs layout/.venv)")
class Met2DrcCase(unittest.TestCase):
    """Base: build a one-cell GDS from micron rectangles and check it."""

    def _check(self, shapes: dict[tuple[int, int], list[tuple[float, ...]]]):
        layout = db.Layout()
        layout.dbu = DBU
        cell = layout.create_cell("t")
        for layer, boxes in shapes.items():
            index = layout.layer(layer[0], layer[1])
            for x0, y0, x1, y1 in boxes:
                cell.shapes(index).insert(
                    db.Box(
                        int(round(x0 / DBU)),
                        int(round(y0 / DBU)),
                        int(round(x1 / DBU)),
                        int(round(y1 / DBU)),
                    )
                )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.gds"
            layout.write(str(path))
            return met2_drc.check(path, "t")

    def _rules(self, report) -> set:
        return {v["rule"] for v in report["violations"]}

    @staticmethod
    def _via_stack(x: float, y: float) -> dict:
        """One compliant via1 stack: 0.15 cut inside 0.32 met1 and met2 pads."""
        cut = met2_drc.VIA_SIDE_UM / 2.0
        pad = 0.32 / 2.0
        return {
            met2_drc.MET1: [(x - pad, y - pad, x + pad, y + pad)],
            met2_drc.VIA1: [(x - cut, y - cut, x + cut, y + cut)],
            met2_drc.MET2: [(x - pad, y - pad, x + pad, y + pad)],
        }


class TestCleanGeometryPasses(Met2DrcCase):
    def test_an_empty_layout_is_clean(self) -> None:
        report = self._check({})
        self.assertEqual(report["status"], "clean")
        self.assertEqual(report["violation_count"], 0)

    def test_a_compliant_via_stack_and_wire_is_clean(self) -> None:
        """The exact geometry `met1_bus.via1()`/`hseg2()` draw. If this ever
        starts reporting, the checker and the drawer have diverged."""
        shapes = self._via_stack(0.0, 0.0)
        shapes[met2_drc.MET2].append((0.0, -0.16, 10.0, 0.16))
        shapes[met2_drc.MET1].append((9.84, -0.16, 10.16, 0.16))
        report = self._check(shapes)
        self.assertEqual(report["violations"], [])
        self.assertEqual(report["counts"]["via1_cuts"], 1)


class TestEachRuleFiresOnItsOwnViolation(Met2DrcCase):
    def test_m2_1_min_width(self) -> None:
        report = self._check({met2_drc.MET2: [(0.0, 0.0, 5.0, 0.10)]})
        self.assertIn("m2.1", self._rules(report))

    def test_m2_2_min_spacing(self) -> None:
        report = self._check({
            met2_drc.MET2: [
                (0.0, 0.0, 5.0, 0.32),
                (0.0, 0.42, 5.0, 0.74),  # 0.10 um gap, under m2.2's 0.14
            ]
        })
        self.assertIn("m2.2", self._rules(report))

    def test_m2_2_passes_at_exactly_the_threshold(self) -> None:
        """The boundary matters: a checker that rejects a legal 0.14 um gap
        would push this flow's router into detours it does not need."""
        report = self._check({
            met2_drc.MET2: [
                (0.0, 0.0, 5.0, 0.32),
                (0.0, 0.46, 5.0, 0.78),  # exactly 0.14
            ]
        })
        self.assertNotIn("m2.2", self._rules(report))

    def test_m2_6_min_area(self) -> None:
        """The rule whose first cut passed everything -- see module docstring.
        0.2 x 0.2 = 0.04 um^2, under the 0.0676 um^2 threshold, but wide
        enough that `m2.1` does NOT fire, so only the area rule can catch it."""
        report = self._check({met2_drc.MET2: [(0.0, 0.0, 0.2, 0.2)]})
        self.assertIn("m2.6", self._rules(report))
        self.assertNotIn("m2.1", self._rules(report))

    def test_m2_6_does_not_fire_on_a_compliant_landing_pad(self) -> None:
        """The counterfactual for the same rule: a 0.32 um pad is 0.1024
        um^2, comfortably over. This is the assertion that would have caught
        the overload bug on its own."""
        report = self._check({met2_drc.MET2: [(0.0, 0.0, 0.32, 0.32)]})
        self.assertNotIn("m2.6", self._rules(report))

    def test_via_1a_wrong_cut_size(self) -> None:
        shapes = self._via_stack(0.0, 0.0)
        shapes[met2_drc.VIA1] = [(-0.10, -0.10, 0.10, 0.10)]  # 0.20, not 0.15
        report = self._check(shapes)
        self.assertIn("via.1a", self._rules(report))

    def test_via_2_min_cut_spacing(self) -> None:
        shapes = self._via_stack(0.0, 0.0)
        cut = met2_drc.VIA_SIDE_UM / 2.0
        shapes[met2_drc.VIA1].append((0.25 - cut, -cut, 0.25 + cut, cut))
        shapes[met2_drc.MET1].append((-0.16, -0.16, 0.41, 0.16))
        shapes[met2_drc.MET2].append((-0.16, -0.16, 0.41, 0.16))
        report = self._check(shapes)
        self.assertIn("via.2", self._rules(report))

    def test_met1_enclosure_of_via(self) -> None:
        shapes = self._via_stack(0.0, 0.0)
        shapes[met2_drc.MET1] = [(-0.09, -0.09, 0.09, 0.09)]  # 0.015 enclosure
        report = self._check(shapes)
        self.assertIn("via.4a/via.5a", self._rules(report))

    def test_met2_enclosure_of_via(self) -> None:
        shapes = self._via_stack(0.0, 0.0)
        shapes[met2_drc.MET2] = [(-0.09, -0.09, 0.09, 0.09)]
        report = self._check(shapes)
        self.assertIn("m2.4/m2.5", self._rules(report))

    def test_a_via_with_no_met1_under_it_is_reported(self) -> None:
        """Not a spacing rule but a hard connectivity error, and nothing else
        in the flow would report it -- `klt extract` would just produce one
        fewer connection and the node would silently be in two pieces."""
        shapes = self._via_stack(0.0, 0.0)
        del shapes[met2_drc.MET1]
        report = self._check(shapes)
        self.assertIn("via.4a_a", self._rules(report))

    def test_a_via_with_no_met2_over_it_is_reported(self) -> None:
        shapes = self._via_stack(0.0, 0.0)
        del shapes[met2_drc.MET2]
        report = self._check(shapes)
        self.assertIn("m2.4_a", self._rules(report))


@unittest.skipUnless(HAVE_KLAYOUT, "klayout not importable (needs layout/.venv)")
class TestThresholdsMatchTheDrawer(unittest.TestCase):
    """The checker and `met1_bus.py` must agree about sky130's numbers, or the
    flow draws to one budget and proves another."""

    def test_layers_match_met1_bus(self) -> None:
        import met1_bus

        self.assertEqual(list(met2_drc.MET1), met1_bus.MET1_LAYER)
        self.assertEqual(list(met2_drc.VIA1), met1_bus.VIA1_LAYER)
        self.assertEqual(list(met2_drc.MET2), met1_bus.MET2_LAYER)

    def test_via_size_and_spacing_match_met1_bus(self) -> None:
        import met1_bus

        self.assertEqual(met2_drc.VIA_SIDE_UM, met1_bus.VIA1_UM)
        self.assertEqual(met2_drc.VIA_SPACE_UM, met1_bus.VIA1_SPACE_UM)
        self.assertEqual(met2_drc.M2_SPACE_UM, met1_bus.MET2_SPACE_UM)

    def test_the_drawn_pads_clear_the_enclosure_rules_by_construction(
        self,
    ) -> None:
        import met1_bus

        for pad in (met1_bus.MET1_VIA1_LANDING_UM, met1_bus.MET2_LANDING_UM):
            self.assertGreaterEqual(
                (pad - met1_bus.VIA1_UM) / 2.0, met2_drc.MET1_ENC_VIA_UM
            )

    def test_the_drawn_met2_wire_clears_width_and_area_by_construction(
        self,
    ) -> None:
        import met1_bus

        self.assertGreaterEqual(met1_bus.MET2_WIRE_WIDTH_UM, met2_drc.M2_WIDTH_UM)
        self.assertGreaterEqual(
            met1_bus.MET2_LANDING_UM ** 2, met2_drc.M2_AREA_UM2
        )


if __name__ == "__main__":
    unittest.main()
