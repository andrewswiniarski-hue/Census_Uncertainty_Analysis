"""Pull 2020 Census DHC (Demographic and Housing Characteristics) counts for NJ.

What it does
------------
Downloads real 2020 production Decennial counts -- the Phase B counterpart
to ACS -- for New Jersey at all five DHC geography levels: state, county,
tract, block group, and block. DHC ships no per-cell uncertainty measure
(full count, no MOE); Phase B pairs these counts with the modeled noise
in analysis/noise_model.py (fitted on the 2010 DAS demonstration data, EDA
04) rather than a measured one -- see that module's docstring for the
caveat.

Variables: total population (table P1, P1_001N) and the twelve sex-x-age
cells that make up "Black or African American alone, 65+" (table P12B:
P12B_020N..025N male, P12B_044N..049N female) -- the same subgroup pulled
for ACS (pull_acs_nj.py) and 2010 SF1 (pull_sf1_2010_nj.py), for a
like-for-like variable-type contrast.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt (censusdis, pandas,
  python-dotenv, pyarrow, requests)

What it produces
----------------
- data/raw/dhc_2020_nj_state.parquet         (1 row -- hard-checked)
- data/raw/dhc_2020_nj_county.parquet        (21 rows -- hard-checked)
- data/raw/dhc_2020_nj_tract.parquet         (2,181 rows -- hard-checked)
- data/raw/dhc_2020_nj_block_group.parquet   (6,599 rows -- hard-checked)
- data/raw/dhc_2020_nj_block.parquet         (137,972 rows -- hard-checked)

Row counts and the state population total were confirmed live against the
API on 2026-07-31 (unlike the 2010 SF1 script, all five levels accept a
single statewide wildcard query -- no per-county looping needed). If an
output file already exists it is NOT re-downloaded (delete it to force a
fresh pull); its sanity checks still run and print.

Run from the repo root:
    python ingestion/pull_dhc_nj.py
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

DATASET = "dec/dhc"  # 2020 Census Demographic and Housing Characteristics
VINTAGE = 2020
STATE_NJ = "34"       # FIPS code for New Jersey

# Variable codes verified against the live API on 2026-07-31
# (https://api.census.gov/data/2020/dec/dhc/variables/<code>.json).
VARIABLES = {
    "P1_001N": "Total population (table P1)",
    "P12B_020N": "Black male 65-66", "P12B_021N": "Black male 67-69",
    "P12B_022N": "Black male 70-74", "P12B_023N": "Black male 75-79",
    "P12B_024N": "Black male 80-84", "P12B_025N": "Black male 85+",
    "P12B_044N": "Black female 65-66", "P12B_045N": "Black female 67-69",
    "P12B_046N": "Black female 70-74", "P12B_047N": "Black female 75-79",
    "P12B_048N": "Black female 80-84", "P12B_049N": "Black female 85+",
}

VARIABLE_COLS = list(VARIABLES)
DOWNLOAD_VARS = ["NAME"] + VARIABLE_COLS
BLACK_65PLUS_CELLS = VARIABLE_COLS[1:]  # the twelve P12B cells

# Fixed 2020 Census geography counts for New Jersey, confirmed live against
# the API on 2026-07-31. Not comparable to the 2010 SF1 counts (tract/block
# group/block boundaries changed between the 2010 and 2020 vintages) --
# never row-join dhc_2020_* to sf1_2010_*.
EXPECTED_ROWS = {
    "state": 1, "county": 21, "tract": 2_181,
    "block_group": 6_599, "block": 137_972,
}

NJ_POP_2020 = 9_288_994  # published 2020 total population of New Jersey

GEO_LEVELS = {
    "state": dict(state=STATE_NJ),
    "county": dict(state=STATE_NJ, county="*"),
    "tract": dict(state=STATE_NJ, county="*", tract="*"),
    "block_group": dict(state=STATE_NJ, county="*", tract="*", block_group="*"),
    "block": dict(state=STATE_NJ, county="*", tract="*", block="*"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanity_report(df: pd.DataFrame, level: str, checks: list[str]) -> None:
    """Print per-column checks plus level-level PASS/FAIL lines.

    DHC is a full count like SF1: no annotation codes, no negatives, no
    nulls expected anywhere -- mirrors pull_sf1_2010_nj.py's local check.
    """
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

    total = int(pd.to_numeric(df["P1_001N"]).sum())
    ok = total == NJ_POP_2020
    checks.append(
        f"{'PASS' if ok else 'FAIL'} [{level}] P1_001N sums to {total:,} "
        f"(published state total {NJ_POP_2020:,})"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"2020 Census DHC (production), New Jersey (FIPS {STATE_NJ})")
    print("\nOfficial variable labels from the API -- verify they match intent:")
    for code, label in fetch_official_labels(DATASET, VINTAGE, VARIABLE_COLS).items():
        print(f"  {code}  {label}")
        print(f"  {'':<11}-> we call it: {VARIABLES[code]}")

    checks: list[str] = []

    for level, geo_kwargs in GEO_LEVELS.items():
        out_path = OUT_DIR / f"dhc_{VINTAGE}_nj_{level}.parquet"
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

        if level == "state":
            pop = int(pd.to_numeric(df["P1_001N"]).iloc[0])
            black65 = int(df[BLACK_65PLUS_CELLS].apply(pd.to_numeric).sum().sum())
            print(f"  Example -- NJ 2020: total population {pop:,}; "
                  f"Black alone 65+ (12 cells summed) {black65:,}")

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
