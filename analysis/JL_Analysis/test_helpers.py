"""Tests for JL_Analysis helper functions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import (  # noqa: E402
    ANNOTATION_CUTOFF,
    INCOME_TOP_CODE,
    MOE_TO_SE,
    annotation_mask,
    combine_moes_rss,
    compute_cv,
    is_valid_for_cv,
)


class CombineMoesRssTest(unittest.TestCase):
    def test_sums_estimates_and_combines_moes_by_root_sum_of_squares(self) -> None:
        estimates = pd.DataFrame(
            {
                "cell_a": [10, 20],
                "cell_b": [5, 30],
                "cell_c": [2, 40],
            }
        )
        moes = pd.DataFrame(
            {
                "cell_a": [3, 6],
                "cell_b": [4, 8],
                "cell_c": [12, 0],
            }
        )

        combined_estimate, combined_moe = combine_moes_rss(estimates, moes)

        pd.testing.assert_series_equal(
            combined_estimate,
            pd.Series([17, 90], name="combined_estimate"),
        )
        pd.testing.assert_series_equal(
            combined_moe,
            pd.Series([13.0, 10.0], name="combined_moe"),
        )

    def test_pairs_estimate_and_moe_columns_by_position(self) -> None:
        estimates = pd.DataFrame({"B01001B_014E": [10], "B01001B_015E": [5]})
        moes = pd.DataFrame({"B01001B_014M": [3], "B01001B_015M": [4]})

        combined_estimate, combined_moe = combine_moes_rss(estimates, moes)

        pd.testing.assert_series_equal(
            combined_estimate,
            pd.Series([15], name="combined_estimate"),
        )
        pd.testing.assert_series_equal(
            combined_moe,
            pd.Series([5.0], name="combined_moe"),
        )

    def test_rejects_out_of_order_acs_moe_columns(self) -> None:
        estimates = pd.DataFrame({"B01001B_014E": [10], "B01001B_015E": [5]})
        moes = pd.DataFrame({"B01001B_015M": [4], "B01001B_014M": [3]})

        with self.assertRaisesRegex(ValueError, "MOE columns"):
            combine_moes_rss(estimates, moes)

    def test_returns_scalars_for_series_inputs(self) -> None:
        combined_estimate, combined_moe = combine_moes_rss(
            pd.Series([8, 12]),
            pd.Series([5, 12]),
        )

        self.assertEqual(combined_estimate, 20)
        self.assertEqual(combined_moe, 13.0)

    def test_requires_complete_valid_estimate_moe_pairs(self) -> None:
        estimates = pd.DataFrame(
            {
                "cell_a": [10, 20, 30],
                "cell_b": [pd.NA, 5, 6],
            }
        )
        moes = pd.DataFrame(
            {
                "cell_a": [3, 4, 5],
                "cell_b": [4, pd.NA, ANNOTATION_CUTOFF - 1],
            }
        )

        combined_estimate, combined_moe = combine_moes_rss(estimates, moes)

        pd.testing.assert_series_equal(
            combined_estimate,
            pd.Series([float("nan"), float("nan"), float("nan")], name="combined_estimate"),
        )
        pd.testing.assert_series_equal(
            combined_moe,
            pd.Series([float("nan"), float("nan"), float("nan")], name="combined_moe"),
        )

    def test_rejects_negative_moe_in_dataframe_path(self) -> None:
        estimates = pd.DataFrame({"cell_a": [10]})
        moes = pd.DataFrame({"cell_a": [-1]})

        combined_estimate, combined_moe = combine_moes_rss(estimates, moes)

        self.assertTrue(pd.isna(combined_estimate.iloc[0]))
        self.assertTrue(pd.isna(combined_moe.iloc[0]))

    def test_series_inputs_return_missing_when_any_pair_is_invalid(self) -> None:
        combined_estimate, combined_moe = combine_moes_rss(
            pd.Series([8, pd.NA]),
            pd.Series([5, 12]),
        )

        self.assertTrue(pd.isna(combined_estimate))
        self.assertTrue(pd.isna(combined_moe))

    def test_rejects_shape_and_length_mismatches(self) -> None:
        with self.assertRaisesRegex(ValueError, "same shape"):
            combine_moes_rss(
                pd.DataFrame({"cell_a": [1], "cell_b": [2]}),
                pd.DataFrame({"cell_a": [1]}),
            )

        with self.assertRaisesRegex(ValueError, "same length"):
            combine_moes_rss(pd.Series([1, 2]), pd.Series([1]))

    def test_rejects_mixed_dataframe_and_series_inputs(self) -> None:
        with self.assertRaisesRegex(TypeError, "both be DataFrames or both be Series"):
            combine_moes_rss(pd.DataFrame({"cell_a": [1]}), pd.Series([1]))


class CvHelpersTest(unittest.TestCase):
    def test_annotation_mask_flags_census_sentinel_values(self) -> None:
        values = pd.Series([ANNOTATION_CUTOFF + 1, ANNOTATION_CUTOFF, ANNOTATION_CUTOFF - 1, 25])

        mask = annotation_mask(values)

        pd.testing.assert_series_equal(mask, pd.Series([False, True, True, False]))

    def test_is_valid_for_cv_excludes_invalid_and_top_coded_values(self) -> None:
        estimate = pd.Series([100, 0, 50, INCOME_TOP_CODE, ANNOTATION_CUTOFF - 1])
        moe = pd.Series([10, 10, -1, 10, 10])

        valid = is_valid_for_cv(estimate, moe, var_code="B19013_001")

        pd.testing.assert_series_equal(valid, pd.Series([True, False, False, False, False]))

    def test_compute_cv_uses_acs_90_percent_moe_conversion(self) -> None:
        estimate = pd.Series([100, 0, 50])
        moe = pd.Series([MOE_TO_SE * 10, 10, -1])

        cv = compute_cv(estimate, moe, var_code="B01003_001")

        pd.testing.assert_series_equal(cv, pd.Series([0.1, float("nan"), float("nan")]))


if __name__ == "__main__":
    unittest.main()
