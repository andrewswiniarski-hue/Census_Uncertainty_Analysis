"""Tests for analysis.composite reliability helpers."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from analysis.composite import (
    CV_THRESHOLD_DEFAULT,
    allocation_flag_threshold,
    attach_cv_residual_flag,
    build_reliability_frame,
    classify_quadrant,
    equal_weight_score,
    percentile_risk,
    quadrant_counts,
    worst_component_score,
)


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


if __name__ == "__main__":
    unittest.main()
