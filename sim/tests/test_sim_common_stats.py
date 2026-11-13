#!/usr/bin/env python3
"""Coverage for the shared summary statistics (`sim/bin/sim_common.py`).

`mean` and `stdev` are the one implementation behind `per_vector_stats`, so
every mismatch bench -- `error-amp-offset-mc`, `pnp-mismatch` and
`monte-carlo-untrimmed` -- reads its sigmas from here.

Properties pinned:

  * `stdev` is **exactly** 0.0 when every draw is equal, for every value and
    sample count. All three benches assert `sigma == 0.0` exactly on their
    MC-off control point, where the mismatch switch makes every draw
    bit-identical; a sigma of ~1e-16 there is float residue from deriving the
    spread through the mean, not mismatch, and it would fail a bench that has
    nothing wrong with it (PR #515: this is how it was found -- the residue
    appears on Python 3.11 and not on 3.12, whose builtin `sum` compensates).
  * `mean` and `stdev` do not depend on the builtin `sum`, so a recorded
    statistic is the same on every interpreter.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import sim_common  # noqa: E402

# Values the benches actually record: VOS, VOUT, dVBE, VEB, a resistor ratio,
# a supply, a temperature, zero, a negative, and a long mantissa. `1.21` and
# `1e-3` are the two that failed on CI in PR #515.
BENCH_VALUES = (
    1e-3, 1.21, 63e-3, 0.65, 0.5, 2.0, 1.0, 0.0, -1e-3,
    1.2345678901234e-2, 300.0, 27.0,
)

NAN = float("nan")


class StdevIsExactOnIdenticalDraws(unittest.TestCase):
    """The MC-off control-point invariant, across value and sample count."""

    def test_identical_draws_give_exactly_zero_sigma(self):
        offenders = []
        for value in BENCH_VALUES:
            for n in range(2, 401):
                sigma = sim_common.stdev([value] * n)
                if sigma != 0.0:
                    offenders.append((value, n, sigma))
        self.assertEqual(
            offenders[:8], [],
            f"{len(offenders)} (value, n) pairs gave a non-zero sigma for "
            f"identical draws; the benches' sigma_zero checks demand exactly 0",
        )

    def test_the_two_vectors_that_failed_ci_at_the_benchs_sample_count(self):
        # sigma_zero[vout] = 4.55626e-16 and sigma_zero[vos] = 4.44947e-19 on
        # Python 3.11 before the fix, with the 20 draws the batch test collects.
        self.assertEqual(sim_common.stdev([1.21] * 20), 0.0)
        self.assertEqual(sim_common.stdev([1e-3] * 20), 0.0)

    def test_a_single_draw_and_an_empty_spread_are_zero(self):
        self.assertEqual(sim_common.stdev([1.21]), 0.0)
        self.assertEqual(sim_common.stdev([]), 0.0)


class StdevStillMeasuresRealSpread(unittest.TestCase):
    """The exact-zero shortcut must not swallow a genuine distribution."""

    def test_known_sample_sigma(self):
        # n-1 sigma of 2,4,4,4,5,5,7,9 is sqrt(32/7).
        self.assertAlmostEqual(
            sim_common.stdev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]),
            math.sqrt(32.0 / 7.0), places=15,
        )

    def test_one_differing_draw_is_not_reported_as_zero(self):
        values = [1.21] * 20
        values[7] = math.nextafter(1.21, 2.0)  # a single ulp of real spread
        self.assertGreater(sim_common.stdev(values), 0.0)

    def test_mean_of_identical_draws_is_that_value(self):
        for value in BENCH_VALUES:
            for n in (2, 7, 20, 300):
                self.assertEqual(sim_common.mean([value] * n), value,
                                 f"mean of {n} x {value!r}")


class MeanStaysInsideTheRangeItIsReportedWith(unittest.TestCase):
    """`per_vector_stats` emits `mean` next to `min` and `max` in one block.

    `fsum(values) / n` is not exact for every (value, n) -- 7 draws of `1.21`
    gave 1.2099999999999997, *below* the `min` of the very same draws -- so a
    recorded stats block could contradict itself (PR #515).
    """

    def test_mean_is_within_min_and_max(self):
        offenders = []
        for value in BENCH_VALUES:
            for n in range(2, 401):
                values = [value] * n
                mu = sim_common.mean(values)
                if not (min(values) <= mu <= max(values)):
                    offenders.append((value, n, mu))
        self.assertEqual(offenders[:8], [],
                         f"{len(offenders)} (value, n) pairs put the mean "
                         f"outside [min, max] of the same draws")

    def test_per_vector_stats_block_is_self_consistent(self):
        samples = [{"vout": 1.21, "vos": 1e-3} for _ in range(7)]
        stats = sim_common.per_vector_stats(("vout", "vos"), samples)
        for name, st in stats.items():
            self.assertLessEqual(st["min"], st["mean"], name)
            self.assertLessEqual(st["mean"], st["max"], name)
            self.assertEqual(st["sigma"], 0.0, name)
        self.assertEqual(stats["vout"]["mean"], 1.21)

    def test_mean_of_no_values_still_raises(self):
        with self.assertRaises(ZeroDivisionError):
            sim_common.mean([])


class ANaNDrawCannotPassForIdenticalDraws(unittest.TestCase):
    """A NaN anywhere in the draws must still poison `mean` and `sigma`.

    The equal-values shortcut decides equality with `all(v == values[0] ...)`
    rather than `min(values) == max(values)`, because `min`/`max` skip a NaN
    that is not the first element: `[0.5, nan, nan]` would pass `min == max`
    and report `mean 0.5, sigma 0.0` for a sample set with no usable draws.

    This matters at exactly one place, and it is the place the shortcut exists
    for: the MC-off control point, where `evaluate()` asserts
    `stats[name]["sigma"] == 0.0` (`run_amp_offset_mc.py`). `rratio` is set to
    `float("nan")` by that runner whenever `rrb` is falsy and is not covered by
    the `vout` operating-window filter, so a NaN draw there has to keep failing
    the check loudly -- "something already wrong at the control point" is what
    the check is for (PR #515 review).
    """

    NAN_PATTERNS = (
        [0.5, NAN, NAN],      # NaN in the tail: min/max would skip both
        [0.5, NAN, 0.5],      # finite values all equal, NaN between them
        [NAN, 0.5, 0.5],      # NaN first
        [0.5, NAN, 0.6],      # NaN plus genuine spread
        [NAN] * 3,            # nothing but NaN
        [1.21] * 19 + [NAN],  # one bad draw at the bench's control point
    )

    def test_mean_of_any_list_containing_nan_is_nan(self):
        for values in self.NAN_PATTERNS:
            self.assertTrue(math.isnan(sim_common.mean(values)),
                            f"mean{values!r} must be NaN")

    def test_stdev_of_any_list_containing_nan_is_nan(self):
        for values in self.NAN_PATTERNS:
            self.assertTrue(math.isnan(sim_common.stdev(values)),
                            f"stdev{values!r} must be NaN")

    def test_a_nan_draw_fails_the_benches_sigma_zero_comparison(self):
        for values in self.NAN_PATTERNS:
            self.assertFalse(sim_common.stdev(values) == 0.0,
                             f"stdev{values!r} == 0.0 would pass sigma_zero")

    def test_per_vector_stats_reports_nan_for_a_nan_bearing_vector(self):
        # The runner's own `rratio = float("nan")` path, at a control point.
        samples = [{"rratio": 0.5}, {"rratio": NAN}, {"rratio": NAN}]
        stats = sim_common.per_vector_stats(("rratio",), samples)
        self.assertTrue(math.isnan(stats["rratio"]["mean"]))
        self.assertTrue(math.isnan(stats["rratio"]["sigma"]))
        self.assertFalse(stats["rratio"]["sigma"] == 0.0)


class StatisticsDoNotDependOnTheBuiltinSum(unittest.TestCase):
    """Recorded evidence must not change with the interpreter version.

    CPython 3.12 gave the builtin `sum` Neumaier compensation (gh-100425);
    `math.fsum` is correctly rounded on every version. A sum whose accuracy
    depends on the interpreter makes two runs of the same samples disagree.
    """

    def test_mean_matches_correctly_rounded_summation(self):
        # Ill-conditioned on purpose: naive accumulation loses the small terms.
        values = [1e16, 1.0, -1e16, 1.0, 1e16, 1.0, -1e16]
        self.assertEqual(
            sim_common.mean(values), math.fsum(values) / len(values),
        )

    def test_mean_recovers_terms_a_naive_accumulation_drops(self):
        values = [1e16, 1.0, -1e16]
        naive = 0.0
        for v in values:
            naive += v
        self.assertEqual(naive, 0.0)  # the 1.0 is lost
        self.assertEqual(sim_common.mean(values), 1.0 / 3.0)


if __name__ == "__main__":
    unittest.main()
