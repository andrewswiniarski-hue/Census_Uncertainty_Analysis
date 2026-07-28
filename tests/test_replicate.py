"""Tests for analysis/replicate.py.

Run:
    python -m pytest tests/test_replicate.py -v
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

from analysis import replicate as rep  # noqa: E402


def frame(flag, base_w, rep_w=None, group=None, n_reps=rep.N_REPLICATES):
    """Build a frame with base and replicate weights."""
    d = {"flag": flag, rep.BASE_WEIGHT: base_w}
    if rep_w is not None:
        for i in range(1, n_reps + 1):
            d[f"PWGTP{i}"] = rep_w[i - 1] if isinstance(rep_w[0], list) else rep_w
    if group is not None:
        d["grp"] = group
    return pd.DataFrame(d)


# ---------------------------------------------------------------------------
# The SDR formula
# ---------------------------------------------------------------------------

def test_sdr_constant_is_four_over_eighty():
    """Specific to the ACS replicate design -- not a generic jackknife."""
    assert rep.N_REPLICATES == 80
    assert rep.SDR_CONSTANT == pytest.approx(0.05)


def test_sdr_variance_by_hand():
    # point 10, replicates all 11 -> each squared deviation 1, 80 of them
    var = rep.sdr_variance(10.0, [11.0] * 80)
    assert var == pytest.approx(0.05 * 80 * 1.0)


def test_sdr_variance_zero_when_replicates_match_point():
    assert rep.sdr_variance(5.0, [5.0] * 80) == pytest.approx(0.0)


def test_sdr_variance_ignores_non_finite_replicates():
    a = rep.sdr_variance(10.0, [11.0] * 80)
    b = rep.sdr_variance(10.0, [11.0] * 80 + [np.nan, np.inf])
    assert a == pytest.approx(b)


def test_sdr_variance_nan_point_gives_nan():
    assert np.isnan(rep.sdr_variance(np.nan, [1.0] * 80))


def test_sdr_variance_empty_replicates_gives_nan():
    assert np.isnan(rep.sdr_variance(1.0, []))


def test_moe_uses_the_ninety_percent_multiplier():
    assert rep.Z_90 == 1.645


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_has_replicates_requires_all_eighty():
    full = frame([1, 0], [1, 1], [1, 1])
    assert rep.has_replicates(full)
    assert not rep.has_replicates(full.drop(columns=["PWGTP80"]))


def test_available_replicates_is_ordered():
    df = frame([1, 0], [1, 1], [1, 1])
    cols = rep.available_replicates(df)
    assert cols[0] == "PWGTP1" and cols[-1] == "PWGTP80"
    assert len(cols) == 80


def test_graceful_without_replicates():
    """Missing replicate weights must return NaN, not raise."""
    df = frame([1, 0, 1], [1, 1, 1])
    out = rep.share(df, df["flag"] == 1)
    assert out["estimate"] == pytest.approx(2 / 3)
    assert np.isnan(out["se"]) and out["n_replicates"] == 0


# ---------------------------------------------------------------------------
# Share
# ---------------------------------------------------------------------------

def test_share_point_estimate_is_weighted():
    df = frame([1, 0], [3, 1], [3, 1])
    assert rep.share(df, df["flag"] == 1)["estimate"] == pytest.approx(0.75)


def test_share_zero_variance_when_replicates_equal_base():
    df = frame([1, 0, 1, 0], [1, 1, 1, 1], [1, 1, 1, 1])
    out = rep.share(df, df["flag"] == 1)
    assert out["estimate"] == pytest.approx(0.5)
    assert out["se"] == pytest.approx(0.0)
    assert out["ci_low"] == pytest.approx(out["ci_high"])


def test_share_ci_brackets_the_estimate():
    reps = [[1 + (i % 3), 1, 1, 1] for i in range(80)]
    df = frame([1, 0, 1, 0], [1, 1, 1, 1], reps)
    out = rep.share(df, df["flag"] == 1)
    assert out["ci_low"] <= out["estimate"] <= out["ci_high"]
    assert out["moe"] == pytest.approx(rep.Z_90 * out["se"])


def test_share_respects_denominator_mask():
    df = frame([1, 0, 1, 1], [1, 1, 1, 1], [1, 1, 1, 1])
    den = pd.Series([True, True, False, False])
    assert rep.share(df, df["flag"] == 1, den)["estimate"] == pytest.approx(0.5)


def test_share_empty_denominator_is_nan():
    df = frame([1, 0], [1, 1], [1, 1])
    out = rep.share(df, df["flag"] == 1, pd.Series([False, False]))
    assert np.isnan(out["estimate"])


# ---------------------------------------------------------------------------
# Mean
# ---------------------------------------------------------------------------

def test_mean_weighted_by_hand():
    df = frame([0, 0], [1, 3], [1, 3])
    df["x"] = [10.0, 20.0]
    assert rep.mean(df, "x")["estimate"] == pytest.approx((10 + 60) / 4)


def test_mean_skips_nan_values():
    df = frame([0, 0, 0], [1, 1, 1], [1, 1, 1])
    df["x"] = [10.0, np.nan, 20.0]
    assert rep.mean(df, "x")["estimate"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Difference -- the part that is easy to get wrong
# ---------------------------------------------------------------------------

def test_difference_point_is_a_minus_b():
    df = frame([1, 1, 0, 0], [1, 1, 1, 1], [1, 1, 1, 1],
               group=["a", "a", "b", "b"])
    out = rep.difference(df, df["flag"] == 1, df["grp"] == "a", df["grp"] == "b")
    assert out["estimate_a"] == pytest.approx(1.0)
    assert out["estimate_b"] == pytest.approx(0.0)
    assert out["difference"] == pytest.approx(1.0)


def test_difference_variance_is_taken_on_the_differences():
    """Correlated groups: each replicate moves both the same way, so the
    DIFFERENCE is stable even though each share is noisy. A formula that
    combined separate SEs would report uncertainty that is not there."""
    reps = []
    for i in range(80):
        s = 1 + (i % 5)          # scales both groups together
        reps.append([s, s, s, s])
    df = frame([1, 0, 1, 0], [1, 1, 1, 1], reps, group=["a", "a", "b", "b"])
    out = rep.difference(df, df["flag"] == 1, df["grp"] == "a", df["grp"] == "b")
    assert out["difference"] == pytest.approx(0.0)
    assert out["se"] == pytest.approx(0.0)
    assert out["significant"] is False


def test_naive_difference_se_is_labelled_and_differs():
    """The wrong formula is kept deliberately; prove it disagrees."""
    reps = []
    for i in range(80):
        s = 1 + (i % 5)
        reps.append([s, 1, s, 1])
    df = frame([1, 0, 1, 0], [1, 1, 1, 1], reps, group=["a", "a", "b", "b"])
    a = rep.share(df[df.grp == "a"], df.loc[df.grp == "a", "flag"] == 1)
    b = rep.share(df[df.grp == "b"], df.loc[df.grp == "b", "flag"] == 1)
    correct = rep.difference(df, df["flag"] == 1,
                             df["grp"] == "a", df["grp"] == "b")["se"]
    naive = rep.naive_difference_se(a["se"], b["se"])
    assert not np.isclose(correct, naive)


def test_significance_flag_matches_the_interval():
    reps = [[1, 1, 1, 1] for _ in range(80)]
    df = frame([1, 1, 0, 0], [1, 1, 1, 1], reps, group=["a", "a", "b", "b"])
    out = rep.difference(df, df["flag"] == 1, df["grp"] == "a", df["grp"] == "b")
    assert out["significant"] is True
    assert out["ci_low"] > 0


def test_difference_without_replicates_returns_none_significance():
    df = frame([1, 0], [1, 1], group=["a", "b"])
    out = rep.difference(df, df["flag"] == 1, df["grp"] == "a", df["grp"] == "b")
    assert out["significant"] is None


# ---------------------------------------------------------------------------
# Profiles and pairwise
# ---------------------------------------------------------------------------

def test_profile_with_moe_suppresses_thin_groups():
    df = frame([1] * 50 + [0] * 150, [1] * 200, [1] * 200,
               group=["a"] * 50 + ["b"] * 150)
    out = rep.profile_with_moe(df, "grp", df["flag"] == 1, min_records=100)
    assert set(out["level"]) == {"b"}


def test_pairwise_significance_covers_all_pairs():
    df = frame([1, 0, 1, 0, 1, 0], [1] * 6, [1] * 6,
               group=["a", "a", "b", "b", "c", "c"])
    out = rep.pairwise_significance(df, "grp", df["flag"] == 1)
    assert len(out) == 3
    assert set(out.columns) >= {"level_a", "level_b", "difference",
                                "moe", "significant"}


def test_pairwise_missing_column_returns_empty():
    df = frame([1, 0], [1, 1], [1, 1])
    assert rep.pairwise_significance(df, "nope", df["flag"] == 1).empty
