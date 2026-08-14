"""Pull ACS age x sex, poverty, and income data for every US county and state.

What it does
------------
Nationwide counterpart to pull_njdash.py: the same ACS 5-year variable set
(B01001 sex-by-age, B17001 poverty below + at-or-above, B19013 median
household income) but for all 50 states + DC, at state and county level.
This is the data behind the nationwide county dashboard
(Streamlit/app_US.py): clicking any US state or county needs the full
age-band and poverty-rate variable set, matching what the NJ dashboard
already reads via analysis/dashboard.py.

Also pulls the same anchor variables from ACS 1-year (acs/acs1) at county
level. The 1-year product only publishes for geographies at or above
65,000 population, so this query's RETURNED ROW SET is the exact
1-year-availability list -- no population-threshold proxy needed
(the app must not derive availability from B01001_001E >= 65000; see
analysis/dashboard.py::acs_1yr_available docstring for why that proxy is
wrong at the boundary).

Puerto Rico is excluded, not carried as an unclassified row: state="*"
on the Census API returns PR's 78 municipios alongside the 50 states + DC,
but USDA's Rural-Urban Continuum Codes (the classification
Streamlit/app_US.py filters by) do not cover PR, and SAIPE/allocation
coverage there is inconsistent. Filtered out immediately after each
download, before anything is saved or sanity-checked.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt

What it produces
----------------
- data/raw/acs5_2024_usdash_state.parquet    (51 rows -- 50 states + DC)
- data/raw/acs5_2024_usdash_county.parquet   (~3,144 rows)
- data/raw/acs1_2024_usdash_county.parquet   (~800 rows -- exact 1-yr availability list)

If an output file already exists it is NOT re-downloaded (delete it to
force a fresh pull); its sanity checks still run and print.

Run from the repo root:
    python ingestion/pull_usdash.py
"""

from __future__ import annotations

import sys
import time

import censusdis.data as ced
import pandas as pd

from _common import OUT_DIR, REPO_ROOT, load_api_key
from pull_trenton_dashboard import ACS_DOWNLOAD_VARS, acs_sanity

STATE_PR = "72"  # excluded -- see module docstring

USDASH_ACS5_GEO_LEVELS = {
    "state": dict(state="*"),
    "county": dict(state="*", county="*"),
}
EXPECTED_ROWS = {"state": 51, "county": 3_144}  # 50 states + DC; US counties, PR excluded

# 1-year only publishes above the 65,000-population floor -- expect roughly
# a quarter of all counties, not close to 3,144. Not a fixed exact number
# (which counties clear the floor can shift slightly year to year), so this
# is a sanity range, not an exact-match check like EXPECTED_ROWS above.
ACS1_COUNTY_ROWS_EXPECTED_RANGE = (700, 900)


def drop_puerto_rico(df: pd.DataFrame, level: str, checks: list[str]) -> pd.DataFrame:
    if "STATE" not in df.columns:
        return df
    pr_mask = df["STATE"] == STATE_PR
    n_pr = int(pr_mask.sum())
    checks.append(f"INFO [{level}] dropped {n_pr} Puerto Rico row(s) (STATE == '72')")
    return df[~pr_mask].reset_index(drop=True)


def pull_level(
    dataset: str, vintage: int, download_vars: list[str], geo_kwargs: dict,
    out_path, level_label: str, checks: list[str], api_key: str,
) -> pd.DataFrame | None:
    """Download one (dataset, geography) pair, drop PR, cache to disk.

    Deliberately not analysis.dashboard's shared pull_product(): that
    helper writes to disk BEFORE any per-row filtering runs, which would
    save Puerto Rico's rows into the cached file. This version filters
    first, so the file on disk (and everything cached-ok on a later rerun)
    is already PR-free.
    """
    expected_cols = set(download_vars) - {"NAME"}
    if out_path.exists() and out_path.stat().st_size > 0:
        cached = pd.read_parquet(out_path)
        if expected_cols.issubset(cached.columns):
            print(f"\nAlready on disk, skipping download: "
                  f"{out_path.relative_to(REPO_ROOT)} (delete to re-pull)")
            return cached
        print(f"\n{out_path.name} is missing columns from a newer variable "
              f"list -- re-pulling ...")

    print(f"\nDownloading {level_label} ...")
    try:
        df = ced.download(
            dataset, vintage, download_variables=download_vars,
            api_key=api_key, **geo_kwargs,
        )
    except Exception as exc:
        checks.append(f"FAIL [{level_label}] download error: {exc}")
        print(f"  FAILED: {exc}")
        return None

    df = drop_puerto_rico(df, level_label, checks)
    df.to_parquet(out_path, index=False)
    print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
          f"({out_path.stat().st_size / 1024:,.0f} KB, {len(df):,} rows)")
    return df


def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []

    print("Nationwide dashboard pull: ACS 5-yr (B01001 + B17001 + B19013), "
          "all states + counties, Puerto Rico excluded")
    for level, geo_kwargs in USDASH_ACS5_GEO_LEVELS.items():
        out_path = OUT_DIR / f"acs5_2024_usdash_{level}.parquet"
        df = pull_level(
            "acs/acs5", 2024, ACS_DOWNLOAD_VARS, geo_kwargs,
            out_path, level, checks, api_key,
        )
        if df is None:
            continue
        expected = EXPECTED_ROWS[level]
        ok = len(df) == expected
        checks.append(
            f"{'PASS' if ok else 'FAIL'} [{level}] row count {len(df):,} "
            f"(expected exactly {expected:,})"
        )
        acs_sanity(df, level, checks)

    print("\nACS 1-year pull (acs/acs1), county level -- the returned rows "
          "ARE the exact 1-year-availability list, not a proxy")
    acs1_out_path = OUT_DIR / "acs1_2024_usdash_county.parquet"
    acs1_df = pull_level(
        "acs/acs1", 2024, ACS_DOWNLOAD_VARS, dict(state="*", county="*"),
        acs1_out_path, "acs1/county", checks, api_key,
    )
    if acs1_df is not None:
        lo, hi = ACS1_COUNTY_ROWS_EXPECTED_RANGE
        ok = lo <= len(acs1_df) <= hi
        checks.append(
            f"{'PASS' if ok else 'FAIL'} [acs1/county] row count {len(acs1_df):,} "
            f"(expected roughly {lo:,}-{hi:,} -- counties >= 65,000 population)"
        )
        acs_sanity(acs1_df, "acs1/county", checks)

    print(f"\n{'=' * 60}\nCheck summary:")
    for line in checks:
        print(f"  {line}")
    failures = [c for c in checks if c.startswith("FAIL")]
    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        raise SystemExit(f"{len(failures)} sanity check(s) FAILED -- see summary above.")
    print("All sanity checks passed.")


if __name__ == "__main__":
    main()
