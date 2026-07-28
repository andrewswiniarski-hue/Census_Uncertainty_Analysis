"""Pull ACS 5-year median household income and its bracket distribution.

What it does
------------
Downloads B19013 (median household income, E + M) and B19001 (the 16
household-income brackets plus universe total, E + M) at census tract for
New Jersey, optionally plus contrasting states. Track A of the financial
EDA: B19013 is interpolated from the B19001 distribution, so its
uncertainty depends on bracket geometry -- which bracket the median falls
in, how wide that bracket is, how densely populated -- none of which is a
sample-size story.

Every variable name here was CONFIRMED against the live metadata endpoint;
see docs/api-surface-verified.md. Notably B19001 has 16 BRACKETS plus one
universe total, not 17 brackets -- the total row is not a bracket, and an
interpolation loop written off 17 runs off the end of the distribution.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
  (free + instant: https://api.census.gov/data/key_signup.html)
- Internet access; packages from requirements.txt (censusdis, pandas,
  python-dotenv, pyarrow, requests)

What it produces
----------------
- data/raw/acs5_2024_income_dist_tract.parquet   (~2,000 rows NJ only)

Columns keep the official ACS variable codes. Giant negative values are
ACS annotation codes, not data -- see the sanity-check output,
analysis/common.py, and docs/glossary.md.

Run from the repo root:
    python ingestion/pull_acs_income_dist.py --dry-run
    python ingestion/pull_acs_income_dist.py
    python ingestion/pull_acs_income_dist.py --states 34 06 48
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import censusdis.data as ced
import pandas as pd
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from analysis import common  # noqa: E402

DATASET = common.ACS_DATASET
VINTAGE = common.ACS_VINTAGE
OUT_DIR = REPO_ROOT / "data" / "raw"

# Working names are EXPECTED meanings; the run-time label printout is the
# authority -- eyeball it before any analysis pins a bracket index.
VARIABLES = {
    "B19013_001": "Median household income (dollars)",
    "B19001_001": "Household income: total households (universe, NOT a bracket)",
}
for _cell, _lo, _hi in common.B19001_BRACKETS:
    _code = _cell[:-1]
    VARIABLES[_code] = (
        f"Household income bracket: ${_lo:,}+ (open)" if _hi is None
        else f"Household income bracket: ${_lo:,} to ${_hi:,}"
    )

ESTIMATE_COLS = [f"{v}E" for v in VARIABLES]
MOE_COLS = [f"{v}M" for v in VARIABLES]
DOWNLOAD_VARS = ["NAME"] + [c for e, m in zip(ESTIMATE_COLS, MOE_COLS) for c in (e, m)]

# Rough tract counts for the --dry-run estimate. NJ is hard-checked below;
# the others are order-of-magnitude only.
KNOWN_TRACT_COUNTS = {"34": 2_181, "06": 9_129, "48": 6_896, "36": 5_411, "13": 2_796}
EXPECTED_NJ_TRACTS = 2_181  # matches the assert in notebooks/06

ANNOTATION_CUTOFF = common.ANNOTATION_CUTOFF
KNOWN_ANNOTATIONS = common.KNOWN_ANNOTATIONS


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

    The guard that pins bracket meanings: printed at run time so a wrong
    code or bin assumption is caught by eyeball before the analysis layer
    trusts an index. No API key needed.
    """
    labels: dict[str, str] = {}
    for code in ESTIMATE_COLS:
        url = f"https://api.census.gov/data/{VINTAGE}/{DATASET}/variables/{code}.json"
        try:
            labels[code] = requests.get(url, timeout=30).json().get(
                "label", "<no label in response>")
        except requests.RequestException as exc:
            labels[code] = f"<label fetch failed: {exc}>"
    return labels


def annotation_mask(s: pd.Series) -> pd.Series:
    """True where a value is an ACS annotation code rather than real data."""
    return s.notna() & (s <= ANNOTATION_CUTOFF)


