"""Tests for analysis/common.py -- sentinels, zero-estimate CV, null propagation.

Run:
    python -m pytest tests/test_common.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import acs, common  # noqa: E402


# ---------------------------------------------------------------------------
# Sentinel handling
# ---------------------------------------------------------------------------

def test_clean_sentinels_replaces_known_codes():
    df = pd.DataFrame({
        "B19013_001E": [50_000, -666666666, -555555555, 75_000],
        "B19013_001M": [1_200, 900, -666666666, 1_500],
    })
    out = common.clean_sentinels(df)
    assert out["B19013_001E"].tolist()[0] == 50_000
    assert pd.isna(out["B19013_001E"].iloc[1])
    assert pd.isna(out["B19013_001E"].iloc[2])
    assert pd.isna(out["B19013_001M"].iloc[2])
    assert out["B19013_001M"].iloc[1] == 900


def test_clean_sentinels_does_not_mutate_input():
    df = pd.DataFrame({"B19013_001E": [-666666666, 10]})
    original = df["B19013_001E"].tolist()
    common.clean_sentinels(df)
    assert df["B19013_001E"].tolist() == original


def test_clean_sentinels_leaves_legitimate_negatives_alone():
    """A real negative (net self-employment loss) is data, not a sentinel."""
    df = pd.DataFrame({"B19013_001E": [-5_000, -111111110, -111111111]})
    out = common.clean_sentinels(df)
    assert out["B19013_001E"].iloc[0] == -5_000
    assert out["B19013_001E"].iloc[1] == -111111110
    assert pd.isna(out["B19013_001E"].iloc[2])   # exactly at the cutoff


def test_clean_sentinels_handles_already_null():
    """censusdis converts some sentinels to NaN before we see them."""
    df = pd.DataFrame({"B19013_001E": [None, -666666666, 42.0]})
    out = common.clean_sentinels(df)
    assert pd.isna(out["B19013_001E"].iloc[0])
    assert pd.isna(out["B19013_001E"].iloc[1])
    assert out["B19013_001E"].iloc[2] == 42.0


def test_clean_sentinels_ignores_non_cell_columns():
    df = pd.DataFrame({"NAME": ["Mercer County"], "B01003_001E": [-666666666]})
    out = common.clean_sentinels(df)
    assert out["NAME"].iloc[0] == "Mercer County"
    assert pd.isna(out["B01003_001E"].iloc[0])


def test_sentinel_report_counts_before_cleaning():
    df = pd.DataFrame({
        "B19013_001E": [1.0, -666666666, -666666666, None],
        "B19013_001M": [1.0, 2.0, 3.0, 4.0],
    })
    rep = common.sentinel_report(df).set_index("column")
    assert rep.loc["B19013_001E", "sentinel"] == 2
    assert rep.loc["B19013_001E", "null"] == 1
    assert rep.loc["B19013_001E", "codes"] == [-666666666]
    assert rep.loc["B19013_001M", "sentinel"] == 0


# ---------------------------------------------------------------------------
# CV -- zero estimates and nulls
# ---------------------------------------------------------------------------

def test_moe_to_cv_matches_acs_convention_exactly():
    """common.moe_to_cv must not drift from acs.cv."""
    est = pd.Series([50_000.0, 1_000.0, 250.0])
    moe = pd.Series([1_645.0, 164.5, 82.25])
    pd.testing.assert_series_equal(
        common.moe_to_cv(est, moe), acs.cv(est, moe), check_names=False
    )


def test_moe_to_cv_known_value():
    """MOE of 1645 on an estimate of 50000 -> SE 1000 -> CV 0.02."""
    assert common.moe_to_cv(50_000, 1_645) == pytest.approx(0.02)


def test_moe_to_cv_zero_estimate_is_nan():
    """CV is undefined at zero -- a zero count has no scale to be relative to."""
    assert np.isnan(common.moe_to_cv(0, 100))


def test_moe_to_cv_negative_estimate_is_nan():
    assert np.isnan(common.moe_to_cv(-500, 100))


def test_moe_to_cv_null_propagates():
    assert np.isnan(common.moe_to_cv(np.nan, 100))
    assert np.isnan(common.moe_to_cv(50_000, np.nan))


def test_moe_to_cv_sentinel_inputs_are_nan_not_huge():
    """A sentinel that slipped past the cleaner must not become a CV."""
    assert np.isnan(common.moe_to_cv(-666666666, 100))
    assert np.isnan(common.moe_to_cv(50_000, -666666666))


def test_moe_to_cv_series_preserves_index():
    est = pd.Series([100.0, 0.0, np.nan], index=["a", "b", "c"])
    moe = pd.Series([10.0, 10.0, 10.0], index=["a", "b", "c"])
    out = common.moe_to_cv(est, moe)
    assert list(out.index) == ["a", "b", "c"]
    assert out["a"] == pytest.approx(10.0 / 1.645 / 100.0)
    assert np.isnan(out["b"])
    assert np.isnan(out["c"])


# ---------------------------------------------------------------------------
# B19001 brackets
# ---------------------------------------------------------------------------

def test_sixteen_brackets_not_seventeen():
    """The proposal says 17; the live API gives 16 plus a universe total."""
    assert len(common.B19001_BRACKETS) == 16
    assert common.B19001_TOTAL == "B19001_001E"
    assert common.B19001_TOTAL not in [c for c, _, _ in common.B19001_BRACKETS]


def test_brackets_are_contiguous_and_ascending():
    for (_, _, hi), (_, lo_next, _) in zip(
        common.B19001_BRACKETS, common.B19001_BRACKETS[1:]
    ):
        assert hi is not None
        assert lo_next == hi + 1


def test_top_bracket_is_open_ended():
    cell, lo, hi = common.B19001_BRACKETS[-1]
    assert cell == "B19001_017E"
    assert lo == 200_000
    assert hi is None, "top bracket must stay open -- flag, never impute"


def test_bracket_widths_are_irregular():
    """If these ever become uniform, Track A's bracket_width driver is dead."""
    widths = [w for w in common.bracket_widths() if w is not None]
    assert len(widths) == 15
    assert min(widths) == 5_000
    assert max(widths) == 50_000
    assert len(set(widths)) > 1


def test_bracket_width_none_only_for_top():
    widths = common.bracket_widths()
    assert widths[-1] is None
    assert all(w is not None for w in widths[:-1])


# ---------------------------------------------------------------------------
# SAIPE half-width
# ---------------------------------------------------------------------------

def test_half_width_basic():
    lo = pd.Series([40_000.0, 10.0])
    hi = pd.Series([60_000.0, 20.0])
    out = common.half_width(lo, hi)
    assert out.iloc[0] == pytest.approx(10_000.0)
    assert out.iloc[1] == pytest.approx(5.0)


def test_half_width_null_propagates():
    out = common.half_width(pd.Series([np.nan]), pd.Series([100.0]))
    assert np.isnan(out.iloc[0])


# ---------------------------------------------------------------------------
# Convention pins
# ---------------------------------------------------------------------------

def test_vintage_matches_acs_module():
    """common and acs must agree, or notebook filenames diverge from pulls."""
    assert common.ACS_VINTAGE == acs.VINTAGE


def test_z90_is_shared_not_redefined():
    assert common.Z_90 is acs.Z_90
    assert common.Z_90 == 1.645


def test_saipe_years_verified_window():
    assert common.SAIPE_YEARS == [2019, 2020, 2021, 2022, 2023, 2024]
