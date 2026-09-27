"""Tests for analysis.composite reliability helpers."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from analysis.composite import (
    BAND_HIGHER,
    BAND_LOWER,
    BAND_MODERATE,
    CV_THRESHOLD_DEFAULT,
    ReliabilityScore,
    allocation_flag_threshold,
    attach_cv_residual_flag,
    build_reliability_frame,
    classify_quadrant,
    cv_subscore,
    equal_weight_score,
    imputation_subscores,
    percentile_risk,
    quadrant_counts,
    reliability_score,
    worst_component_score,
)
from analysis.dashboard import RAW_DIR, load_alloc_us_county


class AllocationFlagThresholdTest(unittest.TestCase):
    def test_75th_percentile(self) -> None:
        rates = pd.Series([0.1, 0.2, 0.3, 0.4])
        self.assertAlmostEqual(allocation_flag_threshold(rates, 0.75), 0.325)

    def test_ignores_nan(self) -> None:
        rates = pd.Series([0.1, np.nan, 0.9])
        self.assertAlmostEqual(allocation_flag_threshold(rates, 0.5), 0.5)


class ClassifyQuadrantTest(unittest.TestCase):
    def test_four_quadrants_and_boundary_at_cv_threshold(self) -> None:
        cv = pd.Series([0.20, 0.30, 0.31, 0.50, np.nan])
        alloc = pd.Series([0.10, 0.40, 0.10, 0.40, 0.10])
        labels = classify_quadrant(
            cv, alloc, cv_threshold=0.30, alloc_threshold=0.25
        )
        self.assertEqual(labels.iloc[0], "low_cv_low_alloc")
        self.assertEqual(labels.iloc[1], "low_cv_high_alloc")  # CV == 0.30 counts as ok
        self.assertEqual(labels.iloc[2], "high_cv_low_alloc")
        self.assertEqual(labels.iloc[3], "high_cv_high_alloc")
        self.assertTrue(pd.isna(labels.iloc[4]))

    def test_missing_alloc_is_unclassified(self) -> None:
        cv = pd.Series([0.1])
        alloc = pd.Series([np.nan])
        labels = classify_quadrant(cv, alloc, alloc_threshold=0.2)
        self.assertTrue(pd.isna(labels.iloc[0]))


class PercentileRiskTest(unittest.TestCase):
    def test_ties_use_average_rank(self) -> None:
        s = pd.Series([1.0, 2.0, 2.0, 4.0])
        ranks = percentile_risk(s)
        # ranks of values 1,2,2,4 among n=4 with average ties:
        # 1 -> 0.25, 2/2 -> 0.625, 4 -> 1.0
        self.assertAlmostEqual(ranks.iloc[0], 0.25)
        self.assertAlmostEqual(ranks.iloc[1], 0.625)
        self.assertAlmostEqual(ranks.iloc[2], 0.625)
        self.assertAlmostEqual(ranks.iloc[3], 1.0)

    def test_preserves_nan(self) -> None:
        s = pd.Series([1.0, np.nan, 3.0])
        ranks = percentile_risk(s)
        self.assertTrue(np.isnan(ranks.iloc[1]))


class SensitivityScoresTest(unittest.TestCase):
    def test_equal_weight_is_mean_of_percentile_risks(self) -> None:
        cv = pd.Series([1.0, 2.0, 3.0])
        alloc = pd.Series([3.0, 2.0, 1.0])
        got = equal_weight_score(cv, alloc)
        expected = (percentile_risk(cv) + percentile_risk(alloc)) / 2
        pd.testing.assert_series_equal(got, expected)

    def test_worst_component_takes_max(self) -> None:
        cv = pd.Series([1.0, 2.0, 3.0])
        alloc = pd.Series([3.0, 2.0, 1.0])
        got = worst_component_score(cv, alloc)
        expected = pd.concat(
            [percentile_risk(cv), percentile_risk(alloc)], axis=1
        ).max(axis=1)
        pd.testing.assert_series_equal(got, expected)
        # First row: low CV risk, high alloc risk -> worst is alloc risk
        self.assertGreater(got.iloc[0], equal_weight_score(cv, alloc).iloc[0])


class BuildReliabilityFrameTest(unittest.TestCase):
    def test_attaches_scores_and_uses_default_cv_threshold(self) -> None:
        df = pd.DataFrame(
            {
                "cv": [0.1, 0.2, 0.4, 0.5],
                "income_alloc": [0.1, 0.5, 0.1, 0.5],
            }
        )
        out, thresholds = build_reliability_frame(
            df, cv_col="cv", alloc_col="income_alloc"
        )
        self.assertEqual(thresholds["cv_threshold"], CV_THRESHOLD_DEFAULT)
        self.assertIn("quadrant", out.columns)
        self.assertIn("equal_weight_score", out.columns)
        self.assertIn("worst_component_score", out.columns)
        counts = quadrant_counts(out["quadrant"])
        self.assertEqual(int(counts.sum()), 4)
        # Input not mutated.
        self.assertNotIn("quadrant", df.columns)


class ResidualFlagAttachTest(unittest.TestCase):
    def test_attach_cv_residual_flag_adds_column(self) -> None:
        est = pd.Series([100.0 * (1.3**i) for i in range(15)])
        cv = 0.4 / np.sqrt(est)
        cv = cv.copy()
        cv.iloc[-1] = float(cv.iloc[-1] * 6)
        df = pd.DataFrame({"cv": cv, "hh": est})
        out, meta = attach_cv_residual_flag(
            df, cv_col="cv", estimate_size_col="hh"
        )
        self.assertIn("cv_residual_high", out.columns)
        self.assertTrue(bool(out["cv_residual_high"].iloc[-1]))
        self.assertNotIn("cv_residual_high", df.columns)
        self.assertIn("r_squared", meta)


class CvSubscoreTest(unittest.TestCase):
    def test_anchors_map_exactly(self) -> None:
        self.assertAlmostEqual(cv_subscore(0.0), 100.0)
        self.assertAlmostEqual(cv_subscore(0.12), 75.0)
        self.assertAlmostEqual(cv_subscore(0.30), 50.0)
        self.assertAlmostEqual(cv_subscore(1 / 1.645), 0.0)

    def test_linear_between_anchors(self) -> None:
        self.assertAlmostEqual(cv_subscore(0.06), 87.5)
        self.assertAlmostEqual(cv_subscore(0.21), 62.5)

    def test_zero_beyond_last_anchor(self) -> None:
        self.assertEqual(cv_subscore(0.9), 0.0)
        self.assertEqual(cv_subscore(12.5), 0.0)

    def test_falls_steadily(self) -> None:
        values = [cv_subscore(c) for c in np.linspace(0, 0.6, 61)]
        self.assertTrue(all(a > b for a, b in zip(values, values[1:])))

    def test_nan_in_nan_out(self) -> None:
        self.assertTrue(np.isnan(cv_subscore(float("nan"))))


class ImputationSubscoresTest(unittest.TestCase):
    def test_median_75th_and_max(self) -> None:
        rates = pd.Series(np.arange(1, 101, dtype=float))  # p = value / 100
        subs = imputation_subscores(rates)
        self.assertEqual(subs.iloc[0], 100.0)            # well below the median
        self.assertAlmostEqual(subs.iloc[49], 100.0)     # p = 0.50
        self.assertAlmostEqual(subs.iloc[74], 50.0)      # p = 0.75
        self.assertAlmostEqual(subs.iloc[99], 0.0)       # p = 1.00, the most imputed

    def test_nan_rates_stay_nan_and_keep_index(self) -> None:
        rates = pd.Series([0.3, np.nan, 0.5], index=["a", "b", "c"])
        subs = imputation_subscores(rates)
        self.assertEqual(list(subs.index), ["a", "b", "c"])
        self.assertTrue(np.isnan(subs["b"]))


class ReliabilityScoreTest(unittest.TestCase):
    def test_averages_two_components(self) -> None:
        rs = reliability_score(0.12, 25.0, source="household income, Table B99192")
        self.assertAlmostEqual(rs.score, 50.0)
        self.assertEqual(rs.sampling_sub, 75.0)
        self.assertEqual(rs.imputation_sub, 25.0)
        self.assertEqual(rs.band, BAND_MODERATE)
        self.assertEqual(rs.imputation_source, "household income, Table B99192")

    def test_sampling_only(self) -> None:
        rs = reliability_score(0.06, note="not published")
        self.assertAlmostEqual(rs.score, 87.5)
        self.assertIsNone(rs.imputation_sub)
        self.assertIsNone(rs.imputation_source)
        self.assertEqual(rs.imputation_note, "not published")
        self.assertEqual(rs.band, BAND_HIGHER)
        self.assertFalse(rs.capped_by_cv)

    def test_band_edges(self) -> None:
        # Score edges: 75 is Higher, 50 is Moderate.
        self.assertEqual(reliability_score(0.12).band, BAND_HIGHER)    # score 75
        self.assertEqual(reliability_score(0.30).band, BAND_MODERATE)  # score 50
        self.assertEqual(reliability_score(0.31).band, BAND_LOWER)

    def test_guard_caps_band_at_cv_band(self) -> None:
        # CV 0.35 alone is Lower; a perfect imputation sub-score lifts the
        # SCORE to about 71 (Moderate range) but must not lift the BAND.
        rs = reliability_score(0.35, 100.0, source="x")
        self.assertAlmostEqual(rs.score, 70.94, places=2)
        self.assertEqual(rs.band, BAND_LOWER)
        self.assertTrue(rs.capped_by_cv)

    def test_imputation_can_lower_band(self) -> None:
        rs = reliability_score(0.04, 1.7, source="x")  # Apache-like
        self.assertEqual(rs.band, BAND_LOWER)
        self.assertFalse(rs.capped_by_cv)

    def test_moe_larger_than_estimate(self) -> None:
        rs = reliability_score(1.5)
        self.assertEqual(rs.sampling_sub, 0.0)
        self.assertEqual(rs.band, BAND_LOWER)

    def test_nan_cv_gives_none(self) -> None:
        self.assertIsNone(reliability_score(float("nan"), 80.0, source="x"))

    def test_nan_imputation_falls_back_to_sampling_only(self) -> None:
        rs = reliability_score(0.06, float("nan"), source="x",
                               note="not available for this county")
        self.assertIsNone(rs.imputation_sub)
        self.assertIsNone(rs.imputation_source)
        self.assertAlmostEqual(rs.score, 87.5)

    def test_is_frozen(self) -> None:
        rs = reliability_score(0.1)
        self.assertIsInstance(rs, ReliabilityScore)
        with self.assertRaises(Exception):
            rs.score = 1.0  # type: ignore[misc]


_USDASH = RAW_DIR / "acs5_2024_usdash_county.parquet"
_USALLOC = RAW_DIR / "acs5_2024_usdash_alloc_county.parquet"


@unittest.skipUnless(_USDASH.exists() and _USALLOC.exists(), "US dashboard data not pulled")
class ReliabilityScoreRealDataTest(unittest.TestCase):
    """Reference values from the spec, computed from the 2026-09-14 pull."""

    @classmethod
    def setUpClass(cls) -> None:
        df = pd.read_parquet(_USDASH)
        alloc = load_alloc_us_county()

        def key(d: pd.DataFrame) -> pd.Series:
            return d["STATE"].astype(str).str.zfill(2) + d["COUNTY"].astype(str).str.zfill(3)

        df.index = key(df)
        alloc.index = key(alloc)
        est = pd.to_numeric(df["B19013_001E"], errors="coerce")
        moe = pd.to_numeric(df["B19013_001M"], errors="coerce")
        cls.cv = (moe / 1.645) / est.where(est > 0)
        cls.imp = imputation_subscores(alloc["income_alloc"]).reindex(df.index)

    def test_apache_county_median_income(self) -> None:
        rs = reliability_score(float(self.cv["04001"]), float(self.imp["04001"]), source="x")
        self.assertAlmostEqual(rs.sampling_sub, 92.11, places=2)
        self.assertAlmostEqual(rs.imputation_sub, 1.72, places=2)
        self.assertAlmostEqual(rs.score, 46.91, places=2)
        self.assertEqual(rs.band, BAND_LOWER)

    def test_national_band_shares_median_income(self) -> None:
        bands = [
            rs.band for rs in (
                reliability_score(float(c), float(i), source="x")
                for c, i in zip(self.cv, self.imp)
            ) if rs is not None
        ]
        self.assertEqual(len(bands), 3143)
        share = pd.Series(bands).value_counts(normalize=True) * 100
        self.assertAlmostEqual(share[BAND_HIGHER], 67.58, places=2)
        self.assertAlmostEqual(share[BAND_MODERATE], 24.98, places=2)
        self.assertAlmostEqual(share[BAND_LOWER], 7.45, places=2)


if __name__ == "__main__":
    unittest.main()