def sanity_report(df: pd.DataFrame, label: str) -> None:
    """Print per-column checks: nulls, annotation codes, clean value range."""
    print(f"\n  Sanity checks -- {label}: {len(df):,} rows x {len(df.columns)} columns")
    print(f"  {'column':<16} {'nulls':>12} {'annotations':>12}   clean min / max")
    codes_seen: dict[int, int] = {}
    for col in DOWNLOAD_VARS:
        if col == "NAME":
            continue
        if col not in df.columns:
            print(f"  {col:<16} MISSING FROM API RESPONSE")
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        n = len(s)
        nulls = int(s.isna().sum())
        ann = annotation_mask(s)
        for val, cnt in s[ann].value_counts().items():
            codes_seen[int(val)] = codes_seen.get(int(val), 0) + int(cnt)
        clean = s[s.notna() & ~ann]
        rng = (f"{clean.min():>14,.1f} / {clean.max():<14,.1f}"
               if len(clean) else "   (no clean values)")
        print(f"  {col:<16} {nulls:>5} ({nulls / n:5.1%}) {int(ann.sum()):>5} "
              f"({ann.sum() / n:5.1%})   {rng}")
    if codes_seen:
        print("  Annotation codes present in this file:")
        for val, cnt in sorted(codes_seen.items()):
            meaning = KNOWN_ANNOTATIONS.get(val, "look up in ACS annotation docs")
            print(f"    {val}: {cnt:,} cells -- {meaning}")

    # Brackets must sum to the universe total where nothing is suppressed.
    bracket_cols = [c for c, _, _ in common.B19001_BRACKETS]
    if all(c in df.columns for c in bracket_cols + [common.B19001_TOTAL]):
        clean_df = common.clean_sentinels(df)
        s = clean_df[bracket_cols].sum(axis=1, min_count=len(bracket_cols))
        total = clean_df[common.B19001_TOTAL]
        comparable = s.notna() & total.notna()
        mismatch = int((s[comparable] != total[comparable]).sum())
        print(f"  {'PASS' if not mismatch else 'FAIL'}  16 brackets sum to "
              f"{common.B19001_TOTAL} on {int(comparable.sum()):,} comparable rows "
              f"({mismatch} mismatches)")

    # Top-coding is censoring, not measurement -- count it, never silently keep it.
    if "B19013_001E" in df.columns:
        s = pd.to_numeric(df["B19013_001E"], errors="coerce")
        topcoded = int((s == common.INCOME_TOP_CODE).sum())
        print(f"  Top-coded medians (== {common.INCOME_TOP_CODE:,}): {topcoded:,} "
              f"-- censored, exclude from CV distributions")


def dry_run(states: list[str]) -> None:
    """Print the request plan and expected volume. Fetch nothing."""
    print("DRY RUN -- no data will be fetched.\n")
    print(f"  Dataset       {DATASET} vintage {VINTAGE}")
    print(f"  Geography     tract, all counties in state(s) {', '.join(states)}")
    print(f"  Variables     {len(DOWNLOAD_VARS)} columns "
          f"({len(ESTIMATE_COLS)} E + {len(MOE_COLS)} M + NAME)")
    print(f"  Tables        B19013 (median), B19001 (16 brackets + total)")
    total = 0
    for st in states:
        n = KNOWN_TRACT_COUNTS.get(st)
        print(f"    state {st}: {n:,} tracts" if n else
              f"    state {st}: tract count unknown -- not in KNOWN_TRACT_COUNTS")
        total += n or 0
    print(f"\n  Expected rows ~{total:,}" if total else "\n  Expected rows unknown")
    print(f"  Expected cells ~{total * len(DOWNLOAD_VARS):,}")
    print(f"  Output        {(OUT_DIR / out_name(states)).relative_to(REPO_ROOT)}")
    print("\n  censusdis loops counties internally for tract queries; expect one "
          "request per county.")


def out_name(states: list[str]) -> str:
    scope = "nj" if states == [common.STATE_NJ] else "_".join(states)
    return f"acs5_{VINTAGE}_income_dist_tract_{scope}.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull B19013 + B19001 at tract for Track A.")
    parser.add_argument("--states", nargs="+", default=[common.STATE_NJ],
                        help="state FIPS codes (default 34 = NJ)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the request plan and expected rows, fetch nothing")
    args = parser.parse_args()
    states = list(args.states)

    if args.dry_run:
        dry_run(states)
        return

    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"ACS 5-year income distribution, vintage {VINTAGE}, "
          f"state(s) {', '.join(states)}")
    print("\nOfficial variable labels from the API -- verify they match intent:")
    for code, label in fetch_official_labels().items():
        print(f"  {code}  {label}")
        print(f"  {'':<12}-> we call it: {VARIABLES[code[:-1]]}")

    frames = []
    failures: list[str] = []
    for st in states:
        print(f"\nDownloading tracts for state {st} ...")
        try:
            df = ced.download(DATASET, VINTAGE, download_variables=DOWNLOAD_VARS,
                              api_key=api_key, state=st, county="*", tract="*")
        except Exception as exc:  # report and keep going; fail loudly at the end
            failures.append(st)
            print(f"  FAILED: {exc}")
            continue
        print(f"  {len(df):,} tracts")
        if st == common.STATE_NJ and len(df) != EXPECTED_NJ_TRACTS:
            print(f"  WARNING: NJ returned {len(df):,} tracts, notebooks/06 asserts "
                  f"{EXPECTED_NJ_TRACTS:,}. Vintage boundary change? Investigate "
                  f"before joining to Phase 1 data.")
        frames.append(df)

    if not frames:
        sys.exit("No state returned data. Nothing written.")

    out = pd.concat(frames, ignore_index=True)
    out_path = OUT_DIR / out_name(states)
    out.to_parquet(out_path, index=False)
    sanity_report(out, f"tract, state(s) {', '.join(states)}")
    print(f"\n  Saved {out_path.relative_to(REPO_ROOT)} "
          f"({out_path.stat().st_size / 1024:,.0f} KB)")

    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        sys.exit(f"One or more states FAILED: {', '.join(failures)}")


if __name__ == "__main__":
    main()
