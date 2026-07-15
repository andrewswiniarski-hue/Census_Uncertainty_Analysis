"""Shared helpers for working with the project's ACS pull.

What it does
------------
Loads the parquet files produced by ingestion/pull_acs_nj.py and provides
the small, formula-bearing functions the EDA notebooks share: coefficient
of variation (CV), top-code flagging, and MOE aggregation. Keeping the
formulas here means every notebook computes them identically and each
formula's citation lives in exactly one place.

What it needs
-------------
data/raw/acs5_2024_nj_{county,tract,block_group}.parquet on disk
(regenerate with: python ingestion/pull_acs_nj.py).

Formulas and sources
--------------------
- SE = MOE / 1.645          ACS MOEs are published at 90% confidence;
                            1.645 is the 90% normal multiplier.
- CV = SE / estimate        Undefined (NaN) when the estimate is 0 or missing.
  Source for both: U.S. Census Bureau, "American Community Survey:
  Accuracy of the Data" (any recent vintage).
- MOE_agg = sqrt(sum(MOE_i^2))   for a sum of estimates.
  Source: U.S. Census Bureau, "Understanding and Using American Community
  Survey Data: What All Data Users Need to Know," Ch. 8 ("Calculating
  Measures of Error for Derived Estimates"). Approximate: it assumes the
  component estimates are independent, which the handbook notes tends to
  overstate the combined MOE for same-table cells.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"

VINTAGE = 2024
LEVELS = ["county", "tract", "block_group"]

# Same codes and working names as ingestion/pull_acs_nj.py.
VARIABLES = {
    "B01003_001": "Total population",
    "B19013_001": "Median household income",
    "B17001_002": "People below poverty level",
    "B01001B_014": "Black male 65-74",
    "B01001B_015": "Black male 75-84",
    "B01001B_016": "Black male 85+",
    "B01001B_029": "Black female 65-74",
    "B01001B_030": "Black female 75-84",
    "B01001B_031": "Black female 85+",
}

# The six cells that sum to "Black or African American alone, 65+".
BLACK_65PLUS_CELLS = [v for v in VARIABLES if v.startswith("B01001B")]

Z_90 = 1.645  # 90%-confidence multiplier (ACS "Accuracy of the Data")

# ACS publishes median household income above $250k as exactly 250,001
# ("top-coding" -- see docs/glossary.md).
INCOME_TOP_CODE = 250_001


def load_level(level: str) -> pd.DataFrame:
    """Load one geography level's ACS pull with numeric E/M columns.

    `level` is one of LEVELS. Raises FileNotFoundError with a regeneration
    hint if the parquet is missing.
    """
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    path = RAW_DIR / f"acs5_{VINTAGE}_nj_{level}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_acs_nj.py"
        )
    df = pd.read_parquet(path)
    value_cols = [c for c in df.columns if c[:-1] in VARIABLES]
    df[value_cols] = df[value_cols].apply(pd.to_numeric, errors="coerce")
    return df


def cv(estimate: pd.Series, moe: pd.Series) -> pd.Series:
    """Coefficient of variation: (MOE / 1.645) / estimate.

    NaN where the estimate is missing or <= 0 (CV is undefined at zero --
    a zero count carries no scale to be 'relative' to) or the MOE is
    missing. Missing MOEs are ambiguous in this dataset: censusdis turns
    both 'controlled estimate' (very reliable) and 'insufficient sample'
    (unreliable) annotation codes into NaN. See docs/glossary.md.
    """
    se = moe / Z_90
    result = se / estimate.where(estimate > 0)
    return result.rename(None)


def add_cv(df: pd.DataFrame, var: str) -> pd.DataFrame:
    """Add a `{var}_CV` column computed from `{var}E` and `{var}M`."""
    df[f"{var}_CV"] = cv(df[f"{var}E"], df[f"{var}M"])
    return df


def flag_topcoded_income(df: pd.DataFrame) -> pd.Series:
    """True where median household income is top-coded (published as 250,001).

    Top-coded values are censored, not measured; their CVs are not
    comparable and should be excluded from CV distributions (flag first,
    report the count).
    """
    return df["B19013_001E"] == INCOME_TOP_CODE


def aggregate_moe(df: pd.DataFrame, variables: list[str]) -> pd.Series:
    """Root-sum-of-squares MOE for a sum of estimates (see module docstring).

    `variables` are codes without the E/M suffix. Rows where any component
    MOE is missing return NaN rather than a silently-partial aggregate.
    """
    moes = df[[f"{v}M" for v in variables]]
    return pd.Series(np.sqrt((moes**2).sum(axis=1, min_count=len(variables))),
                     index=df.index)


def cv_long(df: pd.DataFrame, variables: list[str], level: str) -> pd.DataFrame:
    """Tidy long-format CV table: one row per (geography, variable).

    Columns: level, variable (working name), code, estimate, moe, cv.
    Convenient for grouped summaries and plotting across variables/levels.
    """
    frames = []
    for code in variables:
        frames.append(pd.DataFrame({
            "level": level,
            "variable": VARIABLES[code],
            "code": code,
            "estimate": df[f"{code}E"],
            "moe": df[f"{code}M"],
            "cv": cv(df[f"{code}E"], df[f"{code}M"]),
        }))
    return pd.concat(frames, ignore_index=True)
