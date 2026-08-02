"""Pull poverty tables at tract AND block group for the derived-quantity work.

What it does
------------
Downloads B17001 (poverty status, cells 001/002), C17002 (ratio of income
to poverty, all 8 cells) and B01003 (total population), E + M, at census
tract and block group for New Jersey. Plus a second vintage of the same
tract pull, so the overlapping-window demonstration has both windows.

Track D of the financial EDA, and the empirical answer to the tract-floor
question. B17001 stops at tract; C17002 reaches block group with less
detail. Pulling both at tract quantifies exactly what detail is lost and
what precision is gained, instead of asking the sponsors the open question
cold.

One asymmetry the notebook must state: below-poverty in C17002 is
002E + 003E (under .50 plus .50-.99), a two-cell SUM, so that side carries
a root-sum-square propagated MOE while B17001_002E carries a published one.
Part of what the comparison measures, not a nuisance.

Overlapping windows: ACS 5-year vintages 2023 and 2024 share four years of
sample. The standard significance test assumes independence and therefore
overstates significance on such a pair. The Bureau warns against it; users
do it constantly. Both vintages are pulled here so notebook 11 can
demonstrate the inflation.

All names CONFIRMED against the live endpoint -- B17001 has 59 estimate
cells, C17002 has 8, both at vintages 2023 and 2024. See
docs/api-surface-verified.md.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt (censusdis, pandas,
  python-dotenv, pyarrow, requests)

What it produces
----------------
- data/raw/acs5_2024_nj_poverty_tract.parquet        (~2,000 rows)
- data/raw/acs5_2024_nj_poverty_block_group.parquet  (~6,600 rows)
- data/raw/acs5_2023_nj_poverty_tract.parquet        (prior window)

Run from the repo root:
    python ingestion/pull_acs_poverty_bg.py --dry-run
    python ingestion/pull_acs_poverty_bg.py
    python ingestion/pull_acs_poverty_bg.py --skip-prior-vintage
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
PRIOR_VINTAGE = VINTAGE - 1     # shares four of five sample years
STATE_NJ = common.STATE_NJ
OUT_DIR = REPO_ROOT / "data" / "raw"

VARIABLES = {
    "B17001_001": "Poverty universe: population for whom status is determined",
    "B17001_002": "Below poverty level (tract floor -- not published at block group)",
    "C17002_001": "Ratio of income to poverty: total (universe)",
    "C17002_002": "Ratio of income to poverty: under .50",
    "C17002_003": "Ratio of income to poverty: .50 to .99",
    "C17002_004": "Ratio of income to poverty: 1.00 to 1.24",
    "C17002_005": "Ratio of income to poverty: 1.25 to 1.49",
    "C17002_006": "Ratio of income to poverty: 1.50 to 1.84",
    "C17002_007": "Ratio of income to poverty: 1.85 to 1.99",
    "C17002_008": "Ratio of income to poverty: 2.00 and over",
    "B01003_001": "Total population",
}

# C17002's below-poverty equivalent: under .50 plus .50-.99. A SUM, so its
# MOE is propagated where B17001_002M is published.
C17002_BELOW_POVERTY = ["C17002_002", "C17002_003"]

ESTIMATE_COLS = [f"{v}E" for v in VARIABLES]
MOE_COLS = [f"{v}M" for v in VARIABLES]
DOWNLOAD_VARS = ["NAME"] + [c for e, m in zip(ESTIMATE_COLS, MOE_COLS) for c in (e, m)]

# B17001 is NOT published at block group. Requesting it there errors the
# whole query, exactly like requesting a nonexistent _M.
BLOCK_GROUP_VARS = ["NAME"] + [
    c for v in VARIABLES if not v.startswith("B17001")
    for c in (f"{v}E", f"{v}M")
]

GEO_LEVELS = {
    "tract": (dict(state=STATE_NJ, county="*", tract="*"), DOWNLOAD_VARS),
    "block_group": (dict(state=STATE_NJ, county="*", tract="*", block_group="*"),
                    BLOCK_GROUP_VARS),
}

EXPECTED_NJ_TRACTS = 2_181
EXPECTED_NJ_BLOCK_GROUPS = 6_600  # order of magnitude; not a hard check
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
    """Ask the API for each variable's official label."""
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


def sanity_report(df: pd.DataFrame, level: str, columns: list[str]) -> None:
    """Per-column checks plus the universe-coherence checks."""
    print(f"\n  Sanity checks -- {level}: {len(df):,} rows x {len(df.columns)} columns")
    print(f"  {'column':<16} {'nulls':>12} {'annotations':>12}   clean min / max")
    codes_seen: dict[int, int] = {}
    for col in columns:
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

    clean_df = common.clean_sentinels(df)

    # C17002's 7 detail cells must sum to its own universe.
    detail = [f"C17002_{i:03d}E" for i in range(2, 9)]
    if all(c in clean_df.columns for c in detail + ["C17002_001E"]):
        s = clean_df[detail].sum(axis=1, min_count=len(detail))
        total = clean_df["C17002_001E"]
        comparable = s.notna() & total.notna()
        bad = int((s[comparable] != total[comparable]).sum())
        print(f"  {'PASS' if not bad else 'FAIL'}  C17002 cells 002-008 sum to "
              f"C17002_001E on {int(comparable.sum()):,} rows ({bad} mismatches)")

    # Where both are present, the two poverty universes should agree closely.
    if all(c in clean_df.columns for c in ("B17001_001E", "C17002_001E")):
        ok = clean_df[["B17001_001E", "C17002_001E"]].dropna()
        if len(ok):
            same = int((ok["B17001_001E"] == ok["C17002_001E"]).sum())
            print(f"  B17001 and C17002 universes identical on "
                  f"{same:,}/{len(ok):,} rows -- they should be the same universe")

    # The tract-floor comparison, previewed at pull time.
    below = [f"{v}E" for v in C17002_BELOW_POVERTY]
    if all(c in clean_df.columns for c in below + ["B17001_002E"]):
        c_below = clean_df[below].sum(axis=1, min_count=len(below))
        ok = c_below.notna() & clean_df["B17001_002E"].notna()
        if ok.any():
            diff = (c_below[ok] - clean_df["B17001_002E"][ok]).abs()
            print(f"  Tract floor preview: C17002(002+003) vs B17001_002E -- "
                  f"identical on {int((diff == 0).sum()):,}/{int(ok.sum()):,} rows, "
                  f"max abs diff {diff.max():,.0f}")


