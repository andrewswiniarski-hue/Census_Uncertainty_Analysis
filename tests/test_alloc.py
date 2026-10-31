"""Tests for analysis.alloc rate derivation (EDA 05 formulas preserved)."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from analysis.alloc import PROXY_RATES, derive_rates, safe_div


class SafeDivTest(unittest.TestCase):
    def test_divides_when_denominator_positive(self) -> None:
        num = pd.Series([2.0, 5.0])
        den = pd.Series([4.0, 10.0])
        pd.testing.assert_series_equal(safe_div(num, den), pd.Series([0.5, 0.5]))

    def test_nan_when_denominator_zero_or_missing(self) -> None:
        num = pd.Series([1.0, 2.0, 3.0])
        den = pd.Series([0.0, np.nan, -1.0])
        out = safe_div(num, den)
        self.assertTrue(out.isna().all())


class DeriveRatesTest(unittest.TestCase):
    def _base_row(self, **overrides: float) -> dict[str, float]:
        row = {
            "B99011_001E": 100.0,
            "B99011_002E": 5.0,
            "B99012_001E": 100.0,
            "B99012_002E": 10.0,
            "B99021_001E": 100.0,
            "B99021_002E": 20.0,
            "B99192_001E": 50.0,
            "B99192_002E": 20.0,  # no income allocated
            "B99172_001E": 40.0,
            "B99172_002E": 10.0,
            "B99172_009E": 6.0,
            "B98031_001E": 12.5,
        }
        row.update(overrides)
        return row

    def test_demographic_and_income_formulas(self) -> None:
        df = pd.DataFrame([self._base_row()])
        out = derive_rates(df)
        self.assertAlmostEqual(out.loc[0, "sex_alloc"], 0.05)
        self.assertAlmostEqual(out.loc[0, "age_alloc"], 0.10)
        self.assertAlmostEqual(out.loc[0, "race_alloc"], 0.20)
        self.assertAlmostEqual(out.loc[0, "demo_mean_alloc"], (0.05 + 0.10 + 0.20) / 3)
        # income_alloc = 1 - (20/50) = 0.60
        self.assertAlmostEqual(out.loc[0, "income_alloc"], 0.60)
        # fam_pov_alloc = 1 - ((10+6)/40) = 0.60
        self.assertAlmostEqual(out.loc[0, "fam_pov_alloc"], 0.60)
        self.assertAlmostEqual(out.loc[0, "overall_alloc"], 0.125)

    def test_zero_denominator_yields_nan_rates(self) -> None:
        df = pd.DataFrame(
            [
                self._base_row(
                    B99011_001E=0.0,
                    B99192_001E=0.0,
                    B99172_001E=0.0,
                )
            ]
        )
        out = derive_rates(df)
        self.assertTrue(np.isnan(out.loc[0, "sex_alloc"]))
        self.assertTrue(np.isnan(out.loc[0, "income_alloc"]))
        self.assertTrue(np.isnan(out.loc[0, "fam_pov_alloc"]))

    def test_county_only_overall_stays_nan_when_missing(self) -> None:
        df = pd.DataFrame([self._base_row(B98031_001E=np.nan)])
        out = derive_rates(df)
        self.assertTrue(np.isnan(out.loc[0, "overall_alloc"]))
        # Item rates still compute.
        self.assertAlmostEqual(out.loc[0, "income_alloc"], 0.60)

    def test_does_not_mutate_input(self) -> None:
        df = pd.DataFrame([self._base_row()])
        before = df.copy()
        _ = derive_rates(df)
        pd.testing.assert_frame_equal(df, before)

    def test_fam_pov_marked_as_proxy(self) -> None:
        self.assertIn("fam_pov_alloc", PROXY_RATES)


if __name__ == "__main__":
    unittest.main()
