"""Tests for analysis.decennial loaders and the Black-65+ aggregate.

Needs data/raw/dhc_2020_nj_*.parquet and dp1_2020_nj_*.parquet on disk
(python ingestion/pull_dhc_nj.py, pull_dp_nj.py) -- skipped if absent, same
convention as the rest of the suite has for data-dependent checks.
"""

from __future__ import annotations

import unittest

import pandas as pd

from analysis.decennial import BLACK_65PLUS_CELLS_DHC, DP1_LEVELS, black_65plus, load_dhc, load_dp1


class BlackSixtyFivePlusTest(unittest.TestCase):
    def test_sums_the_twelve_cells_exactly(self) -> None:
        df = pd.DataFrame({c: [1] for c in BLACK_65PLUS_CELLS_DHC})
        got = black_65plus(df)
        self.assertEqual(got.iloc[0], 12)


class LoadersTest(unittest.TestCase):
    def test_bad_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_dhc("neighborhood")
        with self.assertRaises(ValueError):
            load_dp1("block")

    def test_dhc_tract_row_count(self) -> None:
        try:
            df = load_dhc("tract")
        except FileNotFoundError:
            self.skipTest("data/raw/dhc_2020_nj_tract.parquet not present")
        self.assertEqual(len(df), 2_181)

    def test_dp1_has_no_block_group_level(self) -> None:
        self.assertNotIn("block_group", DP1_LEVELS)


if __name__ == "__main__":
    unittest.main()
