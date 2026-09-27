"""Shared helpers for ACS allocation (imputation) rates.

What it does
------------
Loads the parquet files produced by ingestion/pull_acs_alloc_nj.py and
derives item allocation rates as fractions in [0, 1]. Keeping the rate
formulas here means EDA 05 and later composite-score work use the same
definitions.

What it needs
-------------
data/raw/acs5_2024_nj_alloc_{county,tract,block_group}.parquet on disk
(regenerate with: python ingestion/pull_acs_alloc_nj.py).

Rate definitions (plain English first)
--------------------------------------
- sex/age/race allocation = allocated / total
- income_alloc = 1 - (households with no income allocated / total households)
  i.e. share of households with any income imputed
- fam_pov_alloc = 1 - (families with no income allocated / total families)
  LABELLED PROXY: family universe, not person-level poverty
- overall_alloc = B98031 / 100 (published percent; county-only values)

Rates are NaN where the denominator is 0 or missing — same convention as
undefined CVs at zero estimates.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from analysis.acs import LEVELS, VINTAGE

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"

RATE_COLUMNS = [
    "overall_alloc",
    "sex_alloc",
    "age_alloc",
    "race_alloc",
    "demo_mean_alloc",
    "income_alloc",
    "fam_pov_alloc",
]

# fam_pov_alloc uses the family-universe table B99172 as a labeled proxy for
# person-level poverty completeness (no person-level poverty allocation table).
PROXY_RATES = frozenset({"fam_pov_alloc"})


def load_level(level: str) -> pd.DataFrame:
    """Load one geography level's allocation pull with numeric B9* columns."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    path = RAW_DIR / f"acs5_{VINTAGE}_nj_alloc_{level}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_acs_alloc_nj.py"
        )
    df = pd.read_parquet(path)
    value_cols = [c for c in df.columns if c.startswith("B9")]
    df[value_cols] = df[value_cols].apply(pd.to_numeric, errors="coerce")
    return df


def safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divide with NaN where the denominator is missing or <= 0."""
    return numerator / denominator.where(denominator > 0)


def derive_rates(df: pd.DataFrame) -> pd.DataFrame:
    """Add allocation-rate columns (fractions 0-1) to an allocation dataframe.

    Preserves EDA 05 formulas exactly. Returns a copy with rate columns added.
    """
    out = df.copy()
    out["sex_alloc"] = safe_div(out["B99011_002E"], out["B99011_001E"])
    out["age_alloc"] = safe_div(out["B99012_002E"], out["B99012_001E"])
    out["race_alloc"] = safe_div(out["B99021_002E"], out["B99021_001E"])
    out["demo_mean_alloc"] = out[["sex_alloc", "age_alloc", "race_alloc"]].mean(axis=1)
    out["income_alloc"] = 1 - safe_div(out["B99192_002E"], out["B99192_001E"])
    out["fam_pov_alloc"] = 1 - safe_div(
        out["B99172_002E"] + out["B99172_009E"], out["B99172_001E"]
    )
    out["overall_alloc"] = out["B98031_001E"] / 100  # published as a percent
    return out
