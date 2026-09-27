"""Tests for analysis.noise_model.estimate_relative_noise's per-level branching."""

from __future__ import annotations

import unittest

from analysis.noise_model import estimate_relative_noise


class EstimateRelativeNoiseTest(unittest.TestCase):
    def test_state_is_the_das_invariant(self) -> None:
        self.assertEqual(estimate_relative_noise("state", 1_000_000), 0.0)

    def test_county_is_constant_across_size(self) -> None:
        self.assertEqual(
            estimate_relative_noise("county", 1_000), estimate_relative_noise("county", 500_000)
        )

    def test_block_group_noisier_than_tract_at_same_size(self) -> None:
        # Matches notebook 04's "12x gap at ~1,400 residents" finding.
        bg = estimate_relative_noise("block group", 1_400)
        tract = estimate_relative_noise("tract", 1_400)
        self.assertGreater(bg, tract)

    def test_block_curve_decreases_with_size(self) -> None:
        small = estimate_relative_noise("block", 5)
        big = estimate_relative_noise("block", 2000)
        self.assertGreater(small, big)

    def test_unknown_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            estimate_relative_noise("neighborhood", 100)


if __name__ == "__main__":
    unittest.main()
