"""Pull ACS 5-year county income & poverty (with MOEs) for NJ, vintages 2019-2024.

What it does
------------
Downloads median household income and poverty (universe + below-poverty
count) with margins of error for every New Jersey county, once per ACS
5-year vintage 2019 through 2024. This is the ACS side of EDA 10's
SAIPE-vs-ACS comparison: same county, same year label, the Bureau's two
published uncertainty styles. Prints sanity checks per vintage and saves
one combined parquet.

Variables: B19013_001 (median household income), B17001_001 (poverty
universe -- people for whom poverty status is determined), B17001_002
(people below poverty). B17001_001 is pulled here (the Phase 1 county
pull carries only _002) because a poverty RATE needs its true universe
denominator, and the rate's MOE needs the handbook proportion formula
(analysis/acs.py::proportion_moe) -- the universe is NOT total population
(B17001 excludes some group-quarters residents).

Window warning that shapes all downstream use: ACS 5-year vintage Y
averages years Y-4..Y (vintage 2024 is centered near 2022), while SAIPE
year Y is a single-year model estimate. Same label, different windows --
compare uncertainty styles, never treat as the same quantity.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
  (free + instant: https://api.census.gov/data/key_signup.html)
- Internet access; packages from requirements.txt
  (censusdis, pandas, python-dotenv, pyarrow, requests)

What it produces
----------------
- data/raw/acs5_nj_county_income_2019_2024.parquet   (126 rows --
  hard-checked: 21 counties x 6 vintages, VINTAGE column added)

The filename spans vintages, unlike the single-vintage
acs5_{VINTAGE}_nj_{level} pattern, because this file's whole point is the
vintage panel. Columns keep official ACS codes (estimates end E, MOEs end
M; 90% confidence). censusdis converts annotation codes to NaN -- the
known landmine: "controlled" and "insufficient sample" both arrive blank.

Run from the repo root:
    python ingestion/pull_acs_income_county_nj.py
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

DATASET = "acs/acs5"
VINTAGES = [2019, 2020, 2021, 2022, 2023, 2024]
STATE_NJ = "34"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "raw"
OUT_PATH = OUT_DIR / "acs5_nj_county_income_2019_2024.parquet"

VARIABLES = {
    "B19013_001": "Median household income ($)",
    "B17001_001": "Poverty universe (people)",
    "B17001_002": "People below poverty level",
}
ESTIMATE_COLS = [f"{code}E" for code in VARIABLES]
MOE_COLS = [f"{code}M" for code in VARIABLES]
DOWNLOAD_VARS = ["NAME"] + [c for pair in zip(ESTIMATE_COLS, MOE_COLS) for c in pair]

EXPECTED_NJ_COUNTIES = 21
INCOME_TOP_CODE = 250_001  # median income top-coding sentinel (see glossary)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_api_key() -> str:
    """Read CENSUS_API_KEY from .env, with setup guidance if missing."""
    load_dotenv(REPO_ROOT / ".env")
    key = os.getenv("CENSUS_API_KEY")
    if not key or key in ("your_key_here", "paste_your_key_here"):
        sys.exit(
            "CENSUS_API_KEY is missing. Copy .env.example to .env and paste in a free "
            "key from https://api.census.gov/data/key_signup.html"
        )
    return key


def fetch_official_labels(vintage: int) -> dict[str, str]:
    """Official API labels for our estimate columns, for runtime verification."""
    labels: dict[str, str] = {}
    for code in ESTIMATE_COLS:
        url = f"https://api.census.gov/data/{vintage}/{DATASET}/variables/{code}.json"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            labels[code] = resp.json().get("label", "<no label in response>")
        except requests.RequestException as exc:
            labels[code] = f"<label fetch failed: {exc}>"
    return labels


def sanity_report(df: pd.DataFrame, vintage: int) -> None:
    """Print per-column checks: nulls, clean value range, internal consistency."""
    print(f"\n  Sanity checks -- vintage {vintage}: {len(df):,} rows x {len(df.columns)} columns")
    print(f"  {'column':<15} {'nulls':>12}   clean min / max")
    for col in DOWNLOAD_VARS:
        if col == "NAME":
            continue
        if col not in df.columns:
            print(f"  {col:<15} MISSING FROM API RESPONSE")
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        n = len(s)
        nulls = int(s.isna().sum())
        clean = s[s.notna()]
        rng = (
            f"{clean.min():>14,.0f} / {clean.max():<14,.0f}"
            if len(clean)
            else "   (no clean values)"
        )
        print(f"  {col:<15} {nulls:>5} ({nulls / n:5.1%})   {rng}")

    below = pd.to_numeric(df["B17001_002E"], errors="coerce")
    universe = pd.to_numeric(df["B17001_001E"], errors="coerce")
    ok = bool((below <= universe).all())
    print(f"  {'PASS' if ok else 'FAIL'}  B17001_002E <= B17001_001E on every row")
    if not ok:
        sys.exit(f"vintage {vintage}: below-poverty count exceeds its universe -- bad pull?")

    topcoded = int((pd.to_numeric(df["B19013_001E"], errors="coerce") == INCOME_TOP_CODE).sum())
    print(f"  {'PASS' if topcoded == 0 else 'NOTE'}  top-coded county incomes: {topcoded} "
          "(expected 0 at county scale)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for vintage in (VINTAGES[0], VINTAGES[-1]):
        print(f"\nOfficial variable labels from the API (vintage {vintage}) -- verify they match intent:")
        for code, label in fetch_official_labels(vintage).items():
            print(f"  {code}: {label}")
            print(f"    -> we call it: {VARIABLES[code[:-1]]}")

    frames = []
    failures: list[str] = []
    for vintage in VINTAGES:
        print(f"\nPulling {DATASET} vintage {vintage}, NJ counties ...")
        try:
            df = ced.download(
                DATASET,
                vintage,
                download_variables=DOWNLOAD_VARS,
                api_key=api_key,
                state=STATE_NJ,
                county="*",
            )
        except Exception as exc:  # noqa: BLE001 - report and continue, fail at the end
            print(f"  FAILED: {exc}")
            failures.append(str(vintage))
            continue
        if len(df) != EXPECTED_NJ_COUNTIES:
            sys.exit(f"vintage {vintage}: expected {EXPECTED_NJ_COUNTIES} counties, got {len(df)}.")
        df.insert(0, "VINTAGE", vintage)
        sanity_report(df, vintage)
        frames.append(df)
        time.sleep(0.5)

    if failures:
        sys.exit(f"One or more vintages FAILED: {', '.join(failures)}")

    out = pd.concat(frames, ignore_index=True)
    if len(out) != EXPECTED_NJ_COUNTIES * len(VINTAGES):
        sys.exit(f"Expected {EXPECTED_NJ_COUNTIES * len(VINTAGES)} rows, got {len(out)}.")

    out.to_parquet(OUT_PATH, index=False)
    print(f"\n  Saved {OUT_PATH.relative_to(REPO_ROOT)} ({OUT_PATH.stat().st_size / 1024:,.0f} KB)")

    mercer = out[(out["COUNTY"] == "021") & (out["VINTAGE"] == VINTAGES[-1])].iloc[0]
    print(
        f"\n  Worked example -- {mercer['NAME']} (vintage {mercer['VINTAGE']}): median household "
        f"income ${mercer['B19013_001E']:,.0f} +/- ${mercer['B19013_001M']:,.0f} (90% confidence); "
        f"{mercer['B17001_002E']:,.0f} of {mercer['B17001_001E']:,.0f} people below poverty."
    )
    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")


if __name__ == "__main__":
    main()
