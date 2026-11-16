#!/usr/bin/env python3
"""Unit test: grid solver and series sum on synthetic rectangles (no klayout, no ngspice).

Run: uvx --with numpy --with scipy python -I sim/pex-native/test_geometry_resistance.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geometry_resistance as g  # noqa: E402


class GridSquares(unittest.TestCase):
    def test_single_rectangle_is_length_over_width(self):
        # 10 um x 1 um strip, ports are the end faces -> 10 squares
        r = [(0, 0, 10000, 1000)]
        sq = g.grid_squares(r, [(0, 0, 40, 1000)], [(9960, 0, 10000, 1000)], 20)
        self.assertAlmostEqual(sq, 10.0 * (9920 / 10000) + 0, delta=0.15)  # ports are 40 nm slabs

    def test_two_rectangles_in_series_add(self):
        # 10x1 um then 5x0.5 um abutting: 10 sq + 10 sq = 20 sq (end slabs shave ~0.05 sq)
        r = [(0, 0, 10000, 1000), (10000, 250, 15000, 750)]
        sq = g.grid_squares(r, [(0, 0, 40, 1000)], [(14960, 250, 15000, 750)], 20)
        parts = [g.grid_squares([r[0]], [(0, 0, 40, 1000)], [(9960, 0, 10000, 1000)], 20),
                 g.grid_squares([r[1]], [(10000, 250, 10040, 750)], [(14960, 250, 15000, 750)], 20)]
        self.assertAlmostEqual(g.series_squares(parts), 20.0, delta=0.3)
        self.assertAlmostEqual(sq, 20.0, delta=0.6)  # + spreading at the width step

    def test_bad_port_raises(self):
        with self.assertRaises(ValueError):
            g.grid_squares([(0, 0, 1000, 1000)], [(0, 0, 40, 1000)], [(5000, 0, 5040, 1000)], 20)


if __name__ == "__main__":
    unittest.main()
