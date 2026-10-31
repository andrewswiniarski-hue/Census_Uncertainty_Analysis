"""Tests for analysis.cv_model helpers."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from analysis.cv_model import (
    design_matrix,
    fit_ols,
    flag_high_cv_residual,
    incremental_r2,
    model_ready,
)


class ModelReadyTest(unittest.TestCase):
    def test_requires_positive_cv_and_sizes(self) -> None:
        frame = pd.DataFrame(
            {
                "cv": [0.1, 0.0, np.nan, 0.2],
                "place_pop": [1000, 1000, 1000, 0],
                "estimate_size": [100, 100, 100, 100],
                "level": ["tract"] * 4,
                "variable_group": ["population"] * 4,
            }
        )
        ready = model_ready(frame)
        self.assertEqual(len(ready), 1)
        self.assertAlmostEqual(ready.loc[0, "log_cv"], np.log(0.1))


class FitOlsTest(unittest.TestCase):
    def test_perfect_line_has_r2_one(self) -> None:
        # log_cv = 1 - 0.5 * log_estimate_size
        est = np.array([10.0, 100.0, 1000.0, 10_000.0])
        log_est = np.log(est)
        log_cv = 1.0 - 0.5 * log_est
        df = pd.DataFrame(
            {
                "log_cv": log_cv,
                "log_estimate_size": log_est,
                "log_place_pop": np.log(np.full_like(est, 5000.0)),
                "level": ["tract"] * 4,
                "variable_group": ["population"] * 4,
            }
        )
        res = fit_ols(df, ["log_estimate_size"], name="B")
        self.assertAlmostEqual(res.r_squared, 1.0, places=6)
        self.assertAlmostEqual(res.coefficients["log_estimate_size"], -0.5, places=5)

    def test_incremental_r2_nested(self) -> None:
        rng = np.random.default_rng(0)
        n = 200
        log_est = rng.normal(5, 1, n)
        log_pop = rng.normal(8, 0.5, n)
        # True driver is estimate size; place pop is noise.
        log_cv = 0.5 - 0.4 * log_est + rng.normal(0, 0.05, n)
        df = pd.DataFrame(
            {
                "log_cv": log_cv,
                "log_estimate_size": log_est,
                "log_place_pop": log_pop,
                "level": np.where(rng.random(n) > 0.5, "tract", "county"),
                "variable_group": np.where(
                    rng.random(n) > 0.5, "population", "poverty"
                ),
            }
        )
        a = fit_ols(df, ["log_place_pop"], name="A")
        b = fit_ols(df, ["log_estimate_size"], name="B")
        full = fit_ols(
            df,
            [
                "log_place_pop",
                "log_estimate_size",
                "C(level)",
                "C(variable_group)",
            ],
            name="full",
        )
        table = incremental_r2([a, b, full])
        self.assertLess(a.r_squared, 0.15)
        self.assertGreater(b.r_squared, 0.8)
        self.assertGreaterEqual(full.r_squared, b.r_squared - 1e-9)
        self.assertAlmostEqual(
            table.loc[1, "incremental_r2"],
            b.r_squared - a.r_squared,
            places=8,
        )


class DesignMatrixTest(unittest.TestCase):
    def test_interaction_term_columns(self) -> None:
        df = pd.DataFrame(
            {
                "log_cv": [0.0, 0.1, 0.2],
                "log_estimate_size": [1.0, 2.0, 3.0],
                "variable_group": ["population", "poverty", "population"],
            }
        )
        X, y = design_matrix(df, ["log_estimate_size:C(variable_group)"])
        self.assertIn("intercept", X.columns)
        self.assertTrue(any(c.startswith("log_est×") for c in X.columns))
        self.assertEqual(len(y), 3)


class ResidualFlagTest(unittest.TestCase):
    def test_flags_worse_than_size_prediction(self) -> None:
        # Most points on a -0.5 line; one point far above (worse CV).
        est = pd.Series([100.0 * (1.4**i) for i in range(12)])
        cv = 0.5 / np.sqrt(est)  # roughly size-driven
        cv = cv.copy()
        cv.iloc[-1] = float(cv.iloc[-1] * 8)  # unexpectedly high CV
        flag, meta = flag_high_cv_residual(cv, est, residual_percentile=0.8)
        self.assertTrue(bool(flag.iloc[-1]))
        self.assertIn("r_squared", meta)
        self.assertGreater(meta["n_train"], 0)


if __name__ == "__main__":
    unittest.main()
