"""Shared conventions for the financial EDA. Single source of truth.

What it does
------------
Pins the vintage and dataset, cleans ACS suppression sentinels, and
converts MOE to CV. Every financial-track script and notebook reads these
rather than redefining them, so a convention change happens in one place.

CV convention
-------------
CONFIRMED against analysis/acs.py, which notebooks 01-07 already use:

    SE = MOE / 1.645        1.645 is the 90% normal multiplier; ACS
                            publishes MOEs at 90% confidence.
    CV = SE / estimate      NaN where the estimate is missing or <= 0.

`moe_to_cv` delegates to `acs.cv` rather than restating the formula, so
the two cannot drift apart. The proposal asked to confirm this matches
what 07 used -- it does; 07 imports `analysis.cv_model`, which is not yet
committed, but `acs.cv` is what 06 calls directly and what `cv_model` was
built on top of.

MOE aggregation already exists as `acs.aggregate_moe`, including the
Handbook zero-cell rule. Do NOT reimplement it in analysis/derive.py --
import it.

Bracket bounds
--------------
B19001's 16 bracket bounds are recorded here as data, verified against the
live API at BOTH vintage 2023 and 2024 (identical -- the bins are nominal
dollars; only the concept string's inflation-adjustment year changes).
`median_moe` takes bounds as an argument rather than hardcoding them, so a
future vintage that does move the bins fails loudly instead of silently.

What it needs
-------------
numpy, pandas. No I/O of its own.

Run the tests:
    python -m pytest tests/test_common.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import acs  # noqa: E402  -- path set above

# ---------------------------------------------------------------------------
# Vintage and dataset -- change here, nowhere else
# ---------------------------------------------------------------------------

ACS_VINTAGE = 2024          # matches analysis/acs.py and ingestion/pull_acs_*.py
ACS_DATASET = "acs/acs5"
PUMS_DATASET = "acs/acs5/pums"

SAIPE_ENDPOINT = "https://api.census.gov/data/timeseries/poverty/saipe"
SAIPE_YEARS = list(range(2019, 2025))   # all six VERIFIED to serve, 3,142-3,144 rows

STATE_NJ = "34"

Z_90 = acs.Z_90                          # 1.645 -- do not redefine
INCOME_TOP_CODE = acs.INCOME_TOP_CODE    # 250_001

# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------

# ACS returns giant negative annotation codes in place of real values. They
# are not data and must never enter an arithmetic path. Same cutoff and map
# as ingestion/pull_acs_alloc_nj.py.
ANNOTATION_CUTOFF = -111111111
KNOWN_ANNOTATIONS = {
    -555555555: "controlled estimate -- no sampling-error MOE published",
    -666666666: "estimate not computed (insufficient sample observations)",
    -999999999: "estimate not applicable or not available",
    -222222222: "estimate not computed (too few sample observations)",
    -333333333: "estimate not computed (ratio of medians undefined)",
}

# ---------------------------------------------------------------------------
# B19001 brackets -- VERIFIED, vintages 2023 and 2024, identical
# ---------------------------------------------------------------------------

# (cell, lower, upper). Upper is None for the open-ended top bracket.
# 16 brackets. B19001_001E is the universe TOTAL and is not in this list --
# the proposal's "17 bracket counts" counts the total row as a bracket.
B19001_BRACKETS = [
    ("B19001_002E", 0, 9_999),
    ("B19001_003E", 10_000, 14_999),
    ("B19001_004E", 15_000, 19_999),
    ("B19001_005E", 20_000, 24_999),
    ("B19001_006E", 25_000, 29_999),
    ("B19001_007E", 30_000, 34_999),
    ("B19001_008E", 35_000, 39_999),
    ("B19001_009E", 40_000, 44_999),
    ("B19001_010E", 45_000, 49_999),
    ("B19001_011E", 50_000, 59_999),
    ("B19001_012E", 60_000, 74_999),
    ("B19001_013E", 75_000, 99_999),
    ("B19001_014E", 100_000, 124_999),
    ("B19001_015E", 125_000, 149_999),
    ("B19001_016E", 150_000, 199_999),
    ("B19001_017E", 200_000, None),      # OPEN-ENDED -- flag, never impute
]
B19001_TOTAL = "B19001_001E"


def bracket_widths() -> list[int | None]:
    """Dollar width of each bracket; None for the open-ended top.

    Widths are irregular -- $5,000 through $50,000 -- which is why
    bracket_width is a per-tract driver in Track A rather than a constant.
    """
    return [None if hi is None else hi - lo + 1 for _, lo, hi in B19001_BRACKETS]


# ---------------------------------------------------------------------------
# Cleaners
# ---------------------------------------------------------------------------

def clean_sentinels(
    df: pd.DataFrame, columns: list[str] | None = None
) -> pd.DataFrame:
    """Replace ACS annotation sentinels with NaN, on a copy.

    Suppression reaches us two ways: as a giant negative sentinel (raw API
    responses) and already as null (censusdis converts some of them). One
    cleaner handles both so no script has to know which path its data took.

    `columns` defaults to every numeric-looking column ending in E or M.
    Non-numeric columns are coerced with errors="coerce", so a stray string
    becomes NaN rather than raising.
    """
    out = df.copy()
    if columns is None:
        columns = [
            c for c in out.columns
            if isinstance(c, str) and c.endswith(("E", "M")) and "_" in c
        ]
    for col in columns:
        if col not in out.columns:
            continue
        s = pd.to_numeric(out[col], errors="coerce")
        out[col] = s.mask(s <= ANNOTATION_CUTOFF)
    return out


def sentinel_report(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Per-column count of sentinels and nulls, BEFORE cleaning.

    Suppression prevalence is a finding in its own right, not just a data
    problem -- run this before clean_sentinels and keep the output.
    """
    if columns is None:
        columns = [
            c for c in df.columns
            if isinstance(c, str) and c.endswith(("E", "M")) and "_" in c
        ]
    rows = []
    for col in columns:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        sentinel = s.notna() & (s <= ANNOTATION_CUTOFF)
        codes = sorted(int(v) for v in s[sentinel].unique())
        rows.append({
            "column": col,
            "n": len(s),
            "null": int(s.isna().sum()),
            "sentinel": int(sentinel.sum()),
            "codes": codes,
        })
    return pd.DataFrame(rows)


