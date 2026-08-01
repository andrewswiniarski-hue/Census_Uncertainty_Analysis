"""Pull ACS + DHC age x sex and poverty data for the Trenton dashboard prototype.

What it does
------------
Downloads the data behind the Streamlit prototype (Streamlit/app.py): ACS
5-year sex-by-age (B01001) and poverty-by-sex-by-age (B17001), plus 2020
DHC sex-by-age (P12) -- the full-count counterpart with an identical cell
layout to B01001, which is what makes the ACS-vs-DHC comparison tab a
like-for-like join. Pulled for the City of Trenton (place), Mercer County,
and every Mercer County tract.

Also builds trenton_tracts.parquet: the 25 Mercer tracts whose centroids
fall inside the Trenton place polygon. Trenton is exactly tract-coextensive
(confirmed live against the API during planning) -- the 25 tracts' ACS
populations sum to exactly the place total, 90,338. Doing this spatial
join once here, at ingestion, keeps it out of the app's hot path.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- data/raw/geo_2024_nj_tract.parquet (from ingestion/pull_nj_geometry.py)
- Internet access; packages from requirements.txt

What it produces
----------------
- data/raw/acs5_2024_trenton_{place,county,tract}.parquet
- data/raw/dhc_2020_trenton_{place,county,tract}.parquet
- data/raw/trenton_tracts.parquet   (25 rows -- hard-checked, GeoParquet)

If an output file already exists it is NOT re-downloaded (delete it to
force a fresh pull); its sanity checks still run and print.

Run from the repo root:
    python ingestion/pull_trenton_dashboard.py
"""

from __future__ import annotations

import sys
import time

import censusdis.data as ced
import pandas as pd

from _common import OUT_DIR, REPO_ROOT, fetch_official_labels, load_api_key

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STATE_NJ = "34"
COUNTY_MERCER = "021"
PLACE_TRENTON = "74000"

TRENTON_POP_2024 = 90_338   # ACS 5-yr place total, verified live in planning
TRENTON_POP_2020 = 90_871   # DHC place total, verified live in planning
EXPECTED_TRACTS = 25        # Mercer tracts inside the Trenton place polygon

# B01001 (ACS) and P12 (DHC) share an identical sex-x-age cell layout:
# male _003.._025, female _027.._049, same age brackets both tables.
# Verified live against both APIs during planning.
SEX_AGE_CELLS = {
    "male": [f"{i:03d}" for i in range(3, 26)],     # _003 .. _025
    "female": [f"{i:03d}" for i in range(27, 50)],  # _027 .. _049
}

ACS_SEXAGE_VARS = [f"B01001_{n}" for cells in SEX_AGE_CELLS.values() for n in cells]
DHC_SEXAGE_VARS = [f"P12_{n}" for cells in SEX_AGE_CELLS.values() for n in cells]

# B17001 poverty status by sex by age -- different brackets than B01001,
# collapsed onto the same four grant-relevant bands in analysis/dashboard.py.
# Male _004..016, female _018..030 (offset +14), verified live in planning.
ACS_POVERTY_VARS = [f"B17001_{n:03d}" for n in list(range(4, 17)) + list(range(18, 31))]

ACS_VARS = ["B01001_001"] + ACS_SEXAGE_VARS + ACS_POVERTY_VARS
DHC_VARS = ["P1_001N"] + [f"{v}N" for v in DHC_SEXAGE_VARS]

ACS_ESTIMATE_COLS = [f"{v}E" for v in ACS_VARS]
ACS_MOE_COLS = [f"{v}M" for v in ACS_VARS]
ACS_DOWNLOAD_VARS = ["NAME"] + [c for pair in zip(ACS_ESTIMATE_COLS, ACS_MOE_COLS) for c in pair]
DHC_DOWNLOAD_VARS = ["NAME"] + DHC_VARS

ACS_GEO_LEVELS = {
    "place": dict(state=STATE_NJ, place=PLACE_TRENTON),
    "county": dict(state=STATE_NJ, county=COUNTY_MERCER),
    "tract": dict(state=STATE_NJ, county=COUNTY_MERCER, tract="*"),
}
DHC_GEO_LEVELS = ACS_GEO_LEVELS  # identical geography shape for both products


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def acs_sanity(df: pd.DataFrame, level: str, checks: list[str]) -> None:
    est = pd.to_numeric(df["B01001_001E"], errors="coerce")
    nulls = int(est.isna().sum())
    checks.append(f"{'PASS' if nulls == 0 else 'FAIL'} [acs/{level}] B01001_001E nulls: {nulls}")
    print(f"  [acs/{level}] {len(df):,} rows, B01001_001E range "
          f"{est.min():,.0f} / {est.max():,.0f}, nulls {nulls}")
    if level == "place":
        total = int(est.iloc[0])
        ok = total == TRENTON_POP_2024
        checks.append(f"{'PASS' if ok else 'FAIL'} [acs/place] population {total:,} "
                       f"(expected {TRENTON_POP_2024:,})")


