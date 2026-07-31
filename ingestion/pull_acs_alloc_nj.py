"""Pull ACS 5-year item ALLOCATION (imputation) tables for New Jersey.

What it does
------------
Downloads the allocation tables that pair with the project's Phase 1
variables from the ACS 5-year detailed tables (2020-2024 release,
vintage 2024) for every New Jersey county, census tract, and block
group. Allocation tables report how much of each published variable was
imputed (statistically filled in) rather than reported -- the raw
material for EDA 05's imputation-prevalence and independence analysis.

Tables: B98031/B98032 (overall person / housing-unit allocation rate --
single values, ALREADY percentages 0-100), B99011/B99012/B99021
(allocation of sex / age / race: Total, Allocated, Not allocated),
B99192 (allocation of household income: total households plus
percent-of-income-allocated bins), and B99172 (allocation of poverty
status for FAMILIES -- note the universe is families, not people; it is
used only as a documented proxy for person-level poverty).

Unlike the estimate tables, ALLOCATION TABLES PUBLISH NO MARGINS OF
ERROR -- the API has no _M variables for them, so this script downloads
estimates only. (Requesting a nonexistent _M errors the whole query.)

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
  (free + instant: https://api.census.gov/data/key_signup.html)
- Internet access; packages from requirements.txt
  (censusdis, pandas, python-dotenv, pyarrow, requests)

What it produces
----------------
- data/raw/acs5_2024_nj_alloc_county.parquet        (21 rows -- hard-checked)
- data/raw/acs5_2024_nj_alloc_tract.parquet         (~2,000 rows)
- data/raw/acs5_2024_nj_alloc_block_group.parquet   (~6,600 rows)

Columns keep the official ACS variable codes (raw = exactly what the
API returned; rate derivation happens in the analysis layer). All
columns end in E. Giant negative values (e.g. -666666666) are ACS
annotation codes, not data -- see the sanity-check output and
docs/glossary.md.

Run from the repo root:
    python ingestion/pull_acs_alloc_nj.py
"""

from __future__ import annotations

import sys
import time

import censusdis.data as ced
import pandas as pd