def moe_to_cv(estimate, moe):
    """Coefficient of variation: (MOE / 1.645) / estimate.

    Delegates to acs.cv so the convention cannot drift. NaN where the
    estimate is 0, negative, or null, and where the MOE is null.

    Accepts Series or scalars; scalars come back as float (NaN where
    undefined) rather than a one-element Series.
    """
    scalar = not isinstance(estimate, pd.Series)
    est = pd.Series([estimate], dtype="float64") if scalar else estimate
    m = pd.Series([moe], dtype="float64") if not isinstance(moe, pd.Series) else moe
    est = pd.to_numeric(est, errors="coerce")
    m = pd.to_numeric(m, errors="coerce")
    est = est.mask(est <= ANNOTATION_CUTOFF)
    m = m.mask(m <= ANNOTATION_CUTOFF)
    result = acs.cv(est, m)
    return float(result.iloc[0]) if scalar else result


def half_width(lower, upper):
    """SAIPE 90% interval -> comparable half-width: (UB90 - LB90) / 2.

    SAIPE also publishes SAEMHI_MOE / SAEPOVRTALL_MOE directly. Pull both
    and compare -- agreement validates this derivation, disagreement is
    itself the Track B finding about what a model-based interval covers.
    """
    lo = pd.to_numeric(lower, errors="coerce")
    hi = pd.to_numeric(upper, errors="coerce")
    return (hi - lo) / 2.0


__all__ = [
    "ACS_VINTAGE", "ACS_DATASET", "PUMS_DATASET", "SAIPE_ENDPOINT",
    "SAIPE_YEARS", "STATE_NJ", "Z_90", "INCOME_TOP_CODE",
    "ANNOTATION_CUTOFF", "KNOWN_ANNOTATIONS",
    "B19001_BRACKETS", "B19001_TOTAL", "bracket_widths",
    "clean_sentinels", "sentinel_report", "moe_to_cv", "half_width",
]
