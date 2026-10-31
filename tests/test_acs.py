"""Tests for analysis.acs formulas (CV, top-code flag, MOE aggregation).

acs.py holds the CV formula every notebook in the suite depends on and had
zero test coverage before this file -- added in the 2026-07-31 audit pass.
load_level/load_geo (file I/O) are not unit-tested here; the notebooks'
row-count assertions cover them at the integration level.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from analysis.acs import (
    INCOME_TOP_CODE,
    Z_90,
    aggregate_estimate,
    aggregate_moe,
    cv,
    flag_topcoded_income,
    income_cv,
)


class CvTest(unittest.TestCase):
    def test_formula(self) -> None:
        # MOE 1645 at 90% confidence -> SE 1000; estimate 10000 -> CV 0.10.
        got = cv(pd.Series([10_000.0]), pd.Series([1_645.0]))
        self.assertAlmostEqual(got.iloc[0], 1_645.0 / Z_90 / 10_000.0)
        self.assertAlmostEqual(got.iloc[0], 0.1, places=6)

    def test_nan_at_zero_or_negative_estimate(self) -> None:
        got = cv(pd.Series([0.0, -5.0]), pd.Series([100.0, 100.0]))
        self.assertTrue(got.isna().all())

    def test_nan_when_moe_missing(self) -> None:
        got = cv(pd.Series([100.0]), pd.Series([np.nan]))
        self.assertTrue(got.isna().all())


class FlagTopcodedIncomeTest(unittest.TestCase):
    def test_flags_exact_top_code_only(self) -> None:
        df = pd.DataFrame({"B19013_001E": [INCOME_TOP_CODE, INCOME_TOP_CODE - 1, np.nan]})
        flag = flag_topcoded_income(df)
        self.assertEqual(list(flag), [True, False, False])


class IncomeCvTest(unittest.TestCase):
    def test_matches_cv_when_not_topcoded(self) -> None:
        df = pd.DataFrame({"B19013_001E": [80_000.0], "B19013_001M": [1_645.0]})
        got = income_cv(df)
        self.assertAlmostEqual(got.iloc[0], cv(df["B19013_001E"], df["B19013_001M"]).iloc[0])

    def test_nan_when_topcoded(self) -> None:
        df = pd.DataFrame({"B19013_001E": [INCOME_TOP_CODE], "B19013_001M": [500.0]})
        got = income_cv(df)
        self.assertTrue(got.isna().all())


class AggregateEstimateTest(unittest.TestCase):
    def test_sums_components(self) -> None:
        df = pd.DataFrame({"AE": [10.0], "BE": [20.0]})
        got = aggregate_estimate(df, ["A", "B"])
        self.assertEqual(got.iloc[0], 30.0)

    def test_nan_if_any_component_missing(self) -> None:
        df = pd.DataFrame({"AE": [10.0], "BE": [np.nan]})
        got = aggregate_estimate(df, ["A", "B"])
        self.assertTrue(got.isna().all())


class AggregateMoeTest(unittest.TestCase):
    def test_plain_rss_without_zero_rule(self) -> None:
        df = pd.DataFrame({"AE": [10.0], "AM": [3.0], "BE": [20.0], "BM": [4.0]})
        got = aggregate_moe(df, ["A", "B"], zero_rule=False)
        self.assertAlmostEqual(got.iloc[0], (3.0**2 + 4.0**2) ** 0.5)

    def test_zero_rule_keeps_only_largest_zero_cell_moe(self) -> None:
        # Two zero-estimate components (MOEs 5 and 9) plus one real component
        # (estimate 10, MOE 3): zero-rule keeps only the larger zero MOE (9).
        df = pd.DataFrame(
            {
                "AE": [0.0], "AM": [5.0],
                "BE": [0.0], "BM": [9.0],
                "CE": [10.0], "CM": [3.0],
            }
        )
        got_zero_rule = aggregate_moe(df, ["A", "B", "C"], zero_rule=True)
        got_plain = aggregate_moe(df, ["A", "B", "C"], zero_rule=False)
        self.assertAlmostEqual(got_zero_rule.iloc[0], (9.0**2 + 3.0**2) ** 0.5)
        self.assertAlmostEqual(got_plain.iloc[0], (5.0**2 + 9.0**2 + 3.0**2) ** 0.5)
        self.assertLess(got_zero_rule.iloc[0], got_plain.iloc[0])

    def test_nan_if_any_component_missing(self) -> None:
        df = pd.DataFrame({"AE": [10.0], "AM": [np.nan], "BE": [20.0], "BM": [4.0]})
        got = aggregate_moe(df, ["A", "B"])
        self.assertTrue(got.isna().all())


if __name__ == "__main__":
    unittest.main()
