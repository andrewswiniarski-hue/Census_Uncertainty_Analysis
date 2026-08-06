"""Pull SAIPE model-based income & poverty estimates for New Jersey counties.

What it does
------------
Downloads the Bureau's Small Area Income & Poverty Estimates (SAIPE) for
all 21 New Jersey counties, one API call per year 2019-2024. SAIPE is the
comparator product in the income & poverty stack (see
docs/product-shortlist-proposal.md): model-based single-year estimates
published WITH uncertainty -- every measure ships a point estimate, a 90%
confidence interval, and a margin of error. Prints sanity checks (row
counts, FIPS coverage, the MOE-equals-half-the-interval self-consistency
identity, value ranges) and saves one parquet file.

Variables: median household income (SAEMHI_PT/_MOE/_LB90/_UB90), all-ages
poverty rate (SAEPOVRTALL_PT/_MOE/_LB90/_UB90), all-ages poverty count
(SAEPOVALL_PT), and the poverty universe (SAEPOVU_ALL). A SAIPE interval
reflects MODEL error, not ACS sampling error: SAIPE year Y is a
single-year estimate, while ACS 5-year vintage Y averages Y-4..Y -- the
two must never be treated as the same quantity (see the SAIPE entry in
docs/data-dictionary.md).

Transport is plain `requests` rather than censusdis: this endpoint's
`time=` parameter and exact variable surface were verified live against
the API on 2026-08-01 (shortlist sprint receipts), and the query below is
byte-for-byte the verified shape. (Precedent for a non-censusdis pull:
ingestion/pull_das_demo_nj.py.)

What it needs
-------------
- Internet access; packages from requirements.txt (requests, pandas,
  python-dotenv, pyarrow)
- CENSUS_API_KEY in the repo-root .env is used when present but is
  OPTIONAL here -- this script makes six small keyless-eligible requests
  (the anonymous limit is ~500/day/IP).

What it produces
----------------
- data/raw/saipe_nj_county_2019_2024.parquet   (126 rows -- hard-checked:
  21 counties x 6 years)

Columns keep the official SAIPE variable codes plus YEAR; values are the
raw API strings (raw = exactly what the API returned; numeric coercion
happens in the analysis layer, per the project convention set by the SF1
pull).

Run from the repo root:
    python ingestion/pull_saipe_nj.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://api.census.gov/data/timeseries/poverty/saipe"
STATE_NJ = "34"
YEARS = [2019, 2020, 2021, 2022, 2023, 2024]  # verified live: time= serves these

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "raw"
OUT_PATH = OUT_DIR / "saipe_nj_county_2019_2024.parquet"

# Official SAIPE codes -> working names. The suffix grammar is _PT (point
# estimate), _MOE (90% margin of error), _LB90/_UB90 (90% CI bounds).
VARIABLES = {
    "SAEMHI_PT": "Median household income ($)",
    "SAEMHI_MOE": "Median HH income MOE",
    "SAEMHI_LB90": "Median HH income 90% CI lower",
    "SAEMHI_UB90": "Median HH income 90% CI upper",
    "SAEPOVRTALL_PT": "Poverty rate, all ages (%)",
    "SAEPOVRTALL_MOE": "Poverty rate MOE",
    "SAEPOVRTALL_LB90": "Poverty rate 90% CI lower",
    "SAEPOVRTALL_UB90": "Poverty rate 90% CI upper",
    "SAEPOVALL_PT": "People in poverty, all ages",
    "SAEPOVU_ALL": "Poverty universe (people)",
}
DOWNLOAD_VARS = ["NAME"] + list(VARIABLES)

# The MOE published with each measure should equal half the width of its
# published 90% CI (verified exactly for Bergen/Mercer 2024 during the
# shortlist sprint). Tolerances allow integer/one-decimal rounding.
HALF_WIDTH_CHECKS = {
    "SAEMHI": 0.51,       # income: integer dollars -> half-widths end in .0/.5
    "SAEPOVRTALL": 0.06,  # rate: one decimal place
}

EXPECTED_NJ_COUNTIES = 21
# New Jersey's 21 county FIPS codes are the odd numbers 001..041.
EXPECTED_FIPS = {f"{i:03d}" for i in range(1, 42, 2)}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_api_key() -> str | None:
    """Return the Census API key if configured; SAIPE pulls work without one."""
    load_dotenv(REPO_ROOT / ".env")
    key = os.getenv("CENSUS_API_KEY")
    if not key or key in ("your_key_here", "paste_your_key_here"):
        print("  (no CENSUS_API_KEY found -- proceeding anonymously; six small requests)")
        return None
    return key


def fetch_year(year: int, api_key: str | None) -> pd.DataFrame:
    """One SAIPE request for all NJ counties in one year, as raw strings."""
    params = {
        "get": ",".join(DOWNLOAD_VARS),
        "for": "county:*",
        "in": f"state:{STATE_NJ}",
        "time": str(year),
    }
    if api_key:
        params["key"] = api_key
    resp = requests.get(BASE_URL, params=params, timeout=60)
    resp.raise_for_status()
    rows = resp.json()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    if len(df) != EXPECTED_NJ_COUNTIES:
        sys.exit(
            f"SAIPE {year}: expected {EXPECTED_NJ_COUNTIES} NJ counties, got {len(df)} -- "
            "partial response, do not trust this pull."
        )
    return df


def sanity_report(df: pd.DataFrame) -> None:
    """Print per-column checks plus the SAIPE-specific identities."""
    print(f"\n  Sanity checks -- {len(df):,} rows x {len(df.columns)} columns")
    print(f"  {'column':<18} {'nulls':>6}   clean min / max")
    for col in DOWNLOAD_VARS:
        if col == "NAME":
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        nulls = int(s.isna().sum())
        clean = s[s.notna()]
        rng = (
            f"{clean.min():>14,.1f} / {clean.max():<14,.1f}"
            if len(clean)
            else "   (no clean values)"
        )
        print(f"  {col:<18} {nulls:>6}   {rng}")
        if nulls:
            sys.exit(f"{col} has {nulls} null values -- SAIPE publishes complete counties; bad pull?")

    # Identity: published MOE == (UB90 - LB90) / 2, within rounding.
    for stem, tol in HALF_WIDTH_CHECKS.items():
        moe = pd.to_numeric(df[f"{stem}_MOE"], errors="coerce")
        half = (
            pd.to_numeric(df[f"{stem}_UB90"], errors="coerce")
            - pd.to_numeric(df[f"{stem}_LB90"], errors="coerce")
        ) / 2
        worst = (moe - half).abs().max()
        ok = worst <= tol
        print(f"  {'PASS' if ok else 'FAIL'}  {stem}: published MOE == half the 90% CI width "
              f"(max |diff| {worst:.3f}, tolerance {tol})")
        if not ok:
            sys.exit(f"{stem} MOE does not match its CI half-width -- schema misunderstanding?")

    # Rates within [0, 100]; poverty count <= universe.
    rate = pd.to_numeric(df["SAEPOVRTALL_PT"], errors="coerce")
    ok = bool(((rate >= 0) & (rate <= 100)).all())
    print(f"  {'PASS' if ok else 'FAIL'}  SAEPOVRTALL_PT within [0, 100]")
    if not ok:
        sys.exit("poverty rate outside [0, 100] -- bad pull?")
    pov = pd.to_numeric(df["SAEPOVALL_PT"], errors="coerce")
    uni = pd.to_numeric(df["SAEPOVU_ALL"], errors="coerce")
    ok = bool((pov <= uni).all())
    print(f"  {'PASS' if ok else 'FAIL'}  poverty count <= poverty universe on every row")
    if not ok:
        sys.exit("poverty count exceeds its universe -- bad pull?")

    # FIPS coverage: exactly NJ's 21 counties, every year.
    for year, grp in df.groupby("YEAR"):
        got = set(grp["county"])
        if got != EXPECTED_FIPS:
            sys.exit(f"{year}: county FIPS set mismatch -- missing {EXPECTED_FIPS - got}, "
                     f"unexpected {got - EXPECTED_FIPS}")
    print(f"  PASS  county FIPS set == NJ's 21 counties in all {df['YEAR'].nunique()} years")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Official SAIPE variables requested (verified live 2026-08-01):")
    for code, name in VARIABLES.items():
        print(f"  {code:<18} -> we call it: {name}")

    frames = []
    for year in YEARS:
        print(f"\nPulling SAIPE {year} for NJ counties ...")
        df = fetch_year(year, api_key)
        df = df.rename(columns={"time": "YEAR"})
        frames.append(df)
        print(f"  {len(df)} counties")
        time.sleep(0.5)  # be polite to the API between calls

    out = pd.concat(frames, ignore_index=True)
    if len(out) != EXPECTED_NJ_COUNTIES * len(YEARS):
        sys.exit(f"Expected {EXPECTED_NJ_COUNTIES * len(YEARS)} rows, got {len(out)}.")

    sanity_report(out)

    out.to_parquet(OUT_PATH, index=False)
    print(f"\n  Saved {OUT_PATH.relative_to(REPO_ROOT)} ({OUT_PATH.stat().st_size / 1024:,.0f} KB)")

    # Worked example row, in plain English.
    bergen = out[(out["county"] == "003") & (out["YEAR"] == "2024")].iloc[0]
    print(
        f"\n  Worked example -- {bergen['NAME']} ({bergen['YEAR']}): median household income "
        f"${float(bergen['SAEMHI_PT']):,.0f} +/- ${float(bergen['SAEMHI_MOE']):,.0f}, "
        f"90% CI ${float(bergen['SAEMHI_LB90']):,.0f}-${float(bergen['SAEMHI_UB90']):,.0f}; "
        f"poverty rate {bergen['SAEPOVRTALL_PT']}% +/- {bergen['SAEPOVRTALL_MOE']}."
    )
    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")


if __name__ == "__main__":
    main()
