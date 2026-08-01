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
    _SEXAGE_CELLS,
    acs_poverty,
    acs_range,
    acs_sexage,
    cv_from_range,
    dhc_population_range,
    dhc_subgroup_range,
    load_acs,
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


class DhcRangeTest(unittest.TestCase):
    def test_population_range_widens_at_smaller_size(self) -> None:
        _, small_hi = dhc_population_range(100.0, "tract")
        _, big_hi = dhc_population_range(100_000.0, "tract")
        small_half = small_hi - 100.0
        big_half = big_hi - 100_000.0
        # Relative width (half-width / estimate) must shrink as size grows.
        self.assertGreater(small_half / 100.0, big_half / 100_000.0)

    def test_place_requires_tract_pops(self) -> None:
        with self.assertRaises(ValueError):
            dhc_population_range(90_000.0, "place")

    def test_place_range_is_rss_of_tracts_not_naive_sum(self) -> None:
        pops = pd.Series([90_000.0] * 25)
        lo, hi = dhc_population_range(90_000.0 * 25, "place", tract_pops=pops)
        naive_half = 25 * (90_000.0 * 0.5)  # absurdly large if summed, not RSS'd
        self.assertLess(hi - (90_000.0 * 25), naive_half)

    def test_subgroup_range_place_bigger_than_tract(self) -> None:
        _, tract_hi = dhc_subgroup_range(500.0, "tract")
        _, place_hi = dhc_subgroup_range(500.0, "place")
        self.assertGreater(place_hi - 500.0, tract_hi - 500.0)

    def test_bad_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            dhc_subgroup_range(500.0, "state")  # no Black 65+ RMSE anchor exists for state


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
