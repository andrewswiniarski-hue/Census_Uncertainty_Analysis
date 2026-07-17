"""Pull published 2010 Census SF1 counts for New Jersey (EDA 04 baseline).

What it does
------------
Downloads the published 2010 Census Summary File 1 (SF1) counts that serve
as the baseline for the privacy-noise analysis (EDA 04): the same
quantities are read from the 2010 DHC Demonstration Data Product, and
noise = demonstration - published. Pulled for New Jersey at five levels:
state, county, tract, block group, and block.

Variables: total population (table P1, variable P001001) and the twelve
sex-x-age cells that make up "Black or African American alone, 65+"
(table P12B: P012B020..025 male, P012B044..049 female). The twelve cells
are pulled raw; aggregation to a single 65+ number happens later as a
documented analysis step -- mirroring how the ACS pull handles the same
subgroup.

Unlike the ACS, SF1 is a full count: no margins of error ship with it.
Its published values were protected with the 2010-era disclosure
avoidance (record swapping), which is exactly why the demonstration
comparison is "DAS noise plus residual swapping," never pure DAS noise
(2022-08-25 Technical Document, data/raw/das_demo/).

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
  (free + instant: https://api.census.gov/data/key_signup.html)
- Internet access; packages from requirements.txt
  (censusdis, pandas, python-dotenv, pyarrow, requests)

What it produces
----------------
- data/raw/sf1_2010_nj_state.parquet         (1 row -- hard-checked)
- data/raw/sf1_2010_nj_county.parquet        (21 rows -- hard-checked)
- data/raw/sf1_2010_nj_tract.parquet         (2,010 rows -- hard-checked)
- data/raw/sf1_2010_nj_block_group.parquet   (6,320 rows -- hard-checked)
- data/raw/sf1_2010_nj_block.parquet         (169,588 rows -- hard-checked)

Expected geography counts are fixed 2010 Census facts for New Jersey,
cross-checked against the demonstration file's geo header. Block and
block-group queries run county-by-county (the API requires a containing
county for small-area requests); results are concatenated.

Columns keep the official SF1 variable codes (raw = exactly what the API
returned; friendly names happen in the processing layer). If an output
file already exists it is NOT re-downloaded (delete it to force a fresh
pull); its sanity checks still run and print.

Run from the repo root:
    python ingestion/pull_sf1_2010_nj.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import censusdis.data as ced
import pandas as pd
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATASET = "dec/sf1"  # 2010 Census Summary File 1
VINTAGE = 2010
STATE_NJ = "34"      # FIPS code for New Jersey

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "raw"

# Variable codes verified against the live API on 2026-07-16
# (https://api.census.gov/data/2010/dec/sf1/variables/<code>.json);
# the script re-verifies the labels on every run.
VARIABLES = {
    "P001001": "Total population (table P1)",
    # Small-subgroup parallel to the ACS pull: Black or African American
    # alone, age 65+, stored by SF1 as twelve separate sex x age cells:
    "P012B020": "Black male 65-66",
    "P012B021": "Black male 67-69",
    "P012B022": "Black male 70-74",
    "P012B023": "Black male 75-79",
    "P012B024": "Black male 80-84",
    "P012B025": "Black male 85+",
    "P012B044": "Black female 65-66",
    "P012B045": "Black female 67-69",
    "P012B046": "Black female 70-74",
    "P012B047": "Black female 75-79",
    "P012B048": "Black female 80-84",
    "P012B049": "Black female 85+",
}

VARIABLE_COLS = list(VARIABLES)
DOWNLOAD_VARS = ["NAME"] + VARIABLE_COLS
BLACK_65PLUS_CELLS = VARIABLE_COLS[1:]  # the twelve P12B cells

# Fixed 2010 Census geography counts for New Jersey. Sources: 2010 TIGER
# geography counts; cross-checked against the demonstration file's geo
# header (data/raw/das_demo/nj2010.dhc.zip, njgeo2010.dhc member), which
# tabulates identically. Any other count means a bad query.
EXPECTED_ROWS = {
    "state": 1,
    "county": 21,
    "tract": 2_010,
    "block_group": 6_320,
    "block": 169_588,
}

# Published 2010 total population of New Jersey. This exact value is also
# an *invariant* of the demonstration data (state totals get no noise), so
# it anchors both this pull and the EDA 04 parser checks.
NJ_POP_2010 = 8_791_894

# Statewide queries. Block group and block are pulled per county (the SF1
# API wants a containing county for small-area requests) -- see main().
GEO_LEVELS_STATEWIDE = {
    "state": dict(state=STATE_NJ),
    "county": dict(state=STATE_NJ, county="*"),
    "tract": dict(state=STATE_NJ, county="*", tract="*"),
}
GEO_LEVELS_PER_COUNTY = {
    "block_group": dict(tract="*", block_group="*"),
    "block": dict(tract="*", block="*"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def fetch_official_labels() -> dict[str, str]:
    """Ask the API for each variable's official label.

    Guard against a wrong variable code: the label is printed at run time
    so a mismatch is caught by eyeball instead of trusted silently.
    (The variables endpoint needs no API key.)
    """
    labels: dict[str, str] = {}
    for code in VARIABLE_COLS:
        url = f"https://api.census.gov/data/{VINTAGE}/{DATASET}/variables/{code}.json"
        try:
            meta = requests.get(url, timeout=30).json()
            labels[code] = meta.get("label", "<no label in response>")
        except requests.RequestException as exc:
            labels[code] = f"<label fetch failed: {exc}>"
    return labels


def sanity_report(df: pd.DataFrame, level: str, checks: list[str]) -> None:
    """Print per-column checks plus level-level PASS/FAIL lines.

    SF1 counts are full-count integers: no annotation codes (unlike ACS),
    no negatives, no nulls expected anywhere.
    """
    print(f"\n  Sanity checks -- {level}: {len(df):,} rows x {len(df.columns)} columns")
    print(f"  {'column':<10} {'nulls':>10} {'negatives':>10}   min / max")
    for col in VARIABLE_COLS:
        if col not in df.columns:
            checks.append(f"FAIL [{level}] {col} missing from API response")
            print(f"  {col:<10} MISSING FROM API RESPONSE")
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        nulls = int(s.isna().sum())
        negs = int((s < 0).sum())
        print(
            f"  {col:<10} {nulls:>4} ({nulls / len(s):5.1%}) {negs:>4} "
            f"({negs / len(s):5.1%})   {s.min():>11,.0f} / {s.max():<11,.0f}"
        )
        if nulls or negs:
            checks.append(f"FAIL [{level}] {col}: {nulls} nulls, {negs} negatives")

    expected = EXPECTED_ROWS[level]
    ok = len(df) == expected
    checks.append(
        f"{'PASS' if ok else 'FAIL'} [{level}] row count {len(df):,} "
        f"(expected {expected:,})"
    )

    # Full-count additivity: every level must sum to the state population.
    total = int(pd.to_numeric(df["P001001"]).sum())
    ok = total == NJ_POP_2010
    checks.append(
        f"{'PASS' if ok else 'FAIL'} [{level}] P001001 sums to {total:,} "
        f"(published state total {NJ_POP_2010:,})"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"2010 Census SF1 (published baseline), New Jersey (FIPS {STATE_NJ})")
    print("\nOfficial variable labels from the API -- verify they match intent:")
    for code, label in fetch_official_labels().items():
        print(f"  {code}  {label}")
        print(f"  {'':<9}-> we call it: {VARIABLES[code]}")

    checks: list[str] = []
    county_fips: list[str] = []

    def pull(level: str, downloader) -> pd.DataFrame | None:
        """Download (or load from disk) one level, save, sanity-check."""
        out_path = OUT_DIR / f"sf1_{VINTAGE}_nj_{level}.parquet"
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"\nAlready on disk, skipping download: "
                  f"{out_path.relative_to(REPO_ROOT)} (delete to re-pull)")
            df = pd.read_parquet(out_path)
        else:
            print(f"\nDownloading {level} level ...")
            try:
                df = downloader()
            except Exception as exc:
                checks.append(f"FAIL [{level}] download error: {exc}")
                print(f"  FAILED: {exc}")
                return None
            df.to_parquet(out_path, index=False)
            print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
                  f"({out_path.stat().st_size / 1024:,.0f} KB)")
        sanity_report(df, level, checks)
        return df

    for level, geo_kwargs in GEO_LEVELS_STATEWIDE.items():
        df = pull(
            level,
            lambda kw=geo_kwargs: ced.download(
                DATASET, VINTAGE, download_variables=DOWNLOAD_VARS,
                api_key=api_key, **kw,
            ),
        )
        if df is None:
            continue
        if level == "state":
            pop = int(pd.to_numeric(df["P001001"]).iloc[0])
            black65 = int(df[BLACK_65PLUS_CELLS].apply(pd.to_numeric).sum().sum())
            print(f"  Example -- NJ 2010: total population {pop:,}; "
                  f"Black alone 65+ (12 cells summed) {black65:,}")
        if level == "county":
            county_fips = sorted(df["COUNTY"].astype(str).str.zfill(3).unique())

    if len(county_fips) != EXPECTED_ROWS["county"]:
        sys.exit(
            f"Got {len(county_fips)} county FIPS codes, expected "
            f"{EXPECTED_ROWS['county']} -- cannot run per-county block pulls. "
            "Fix the county-level query first."
        )

    for level, geo_kwargs in GEO_LEVELS_PER_COUNTY.items():
        def download_per_county(kw=geo_kwargs, lvl=level) -> pd.DataFrame:
            frames = []
            for i, fips in enumerate(county_fips, 1):
                print(f"  county {fips} ({i}/{len(county_fips)}) ...", flush=True)
                frames.append(
                    ced.download(
                        DATASET, VINTAGE, download_variables=DOWNLOAD_VARS,
                        api_key=api_key, state=STATE_NJ, county=fips, **kw,
                    )
                )
            return pd.concat(frames, ignore_index=True)

        pull(level, download_per_county)

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
