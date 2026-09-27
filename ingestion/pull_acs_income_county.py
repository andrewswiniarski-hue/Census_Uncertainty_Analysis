"""Pull the ACS county-level counterpart to the SAIPE series.

What it does
------------
Downloads B19013 (median household income, E + M) and B17001 cells 001/002
(poverty universe and below-poverty count, E + M) at county, nationwide,
for the same years as the SAIPE pull. Track B of the financial EDA: this is
the direct-estimate side of the SAIPE-vs-ACS comparison, so it must cover
the same counties and the same years or the width-ratio is meaningless.

ACS 5-year vintages are labelled by their END year. Vintage 2024 is the
2020-2024 release. Comparing SAIPE 2024 (a single-year model estimate) to
ACS vintage 2024 (a five-year average centred on 2022) is NOT comparing
like with like -- that mismatch is part of what Track B is measuring, and
the notebook must state it rather than let the join imply equivalence.

B17001 was CONFIRMED to have 59 estimate cells; only 001 and 002 are pulled
here. 002/001 is the poverty rate and is the canonical proportion case for
Track D -- numerator is a strict subset of the denominator, both from the
same sample.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt (censusdis, pandas,
  python-dotenv, pyarrow, requests)

What it produces
----------------
- data/raw/acs5_income_county_2019_2024.parquet   (~18,900 rows)

Run from the repo root:
    python ingestion/pull_acs_income_county.py --dry-run
    python ingestion/pull_acs_income_county.py
    python ingestion/pull_acs_income_county.py --vintages 2023 2024
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
OUT_DIR = REPO_ROOT / "data" / "raw"

# ACS 5-year is published from 2009; the financial window mirrors SAIPE's.
DEFAULT_VINTAGES = common.SAIPE_YEARS

VARIABLES = {
    "B19013_001": "Median household income (dollars)",
    "B17001_001": "Poverty universe: population for whom status is determined",
    "B17001_002": "Income in the past 12 months below poverty level",
}

ESTIMATE_COLS = [f"{v}E" for v in VARIABLES]
MOE_COLS = [f"{v}M" for v in VARIABLES]
DOWNLOAD_VARS = ["NAME"] + [c for e, m in zip(ESTIMATE_COLS, MOE_COLS) for c in (e, m)]

EXPECTED_COUNTIES = 3_144  # matches the SAIPE national county count
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


def fetch_official_labels(vintage: int) -> dict[str, str]:
    """Ask the API for each variable's official label at this vintage."""
    labels: dict[str, str] = {}
    for code in ESTIMATE_COLS:
        url = f"https://api.census.gov/data/{vintage}/{DATASET}/variables/{code}.json"
        try:
            labels[code] = requests.get(url, timeout=30).json().get(
                "label", "<no label in response>")
        except requests.RequestException as exc:
            labels[code] = f"<label fetch failed: {exc}>"
    return labels


def annotation_mask(s: pd.Series) -> pd.Series:
    """True where a value is an ACS annotation code rather than real data."""
    return s.notna() & (s <= ANNOTATION_CUTOFF)


def sanity_report(df: pd.DataFrame) -> None:
    """Per-column nulls, annotation codes, ranges, plus subset coherence."""
    print(f"\n  Sanity checks: {len(df):,} rows x {len(df.columns)} columns")
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

    # Poverty count must not exceed its own universe.
    if all(c in df.columns for c in ("B17001_001E", "B17001_002E")):
        clean_df = common.clean_sentinels(df)
        ok = clean_df[["B17001_001E", "B17001_002E"]].dropna()
        bad = int((ok["B17001_002E"] > ok["B17001_001E"]).sum())
        print(f"  {'PASS' if not bad else 'FAIL'}  B17001_002E <= B17001_001E "
              f"on {len(ok):,} rows ({bad} violations)")

    if "B19013_001E" in df.columns:
        s = pd.to_numeric(df["B19013_001E"], errors="coerce")
        print(f"  Top-coded medians (== {common.INCOME_TOP_CODE:,}): "
              f"{int((s == common.INCOME_TOP_CODE).sum()):,}")


