#!/usr/bin/env python3
"""Unit coverage for `sim_common.py::csv_list()`/`csv_floats()` (issue #313).

Both `corner-run.py`'s `--process`/`--temp`/`--supply` and the post-layout
benches' `parse_post_layout_args()` route their `type=` callbacks through
these two functions after #313 deduplicated a byte-for-byte private copy
that `post_layout_common.py` had carried (`_csv_list`/`_csv_floats`). No
existing test covered either function before this file -- this closes that
gap and guards against a future regression reintroducing a drifted private
copy in one caller or the other.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SIM_DIR / "bin"))

import sim_common  # noqa: E402


class CsvListTests(unittest.TestCase):
    def test_trims_whitespace_around_each_token(self) -> None:
        self.assertEqual(sim_common.csv_list(" tt , ss ,ff"), ["tt", "ss", "ff"])

    def test_filters_empty_tokens_from_trailing_or_repeated_commas(self) -> None:
        self.assertEqual(sim_common.csv_list("tt,,ss,"), ["tt", "ss"])

    def test_empty_string_yields_empty_list(self) -> None:
        self.assertEqual(sim_common.csv_list(""), [])

    def test_whitespace_only_string_yields_empty_list(self) -> None:
        self.assertEqual(sim_common.csv_list("   "), [])

    def test_single_token_no_commas(self) -> None:
        self.assertEqual(sim_common.csv_list("tt"), ["tt"])


class CsvFloatsTests(unittest.TestCase):
    def test_casts_each_token_to_float(self) -> None:
        self.assertEqual(sim_common.csv_floats("-40,27,125"), [-40.0, 27.0, 125.0])

    def test_trims_and_filters_like_csv_list_before_casting(self) -> None:
        self.assertEqual(sim_common.csv_floats(" 2.97 , 3.3 ,,3.63"), [2.97, 3.3, 3.63])

    def test_empty_string_yields_empty_list(self) -> None:
        self.assertEqual(sim_common.csv_floats(""), [])

    def test_non_numeric_token_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            sim_common.csv_floats("tt,27")


if __name__ == "__main__":
    unittest.main()
