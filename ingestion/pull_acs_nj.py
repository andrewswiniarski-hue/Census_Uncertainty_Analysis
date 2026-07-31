"""Pull ACS 5-year estimates + margins of error for New Jersey.

What it does
------------
Downloads the project's starter variables from the ACS 5-year detailed
tables (2020-2024 release, vintage 2024) for every New Jersey county,
census tract, and block group -- with the margin of error (MOE) for every
estimate. Prints sanity checks (row counts, null rates, sentinel-code
counts, value ranges) and saves one parquet file per geography level.

Variables: total population (B01003_001), median household income
(B19013_001), people below poverty level (B17001_002), and the six
sex-x-age cells that make up "Black or African American alone, 65+"
(B01001B_014..016 male, _029..031 female). The six cells are pulled raw;
any aggregation to a single 65+ number happens later as a documented
analysis step (combining MOEs requires a specific Census formula).

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
  (free + instant: https://api.census.gov/data/key_signup.html)
- Internet access; packages from requirements.txt
  (censusdis, pandas, python-dotenv, pyarrow, requests)

What it produces
----------------
- data/raw/acs5_2024_nj_county.parquet        (21 rows -- hard-checked)
- data/raw/acs5_2024_nj_tract.parquet         (~2,000 rows)
- data/raw/acs5_2024_nj_block_group.parquet   (~6,600 rows)

Columns keep the official ACS variable codes (raw = exactly what the API
returned; friendly names happen in the processing layer). Estimates end
in E, margins of error in M. MOEs are published at 90% confidence.
Giant negative values (e.g. -555555555) are ACS annotation codes, not
data -- see the sanity-check output and docs/glossary.md.

Run from the repo root:
    python ingestion/pull_acs_nj.py
"""

from __future__ import annotations

import sys
import time

import censusdis.data as ced

from _common import (
    OUT_DIR,
    REPO_ROOT,
    fetch_official_labels,
    load_api_key,
    sanity_report,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATASET = "acs/acs5"  # ACS 5-year detailed tables
VINTAGE = 2024        # 2020-2024 release; newest available (checked 2026-07-09)
STATE_NJ = "34"       # FIPS code for New Jersey

# Estimate variables. The API serves each as <code>E (estimate) and
# <code>M (margin of error); we pull both.
VARIABLES = {
    "B01003_001": "Total population",
    "B19013_001": "Median household income (dollars)",
    "B17001_002": "People below poverty level",
    # Small-subgroup example: Black or African American alone, age 65+.
    # Stored by the ACS as six separate sex x age cells:
    "B01001B_014": "Black male 65-74",
    "B01001B_015": "Black male 75-84",
    "B01001B_016": "Black male 85+",
    "B01001B_029": "Black female 65-74",
    "B01001B_030": "Black female 75-84",
    "B01001B_031": "Black female 85+",
}

ESTIMATE_COLS = [f"{v}E" for v in VARIABLES]
MOE_COLS = [f"{v}M" for v in VARIABLES]
# Interleave E/M pairs so related columns sit side by side in the files.
DOWNLOAD_VARS = ["NAME"] + [c for pair in zip(ESTIMATE_COLS, MOE_COLS) for c in pair]

# The three geography levels, as censusdis keyword arguments.
# "*" means "every one of them within the containing geography".
GEO_LEVELS = {
    "county": dict(state=STATE_NJ, county="*"),
    "tract": dict(state=STATE_NJ, county="*", tract="*"),
    "block_group": dict(state=STATE_NJ, county="*", tract="*", block_group="*"),
}

EXPECTED_NJ_COUNTIES = 21  # fixed fact -- any other count means a bad query


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"ACS 5-year, vintage {VINTAGE} (2020-2024), New Jersey (FIPS {STATE_NJ})")
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

        out_path = OUT_DIR / f"acs5_{VINTAGE}_nj_{level}.parquet"
        df.to_parquet(out_path, index=False)
        sanity_report(df, level, DOWNLOAD_VARS)
        print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
              f"({out_path.stat().st_size / 1024:,.0f} KB)")

        if level == "county":
            # One concrete example for the plain-English MOE explanation.
            mercer = df[df["NAME"].str.contains("Mercer", na=False)]
            if len(mercer):
                r = mercer.iloc[0]
                print(
                    f"  Example row -- {r['NAME']}: median household income "
                    f"${float(r['B19013_001E']):,.0f} +/- ${float(r['B19013_001M']):,.0f} "
                    f"(90% confidence)"
                )

    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        sys.exit(f"One or more geography levels FAILED: {', '.join(failures)}")


if __name__ == "__main__":
    main()