from _common import (
    OUT_DIR,
    REPO_ROOT,
    annotation_mask,
    fetch_official_labels,
    load_api_key,
    sanity_report,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATASET = "acs/acs5"  # ACS 5-year detailed tables
VINTAGE = 2024        # 2020-2024 release; same vintage as pull_acs_nj.py
STATE_NJ = "34"       # FIPS code for New Jersey

# Allocation variables. Working names below are EXPECTED meanings; the
# run-time label printout is the authority -- eyeball it before any
# analysis pins a cell index (especially the B99192/B99172 bins).
VARIABLES = {
    # Overall characteristic allocation rates -- published as percents.
    "B98031_001": "Overall PERSON characteristic allocation rate (percent)",
    "B98032_001": "Overall HOUSING UNIT characteristic allocation rate (percent)",
    # Clean 3-cell demographic allocation tables (counts).
    "B99011_001": "Sex allocation: total (population)",
    "B99011_002": "Sex allocation: allocated",
    "B99011_003": "Sex allocation: not allocated",
    "B99012_001": "Age allocation: total (population)",
    "B99012_002": "Age allocation: allocated",
    "B99012_003": "Age allocation: not allocated",
    "B99021_001": "Race allocation: total (population)",
    "B99021_002": "Race allocation: allocated",
    "B99021_003": "Race allocation: not allocated",
    # Household income allocation -- percent-of-income-allocated bins.
    "B99192_001": "HH income allocation: total households",
    "B99192_002": "HH income allocation: no income allocated",
    "B99192_003": "HH income allocation: $0 value allocated",
    "B99192_004": "HH income allocation: >0 to <10% allocated",
    "B99192_005": "HH income allocation: 10 to <25% allocated",
    "B99192_006": "HH income allocation: 25 to <50% allocated",
    "B99192_007": "HH income allocation: 50 to <100% allocated",
    "B99192_008": "HH income allocation: 100% allocated",
    # Poverty-status allocation for FAMILIES (proxy universe -- see docstring).
    "B99172_001": "Family poverty allocation: total families",
    "B99172_002": "Family poverty allocation: below poverty, no income allocated",
    "B99172_003": "Family poverty allocation: below poverty, $0 value allocated",
    "B99172_004": "Family poverty allocation: below poverty, >0 to <10% allocated",
    "B99172_005": "Family poverty allocation: below poverty, 10 to <25% allocated",
    "B99172_006": "Family poverty allocation: below poverty, 25 to <50% allocated",
    "B99172_007": "Family poverty allocation: below poverty, 50 to <100% allocated",
    "B99172_008": "Family poverty allocation: below poverty, 100% allocated",
    "B99172_009": "Family poverty allocation: at/above poverty, no income allocated",
    "B99172_010": "Family poverty allocation: at/above poverty, $0 value allocated",
    "B99172_011": "Family poverty allocation: at/above poverty, >0 to <10% allocated",
    "B99172_012": "Family poverty allocation: at/above poverty, 10 to <25% allocated",
    "B99172_013": "Family poverty allocation: at/above poverty, 25 to <50% allocated",
    "B99172_014": "Family poverty allocation: at/above poverty, 50 to <100% allocated",
    "B99172_015": "Family poverty allocation: at/above poverty, 100% allocated",
}

ESTIMATE_COLS = [f"{v}E" for v in VARIABLES]
# Allocation tables have no _M variables -- download estimates only.
DOWNLOAD_VARS = ["NAME"] + ESTIMATE_COLS

# The three geography levels, as censusdis keyword arguments. Same shape
# as pull_acs_nj.py; censusdis loops counties for the block-group query.
GEO_LEVELS = {
    "county": dict(state=STATE_NJ, county="*"),
    "tract": dict(state=STATE_NJ, county="*", tract="*"),
    "block_group": dict(state=STATE_NJ, county="*", tract="*", block_group="*"),
}

EXPECTED_NJ_COUNTIES = 21  # fixed fact -- any other count means a bad query

# Percent-valued columns get an extra 0-100 range check.
PERCENT_COLS = ["B98031_001E", "B98032_001E"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def percent_range_check(df: pd.DataFrame, level: str) -> None:
    """Percent-valued columns must sit inside 0-100 (annotations excluded).

    Allocation-specific: the estimate-table sanity_report has no notion of
    a percent column, so this runs as an extra pass after it.
    """
    for col in PERCENT_COLS:
        if col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce")
            clean = s[s.notna() & ~annotation_mask(s)]
            ok = bool(((clean >= 0) & (clean <= 100)).all())
            print(f"  {'PASS' if ok else 'FAIL'}  {col} within [0, 100]")
            if not ok:
                sys.exit(f"{col} has values outside [0, 100] at {level} -- bad pull?")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"ACS 5-year allocation tables, vintage {VINTAGE} (2020-2024), "
          f"New Jersey (FIPS {STATE_NJ})")
    print("\nOfficial variable labels from the API -- verify they match intent:")
    for code, label in fetch_official_labels(DATASET, VINTAGE, ESTIMATE_COLS).items():
        print(f"  {code}  {label}")
        print(f"  {'':<12}-> we call it: {VARIABLES[code[:-1]]}")

    failures: list[str] = []
    for level, geo_kwargs in GEO_LEVELS.items():
        print(f"\nDownloading {level} level ...")
        try:
            df = ced.download(
                DATASET,
                VINTAGE,
                download_variables=DOWNLOAD_VARS,
                api_key=api_key,
                **geo_kwargs,
            )
        except Exception as exc:  # report and keep going; fail loudly at the end
            failures.append(level)
            print(f"  FAILED: {exc}")
            continue

        if level == "county" and len(df) != EXPECTED_NJ_COUNTIES:
            sys.exit(
                f"County query returned {len(df)} rows, but New Jersey has exactly "
                f"{EXPECTED_NJ_COUNTIES} counties. Aborting -- check the query."
            )

        out_path = OUT_DIR / f"acs5_{VINTAGE}_nj_alloc_{level}.parquet"
        df.to_parquet(out_path, index=False)
        sanity_report(df, level, DOWNLOAD_VARS, value_fmt=",.1f")
        percent_range_check(df, level)
        print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
              f"({out_path.stat().st_size / 1024:,.0f} KB)")

        if level == "county":
            # One concrete example for the plain-English explanation.
            mercer = df[df["NAME"].str.contains("Mercer", na=False)]
            if len(mercer):
                r = mercer.iloc[0]
                print(
                    f"  Example row -- {r['NAME']}: {float(r['B98031_001E']):.1f}% of "
                    f"person characteristics were allocated (imputed) overall"
                )

    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        sys.exit(f"One or more geography levels FAILED: {', '.join(failures)}")


if __name__ == "__main__":
    main()
