"""Pull nationwide ACS estimates and matching boundaries at practical map scales.

Downloads 2024 ACS 5-year estimates and 2024 cartographic boundaries for all
US Census API states and counties.  It deliberately stops at county level:
nationwide tract and block-group geometries are much larger and are better
pulled for selected states or metro areas.

Outputs (all in data/raw/)
----------------------------
- acs5_2024_us_state.parquet
- acs5_2024_us_county.parquet
- geo_2024_us_state.parquet
- geo_2024_us_county.parquet
- verification_map_us_counties.png

Run from the repository root:
    python Ingestion/pull_acs_us.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # Render the verification map without opening a window.
import censusdis.data as ced
import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv


DATASET = "acs/acs5"
VINTAGE = 2024
SCOPE = "us"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "raw"

# Each table includes an E (estimate) and M (90% confidence margin of error).
VARIABLES = {
    "B01003_001": "Total population",
    "B19013_001": "Median household income (dollars)",
    "B17001_002": "People below poverty level",
    "B01001B_014": "Black male 65-74",
    "B01001B_015": "Black male 75-84",
    "B01001B_016": "Black male 85+",
    "B01001B_029": "Black female 65-74",
    "B01001B_030": "Black female 75-84",
    "B01001B_031": "Black female 85+",
}

ESTIMATE_COLS = [f"{code}E" for code in VARIABLES]
MOE_COLS = [f"{code}M" for code in VARIABLES]
DOWNLOAD_VARS = ["NAME"] + [
    column for estimate, moe in zip(ESTIMATE_COLS, MOE_COLS) for column in (estimate, moe)
]

# National state/county queries remain practical.  Do not add nationwide tracts
# or block groups here without considering download time and storage first.
GEO_LEVELS = {
    "state": (dict(state="*"), ["STATE"]),
    "county": (dict(state="*", county="*"), ["STATE", "COUNTY"]),
}


def load_api_key() -> str:
    """Load the Census key from the untracked repo-root .env file."""
    load_dotenv(REPO_ROOT / ".env")
    key = os.getenv("CENSUS_API_KEY")
    if not key or key == "paste_your_key_here":
        sys.exit(
            "CENSUS_API_KEY is missing. Create .env in the repository root and set "
            "CENSUS_API_KEY to your Census API key."
        )
    return key


def download_data(level: str, geo_kwargs: dict[str, str], api_key: str) -> pd.DataFrame:
    """Download estimates and MOEs, then save one regular Parquet table."""
    print(f"\nDownloading {level}-level ACS data ...")
    df = ced.download(
        DATASET,
        VINTAGE,
        download_variables=DOWNLOAD_VARS,
        api_key=api_key,
        **geo_kwargs,
    )
    out_path = OUT_DIR / f"acs5_{VINTAGE}_{SCOPE}_{level}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"  Saved {len(df):,} rows to {out_path.relative_to(REPO_ROOT)}")
    return df


def download_geometry(level: str, geo_kwargs: dict[str, str], api_key: str) -> pd.DataFrame:
    """Download matching Census cartographic-boundary shapes as GeoParquet."""
    print(f"Downloading {level}-level boundaries ...")
    gdf = ced.download(
        DATASET,
        VINTAGE,
        download_variables=["NAME"],
        api_key=api_key,
        with_geometry=True,
        **geo_kwargs,
    )
    invalid = int((~gdf.geometry.is_valid).sum())
    print(f"  Received {len(gdf):,} shapes; invalid geometries: {invalid}; CRS: {gdf.crs}")
    out_path = OUT_DIR / f"geo_{VINTAGE}_{SCOPE}_{level}.parquet"
    gdf.to_parquet(out_path, index=False)
    print(f"  Saved {out_path.relative_to(REPO_ROOT)}")
    return gdf


def check_join(data: pd.DataFrame, geometry: pd.DataFrame, level: str, keys: list[str]) -> None:
    """Require every estimate row and every boundary to match exactly once."""
    merged = data[keys].merge(
        geometry[keys], on=keys, how="outer", indicator=True, validate="one_to_one"
    )
    data_only = int((merged["_merge"] == "left_only").sum())
    geometry_only = int((merged["_merge"] == "right_only").sum())
    if data_only or geometry_only:
        raise RuntimeError(
            f"{level} join failed: {data_only} data rows lack a boundary and "
            f"{geometry_only} boundaries lack a data row."
        )
    print(f"  Join check passed: {len(data):,} {level} rows match one shape each.")


def save_verification_map(counties: pd.DataFrame) -> None:
    """Write a quick visual check that the nationwide geometry looks sensible."""
    fig, ax = plt.subplots(figsize=(14, 9))
    counties.plot(ax=ax, color="#c8d8e8", edgecolor="white", linewidth=0.05)
    ax.set_axis_off()
    ax.set_title(f"US Census counties, ACS {VINTAGE} cartographic boundaries")
    path = OUT_DIR / "verification_map_us_counties.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nVerification map saved: {path.relative_to(REPO_ROOT)}")


def main() -> None:
    started = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Nationwide ACS 5-year estimates, vintage {VINTAGE}")
    county_geometry = None

    for level, (geo_kwargs, keys) in GEO_LEVELS.items():
        data = download_data(level, geo_kwargs, api_key)
        geometry = download_geometry(level, geo_kwargs, api_key)
        check_join(data, geometry, level, keys)
        if level == "county":
            county_geometry = geometry

    if county_geometry is not None:
        save_verification_map(county_geometry)

    print(f"\nDone in {time.perf_counter() - started:,.1f}s.")


if __name__ == "__main__":
    main()
