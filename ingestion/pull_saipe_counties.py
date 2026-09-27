"""Pull SAIPE county income and poverty estimates with their 90% intervals.

What it does
------------
Downloads Small Area Income and Poverty Estimates for every US county,
2019-2024. Track B of the financial EDA: a SAIPE interval is not an ACS
margin of error. An ACS MOE is sampling variance around a direct estimate;
a SAIPE interval reflects model error -- the sampling variance of the
inputs PLUS uncertainty about whether the model is right. Users read both
as error bars.

All six variable names were CONFIRMED against the live variables endpoint,
as were all six years (3,142-3,144 rows each); see
docs/api-surface-verified.md. SAEMHI_MOE and SAEPOVRTALL_MOE are pulled
alongside the bounds deliberately: the analysis derives a half-width as
(UB90 - LB90) / 2, and the published MOE is the check on that derivation.
Agreement validates it for free; disagreement is itself the finding.

SAIPE is a timeseries endpoint, not a vintage-per-URL dataset -- it takes
&time=YYYY, one call per year. geography.json declares county as requiring
a state qualifier, but the bare for=county:* form was VERIFIED to serve all
3,144 counties; both forms are supported below.

County definitions move across this window (CT planning regions replaced
counties from 2022, AK borough changes). Any FIPS that fails to join is
LOGGED, never dropped silently.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt (pandas, python-dotenv,
  pyarrow, requests)

What it produces
----------------
- data/raw/saipe_counties_2019_2024.parquet   (~18,900 rows)
- data/raw/saipe_fips_churn_2019_2024.csv     (counties not present in all years)

Run from the repo root:
    python ingestion/pull_saipe_counties.py --dry-run
    python ingestion/pull_saipe_counties.py
    python ingestion/pull_saipe_counties.py --years 2019 2020 --qualified
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from analysis import common  # noqa: E402

ENDPOINT = common.SAIPE_ENDPOINT
YEARS = common.SAIPE_YEARS
OUT_DIR = REPO_ROOT / "data" / "raw"

# CONFIRMED names. Do not add one that is not in docs/api-surface-verified.md.
VARIABLES = {
    "SAEMHI_PT": "Median household income, point estimate",
    "SAEMHI_LB90": "Median household income, 90% lower bound",
    "SAEMHI_UB90": "Median household income, 90% upper bound",
    "SAEMHI_MOE": "Median household income, published MOE (checks the derived half-width)",
    "SAEPOVRTALL_PT": "Poverty rate all ages, point estimate",
    "SAEPOVRTALL_LB90": "Poverty rate all ages, 90% lower bound",
    "SAEPOVRTALL_UB90": "Poverty rate all ages, 90% upper bound",
    "SAEPOVRTALL_MOE": "Poverty rate all ages, published MOE",
    "SAEPOVU_ALL": "Poverty universe, all ages (lets the rate be checked against the count)",
}
# YEAR is a data variable, not just the filter -- request it so every row is
# self-labelling rather than trusting the loop variable.
GEO_COLS = ["NAME", "GEOID", "STATE", "COUNTY", "YEAR"]
DOWNLOAD_VARS = GEO_COLS + list(VARIABLES)

EXPECTED_ROWS_PER_YEAR = 3_144  # VERIFIED 2022-2024; 2019 gave 3,142, 2020-21 3,143
TIMEOUT = 120


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
    """Ask the API for each variable's official label, once for all of them."""
    try:
        meta = requests.get(f"{ENDPOINT}/variables.json", timeout=TIMEOUT).json()
    except requests.RequestException as exc:
        return {v: f"<label fetch failed: {exc}>" for v in VARIABLES}
    published = meta.get("variables", meta)
    return {v: published.get(v, {}).get("label", "<NOT PUBLISHED>") for v in VARIABLES}