def dry_run(vintages: list[int]) -> None:
    """Print the request plan and expected volume. Fetch nothing."""
    print("DRY RUN -- no data will be fetched.\n")
    print(f"  Dataset       {DATASET}")
    print(f"  Vintages      {', '.join(str(v) for v in vintages)} "
          f"({len(vintages)} calls, one per vintage)")
    print(f"  Geography     county, nationwide (state=*, county=*)")
    print(f"  Variables     {len(DOWNLOAD_VARS)} columns "
          f"({len(ESTIMATE_COLS)} E + {len(MOE_COLS)} M + NAME)")
    print(f"\n  Expected rows ~{len(vintages) * EXPECTED_COUNTIES:,} "
          f"(~{EXPECTED_COUNTIES:,} per vintage)")
    print(f"  Expected cells ~{len(vintages) * EXPECTED_COUNTIES * len(DOWNLOAD_VARS):,}")
    print(f"  Output        {(OUT_DIR / out_name(vintages)).relative_to(REPO_ROOT)}")
    print("\n  NOTE: ACS 5-year vintages are labelled by END year. Vintage 2024 is")
    print("  the 2020-2024 release -- a five-year average, not a 2024 snapshot.")
    print("  SAIPE 2024 is a single-year model estimate. The join is intentional")
    print("  but the notebook must state the mismatch.")


def out_name(vintages: list[int]) -> str:
    return f"acs5_income_county_{min(vintages)}_{max(vintages)}.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull ACS county income and poverty for the Track B comparison.")
    parser.add_argument("--vintages", nargs="+", type=int, default=DEFAULT_VINTAGES,
                        help=f"ACS 5-year vintages (default "
                             f"{DEFAULT_VINTAGES[0]}-{DEFAULT_VINTAGES[-1]})")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the request plan and expected rows, fetch nothing")
    args = parser.parse_args()
    vintages = sorted(args.vintages)

    if args.dry_run:
        dry_run(vintages)
        return

    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"ACS 5-year county income and poverty, vintages "
          f"{min(vintages)}-{max(vintages)}")
    print(f"\nOfficial variable labels at vintage {max(vintages)} "
          f"-- verify they match intent:")
    for code, label in fetch_official_labels(max(vintages)).items():
        print(f"  {code}  {label}")
        print(f"  {'':<12}-> we call it: {VARIABLES[code[:-1]]}")

    frames = []
    failures: list[str] = []
    for vintage in vintages:
        print(f"\nDownloading vintage {vintage} ...")
        try:
            df = ced.download(DATASET, vintage, download_variables=DOWNLOAD_VARS,
                              api_key=api_key, state="*", county="*")
        except Exception as exc:  # report and keep going; fail loudly at the end
            failures.append(str(vintage))
            print(f"  FAILED: {exc}")
            continue
        df["vintage"] = vintage
        print(f"  {len(df):,} counties")
        if abs(len(df) - EXPECTED_COUNTIES) > 20:
            print(f"  WARNING: {len(df):,} counties, expected ~{EXPECTED_COUNTIES:,}. "
                  f"County definitions move across this window -- check before joining.")
        frames.append(df)
        time.sleep(0.4)

    if not frames:
        sys.exit("No vintage returned data. Nothing written.")

    out = pd.concat(frames, ignore_index=True)
    out_path = OUT_DIR / out_name(vintages)
    out.to_parquet(out_path, index=False)
    sanity_report(out)
    print(f"\n  Saved {out_path.relative_to(REPO_ROOT)} "
          f"({out_path.stat().st_size / 1024:,.0f} KB)")
    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        sys.exit(f"One or more vintages FAILED: {', '.join(failures)}")


if __name__ == "__main__":
    main()
