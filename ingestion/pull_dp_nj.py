"""Pull 2020 Census Demographic Profile (DP1) counts for New Jersey.

What it does
------------
Downloads real 2020 production Decennial counts from the Demographic
Profile -- the second Phase B product, alongside DHC (pull_dhc_nj.py).
DP1 ships no per-cell uncertainty measure (full count, no MOE); Phase B
pairs these counts with the modeled noise in analysis/noise_model.py
rather than a measured one -- see that module's docstring for the caveat.

Variables: total population (DP1_0001C) and total Black-alone population
(DP1_0079C) -- the closest DP1 equivalent of the ACS/DHC/SF1 "small
subgroup" contrast. Landmine: DP1 has NO race-by-age crosstabs (confirmed
against the live variable list, 2026-07-31) -- there is no DP1 "Black
alone, 65+" cell, so this pull can only contrast total population against
a same-race *total*, not an age-restricted subgroup like the other three
products use.

Geography landmine: DP1 stops at tract -- no block group, no block
(confirmed against the API, 2026-07-31). Unlike DHC, which has all five
levels.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt (censusdis, pandas,
  python-dotenv, pyarrow, requests)

What it produces
----------------
- data/raw/dp1_2020_nj_county.parquet   (21 rows -- hard-checked)
- data/raw/dp1_2020_nj_tract.parquet    (2,181 rows -- hard-checked)

Run from the repo root:
    python ingestion/pull_dp_nj.py
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

DATASET = "dec/dp"  # 2020 Census Demographic Profile
VINTAGE = 2020
STATE_NJ = "34"

# Variable codes verified against the live API on 2026-07-31
# (https://api.census.gov/data/2020/dec/dp/variables/<code>.json).
VARIABLES = {
    "DP1_0001C": "Total population",
    "DP1_0079C": "Black or African American alone (one race)",
}

VARIABLE_COLS = list(VARIABLES)
DOWNLOAD_VARS = ["NAME"] + VARIABLE_COLS

# Fixed 2020 Census geography counts for New Jersey, confirmed live against
# the API on 2026-07-31 -- same tract/county universe as DHC (both 2020
# vintage), so dp1_2020_* and dhc_2020_* are safe to join on
# STATE/COUNTY/TRACT.
EXPECTED_ROWS = {"county": 21, "tract": 2_181}

NJ_POP_2020 = 9_288_994  # published 2020 total population of New Jersey

GEO_LEVELS = {
    "county": dict(state=STATE_NJ, county="*"),
    "tract": dict(state=STATE_NJ, county="*", tract="*"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanity_report(df: pd.DataFrame, level: str, checks: list[str]) -> None:
    """Full-count checks: no annotation codes, no negatives, no nulls expected."""
    print(f"\n  Sanity checks -- {level}: {len(df):,} rows x {len(df.columns)} columns")
    print(f"  {'column':<12} {'nulls':>10} {'negatives':>10}   min / max")
    for col in VARIABLE_COLS:
        if col not in df.columns:
            checks.append(f"FAIL [{level}] {col} missing from API response")
            print(f"  {col:<12} MISSING FROM API RESPONSE")
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        nulls = int(s.isna().sum())
        negs = int((s < 0).sum())
        print(
            f"  {col:<12} {nulls:>4} ({nulls / len(s):5.1%}) {negs:>4} "
            f"({negs / len(s):5.1%})   {s.min():>11,.0f} / {s.max():<11,.0f}"
        )
        if nulls or negs:
            checks.append(f"FAIL [{level}] {col}: {nulls} nulls, {negs} negatives")

    expected = EXPECTED_ROWS[level]
    ok = len(df) == expected
    checks.append(
        f"{'PASS' if ok else 'FAIL'} [{level}] row count {len(df):,} (expected {expected:,})"
    )

    total = int(pd.to_numeric(df["DP1_0001C"]).sum())
    ok = total == NJ_POP_2020
    checks.append(
        f"{'PASS' if ok else 'FAIL'} [{level}] DP1_0001C sums to {total:,} "
        f"(published state total {NJ_POP_2020:,})"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"2020 Census Demographic Profile (DP1), New Jersey (FIPS {STATE_NJ})")
    print("\nOfficial variable labels from the API -- verify they match intent:")
    for code, label in fetch_official_labels(DATASET, VINTAGE, VARIABLE_COLS).items():
        print(f"  {code}  {label}")
        print(f"  {'':<11}-> we call it: {VARIABLES[code]}")

    checks: list[str] = []

    for level, geo_kwargs in GEO_LEVELS.items():
        out_path = OUT_DIR / f"dp1_{VINTAGE}_nj_{level}.parquet"
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"\nAlready on disk, skipping download: "
                  f"{out_path.relative_to(REPO_ROOT)} (delete to re-pull)")
            df = pd.read_parquet(out_path)
        else:
            print(f"\nDownloading {level} level ...")
            try:
                df = ced.download(
                    DATASET, VINTAGE, download_variables=DOWNLOAD_VARS,
                    api_key=api_key, **geo_kwargs,
                )
            except Exception as exc:
                checks.append(f"FAIL [{level}] download error: {exc}")
                print(f"  FAILED: {exc}")
                continue
            df.to_parquet(out_path, index=False)
            print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
                  f"({out_path.stat().st_size / 1024:,.0f} KB)")
        sanity_report(df, level, checks)

        if level == "county":
            mercer = df[df["NAME"].str.contains("Mercer", na=False)]
            if len(mercer):
                r = mercer.iloc[0]
                print(
                    f"  Example row -- {r['NAME']}: total population "
                    f"{int(r['DP1_0001C']):,}; Black alone {int(r['DP1_0079C']):,}"
                )

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