def dry_run(prior: bool) -> None:
    """Print the request plan and expected volume. Fetch nothing."""
    print("DRY RUN -- no data will be fetched.\n")
    print(f"  Dataset       {DATASET} vintage {VINTAGE}")
    print(f"  Geography     tract and block group, New Jersey (FIPS {STATE_NJ})")
    print(f"\n  tract        {len(DOWNLOAD_VARS):>3} columns, "
          f"~{EXPECTED_NJ_TRACTS:,} rows "
          f"(~{EXPECTED_NJ_TRACTS * len(DOWNLOAD_VARS):,} cells)")
    print(f"  block group  {len(BLOCK_GROUP_VARS):>3} columns, "
          f"~{EXPECTED_NJ_BLOCK_GROUPS:,} rows "
          f"(~{EXPECTED_NJ_BLOCK_GROUPS * len(BLOCK_GROUP_VARS):,} cells)")
    print(f"\n  B17001 is NOT requested at block group -- it is not published there,")
    print(f"  and a nonexistent variable errors the whole query.")
    if prior:
        print(f"\n  Plus vintage {PRIOR_VINTAGE} at tract "
              f"(~{EXPECTED_NJ_TRACTS:,} rows) for the overlapping-window demo.")
        print(f"  Vintages {PRIOR_VINTAGE} and {VINTAGE} share four of five sample")
        print(f"  years -- the standard significance test overstates significance.")
    print(f"\n  Outputs:")
    print(f"    {(OUT_DIR / f'acs5_{VINTAGE}_nj_poverty_tract.parquet').relative_to(REPO_ROOT)}")
    print(f"    {(OUT_DIR / f'acs5_{VINTAGE}_nj_poverty_block_group.parquet').relative_to(REPO_ROOT)}")
    if prior:
        print(f"    {(OUT_DIR / f'acs5_{PRIOR_VINTAGE}_nj_poverty_tract.parquet').relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull NJ poverty tables at tract and block group for Track D.")
    parser.add_argument("--skip-prior-vintage", action="store_true",
                        help=f"skip the vintage {PRIOR_VINTAGE} tract pull")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the request plan and expected rows, fetch nothing")
    args = parser.parse_args()
    want_prior = not args.skip_prior_vintage

    if args.dry_run:
        dry_run(want_prior)
        return

    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"ACS 5-year poverty tables, vintage {VINTAGE}, "
          f"New Jersey (FIPS {STATE_NJ})")
    print("\nOfficial variable labels from the API -- verify they match intent:")
    for code, label in fetch_official_labels().items():
        print(f"  {code}  {label}")
        print(f"  {'':<12}-> we call it: {VARIABLES[code[:-1]]}")

    failures: list[str] = []
    for level, (geo_kwargs, columns) in GEO_LEVELS.items():
        print(f"\nDownloading {level} level ...")
        try:
            df = ced.download(DATASET, VINTAGE, download_variables=columns,
                              api_key=api_key, **geo_kwargs)
        except Exception as exc:  # report and keep going; fail loudly at the end
            failures.append(level)
            print(f"  FAILED: {exc}")
            continue
        if level == "tract" and len(df) != EXPECTED_NJ_TRACTS:
            print(f"  WARNING: {len(df):,} tracts, notebooks/06 asserts "
                  f"{EXPECTED_NJ_TRACTS:,}")
        out_path = OUT_DIR / f"acs5_{VINTAGE}_nj_poverty_{level}.parquet"
        df.to_parquet(out_path, index=False)
        sanity_report(df, level, columns)
        print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
              f"({out_path.stat().st_size / 1024:,.0f} KB)")

    if want_prior:
        print(f"\nDownloading vintage {PRIOR_VINTAGE} at tract "
              f"(overlapping-window pair) ...")
        try:
            df = ced.download(DATASET, PRIOR_VINTAGE,
                              download_variables=DOWNLOAD_VARS, api_key=api_key,
                              state=STATE_NJ, county="*", tract="*")
            out_path = OUT_DIR / f"acs5_{PRIOR_VINTAGE}_nj_poverty_tract.parquet"
            df.to_parquet(out_path, index=False)
            sanity_report(df, f"tract vintage {PRIOR_VINTAGE}", DOWNLOAD_VARS)
            print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
                  f"({out_path.stat().st_size / 1024:,.0f} KB)")
            print(f"  Vintages {PRIOR_VINTAGE} and {VINTAGE} share four of five "
                  f"sample years -- do NOT run an independent-samples "
                  f"significance test on this pair without stating the inflation.")
        except Exception as exc:
            failures.append(f"vintage {PRIOR_VINTAGE} tract")
            print(f"  FAILED: {exc}")

    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        sys.exit(f"One or more pulls FAILED: {', '.join(failures)}")


if __name__ == "__main__":
    main()