def fetch_year(year: int, key: str, qualified: bool) -> pd.DataFrame:
    """One call per year. Returns a frame with a `year` column."""
    geo = ("&for=county:*&in=state:*" if qualified else "&for=county:*")
    url = (f"{ENDPOINT}?get={','.join(DOWNLOAD_VARS)}"
           f"&time={year}{geo}&key={key}")
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    df = pd.DataFrame(payload[1:], columns=payload[0])
    for col in VARIABLES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["year"] = year
    return df


def sanity_report(df: pd.DataFrame) -> None:
    """Per-column nulls and ranges, plus the interval-coherence checks."""
    print(f"\n  Sanity checks: {len(df):,} rows x {len(df.columns)} columns")
    print(f"  {'column':<20} {'nulls':>13}   clean min / max")
    for col in VARIABLES:
        if col not in df.columns:
            print(f"  {col:<20} MISSING FROM API RESPONSE")
            continue
        s = df[col]
        nulls = int(s.isna().sum())
        clean = s.dropna()
        rng = (f"{clean.min():>14,.1f} / {clean.max():<14,.1f}"
               if len(clean) else "   (no clean values)")
        print(f"  {col:<20} {nulls:>5} ({nulls / len(s):5.1%})   {rng}")

    for pt, lb, ub in [("SAEMHI_PT", "SAEMHI_LB90", "SAEMHI_UB90"),
                       ("SAEPOVRTALL_PT", "SAEPOVRTALL_LB90", "SAEPOVRTALL_UB90")]:
        if not all(c in df.columns for c in (pt, lb, ub)):
            continue
        ok = df[[pt, lb, ub]].dropna()
        bad = int(((ok[lb] > ok[pt]) | (ok[pt] > ok[ub])).sum())
        print(f"  {'PASS' if not bad else 'FAIL'}  {lb} <= {pt} <= {ub} "
              f"on {len(ok):,} rows ({bad} violations)")

    # The check the proposal did not plan for: derived half-width vs published MOE.
    for pt, lb, ub, moe in [("SAEMHI_PT", "SAEMHI_LB90", "SAEMHI_UB90", "SAEMHI_MOE"),
                            ("SAEPOVRTALL_PT", "SAEPOVRTALL_LB90",
                             "SAEPOVRTALL_UB90", "SAEPOVRTALL_MOE")]:
        if not all(c in df.columns for c in (lb, ub, moe)):
            continue
        derived = common.half_width(df[lb], df[ub])
        comparable = derived.notna() & df[moe].notna()
        if not comparable.any():
            continue
        diff = (derived[comparable] - df[moe][comparable]).abs()
        agree = int((diff <= 1).sum())
        print(f"  (UB90-LB90)/2 vs {moe}: {agree:,}/{int(comparable.sum()):,} agree "
              f"within 1 unit; max abs diff {diff.max():,.2f}")
        if agree < int(comparable.sum()):
            print(f"       ^ disagreement is a Track B finding, not a bug -- "
                  f"the two quantities may not be the same thing")