def dhc_sanity(df: pd.DataFrame, level: str, checks: list[str]) -> None:
    pop = pd.to_numeric(df["P1_001N"], errors="coerce")
    nulls = int(pop.isna().sum())
    negs = int((pop < 0).sum())
    checks.append(f"{'PASS' if nulls == 0 and negs == 0 else 'FAIL'} "
                   f"[dhc/{level}] P1_001N nulls={nulls} negatives={negs}")
    print(f"  [dhc/{level}] {len(df):,} rows, P1_001N range "
          f"{pop.min():,.0f} / {pop.max():,.0f}")
    if level == "place":
        total = int(pop.iloc[0])
        ok = total == TRENTON_POP_2020
        checks.append(f"{'PASS' if ok else 'FAIL'} [dhc/place] population {total:,} "
                       f"(expected {TRENTON_POP_2020:,})")


def pull_product(
    dataset: str, vintage: int, download_vars: list[str], geo_levels: dict,
    out_prefix: str, sanity_fn, checks: list[str], api_key: str,
) -> None:
    for level, geo_kwargs in geo_levels.items():
        out_path = OUT_DIR / f"{out_prefix}_{level}.parquet"
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"\nAlready on disk, skipping download: "
                  f"{out_path.relative_to(REPO_ROOT)} (delete to re-pull)")
            df = pd.read_parquet(out_path)
        else:
            print(f"\nDownloading {out_prefix}/{level} ...")
            try:
                df = ced.download(
                    dataset, vintage, download_variables=download_vars,
                    api_key=api_key, **geo_kwargs,
                )
            except Exception as exc:
                checks.append(f"FAIL [{out_prefix}/{level}] download error: {exc}")
                print(f"  FAILED: {exc}")
                continue
            df.to_parquet(out_path, index=False)
            print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
                  f"({out_path.stat().st_size / 1024:,.0f} KB)")
        sanity_fn(df, level, checks)


def build_trenton_tracts(checks: list[str]) -> None:
    """Trenton place polygon centroid-joined against the NJ tract geometry.

    The join, not just the tract list, is the reusable artifact -- the app
    reads this file directly for its map, no spatial math at request time.
    """
    import geopandas as gpd

    out_path = OUT_DIR / "trenton_tracts.parquet"
    tract_geo_path = OUT_DIR / "geo_2024_nj_tract.parquet"
    if not tract_geo_path.exists():
        sys.exit(
            f"{tract_geo_path} not found -- regenerate with: "
            "python ingestion/pull_nj_geometry.py"
        )
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"\nAlready on disk, skipping join: {out_path.relative_to(REPO_ROOT)}")
        result = gpd.read_parquet(out_path)
    else:
        print("\nBuilding trenton_tracts.parquet (Trenton place x Mercer tract centroids) ...")
        place = ced.download(
            "acs/acs5", 2024, download_variables=["NAME"],
            api_key=load_api_key(), with_geometry=True,
            state=STATE_NJ, place=PLACE_TRENTON,
        )
        tracts = gpd.read_parquet(tract_geo_path)
        tracts = tracts[tracts["COUNTY"] == COUNTY_MERCER].to_crs(place.crs)
        inside = tracts[tracts.representative_point().within(place.geometry.iloc[0])]
        result = inside.reset_index(drop=True)
        result.to_parquet(out_path, index=False)
        print(f"  Saved {out_path.relative_to(REPO_ROOT)} ({len(result)} tracts)")

    n = len(result)
    ok = n == EXPECTED_TRACTS
    checks.append(f"{'PASS' if ok else 'FAIL'} [geo] Trenton tract count {n} "
                   f"(expected {EXPECTED_TRACTS})")

    acs_tract_path = OUT_DIR / "acs5_2024_trenton_tract.parquet"
    if acs_tract_path.exists():
        acs_tracts = pd.read_parquet(acs_tract_path)
        joined = acs_tracts.merge(result[["STATE", "COUNTY", "TRACT"]], on=["STATE", "COUNTY", "TRACT"])
        pop_sum = int(pd.to_numeric(joined["B01001_001E"]).sum())
        ok = pop_sum == TRENTON_POP_2024
        checks.append(f"{'PASS' if ok else 'FAIL'} [geo] tract population sum {pop_sum:,} "
                       f"== place total {TRENTON_POP_2024:,}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []

    print(f"Trenton dashboard pull: ACS 5-yr (B01001/B17001) + 2020 DHC (P12), "
          f"place {PLACE_TRENTON} / Mercer County {COUNTY_MERCER}")

    print("\nOfficial ACS variable labels -- spot check the band edges:")
    spot_check = ["B01001_003E", "B01001_025E", "B17001_004E", "B17001_016E", "B17001_030E"]
    for code, label in fetch_official_labels("acs/acs5", 2024, spot_check).items():
        print(f"  {code}  {label}")

    print("\nDownloading ACS (B01001 + B17001) ...")
    pull_product(
        "acs/acs5", 2024, ACS_DOWNLOAD_VARS, ACS_GEO_LEVELS,
        "acs5_2024_trenton", acs_sanity, checks, api_key,
    )

    print("\nDownloading 2020 DHC (P12) ...")
    pull_product(
        "dec/dhc", 2020, DHC_DOWNLOAD_VARS, DHC_GEO_LEVELS,
        "dhc_2020_trenton", dhc_sanity, checks, api_key,
    )

    build_trenton_tracts(checks)

    print(f"\n{'=' * 60}\nCheck summary:")
    for line in checks:
        print(f"  {line}")
    failures = [c for c in checks if c.startswith("FAIL")]
    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        sys.exit(f"{len(failures)} sanity check(s) FAILED -- see summary above.")
    print("All sanity checks passed.")


if __name__ == "__main__":
    main()
