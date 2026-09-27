"""Pull USDA ERS Rural-Urban Continuum Codes (RUCC), 2023 vintage, county level.

What it does
------------
Downloads the RUCC classification the nationwide county app filters by
(Streamlit/app_US.py) -- 9 levels: 1-3 metro (by metro-area population
size), 4-9 nonmetro (by urbanization and adjacency to a metro area). This
is a published federal classification, not something this project
invents -- see docs/glossary.md for the plain-English definition once
added there.

Source file is long/tidy, not wide: 3 rows per county (Population_2020,
RUCC_2023, Description), sharing one combined FIPS integer column, not
separate STATE/COUNTY columns. This script pivots it wide and derives
STATE/COUNTY zero-padded strings matching every other ingestion script's
join keys (see geo_key() in analysis/dashboard.py). Also CONFIRMED
cp1252-encoded, not UTF-8 -- some county/description text uses characters
(e.g. accented Puerto Rico municipio names) that break a naive utf-8 read.

Territories ARE present in this file (AS, GU, MP, PR, VI -- confirmed
live 2026-08-12; ERS's own documentation states RUCC 2023 covers "those
in Puerto Rico and other outlying territories," 3,235 rows total). They
are filtered out here for the same reason Puerto Rico is filtered out of
every other nationwide pull in this project (see pull_usdash.py's module
docstring): downstream joins (ACS, geometry, SAIPE, allocation) are all
scoped to the 50 states + DC, and ERS's own 50-states-+-DC subset is
exactly 3,144 rows -- confirmed live to match the ACS county pull's row
count exactly, so no separate PR/territory row survives as an
unclassified category.

What it needs
-------------
- Internet access (no API key -- this is a plain file download, not the
  Census API)
- Packages from requirements.txt (pandas, requests, pyarrow)

What it produces
----------------
- data/raw/rucc_2023_county.parquet   (3,144 rows -- 50 states + DC)

Run from the repo root:
    python ingestion/pull_rucc.py
"""

from __future__ import annotations

import io
import sys
import time

import pandas as pd
import requests

from _common import OUT_DIR, REPO_ROOT

RUCC_URL = "https://ers.usda.gov/media/5768/2023-rural-urban-continuum-codes.csv"
ENCODING = "cp1252"  # confirmed live 2026-08-12 -- a naive utf-8 read raises UnicodeDecodeError
TIMEOUT = 60

# Territories present in the source file but excluded here -- see module
# docstring. Not just Puerto Rico: American Samoa, Guam, and the Northern
# Mariana Islands also carry a RUCC code in this file.
TERRITORY_STATE_CODES = {"AS", "GU", "MP", "PR", "VI"}

EXPECTED_ROWS = 3_144  # 50 states + DC -- matches the ACS county pull exactly
RUCC_LEVELS = set(range(1, 10))
METRO_CODES = {1, 2, 3}    # counties in a metro area, by that area's population size
NONMETRO_CODES = {4, 5, 6, 7, 8, 9}  # by urbanization / adjacency to a metro area


def fetch_raw() -> pd.DataFrame:
    resp = requests.get(RUCC_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT)
    resp.raise_for_status()
    return pd.read_csv(io.BytesIO(resp.content), encoding=ENCODING)


def pivot_wide(raw: pd.DataFrame) -> pd.DataFrame:
    """Long (3 rows/county) -> wide (1 row/county), plus derived FIPS keys.

    A handful of counties (2 of 3,235, confirmed live) carry only 2 of the
    3 attribute rows -- neither missing attribute is RUCC_2023 itself
    (confirmed: zero nulls in RUCC_2023 after the pivot), so this does not
    block the classification the app actually filters by.
    """
    wide = raw.pivot(
        index=["FIPS", "State", "County_Name"], columns="Attribute", values="Value"
    ).reset_index()
    wide["FIPS5"] = wide["FIPS"].astype(str).str.zfill(5)
    wide["STATE"] = wide["FIPS5"].str[:2]
    wide["COUNTY"] = wide["FIPS5"].str[2:]
    wide["RUCC_2023"] = pd.to_numeric(wide["RUCC_2023"], errors="coerce").astype("Int64")
    wide["Population_2020"] = pd.to_numeric(wide["Population_2020"], errors="coerce")
    return wide


def add_metro_flag(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["RUCC_METRO"] = df["RUCC_2023"].apply(
        lambda v: "Metro" if v in METRO_CODES else ("Nonmetro" if v in NONMETRO_CODES else None)
    )
    return df


def main() -> None:
    t0 = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []

    out_path = OUT_DIR / "rucc_2023_county.parquet"
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"Already on disk, skipping download: {out_path.relative_to(REPO_ROOT)} "
              f"(delete to re-pull)")
    else:
        print(f"Downloading RUCC 2023 from {RUCC_URL} ...")
        raw = fetch_raw()
        print(f"  {len(raw):,} raw rows, {raw['FIPS'].nunique():,} unique FIPS")

        wide = pivot_wide(raw)
        n_territory = int(wide["State"].isin(TERRITORY_STATE_CODES).sum())
        checks.append(f"INFO dropped {n_territory} territory row(s) "
                       f"({', '.join(sorted(TERRITORY_STATE_CODES))})")
        us_only = wide[~wide["State"].isin(TERRITORY_STATE_CODES)].reset_index(drop=True)
        us_only = add_metro_flag(us_only)

        ok = len(us_only) == EXPECTED_ROWS
        checks.append(f"{'PASS' if ok else 'FAIL'} row count {len(us_only):,} "
                       f"(expected exactly {EXPECTED_ROWS:,})")

        codes_seen = set(us_only["RUCC_2023"].dropna().unique().tolist())
        ok_codes = codes_seen.issubset(RUCC_LEVELS)
        checks.append(f"{'PASS' if ok_codes else 'FAIL'} RUCC_2023 codes {sorted(codes_seen)} "
                       f"all within 1-9")
        n_null_rucc = int(us_only["RUCC_2023"].isna().sum())
        checks.append(f"{'PASS' if n_null_rucc == 0 else 'FAIL'} RUCC_2023 nulls: {n_null_rucc}")

        acs_path = OUT_DIR / "acs5_2024_usdash_county.parquet"
        if acs_path.exists():
            acs = pd.read_parquet(acs_path, columns=["STATE", "COUNTY"])
            merged = acs.merge(
                us_only[["STATE", "COUNTY"]], on=["STATE", "COUNTY"],
                how="outer", indicator=True,
            )
            acs_only = int((merged["_merge"] == "left_only").sum())
            rucc_only = int((merged["_merge"] == "right_only").sum())
            checks.append(
                f"{'PASS' if acs_only == 0 and rucc_only == 0 else 'FAIL'} "
                f"join check vs acs5_2024_usdash_county.parquet: "
                f"{acs_only} ACS counties without RUCC, {rucc_only} RUCC counties without ACS"
            )
        else:
            checks.append("INFO join check skipped -- run pull_usdash.py first")

        us_only.to_parquet(out_path, index=False)
        print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
              f"({out_path.stat().st_size / 1024:,.0f} KB, {len(us_only):,} rows)")

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
