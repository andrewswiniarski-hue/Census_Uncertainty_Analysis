"""Tests for analysis/alloc_profile.py.

Run:
    python -m pytest tests/test_alloc_profile.py -v
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

from analysis import alloc_profile as ap  # noqa: E402

FLAGS = ["FWAGP", "FSEMP", "FINTP", "FSSP", "FRETP", "FPAP"]
AMOUNTS = {"FWAGP": "WAGP", "FSEMP": "SEMP", "FINTP": "INTP",
           "FSSP": "SSP", "FRETP": "RETP", "FPAP": "PAP"}
NA = {"WAGP": -1, "SEMP": -10001, "INTP": -10001,
      "SSP": -1, "RETP": -1, "PAP": -1}


def make(n_flags_per_row, ages, sexes=None, schl=None, weights=None):
    """Build a frame with a given number of flags set per row."""
    n = len(n_flags_per_row)
    d = {}
    for i, f in enumerate(FLAGS):
        d[f] = [1 if i < k else 0 for k in n_flags_per_row]
    for f, a in AMOUNTS.items():
        # Out of universe iff under 15.
        d[a] = [NA[a] if age < 15 else 0 for age in ages]
    d["AGEP"] = ages
    d["SEX"] = sexes if sexes is not None else [1] * n
    d["SCHL"] = schl if schl is not None else [21] * n
    d["PWGTP"] = weights if weights is not None else [1] * n
    return pd.DataFrame(d)


# ---------------------------------------------------------------------------
# Outcomes are denominator-free
# ---------------------------------------------------------------------------

def test_outcomes_are_per_record_counts():
    df = ap.add_outcomes(make([0, 1, 3, 6], [30, 30, 30, 30]))
    assert df["n_items_allocated"].tolist() == [0, 1, 3, 6]
    assert df["any_allocated"].tolist() == [False, True, True, True]
    assert df["whole_record"].tolist() == [False, False, False, True]


def test_whole_record_requires_all_six():
    df = ap.add_outcomes(make([5, 6], [40, 40]))
    assert df["whole_record"].tolist() == [False, True]


# ---------------------------------------------------------------------------
# Universe guards -- the ones that would manufacture a false finding
# ---------------------------------------------------------------------------

def test_children_are_excluded_from_the_income_universe():
    """Under-15s carry flag 0 by construction. Including them would
    manufacture 'young people have less allocated data'."""
    df = make([0, 0, 6, 6], [5, 10, 30, 40])
    prepared = ap.prepare(df)
    assert len(prepared) == 2
    assert (prepared["AGEP"] >= 15).all()


def test_including_children_would_flip_the_age_story():
    """Guard against someone removing the universe restriction."""
    df = make([0] * 20 + [6] * 20, [8] * 20 + [30] * 20)
    unrestricted = ap.prepare(df, restrict_universe=False)
    restricted = ap.prepare(df)
    assert unrestricted["whole_record"].mean() == pytest.approx(0.5)
    assert restricted["whole_record"].mean() == pytest.approx(1.0)


def test_income_universe_falls_back_to_age_without_amount_columns():
    df = make([0, 6], [10, 40]).drop(columns=list(AMOUNTS.values()))
    uni = ap.income_universe(df)
    assert uni.tolist() == [False, True]


def test_education_restricted_to_25_plus():
    """SCHL for a teenager measures age, not attainment."""
    df = make([0, 0], [18, 40], schl=[16, 16])
    out = ap.add_demographics(df)
    assert pd.isna(out["education"].iloc[0])
    assert out["education"].iloc[1] == "HS diploma or GED"


# ---------------------------------------------------------------------------
# Banding
# ---------------------------------------------------------------------------

def test_age_bands_are_contiguous_and_cover_15_up():
    lo_hi = [(lo, hi) for lo, hi, _ in ap.AGE_BANDS]
    assert lo_hi[0][0] == ap.INCOME_UNIVERSE_AGE
    for (_, hi), (lo_next, _) in zip(lo_hi, lo_hi[1:]):
        assert lo_next == hi + 1


def test_band_labels_expected_values():
    s = pd.Series([15, 24, 25, 64, 65, 90])
    out = ap.band(s, ap.AGE_BANDS)
    assert out.tolist() == ["15-24", "15-24", "25-34", "55-64", "65-74", "75+"]


def test_band_returns_na_outside_every_band():
    out = ap.band(pd.Series([5, 14]), ap.AGE_BANDS)
    assert out.isna().all()


def test_sex_maps_to_labels():
    out = ap.add_demographics(make([0, 0], [30, 30], sexes=[1, 2]))
    assert out["sex"].tolist() == ["Male", "Female"]


def test_education_bands_cover_the_schl_range():
    covered = set()
    for lo, hi, _ in ap.EDUCATION_BANDS:
        covered |= set(range(lo, hi + 1))
    assert set(range(1, 25)) <= covered


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def test_profile_weighted_shares_by_hand():
    # 200 people 25-34: 100 whole-record, 100 clean. Weight 1.
    df = make([6] * 100 + [0] * 100, [30] * 200)
    prof = ap.profile(ap.prepare(df), "age_band")
    row = prof[prof.level == "25-34"].iloc[0]
    assert row.share_whole_record == pytest.approx(0.5)
    assert row.share_any_allocated == pytest.approx(0.5)
    assert row.mean_items_allocated == pytest.approx(3.0)


def test_profile_respects_weights():
    df = make([6] * 100 + [0] * 100, [30] * 200,
              weights=[9] * 100 + [1] * 100)
    row = ap.profile(ap.prepare(df), "age_band").iloc[0]
    assert row.share_whole_record == pytest.approx(0.9)


def test_thin_groups_are_suppressed():
    """A rate on 20 records is noise wearing a percent sign."""
    df = make([6] * 20 + [0] * 200, [30] * 20 + [40] * 200)
    prof = ap.profile(ap.prepare(df), "age_band", min_records=100)
    assert "25-34" not in set(prof["level"])
    assert "35-44" in set(prof["level"])


def test_profile_returns_empty_for_missing_characteristic():
    assert ap.profile(ap.prepare(make([0], [30])), "nope").empty


def test_profile_all_stacks_available_characteristics():
    df = make([6] * 150 + [0] * 150, [30] * 300, sexes=[1] * 150 + [2] * 150)
    out = ap.profile_all(ap.prepare(df))
    assert set(out["characteristic"]) == {"age_band", "sex", "education"}


# ---------------------------------------------------------------------------
# Spread
# ---------------------------------------------------------------------------

def test_spread_reports_fold_and_extremes():
    df = make([6] * 150 + [0] * 150, [30] * 150 + [50] * 150)
    sp = ap.spread(ap.profile(ap.prepare(df), "age_band"))
    row = sp.iloc[0]
    assert row.highest_level == "25-34"
    assert row.lowest_level == "45-54"
    assert row["min"] == pytest.approx(0.0)
    assert np.isinf(row.fold)


def test_spread_fold_is_one_when_groups_are_identical():
    """No difference between groups is a result, not a failure."""
    df = make(([6] * 75 + [0] * 75) * 2, [30] * 150 + [50] * 150)
    sp = ap.spread(ap.profile(ap.prepare(df), "age_band"))
    assert sp.iloc[0].fold == pytest.approx(1.0)


def test_spread_empty_input():
    assert ap.spread(pd.DataFrame()).empty
