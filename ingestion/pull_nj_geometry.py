"""Pull New Jersey boundary geometries matching the ACS data pull.

What it does
------------
Downloads NJ county, census tract, and block group boundaries for the
same vintage as our ACS data (2024), using censusdis's geometry support
(behind the scenes it fetches the Census Bureau's cartographic boundary
files, which are generalized for mapping). Saves one GeoParquet file per
level, then verifies each against the data files from pull_acs_nj.py by
joining on the geography ID columns -- every data row must find exactly
one shape. Also writes a quick verification map of NJ tracts.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt (censusdis, geopandas,
  pandas, matplotlib, python-dotenv, pyarrow)
- Optional: data/raw/acs5_2024_nj_*.parquet from pull_acs_nj.py --
  if present, the join check runs; if not, it is skipped with a warning.

What it produces
----------------
- data/raw/geo_2024_nj_county.parquet        (GeoParquet, 21 shapes)
- data/raw/geo_2024_nj_tract.parquet         (GeoParquet, ~2,181 shapes)
- data/raw/geo_2024_nj_block_group.parquet   (GeoParquet, ~6,599 shapes)
- data/raw/verification_map_nj_tracts.png    (eyeball check -- looks like NJ?)

Run from the repo root:
    python ingestion/pull_nj_geometry.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: render to file, no display needed
import censusdis.data as ced
import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration (kept identical to pull_acs_nj.py where shared)
# ---------------------------------------------------------------------------

DATASET = "acs/acs5"
VINTAGE = 2024
STATE_NJ = "34"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "raw"

# Geography level -> (censusdis keyword args, ID columns used to join
# geometry to the data files from pull_acs_nj.py).
GEO_LEVELS = {
    "county": (dict(state=STATE_NJ, county="*"), ["STATE", "COUNTY"]),
    "tract": (dict(state=STATE_NJ, county="*", tract="*"), ["STATE", "COUNTY", "TRACT"]),
    "block_group": (
        dict(state=STATE_NJ, county="*", tract="*", block_group="*"),
        ["STATE", "COUNTY", "TRACT", "BLOCK_GROUP"],
    ),
}

# Rough NJ bounding box (lon/lat) for an eyeball range check on the shapes.
NJ_BOUNDS_APPROX = (-75.6, 38.9, -73.9, 41.4)


def load_api_key() -> str:
    """Read CENSUS_API_KEY from the repo-root .env (never from git)."""
    load_dotenv(REPO_ROOT / ".env")
    key = os.getenv("CENSUS_API_KEY")
    if not key or key == "paste_your_key_here":
        sys.exit(
            "CENSUS_API_KEY is missing. Copy .env.example to .env in the repo "
            "root and paste in your key (see README 'Getting Started')."
        )
    return key


def join_check(gdf: pd.DataFrame, level: str, keys: list[str]) -> None:
    """Verify data rows and shapes match 1:1 on the geography ID columns."""
    data_path = OUT_DIR / f"acs5_{VINTAGE}_nj_{level}.parquet"
    if not data_path.exists():
        print(f"  Join check SKIPPED: {data_path.name} not found "
              f"(run pull_acs_nj.py first).")
        return
    df = pd.read_parquet(data_path)
    merged = df[keys].merge(
        gdf[keys], on=keys, how="outer", indicator=True, validate="one_to_one"
    )
    data_only = int((merged["_merge"] == "left_only").sum())
    geo_only = int((merged["_merge"] == "right_only").sum())
    if data_only == 0 and geo_only == 0:
        print(f"  Join check PASSED: all {len(df):,} data rows matched a shape 1:1.")
    else:
        print(f"  Join check FAILED: {data_only} data rows without a shape, "
              f"{geo_only} shapes without a data row.")


def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"NJ boundary geometries, vintage {VINTAGE} "
          f"(cartographic boundary files via censusdis)")

    tract_gdf = None
    failures: list[str] = []
    for level, (geo_kwargs, keys) in GEO_LEVELS.items():
        print(f"\nDownloading {level} geometry ...")
        try:
            gdf = ced.download(
                DATASET,
                VINTAGE,
                download_variables=["NAME"],
                api_key=api_key,
                with_geometry=True,
                **geo_kwargs,
            )
        except Exception as exc:
            failures.append(level)
            print(f"  FAILED: {exc}")
            continue

        invalid = int((~gdf.geometry.is_valid).sum())
        minx, miny, maxx, maxy = gdf.total_bounds
        print(f"  {len(gdf):,} shapes | CRS: {gdf.crs} | invalid geometries: {invalid}")
        print(f"  Bounds: ({minx:.2f}, {miny:.2f}, {maxx:.2f}, {maxy:.2f}) "
              f"-- expect roughly {NJ_BOUNDS_APPROX} for NJ")
        join_check(gdf, level, keys)

        out_path = OUT_DIR / f"geo_{VINTAGE}_nj_{level}.parquet"
        gdf.to_parquet(out_path, index=False)
        print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
              f"({out_path.stat().st_size / 1024:,.0f} KB)")

        if level == "tract":
            tract_gdf = gdf

    if tract_gdf is not None:
        fig, ax = plt.subplots(figsize=(7, 9))
        tract_gdf.plot(ax=ax, color="#c8d8e8", edgecolor="white", linewidth=0.25)
        ax.set_axis_off()
        ax.set_title(f"New Jersey census tracts, ACS {VINTAGE} boundaries\n"
                     f"({len(tract_gdf):,} tracts -- verification map)")
        map_path = OUT_DIR / "verification_map_nj_tracts.png"
        fig.savefig(map_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"\nVerification map saved: {map_path.relative_to(REPO_ROOT)}")

    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        sys.exit(f"One or more levels FAILED: {', '.join(failures)}")


if __name__ == "__main__":
    main()