def report_fips_churn(df: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """Counties absent from at least one year. Logged, never dropped.

    CT replaced its eight counties with nine planning regions effective 2022,
    and AK borough definitions move. A silent inner join would delete them.
    """
    present = df.groupby("GEOID")["year"].nunique()
    churn = present[present < len(years)]
    if churn.empty:
        print(f"\n  All {present.size:,} county FIPS present in all "
              f"{len(years)} years -- no churn.")
        return pd.DataFrame(columns=["GEOID", "NAME", "years_present", "years"])
    rows = []
    for geoid in churn.index:
        sub = df[df["GEOID"] == geoid]
        rows.append({
            "GEOID": geoid,
            "NAME": sub["NAME"].iloc[0] if "NAME" in sub else "",
            "years_present": int(sub["year"].nunique()),
            "years": ",".join(str(y) for y in sorted(sub["year"].unique())),
        })
    out = pd.DataFrame(rows).sort_values("GEOID")
    print(f"\n  FIPS CHURN: {len(out):,} counties are not present in all "
          f"{len(years)} years.")
    print("  These must be handled explicitly in the ACS join, not dropped:")
    for _, r in out.head(20).iterrows():
        print(f"    {r['GEOID']}  {r['NAME'][:44]:<44} years {r['years']}")
    if len(out) > 20:
        print(f"    ... and {len(out) - 20} more (see the csv)")
    return out


def dry_run(years: list[int], qualified: bool) -> None:
    """Print the request plan and expected volume. Fetch nothing."""
    print("DRY RUN -- no data will be fetched.\n")
    print(f"  Endpoint      {ENDPOINT}")
    print(f"  Geography     for=county:*{'&in=state:*' if qualified else ' (bare)'}")
    print(f"  Years         {', '.join(str(y) for y in years)} "
          f"({len(years)} calls, one per year)")
    print(f"  Variables     {len(DOWNLOAD_VARS)} columns "
          f"({len(VARIABLES)} estimates + {len(GEO_COLS)} geo/time)")
    print(f"\n  Expected rows ~{len(years) * EXPECTED_ROWS_PER_YEAR:,} "
          f"(~{EXPECTED_ROWS_PER_YEAR:,} per year)")
    print(f"  Expected cells ~{len(years) * EXPECTED_ROWS_PER_YEAR * len(DOWNLOAD_VARS):,}")
    print(f"  Output        {(OUT_DIR / out_name(years)).relative_to(REPO_ROOT)}")
    print("\n  Requested variables:")
    for code, meaning in VARIABLES.items():
        print(f"    {code:<20} {meaning}")


def out_name(years: list[int]) -> str:
    return f"saipe_counties_{min(years)}_{max(years)}.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull SAIPE county estimates with 90% intervals for Track B.")
    parser.add_argument("--years", nargs="+", type=int, default=YEARS,
                        help=f"years to pull (default {YEARS[0]}-{YEARS[-1]})")
    parser.add_argument("--qualified", action="store_true",
                        help="use for=county:*&in=state:* instead of the bare form")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the request plan and expected rows, fetch nothing")
    args = parser.parse_args()
    years = sorted(args.years)

    if args.dry_run:
        dry_run(years, args.qualified)
        return

    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"SAIPE county estimates, {min(years)}-{max(years)}")
    print("\nOfficial variable labels from the API -- verify they match intent:")
    for code, label in fetch_official_labels().items():
        print(f"  {code:<20} {label}")
        print(f"  {'':<20}-> we call it: {VARIABLES[code]}")

    frames = []
    failures: list[str] = []
    for year in years:
        print(f"\nDownloading {year} ...")
        try:
            df = fetch_year(year, api_key, args.qualified)
        except Exception as exc:  # report and keep going; fail loudly at the end
            failures.append(str(year))
            print(f"  FAILED: {exc}")
            continue
        print(f"  {len(df):,} counties")
        if len(df) < 3_000:
            print(f"  WARNING: {len(df):,} rows looks short for a national county "
                  f"query -- expected ~{EXPECTED_ROWS_PER_YEAR:,}")
        frames.append(df)
        time.sleep(0.4)  # be polite to a rate-limited endpoint

    if not frames:
        sys.exit("No year returned data. Nothing written.")

    out = pd.concat(frames, ignore_index=True)
    out_path = OUT_DIR / out_name(years)
    out.to_parquet(out_path, index=False)
    sanity_report(out)

    churn = report_fips_churn(out, years)
    churn_path = OUT_DIR / f"saipe_fips_churn_{min(years)}_{max(years)}.csv"
    churn.to_csv(churn_path, index=False, encoding="utf-8")

    print(f"\n  Saved {out_path.relative_to(REPO_ROOT)} "
          f"({out_path.stat().st_size / 1024:,.0f} KB)")
    print(f"  Saved {churn_path.relative_to(REPO_ROOT)}")
    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        sys.exit(f"One or more years FAILED: {', '.join(failures)}")


if __name__ == "__main__":
    main()
