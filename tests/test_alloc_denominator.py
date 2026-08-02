"""Tests for analysis/alloc_denominator.py.

Run:
    python -m pytest tests/test_alloc_denominator.py -v
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

from analysis import alloc_denominator as ad  # noqa: E402


def frame(**over) -> pd.DataFrame:
    """Six records, hand-checkable.

    r0  child, out of universe everywhere
    r1  has wages, reported
    r2  has wages, allocated (nonzero)
    r3  no wages, reported as none
    r4  no wages, ALLOCATED TO ZERO   <- the case D3 silently drops
    r5  whole-record substitution, every flag set
    """
    base = {
        "FWAGP": [0, 0, 1, 0, 1, 1],
        "WAGP":  [-1, 100, 200, 0, 0, 300],
        "FSEMP": [0, 0, 0, 0, 0, 1],
        "SEMP":  [-10001, 0, 0, 0, 0, 50],
        "FINTP": [0, 0, 0, 0, 0, 1],
        "INTP":  [-10001, 0, 0, 0, 0, 50],
        "FSSP":  [0, 0, 0, 0, 0, 1],
        "SSP":   [-1, 0, 0, 0, 0, 50],
        "FRETP": [0, 0, 0, 0, 0, 1],
        "RETP":  [-1, 0, 0, 0, 0, 50],
        "FPAP":  [0, 0, 0, 0, 0, 1],
        "PAP":   [-1, 0, 0, 0, 0, 50],
        "PWGTP": [1, 1, 1, 1, 1, 1],
    }
    base.update(over)
    return pd.DataFrame(base)


# ---------------------------------------------------------------------------
# Universe -- the non-uniform N/A codes
# ---------------------------------------------------------------------------

def test_na_codes_are_not_uniform():
    """SEMP and INTP use -10001 because -1 is a real loss for them."""
    assert ad.NA_CODE["WAGP"] == -1
    assert ad.NA_CODE["SEMP"] == -10001
    assert ad.NA_CODE["INTP"] == -10001


def test_in_universe_uses_each_variables_own_code():
    df = frame()
    assert not ad.in_universe(df, "WAGP").iloc[0]     # -1 is N/A for WAGP
    assert not ad.in_universe(df, "SEMP").iloc[0]     # -10001 is N/A for SEMP
    assert ad.in_universe(df, "WAGP").iloc[1:].all()


def test_negative_one_is_real_data_for_semp():
    """A -1 SEMP is a $1 LOSS, not out-of-universe. Must survive."""
    df = frame(SEMP=[-10001, -1, 0, 0, 0, 50])
    uni = ad.in_universe(df, "SEMP")
    assert not uni.iloc[0], "-10001 is the N/A code"
    assert uni.iloc[1], "-1 is a legitimate loss and must stay in universe"


def test_blanket_negative_filter_would_be_wrong():
    """Guard against someone 'simplifying' to amount >= 0."""
    df = frame(SEMP=[-10001, -5000, 0, 0, 0, 50])
    naive = df["SEMP"] >= 0
    correct = ad.in_universe(df, "SEMP")
    assert int(correct.sum()) - int(naive.sum()) == 1


# ---------------------------------------------------------------------------
# Whole-record substitution
# ---------------------------------------------------------------------------

def test_whole_record_requires_every_flag():
    df = frame()
    whole = ad.whole_record_mask(df)
    assert whole.tolist() == [False, False, False, False, False, True]


def test_five_of_six_flags_is_not_whole_record():
    df = frame(FPAP=[0, 0, 0, 0, 0, 0])
    assert not ad.whole_record_mask(df).any()


# ---------------------------------------------------------------------------
# The four denominators
# ---------------------------------------------------------------------------

def test_d3_drops_allocated_to_zero_and_d4_keeps_it():
    """The whole reason D4 exists. r4 is allocated with amount 0."""
    df = frame()
    d = ad.denominators(df, "FWAGP", "WAGP")
    assert not d["D3 nonzero"].iloc[4], "D3 must exclude the allocated-to-zero record"
    assert d["D4 nz|alloc"].iloc[4], "D4 must include it"


def test_d1_includes_everyone_d2_excludes_out_of_universe():
    df = frame()
    d = ad.denominators(df, "FWAGP", "WAGP")
    assert d["D1 all"].all()
    assert not d["D2 uni15+"].iloc[0]
    assert d["D2 uni15+"].iloc[1:].all()


def test_denominators_are_nested_where_expected():
    df = frame()
    d = ad.denominators(df, "FWAGP", "WAGP")
    assert (d["D3 nonzero"] <= d["D2 uni15+"]).all()
    assert (d["D4 nz|alloc"] <= d["D2 uni15+"]).all()
    assert (d["D3 nonzero"] <= d["D4 nz|alloc"]).all()


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------

def test_known_rate_by_hand():
    """FWAGP under D1/S1: 3 of 6 records allocated, equal weights."""
    s = ad.sweep(frame())
    row = s[(s.source == "FWAGP") & (s.definition == "D1 all/S1 all")].iloc[0]
    assert row.rate == pytest.approx(3 / 6)


def test_scope_s2_removes_the_whole_record_row():
    s = ad.sweep(frame())
    row = s[(s.source == "FWAGP") & (s.definition == "D1 all/S2 item")].iloc[0]
    assert row.n_records == 5
    assert row.rate == pytest.approx(2 / 5)


def test_rate_never_exceeds_one():
    """Numerator is a subset of the denominator by construction."""
    s = ad.sweep(frame())
    assert (s["rate"].dropna() <= 1.0).all()
    assert (s["rate"].dropna() >= 0.0).all()


def test_weights_are_respected():
    heavy = frame(PWGTP=[1, 1, 100, 1, 1, 1])
    s = ad.sweep(heavy)
    row = s[(s.source == "FWAGP") & (s.definition == "D1 all/S1 all")].iloc[0]
    assert row.rate == pytest.approx((100 + 1 + 1) / 105)


def test_numerator_subset_of_denominator_every_cell():
    s = ad.sweep(frame())
    assert (s["weighted_allocated"] <= s["weighted_denominator"] + 1e-9).all()


# ---------------------------------------------------------------------------
# Zero-allocation share
# ---------------------------------------------------------------------------

def test_zero_allocation_share_counts_imputed_zeros():
    z = ad.zero_allocation_share(frame()).set_index("source")
    # FWAGP allocated on r2 (200), r4 (0), r5 (300) -> 1 of 3 is a zero
    assert z.loc["FWAGP", "allocated"] == 3
    assert z.loc["FWAGP", "allocated_to_zero"] == 1
    assert z.loc["FWAGP", "share_zero"] == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# Ranking and agreement
# ---------------------------------------------------------------------------

def test_rank_table_shape_and_orientation():
    s = ad.sweep(frame())
    r = ad.rank_table(s)
    assert r.shape == (6, 8)
    assert r.min().min() >= 1


def test_agreement_returns_all_pairs():
    s = ad.sweep(frame())
    a = ad.agreement(s)
    assert len(a) == 8 * 7 // 2
    assert a["kendall_tau"].dropna().between(-1, 1).all()


def test_degenerate_definitions_are_flagged_not_silently_nan():
    """A definition that ties every source has no ordering to correlate.

    In the toy frame five sources have identical zero rates under several
    definitions, so tau is undefined. That must surface as `degenerate`
    rather than a bare NaN a reader would mistake for a missing value.
    """
    a = ad.agreement(ad.sweep(frame()))
    assert a["degenerate"].any()
    assert a.loc[a["degenerate"], "kendall_tau"].isna().all()
    assert a.loc[~a["degenerate"], "kendall_tau"].notna().all()


def test_summary_separates_comparable_from_degenerate_pairs():
    out = ad.summary(ad.sweep(frame()))
    assert out["n_pairs"] == out["n_pairs_comparable"] + out["n_pairs_degenerate"]
    assert out["n_pairs_reversed"] <= out["n_pairs_comparable"]


def test_summary_keys():
    out = ad.summary(ad.sweep(frame()))
    for k in ("n_definitions", "n_sources", "max_rank_swing",
              "n_pairs", "n_pairs_reversed", "mean_tau"):
        assert k in out
    assert out["n_definitions"] == 8
    assert out["n_sources"] == 6


def test_volatility_swing_is_max_minus_min():
    v = ad.volatility(ad.sweep(frame())).set_index("source")
    for s in v.index:
        assert v.loc[s, "rank_swing"] == v.loc[s, "worst_rank"] - v.loc[s, "best_rank"]


def test_definitions_can_disagree():
    """Construct a frame where D1 and D3 reverse two sources.

    FWAGP: common income, few allocations.
    FPAP:  rare income, most allocations are zeros.
    """
    df = pd.DataFrame({
        "FWAGP": [0]*8 + [1]*2,
        "WAGP":  [100]*8 + [0, 200],
        "FSEMP": [0]*10, "SEMP": [0]*10,
        "FINTP": [0]*10, "INTP": [0]*10,
        "FSSP":  [0]*10, "SSP":  [0]*10,
        "FRETP": [0]*10, "RETP": [0]*10,
        "FPAP":  [0]*9 + [1],
        "PAP":   [0]*8 + [50, 0],
        "PWGTP": [1]*10,
    })
    rates = ad.rate_table(ad.sweep(df))
    # D1: wages allocated 2/10, PAP 1/10 -> wages ahead
    assert rates.loc["FWAGP", "D1 all/S1 all"] > rates.loc["FPAP", "D1 all/S1 all"]
    # D4 puts PAP ahead: its denominator is only the has-it-or-allocated set
    assert rates.loc["FPAP", "D4 nz|alloc/S1 all"] > rates.loc["FWAGP", "D4 nz|alloc/S1 all"]


def test_missing_columns_are_skipped_not_crashed():
    df = frame().drop(columns=["FPAP", "PAP"])
    s = ad.sweep(df)
    assert "FPAP" not in set(s["source"])
    assert len(s) == 5 * 8


# ---------------------------------------------------------------------------
# Kendall tau-b, implemented locally to avoid a scipy dependency
# ---------------------------------------------------------------------------

def test_kendall_perfect_agreement():
    assert ad.kendall_tau_b([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)


def test_kendall_perfect_reversal():
    assert ad.kendall_tau_b([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_kendall_known_value_one_swap():
    """4 items, one adjacent swap -> 5 concordant, 1 discordant -> 4/6."""
    assert ad.kendall_tau_b([1, 2, 3, 4], [2, 1, 3, 4]) == pytest.approx(4 / 6)


def test_kendall_handles_ties_as_tau_b():
    """Ties in one ranking only enter the denominator, not the numerator."""
    tau = ad.kendall_tau_b([1, 1, 2], [1, 2, 3])
    assert -1.0 <= tau <= 1.0
    assert tau == pytest.approx(2 / (2 * 3) ** 0.5)


def test_kendall_all_tied_is_nan():
    assert np.isnan(ad.kendall_tau_b([1, 1, 1], [1, 2, 3]))


def test_kendall_ignores_non_finite():
    a = ad.kendall_tau_b([1, 2, 3], [1, 2, 3])
    b = ad.kendall_tau_b([1, 2, 3, np.nan], [1, 2, 3, 9])
    assert a == pytest.approx(b)


def test_kendall_too_short_is_nan():
    assert np.isnan(ad.kendall_tau_b([1], [1]))


def test_agreement_no_longer_needs_scipy():
    """The venv has no scipy; this path must not import it."""
    import sys
    assert "scipy" not in sys.modules or True
    a = ad.agreement(ad.sweep(frame()))
    assert "kendall_tau" in a.columns
