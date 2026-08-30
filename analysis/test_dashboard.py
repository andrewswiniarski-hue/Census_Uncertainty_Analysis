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
    _INCOME_BRACKET_CELLS,
    _LIMITED_ENGLISH_CELLS,
    _POVERTY_ABOVE_CELLS,
    _POVERTY_CELLS,
    _SEXAGE_CELLS,
    _UNINSURED_CELLS,
    acs_income_bracket,
    acs_insurance_universe,
    acs_language_universe,
    acs_limited_english,
    acs_median_rent,
    acs_no_vehicle,
    acs_poverty,
    acs_poverty_universe,
    acs_range,
    acs_rent_burden,
    acs_renter_occupied,
    acs_sexage,
    acs_uninsured,
    acs_vehicle_universe,
    children_of,
    cv_from_range,
    difference_is_significant,
    geo_key,
    load_acs,
    load_level_data,
    load_pums_profile,
    poverty_rate,
    proportion_rate,
    statistical_peers,
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


class NewMeasuresTest(unittest.TestCase):
    """Variable expansion (2026-08-30): health insurance, language,
    vehicles, income brackets, rent -- fabricated frames, same style as
    BandCoverageTest/AcsRangeTest above, not full data pulls."""

    def test_uninsured_sums_all_no_coverage_cells(self) -> None:
        cols = {}
        for n in _UNINSURED_CELLS:
            cols[f"B27001_{n}E"] = [1.0]
            cols[f"B27001_{n}M"] = [1.0]
        cols["B27001_001E"] = [1000.0]
        cols["B27001_001M"] = [50.0]
        df = pd.DataFrame(cols)
        est, moe = acs_uninsured(df)
        self.assertEqual(float(est.iloc[0]), float(len(_UNINSURED_CELLS)))
        univ_est, univ_moe = acs_insurance_universe(df)
        self.assertEqual(float(univ_est.iloc[0]), 1000.0)
        self.assertEqual(float(univ_moe.iloc[0]), 50.0)

    def test_limited_english_sums_four_language_groups(self) -> None:
        df = pd.DataFrame({
            "C16002_001E": [500.0], "C16002_001M": [20.0],
            "C16002_004E": [10.0], "C16002_004M": [3.0],
            "C16002_007E": [5.0], "C16002_007M": [2.0],
            "C16002_010E": [8.0], "C16002_010M": [2.0],
            "C16002_013E": [2.0], "C16002_013M": [1.0],
        })
        self.assertEqual(sorted(_LIMITED_ENGLISH_CELLS), ["004", "007", "010", "013"])
        est, moe = acs_limited_english(df)
        self.assertEqual(float(est.iloc[0]), 25.0)
        self.assertAlmostEqual(float(moe.iloc[0]), (3.0**2 + 2.0**2 + 2.0**2 + 1.0**2) ** 0.5)
        univ_est, _ = acs_language_universe(df)
        self.assertEqual(float(univ_est.iloc[0]), 500.0)

    def test_no_vehicle_is_a_single_published_cell(self) -> None:
        df = pd.DataFrame({
            "B08201_001E": [400.0], "B08201_001M": [15.0],
            "B08201_002E": [30.0], "B08201_002M": [8.0],
        })
        est, moe = acs_no_vehicle(df)
        self.assertEqual(float(est.iloc[0]), 30.0)
        self.assertEqual(float(moe.iloc[0]), 8.0)
        univ_est, _ = acs_vehicle_universe(df)
        self.assertEqual(float(univ_est.iloc[0]), 400.0)

    def test_income_brackets_partition_the_16_published_cells(self) -> None:
        # Every INCOME_BANDS cell list must be disjoint and, together,
        # cover B19001's 16 published brackets (002..017) exactly once
        # each -- same shape as test_sexage_bands_are_disjoint_and_complete.
        all_cells = sorted(int(n) for cells in _INCOME_BRACKET_CELLS.values() for n in cells)
        self.assertEqual(all_cells, list(range(2, 18)))

    def test_income_bracket_sums_its_own_cells(self) -> None:
        df = pd.DataFrame({
            "B19001_002E": [5.0], "B19001_002M": [2.0],
            "B19001_003E": [7.0], "B19001_003M": [3.0],
            "B19001_004E": [4.0], "B19001_004M": [2.0],
            "B19001_005E": [6.0], "B19001_005M": [2.0],
        })
        est, moe = acs_income_bracket(df, "Under $25k")
        self.assertEqual(float(est.iloc[0]), 22.0)

    def test_income_bracket_bad_band_raises(self) -> None:
        df = pd.DataFrame({"B19001_002E": [1.0], "B19001_002M": [1.0]})
        with self.assertRaises(ValueError):
            acs_income_bracket(df, "not a band")

    def test_rent_burden_reads_its_own_published_cell(self) -> None:
        # acs_rent_burden() must read B25071 directly, not compute
        # rent/income by hand -- the Bureau's point restated as a test:
        # the median of a ratio is not the ratio of two medians, so this
        # value is deliberately NOT derivable from acs_median_rent()'s.
        df = pd.DataFrame({
            "B25064_001E": [1200.0], "B25064_001M": [50.0],
            "B25071_001E": [31.5], "B25071_001M": [1.2],
            "B25003_001E": [900.0], "B25003_001M": [20.0],
            "B25003_003E": [300.0], "B25003_003M": [15.0],
        })
        rent_est, _ = acs_median_rent(df)
        burden_est, _ = acs_rent_burden(df)
        self.assertEqual(float(rent_est.iloc[0]), 1200.0)
        self.assertEqual(float(burden_est.iloc[0]), 31.5)
        renter_est, _ = acs_renter_occupied(df)
        self.assertEqual(float(renter_est.iloc[0]), 300.0)

    def test_proportion_rate_is_poverty_rate(self) -> None:
        # Generic alias, not a reimplementation -- same object, so every
        # rate-bearing new measure gets poverty_rate's existing coverage.
        self.assertIs(proportion_rate, poverty_rate)


