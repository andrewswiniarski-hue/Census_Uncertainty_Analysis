"""Shared helpers for JL_Analysis EDA notebooks."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
VINTAGE = 2024

# Mirror ingestion/pull_acs_nj.py variable definitions.
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

VARIABLE_GROUPS = {
    "population": ["B01003_001"],
    "income": ["B19013_001"],
    "poverty": ["B17001_002"],
    "subgroup": [
        "B01001B_014",
        "B01001B_015",
        "B01001B_016",
        "B01001B_029",
        "B01001B_030",
        "B01001B_031",
    ],
}

GEO_LEVELS = ["county", "tract", "block_group"]
GEO_LABELS = {
    "county": "County",
    "tract": "Census tract",
    "block_group": "Block group",
}

# ACS annotation codes (censusdis converts these to NaN in our parquet files).
ANNOTATION_CUTOFF = -111111111
INCOME_TOP_CODE = 250_001
MOE_TO_SE = 1.645  # ACS MOEs are 90% confidence intervals.


def annotation_mask(series: pd.Series) -> pd.Series:
    """True where a value is an ACS annotation code rather than real data."""
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.notna() & (numeric <= ANNOTATION_CUTOFF)


def load_acs(level: str) -> pd.DataFrame:
    """Load one ACS parquet file for New Jersey."""
    path = RAW_DIR / f"acs5_{VINTAGE}_nj_{level}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing ACS file: {path}")
    return pd.read_parquet(path)


def load_geo(level: str) -> gpd.GeoDataFrame:
    """Load one geometry parquet file for New Jersey."""
    path = RAW_DIR / f"geo_{VINTAGE}_nj_{level}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing geometry file: {path}")
    return gpd.read_parquet(path)


def estimate_moe_cols(var_code: str) -> tuple[str, str]:
    return f"{var_code}E", f"{var_code}M"


def is_valid_for_cv(
    estimate: pd.Series,
    moe: pd.Series,
    *,
    var_code: str,
) -> pd.Series:
    """Mask of rows where CV is meaningful (excludes landmines from HANDOFF.md)."""
    est = pd.to_numeric(estimate, errors="coerce")
    moe_num = pd.to_numeric(moe, errors="coerce")
    valid = est.notna() & moe_num.notna() & (est > 0) & (moe_num >= 0)
    valid &= ~annotation_mask(est) & ~annotation_mask(moe_num)
    if var_code == "B19013_001":
        valid &= est != INCOME_TOP_CODE
    return valid


def compute_cv(
    estimate: pd.Series,
    moe: pd.Series,
    *,
    var_code: str,
) -> pd.Series:
    """CV = (MOE / 1.645) / estimate for valid rows; NaN elsewhere."""
    valid = is_valid_for_cv(estimate, moe, var_code=var_code)
    est = pd.to_numeric(estimate, errors="coerce")
    moe_num = pd.to_numeric(moe, errors="coerce")
    se = moe_num / MOE_TO_SE
    cv = se / est
    return cv.where(valid)


def combine_moes_rss(
    estimates: pd.Series | pd.DataFrame,
    moes: pd.Series | pd.DataFrame,
) -> tuple[pd.Series | float, pd.Series | float]:
    """Sum estimates and combine MOEs by root-sum-of-squares.

    The Census Bureau's standard formula for a summed estimate is to add the
    estimates and combine their MOEs as sqrt(sum(MOE_i^2)). A row is only
    combined when every estimate/MOE pair is present and valid; otherwise the
    combined estimate and MOE are set to missing to avoid understated uncertainty.
    """
    if isinstance(estimates, pd.DataFrame) and isinstance(moes, pd.DataFrame):
        if estimates.shape != moes.shape:
            raise ValueError("Estimate and MOE inputs must have the same shape.")
        expected_moe_cols = [
            f"{col[:-1]}M"
            for col in estimates.columns
            if isinstance(col, str) and col.endswith("E")
        ]
        if expected_moe_cols and list(moes.columns) != expected_moe_cols:
            raise ValueError("MOE columns must match the estimate-column order.")
        est_num = estimates.apply(pd.to_numeric, errors="coerce")
        moe_num = moes.apply(pd.to_numeric, errors="coerce")
        # Estimate columns end in E and MOE columns end in M, so pair by position.
        moe_num = moe_num.set_axis(est_num.columns, axis=1)
        valid_pair = (
            est_num.notna()
            & moe_num.notna()
            & ~est_num.apply(annotation_mask)
            & ~moe_num.apply(annotation_mask)
            & (moe_num >= 0)
        )
        complete_row = valid_pair.all(axis=1)
        combined_estimate = (
            est_num.sum(axis=1).where(complete_row).rename("combined_estimate")
        )
        combined_moe = (
            np.sqrt((moe_num**2).sum(axis=1))
            .where(complete_row)
            .rename("combined_moe")
        )
        return combined_estimate, combined_moe

    if isinstance(estimates, pd.DataFrame) or isinstance(moes, pd.DataFrame):
        raise TypeError("Estimates and MOEs must both be DataFrames or both be Series.")

    est_num = pd.to_numeric(estimates, errors="coerce")
    moe_num = pd.to_numeric(moes, errors="coerce")
    if len(est_num) != len(moe_num):
        raise ValueError("Estimate and MOE inputs must have the same length.")
    valid_pair = (
        est_num.notna()
        & moe_num.notna()
        & ~annotation_mask(est_num)
        & ~annotation_mask(moe_num)
        & (moe_num >= 0)
    )
    if not valid_pair.all():
        return np.nan, np.nan
    return est_num.sum(min_count=1), float(np.sqrt((moe_num**2).sum(min_count=1)))


def build_cv_long(level: str) -> pd.DataFrame:
    """Long-format CV table for one geography level."""
    df = load_acs(level)
    rows: list[pd.DataFrame] = []
    for var_code, var_label in VARIABLES.items():
        est_col, moe_col = estimate_moe_cols(var_code)
        if est_col not in df.columns or moe_col not in df.columns:
            continue
        part = df[["NAME"]].copy()
        part["geography_level"] = level
        part["variable_code"] = var_code
        part["variable"] = var_label
        part["variable_group"] = next(
            g for g, codes in VARIABLE_GROUPS.items() if var_code in codes
        )
        part["estimate"] = pd.to_numeric(df[est_col], errors="coerce")
        part["moe"] = pd.to_numeric(df[moe_col], errors="coerce")
        part["cv"] = compute_cv(df[est_col], df[moe_col], var_code=var_code)
        rows.append(part)
    return pd.concat(rows, ignore_index=True)
