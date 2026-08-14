"""Pull ACS 5-year item ALLOCATION (imputation) tables nationwide, county level.

What it does
------------
Nationwide counterpart to pull_acs_alloc_nj.py: the same allocation
(imputation) variable set -- B98031/B98032 overall rates, B99011/B99012/
B99021 demographic allocation, B99192 household income allocation,
B99172 family poverty allocation -- but for every US county instead of
just New Jersey's 21. This feeds the nationwide county app's imputation
axis (Streamlit/app_US.py), the same second, separate reliability signal
the NJ app already shows beside the CV tier.

Like the estimate tables, allocation tables publish no margins of error
(no _M variables exist for them; requesting one errors the whole query),
so this pulls estimates only -- see pull_acs_alloc_nj.py's docstring.

Puerto Rico is excluded for the same reason as every other nationwide
pull in this project (see pull_usdash.py's module docstring): filtered
immediately after download, before saving.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt

What it produces
----------------
- data/raw/acs5_2024_usdash_alloc_county.parquet   (~3,144 rows)

Run from the repo root:
    python ingestion/pull_usdash_alloc.py
"""

from __future__ import annotations

import sys
import time

import censusdis.data as ced
import pandas as pd

from _common import OUT_DIR, REPO_ROOT, annotation_mask, fetch_official_labels, load_api_key, sanity_report
from pull_acs_alloc_nj import VARIABLES, percent_range_check
from pull_usdash import drop_puerto_rico

DATASET = "acs/acs5"
VINTAGE = 2024

ESTIMATE_COLS = [f"{v}E" for v in VARIABLES]
DOWNLOAD_VARS = ["NAME"] + ESTIMATE_COLS

EXPECTED_ROWS = 3_144  # 50 states + DC, PR excluded -- matches every other usdash pull


def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []

    out_path = OUT_DIR / "acs5_2024_usdash_alloc_county.parquet"
    expected_cols = set(ESTIMATE_COLS)
    if out_path.exists() and out_path.stat().st_size > 0:
        cached = pd.read_parquet(out_path)
        if expected_cols.issubset(cached.columns):
            print(f"Already on disk, skipping download: {out_path.relative_to(REPO_ROOT)} "
                  f"(delete to re-pull)")
            df = cached
        else:
            df = None
    else:
        df = None

    if df is None:
        print(f"ACS 5-year allocation tables, vintage {VINTAGE} (2020-2024), nationwide county")
        print("\nOfficial variable labels from the API -- verify they match intent:")
        for code, label in fetch_official_labels(DATASET, VINTAGE, ESTIMATE_COLS).items():
            print(f"  {code}  {label}")
            print(f"  {'':<12}-> we call it: {VARIABLES[code[:-1]]}")

        print("\nDownloading county level ...")
        df = ced.download(
            DATASET, VINTAGE, download_variables=DOWNLOAD_VARS,
            api_key=api_key, state="*", county="*",
        )
        df = drop_puerto_rico(df, "county", checks)
        df.to_parquet(out_path, index=False)
        print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
              f"({out_path.stat().st_size / 1024:,.0f} KB, {len(df):,} rows)")

    ok = len(df) == EXPECTED_ROWS
    checks.append(f"{'PASS' if ok else 'FAIL'} row count {len(df):,} "
                   f"(expected exactly {EXPECTED_ROWS:,})")
    sanity_report(df, "county", DOWNLOAD_VARS, value_fmt=",.1f")
    percent_range_check(df, "county")

    # Allocation tables carry no MOE and no annotation-code guarantee at
    # this scale was pre-verified against NJ only -- check nationwide too
    # rather than assume the NJ finding generalizes.
    for col in ESTIMATE_COLS:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        ann = int(annotation_mask(s).sum())
        if ann:
            checks.append(f"INFO {col}: {ann} annotation-coded cells nationwide")

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