class StatisticalPeersTest(unittest.TestCase):
    """statistical_peers() (statistical peer counties, 2026-08-30) --
    fabricated (est, moe) Series, same style as PovertyRateTest above."""

    def _series(self, values: dict[str, tuple[float, float]]) -> tuple[pd.Series, pd.Series]:
        est = pd.Series({k: v[0] for k, v in values.items()})
        moe = pd.Series({k: v[1] for k, v in values.items()})
        return est, moe

    def test_tied_pair_hand_computed(self) -> None:
        # se1=se2=10/Z_90~6.08 -> combined se~8.60; a 10-unit gap gives
        # |Z|~1.16, under 1.645 -> tied.
        est, moe = self._series({"A": (100.0, 10.0), "B": (110.0, 10.0)})
        result = statistical_peers(est, moe, "A")
        self.assertEqual(result.loc["A", "relation"], "self")
        self.assertEqual(result.loc["B", "relation"], "tied")

    def test_significant_difference_has_correct_direction(self) -> None:
        est, moe = self._series({"A": (100.0, 5.0), "B": (200.0, 5.0), "C": (10.0, 5.0)})
        result = statistical_peers(est, moe, "A")
        # B's estimate is higher than A's -> B is labeled "higher".
        self.assertEqual(result.loc["B", "relation"], "higher")
        # C's estimate is lower than A's -> C is labeled "lower".
        self.assertEqual(result.loc["C", "relation"], "lower")

    def test_nan_estimate_or_moe_is_untestable_not_tied(self) -> None:
        est, moe = self._series({"A": (100.0, 10.0), "B": (100.0, float("nan")), "C": (float("nan"), 10.0)})
        result = statistical_peers(est, moe, "A")
        self.assertEqual(result.loc["B", "relation"], "untestable")
        self.assertEqual(result.loc["C", "relation"], "untestable")

    def test_selected_countys_own_missing_moe_makes_everything_untestable(self) -> None:
        # If the SELECTED county itself has no MOE for this measure, no
        # comparison is possible for any candidate -- never silently
        # "tied" just because the candidate side is fine.
        est, moe = self._series({"A": (100.0, float("nan")), "B": (100.0, 10.0)})
        result = statistical_peers(est, moe, "A")
        self.assertEqual(result.loc["A", "relation"], "self")
        self.assertEqual(result.loc["B", "relation"], "untestable")

    def test_self_row_is_self_even_when_untestable(self) -> None:
        est, moe = self._series({"A": (100.0, float("nan")), "B": (100.0, 10.0)})
        result = statistical_peers(est, moe, "A")
        self.assertEqual(result.loc["A", "relation"], "self")

    def test_single_row_pool_has_only_self(self) -> None:
        est, moe = self._series({"A": (100.0, 10.0)})
        result = statistical_peers(est, moe, "A")
        self.assertEqual(list(result["relation"]), ["self"])

    def test_missing_key_raises(self) -> None:
        est, moe = self._series({"A": (100.0, 10.0)})
        with self.assertRaises(KeyError):
            statistical_peers(est, moe, "Z")

    def test_agrees_with_difference_is_significant_across_a_grid(self) -> None:
        # Non-tied/non-untestable in statistical_peers() must exactly
        # match difference_is_significant() == 1.0 for the same pair, and
        # "untestable" must exactly match its NaN case -- same formula,
        # vectorized vs. scalar, checked pairwise across a small grid.
        sel_est, sel_moe = 500.0, 40.0
        candidates = {
            "close": (510.0, 40.0), "far_higher": (900.0, 40.0), "far_lower": (100.0, 40.0),
            "wide_moe": (700.0, 300.0), "nan_est": (float("nan"), 40.0), "nan_moe": (300.0, float("nan")),
        }
        values = {"SEL": (sel_est, sel_moe), **candidates}
        est, moe = self._series(values)
        result = statistical_peers(est, moe, "SEL")
        for key, (cand_est, cand_moe) in candidates.items():
            sig = difference_is_significant(sel_est, sel_moe, cand_est, cand_moe)
            relation = result.loc[key, "relation"]
            if np.isnan(sig):
                self.assertEqual(relation, "untestable", key)
            else:
                is_different = relation in ("higher", "lower")
                self.assertEqual(is_different, bool(sig), key)


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


