"""Loaders for the project's 2020 DHC and DP1 pulls.

What it does
------------
Loads the parquet files produced by ingestion/pull_dhc_nj.py and
pull_dp_nj.py. Both are full-count 2020 Decennial products (no MOE, no
sampling), so unlike analysis/acs.py there is no CV to compute here --
combine these counts with analysis/noise_model.py's modeled noise instead.

What it needs
-------------
data/raw/dhc_2020_nj_{state,county,tract,block_group,block}.parquet
(regenerate with: python ingestion/pull_dhc_nj.py); data/raw/dp1_2020_nj_
{county,tract}.parquet (regenerate with: python ingestion/pull_dp_nj.py).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
VINTAGE = 2020

DHC_LEVELS = ["state", "county", "tract", "block_group", "block"]
DP1_LEVELS = ["county", "tract"]

GEO_LABELS = {
    "state": "State", "county": "County", "tract": "Census tract",
    "block_group": "Block group", "block": "Block",
}

# The twelve DHC sex-x-age cells that make up "Black or African American
# alone, 65+" -- same subgroup as the ACS and 2010 SF1 pulls, table P12B.
BLACK_65PLUS_CELLS_DHC = [
    "P12B_020N", "P12B_021N", "P12B_022N", "P12B_023N", "P12B_024N", "P12B_025N",
    "P12B_044N", "P12B_045N", "P12B_046N", "P12B_047N", "P12B_048N", "P12B_049N",
]


def load_dhc(level: str) -> pd.DataFrame:
    """Load one geography level's DHC pull. `level` is one of DHC_LEVELS."""
    if level not in DHC_LEVELS:
        raise ValueError(f"level must be one of {DHC_LEVELS}, got {level!r}")
    path = RAW_DIR / f"dhc_{VINTAGE}_nj_{level}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_dhc_nj.py"
        )
    return pd.read_parquet(path)


def load_dp1(level: str) -> pd.DataFrame:
    """Load one geography level's DP1 pull. `level` is one of DP1_LEVELS."""
    if level not in DP1_LEVELS:
        raise ValueError(f"level must be one of {DP1_LEVELS}, got {level!r}")
    path = RAW_DIR / f"dp1_{VINTAGE}_nj_{level}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_dp_nj.py"
        )
    return pd.read_parquet(path)


def black_65plus(df: pd.DataFrame) -> pd.Series:
    """Sum the twelve DHC P12B cells into one 'Black alone 65+' count.

    Unlike the ACS aggregate (analysis/acs.py's aggregate_estimate/
    aggregate_moe), this needs no MOE combination -- DHC is a full count,
    so summing twelve full counts is exact, not estimated.
    """
    return df[BLACK_65PLUS_CELLS_DHC].sum(axis=1)


if __name__ == "__main__":
    # ponytail: smallest check that the loaders and aggregate line up.
    tract = load_dhc("tract")
    assert len(tract) == 2_181
    b65 = black_65plus(tract)
    assert (b65 >= 0).all()
    assert b65.sum() == tract[BLACK_65PLUS_CELLS_DHC].to_numpy().sum()
    dp1_tract = load_dp1("tract")
    assert len(dp1_tract) == 2_181
    print("decennial self-check OK")
