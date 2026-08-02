"""Tests for analysis.dashboard: band membership, ranges, and tiers.

Loading/data-pull tests are skipped if data/raw/*trenton* isn't present
(same convention as test_decennial.py) -- the formula tests below don't
need the data on disk.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from analysis.dashboard import (
    BANDS,
    RAW_DIR,
    TIER_CARE,
    TIER_RISKY,
    TIER_SOLID,
    _POVERTY_ABOVE_CELLS,
    _POVERTY_CELLS,
    _SEXAGE_CELLS,
    acs_poverty,
    acs_poverty_universe,
    acs_range,
    acs_sexage,
    cv_from_range,
    load_acs,
    poverty_rate,
    tier,
)


class BandCoverageTest(unittest.TestCase):
    def test_sexage_bands_are_disjoint_and_complete(self) -> None:
        # Male cells 003-025 (23 cells) must be covered exactly once by the
        # four bands -- same check for female 027-049.
        male_all = sorted(int(n) for band in _SEXAGE_CELLS.values() for n in band["male"])
        self.assertEqual(male_all, list(range(3, 26)))
        female_all = sorted(int(n) for band in _SEXAGE_CELLS.values() for n in band["female"])
        self.assertEqual(female_all, list(range(27, 50)))

    def test_bad_band_raises(self) -> None:
        df = pd.DataFrame({"B01001_003E": [1.0], "B01001_003M": [1.0]})
        with self.assertRaises(ValueError):
            acs_sexage(df, "not a band", "both")

    def test_bad_sex_raises(self) -> None:
        df = pd.DataFrame({"B01001_003E": [1.0], "B01001_003M": [1.0]})
        with self.assertRaises(ValueError):
            acs_sexage(df, "Under 5", "not a sex")

    def test_poverty_below_and_above_cells_are_disjoint_and_mirror_each_other(self) -> None:
        # _POVERTY_ABOVE_CELLS must be exactly _POVERTY_CELLS shifted +29,
        # per band/sex -- that's what makes summing them the true universe.
        for band in BANDS:
            for sex in ("male", "female"):
                below = sorted(int(n) for n in _POVERTY_CELLS[band][sex])
                above = sorted(int(n) for n in _POVERTY_ABOVE_CELLS[band][sex])
                self.assertEqual([n + 29 for n in below], above)


class AcsRangeTest(unittest.TestCase):
    def test_range_is_est_pm_moe(self) -> None:
        self.assertEqual(acs_range(1000.0, 200.0), (800.0, 1200.0))

    def test_band_sums_agree_with_helper(self) -> None:
        # Fabricate a two-cell band so the sum is checkable by hand.
        df = pd.DataFrame({
            "B01001_003E": [10.0], "B01001_003M": [3.0],
            "B01001_027E": [20.0], "B01001_027M": [4.0],
        })
        est, moe = acs_sexage(df, "Under 5", "both")
        self.assertEqual(est.iloc[0], 30.0)
        self.assertAlmostEqual(moe.iloc[0], (3.0**2 + 4.0**2) ** 0.5)


class PovertyRateTest(unittest.TestCase):
    def test_matches_hand_computed_ratio(self) -> None:
        # 100 of 1000 below poverty -> exactly 10%.
        rate, moe = poverty_rate(100.0, 20.0, 1000.0, 50.0)
        self.assertAlmostEqual(rate, 10.0)
        self.assertGreater(moe, 0.0)

    def test_negative_sqrt_term_falls_back_to_addition(self) -> None:
        # below_moe implausibly large relative to universe_moe forces the
        # subtract form negative -- the handbook fallback (add instead of
        # subtract) must still return a finite, positive MOE.
        rate, moe = poverty_rate(100.0, 500.0, 1000.0, 50.0)
        self.assertFalse(np.isnan(moe))
        self.assertGreater(moe, 0.0)

    def test_zero_universe_is_nan_not_a_crash(self) -> None:
        rate, moe = poverty_rate(0.0, 10.0, 0.0, 10.0)
        self.assertTrue(np.isnan(rate) and np.isnan(moe))

    def test_universe_is_below_plus_above(self) -> None:
        df = pd.DataFrame({
            "B17001_004E": [10.0], "B17001_004M": [3.0],  # below, male, Under 5
            "B17001_018E": [8.0], "B17001_018M": [2.0],   # below, female, Under 5
            "B17001_033E": [40.0], "B17001_033M": [5.0],  # at/above, male, Under 5
            "B17001_047E": [42.0], "B17001_047M": [6.0],  # at/above, female, Under 5
        })
        below_est, _ = acs_poverty(df, "Under 5", "both")
        univ_est, _ = acs_poverty_universe(df, "Under 5", "both")
        self.assertEqual(float(below_est.iloc[0]), 18.0)
        self.assertEqual(float(univ_est.iloc[0]), 100.0)


class TierTest(unittest.TestCase):
    def test_boundaries(self) -> None:
        self.assertEqual(tier(0.11)[0], TIER_SOLID)
        self.assertEqual(tier(0.12)[0], TIER_SOLID)
        self.assertEqual(tier(0.13)[0], TIER_CARE)
        self.assertEqual(tier(0.30)[0], TIER_CARE)
        self.assertEqual(tier(0.31)[0], TIER_RISKY)

    def test_nan_is_too_risky(self) -> None:
        self.assertEqual(tier(float("nan"))[0], TIER_RISKY)

    def test_cv_from_range_matches_moe_formula(self) -> None:
        # A 1000 +/- 200 range implies the same CV as the direct MOE formula.
        cv = cv_from_range(1000.0, 800.0, 1200.0)
        from analysis.acs import Z_90
        self.assertAlmostEqual(cv, 200.0 / Z_90 / 1000.0)


@unittest.skipUnless((RAW_DIR / "acs5_2024_trenton_place.parquet").exists(), "trenton data not pulled")
class RealDataTest(unittest.TestCase):
    def test_band_sum_matches_published_total(self) -> None:
        place = load_acs("place")
        total = sum(float(acs_sexage(place, b, "both")[0].iloc[0]) for b in BANDS)
        self.assertAlmostEqual(total, float(place["B01001_001E"].iloc[0]), delta=1.0)

    def test_citywide_poverty_rate_is_plausible(self) -> None:
        # Trenton is a higher-poverty city; a sane rate is well within
        # [5%, 60%] for every band -- catches a wiring mistake (e.g. wrong
        # denominator) without hardcoding the exact figure to a data pull.
        place = load_acs("place")
        for band in BANDS:
            below_est, below_moe = acs_poverty(place, band, "both")
            univ_est, univ_moe = acs_poverty_universe(place, band, "both")
            rate, moe = poverty_rate(
                float(below_est.iloc[0]), float(below_moe.iloc[0]),
                float(univ_est.iloc[0]), float(univ_moe.iloc[0]),
            )
            self.assertTrue(5.0 <= rate <= 60.0, f"{band}: rate {rate} implausible")
            self.assertGreater(moe, 0.0)

    def test_tract1_under5_male_is_too_risky(self) -> None:
        # The concrete example this whole prototype is built around.
        tract = load_acs("tract")
        row = tract[tract["TRACT"] == "000100"]
        est, moe = acs_sexage(row, "Under 5", "male")
        self.assertEqual(float(est.iloc[0]), 462.0)
        self.assertEqual(float(moe.iloc[0]), 307.0)
        lo, hi = acs_range(float(est.iloc[0]), float(moe.iloc[0]))
        self.assertEqual(tier(cv_from_range(float(est.iloc[0]), lo, hi))[0], TIER_RISKY)


if __name__ == "__main__":
    unittest.main()