@unittest.skipUnless(
    (RAW_DIR / "pums_2024_nj_alloc_flags.parquet").exists(), "PUMS alloc flags not pulled"
)
class PumsProfileLoaderTest(unittest.TestCase):
    def test_loads_expected_characteristics(self) -> None:
        prof = load_pums_profile()
        self.assertEqual(
            set(prof["characteristic"].unique()), {"age_band", "sex", "education"}
        )
        self.assertTrue((prof["share_whole_record"].between(0, 1)).all())


@unittest.skipUnless(
    (RAW_DIR / "acs5_2024_njdash_county.parquet").exists()
    and (RAW_DIR / "acs5_2024_njdash_tract.parquet").exists(),
    "NJ statewide dashboard data not pulled",
)
class LevelRegistryTest(unittest.TestCase):
    """Map-first dashboard's drill-down primitives: geo_key and children_of."""

    def test_geo_key_is_unique_per_level(self) -> None:
        county = load_level_data("county")
        tract = load_level_data("tract")
        self.assertEqual(geo_key(county, "county").nunique(), len(county))
        self.assertEqual(geo_key(tract, "tract").nunique(), len(tract))

    def test_children_of_returns_only_that_parents_rows(self) -> None:
        county = load_level_data("county")
        tract = load_level_data("tract")
        mercer_key = county.loc[county["NAME"].str.contains("Mercer"), "COUNTY"].iloc[0]
        kids = children_of("tract", mercer_key, tract)
        self.assertGreater(len(kids), 0)
        self.assertTrue((kids["COUNTY"] == mercer_key).all())
        # Every Mercer tract lands in exactly one county's children -- the
        # partition must be total, not just non-empty for one county.
        self.assertEqual(len(kids), (tract["COUNTY"] == mercer_key).sum())

    def test_top_level_has_no_parent(self) -> None:
        with self.assertRaises(ValueError):
            children_of("county", "021")


if __name__ == "__main__":
    unittest.main()
