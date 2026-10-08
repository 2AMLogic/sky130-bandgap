#!/usr/bin/env python3
"""Unit coverage for `sim/monte-carlo-untrimmed/qualify_dr005.py` (issue #334)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "sim" / "monte-carlo-untrimmed"
sys.path.insert(0, str(HARNESS_DIR))
import qualify_dr005 as q  # noqa: E402

LO, HI = q.WINDOW_V


def draws(mean: float, half: float, n: int) -> list[float]:
    """n values symmetric about mean with sample sigma close to half/3-ish; exact list used verbatim."""
    step = 2 * half / (n - 1)
    return [mean - half + i * step for i in range(n)]


def temps(sets: dict[float, list[float]], req: int = 300) -> list[dict]:
    return [{"temperature_c": t, "requested_n": req, "samples": s} for t, s in sets.items()]


class GradeTests(unittest.TestCase):
    def test_yield_above_floor_but_three_sigma_outside_fails(self) -> None:
        # 70 % tightly inside, 30 % just outside: yield >50 %, sigma large
        s = [1.20] * 210 + [1.24] * 45 + [1.16] * 45
        r = q.grade_temperature(27.0, 300, s)
        self.assertGreater(r["yield_empirical"], 0.5)
        self.assertEqual(r["harness_sanity"], "PASS")
        self.assertFalse(r["three_sigma_inside_window"])
        self.assertEqual(r["spec"], "FAIL")

    def test_shifted_mean_fails_even_with_small_sigma(self) -> None:
        s = [1.2215 + 0.0001 * ((i % 5) - 2) for i in range(300)]
        # sigma ~ 0.14 mV -> 3 sigma ~ 0.4 mV, but mean 1.2215 + ... upper ~1.2219 passes; shift further
        s = [v + 0.0035 for v in s]
        r = q.grade_temperature(27.0, 300, s)
        self.assertEqual(r["spec"], "FAIL")
        self.assertLess(r["margin_upper_mv"], 0)

    def test_tight_centered_sufficient_n_passes_at_temperature_level(self) -> None:
        s = [1.2 + 0.001 * ((i % 7) - 3) for i in range(300)]
        r = q.grade_temperature(27.0, 300, s)
        self.assertEqual(r["spec"], "PASS")
        self.assertEqual(r["yield_empirical"], 1.0)
        self.assertEqual(r["yield_ci95"][1], 1.0)

    def test_exact_boundary_passes_and_epsilon_beyond_fails(self) -> None:
        import statistics
        base = [-1.0, 1.0] * 150  # mean 0, sample sigma s0
        s0 = statistics.stdev(base)
        # scale so that mean + 3 sigma == HI exactly (to floating point): use mean=1.2, half=0.024
        scale = 0.024 / (3 * s0)
        edge = [1.2 + v * scale for v in base]
        r = q.grade_temperature(27.0, 300, edge, window=(1.2 - 0.0240001, 1.2 + 0.0240001))
        self.assertEqual(r["spec"], "PASS")
        r = q.grade_temperature(27.0, 300, edge, window=(1.2 - 0.0239, 1.2 + 0.0239))
        self.assertEqual(r["spec"], "FAIL")
        # inclusive comparison itself
        r = q.grade_temperature(27.0, 300, [1.2] * 300, window=(1.2, 1.2))
        self.assertEqual(r["spec"], "PASS")
        self.assertEqual(r["in_window_n"], 300)

    def test_sanity_floor_boundary_is_inclusive(self) -> None:
        s = [1.2] * 150 + [1.3] * 150
        self.assertEqual(q.grade_temperature(27.0, 300, s)["harness_sanity"], "PASS")
        s = [1.2] * 149 + [1.3] * 151
        self.assertEqual(q.grade_temperature(27.0, 300, s)["harness_sanity"], "FAIL")

    def test_too_few_converged_samples_cannot_pass_but_can_fail(self) -> None:
        tight = [1.2 + 0.0005 * ((i % 5) - 2) for i in range(299)]
        r = q.grade_temperature(27.0, 300, tight)
        self.assertEqual(r["spec"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(r["n_sufficient"])
        wide = [1.2, 1.25] * 100
        self.assertEqual(q.grade_temperature(27.0, 300, wide)["spec"], "FAIL")

    def test_degenerate_samples_are_insufficient(self) -> None:
        for s in (None, [], [1.2]):
            self.assertEqual(q.grade_temperature(27.0, 300, s)["spec"], "INSUFFICIENT_EVIDENCE")

    def test_clopper_pearson_known_values(self) -> None:
        lo, hi = q.clopper_pearson(189, 238)  # matches committed klt envelope
        self.assertAlmostEqual(lo, 0.7371161, places=5)
        self.assertAlmostEqual(hi, 0.8436333, places=5)
        self.assertEqual(q.clopper_pearson(0, 10)[0], 0.0)
        self.assertEqual(q.clopper_pearson(10, 10)[1], 1.0)


class ComposeTests(unittest.TestCase):
    good = [1.2 + 0.001 * ((i % 7) - 3) for i in range(300)]

    def test_all_good_still_not_pass_without_joint_coverage(self) -> None:
        rec = q.qualify(temps({-40.0: self.good, 27.0: self.good, 125.0: self.good}))
        self.assertEqual(rec["verdicts"]["spec"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rec["verdicts"]["harness_sanity"], "PASS")
        rec = q.qualify(temps({-40.0: self.good, 27.0: self.good, 125.0: self.good}),
                        joint_process_mismatch_available=True)
        self.assertEqual(rec["verdicts"]["spec"], "PASS")

    def test_missing_temperature_is_insufficient_not_pass(self) -> None:
        rec = q.qualify(temps({27.0: self.good, 125.0: self.good}), joint_process_mismatch_available=True)
        self.assertEqual(rec["verdicts"]["spec"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rec["verdicts"]["evidence_existence"], "INCOMPLETE")

    def test_fail_dominates_insufficient(self) -> None:
        rec = q.qualify(temps({27.0: [1.2, 1.25] * 150, 125.0: self.good[:10]}))
        self.assertEqual(rec["verdicts"]["spec"], "FAIL")

    def test_sanity_pass_and_spec_fail_are_distinct_fields(self) -> None:
        s = [1.20] * 210 + [1.24] * 45 + [1.16] * 45
        rec = q.qualify(temps({-40.0: s, 27.0: s, 125.0: s}), joint_process_mismatch_available=True)
        self.assertEqual(rec["verdicts"]["harness_sanity"], "PASS")
        self.assertEqual(rec["verdicts"]["spec"], "FAIL")


class CommittedRecordTests(unittest.TestCase):
    RID = "20260817-121131-d7d85b6"
    REC = HARNESS_DIR / "records" / f"{RID}-{q.SUFFIX}.json"

    def test_recompute_matches_committed_klt_envelope_and_record(self) -> None:
        per_temp, _ = q.collect(self.RID)
        env = json.loads((HARNESS_DIR / "records" / "20260923-062524-1e38c62-klt-yield.json").read_text())
        res = q.qualify(per_temp)
        for row, m in zip(res["temperatures"], env["measurements"]):
            self.assertEqual(row["converged_n"], m["n"])
            self.assertAlmostEqual(row["mean_v"], m["distribution"]["mean"], places=9)
            self.assertAlmostEqual(row["sigma_v"], m["distribution"]["stddev"], places=9)
            emp = m["yield"]["empirical"]
            self.assertAlmostEqual(row["yield_empirical"], emp["estimate"], places=9)
            self.assertAlmostEqual(row["yield_ci95"][0], emp["confidence_interval"]["low"], places=5)
            self.assertAlmostEqual(row["yield_ci95"][1], emp["confidence_interval"]["high"], places=5)
        self.assertEqual(res["verdicts"]["harness_sanity"], "PASS")
        self.assertEqual(res["verdicts"]["spec"], "FAIL")
        committed = json.loads(self.REC.read_text())["qualification"]
        self.assertEqual(committed, json.loads(json.dumps(res)))

    def test_mint_refuses_to_overwrite(self) -> None:
        with self.assertRaises(SystemExit):
            q.mint(self.RID)


if __name__ == "__main__":
    unittest.main()
