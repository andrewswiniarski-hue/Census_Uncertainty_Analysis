"""Pull ACS age x sex, poverty, income, and (variable expansion, 2026-08-30)
health insurance, rent, language, vehicle, and income-bracket data for
every US county and state.

What it does
------------
Nationwide counterpart to pull_njdash.py: the same ACS 5-year variable set
(B01001 sex-by-age, B17001 poverty below + at-or-above, B19013 median
household income) but for all 50 states + DC, at state and county level.
This is the data behind the nationwide county dashboard
(Streamlit/app_US.py): clicking any US state or county needs the full
age-band and poverty-rate variable set, matching what the NJ dashboard
already reads via analysis/dashboard.py.

USDASH_EXTRA_VARS adds five more table families, US-app-only: B27001
(health insurance), B25064/B25071/B25003 (rent, rent burden, tenure),
C16002 (limited-English households), B08201 (vehicles available), B19001
(income brackets). These are NOT added to the shared ACS_DOWNLOAD_VARS
(imported below from pull_trenton_dashboard) -- that list is also used by
the Trenton (place/tract) and NJ pulls, and a variable not published at
place or tract level errors the entire query for that geography (the same
failure mode pull_acs_poverty_bg.py documents for B17001 at block group).
Cell numbers for USDASH_EXTRA_VARS were verified live against the ACS 2024
variables-group endpoint during planning; see analysis/dashboard.py's
"US dashboard extra measures" section for the same cell lists on the read
side.

Not pulled from ACS 1-year: none of the new measures wire the
Streamlit/app_US.py acs1_compare precision line (only population and
income do), so there is nothing to consume a 1-year pull of these tables;
skipped rather than downloaded and left unused.

Also pulls the anchor variables from ACS 1-year (acs/acs1) at county
level. The 1-year product only publishes for geographies at or above
65,000 population, so this query's RETURNED ROW SET is the exact
1-year-availability list -- no population-threshold proxy needed
(the app must not derive availability from B01001_001E >= 65000; see
analysis/dashboard.py::acs_1yr_available docstring for why that proxy is
wrong at the boundary).

Puerto Rico is excluded, not carried as an unclassified row: state="*"
on the Census API returns PR's 78 municipios alongside the 50 states + DC,
but USDA's Rural-Urban Continuum Codes (the classification
Streamlit/app_US.py filters by) do not cover PR, and SAIPE/allocation
coverage there is inconsistent. Filtered out immediately after each
download, before anything is saved or sanity-checked.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt

What it produces
----------------
- data/raw/acs5_2024_usdash_state.parquet    (51 rows -- 50 states + DC)
- data/raw/acs5_2024_usdash_county.parquet   (~3,144 rows)
- data/raw/acs1_2024_usdash_county.parquet   (~800 rows -- exact 1-yr availability list)

If an output file already exists it is NOT re-downloaded (delete it to
force a fresh pull); its sanity checks still run and print.

Run from the repo root:
    python ingestion/pull_usdash.py
"""

from __future__ import annotations

import sys
import time

import censusdis.data as ced
import pandas as pd

from _common import OUT_DIR, REPO_ROOT, load_api_key
from pull_trenton_dashboard import ACS_DOWNLOAD_VARS, acs_sanity

STATE_PR = "72"  # excluded -- see module docstring

USDASH_ACS5_GEO_LEVELS = {
    "state": dict(state="*"),
    "county": dict(state="*", county="*"),
}
EXPECTED_ROWS = {"state": 51, "county": 3_144}  # 50 states + DC; US counties, PR excluded

# US-app-only variables, five table families beyond the shared anchor set
# above -- see module docstring for why these are NOT folded into
# ACS_DOWNLOAD_VARS. Bare cell codes (no E/M suffix); _e_m_pairs() below
# expands each to its (estimate, moe) pair for the actual download.
_UNINSURED_VARS = [f"B27001_{n}" for n in (
    "001",  # civilian noninstitutionalized population (universe)
    "005", "008", "011", "014", "017", "020", "023", "026", "029",  # male, no coverage
    "033", "036", "039", "042", "045", "048", "051", "054", "057",  # female, no coverage
)]
_RENT_VARS = ["B25064_001", "B25071_001", "B25003_001", "B25003_003"]
_LANGUAGE_VARS = [f"C16002_{n}" for n in ("001", "004", "007", "010", "013")]
_VEHICLE_VARS = ["B08201_001", "B08201_002"]
_INCOME_BRACKET_VARS = ["B19001_001"] + [f"B19001_{n:03d}" for n in range(2, 18)]

USDASH_EXTRA_VARS = _UNINSURED_VARS + _RENT_VARS + _LANGUAGE_VARS + _VEHICLE_VARS + _INCOME_BRACKET_VARS


def _e_m_pairs(codes: list[str]) -> list[str]:
    """Bare cell codes -> flat [..., codeE, codeM, ...] download-variable
    list, same E/M interleaving ACS_DOWNLOAD_VARS uses (see
    pull_trenton_dashboard.py's ACS_DOWNLOAD_VARS construction)."""
    return [c for code in codes for c in (f"{code}E", f"{code}M")]


USDASH_ACS5_DOWNLOAD_VARS = ACS_DOWNLOAD_VARS + _e_m_pairs(USDASH_EXTRA_VARS)

# 1-year only publishes above the 65,000-population floor -- expect roughly
# a quarter of all counties, not close to 3,144. Not a fixed exact number
# (which counties clear the floor can shift slightly year to year), so this
# is a sanity range, not an exact-match check like EXPECTED_ROWS above.
ACS1_COUNTY_ROWS_EXPECTED_RANGE = (700, 900)


def extra_measures_sanity(df: pd.DataFrame, level: str, checks: list[str]) -> None:
    """Internal-consistency checks for USDASH_EXTRA_VARS, run alongside
    acs_sanity(). Two are exact-equality checks (their component cells are
    already downloaded for the app's own use, so the check is free):

    - B19001's 16 brackets sum to B19001_001 (the collapsed INCOME_BANDS
      in analysis/dashboard.py rely on this being a clean partition).
    - B25003_003 (renter occupied) never exceeds B25003_001 (total
      occupied).

    B27001 and C16002 get a bound check instead of exact equality: their
    "with coverage" / "not limited" mirror cells are NOT downloaded (would
    only ever be used by this check, never by the app), so this can only
    confirm the "no coverage" / "limited" cells don't exceed the universe,
    not that they exactly equal (universe - mirror). The live label
    lookup during planning is the stronger evidence for those two -- see
    module docstring.
    """
    def numeric(col: str) -> pd.Series:
        return pd.to_numeric(df[col], errors="coerce")

    uninsured = sum(numeric(f"B27001_{n}E") for n in (
        "005", "008", "011", "014", "017", "020", "023", "026", "029",
        "033", "036", "039", "042", "045", "048", "051", "054", "057",
    ))
    universe = numeric("B27001_001E")
    bad = int(((uninsured > universe) & universe.notna() & uninsured.notna()).sum())
    checks.append(f"{'PASS' if bad == 0 else 'FAIL'} [{level}] B27001 uninsured <= universe: "
                  f"{bad} violation(s)")

    limited = sum(numeric(f"C16002_{n}E") for n in ("004", "007", "010", "013"))
    households = numeric("C16002_001E")
    bad = int(((limited > households) & households.notna() & limited.notna()).sum())
    checks.append(f"{'PASS' if bad == 0 else 'FAIL'} [{level}] C16002 limited-English <= "
                  f"total households: {bad} violation(s)")

    brackets = sum(numeric(f"B19001_{n:03d}E") for n in range(2, 18))
    total = numeric("B19001_001E")
    diff = (brackets - total).abs()
    bad = int(((diff > 1) & total.notna() & brackets.notna()).sum())
    checks.append(f"{'PASS' if bad == 0 else 'FAIL'} [{level}] B19001 16 brackets sum to "
                  f"total (tolerance 1): {bad} mismatch(es)")

    renter = numeric("B25003_003E")
    occupied = numeric("B25003_001E")
    bad = int(((renter > occupied) & occupied.notna() & renter.notna()).sum())
    checks.append(f"{'PASS' if bad == 0 else 'FAIL'} [{level}] B25003 renter-occupied <= "
                  f"total occupied: {bad} violation(s)")


def drop_puerto_rico(df: pd.DataFrame, level: str, checks: list[str]) -> pd.DataFrame:
    if "STATE" not in df.columns:
        return df
    pr_mask = df["STATE"] == STATE_PR
    n_pr = int(pr_mask.sum())
    checks.append(f"INFO [{level}] dropped {n_pr} Puerto Rico row(s) (STATE == '72')")
    return df[~pr_mask].reset_index(drop=True)


def pull_level(
    dataset: str, vintage: int, download_vars: list[str], geo_kwargs: dict,
    out_path, level_label: str, checks: list[str], api_key: str,
) -> pd.DataFrame | None:
    """Download one (dataset, geography) pair, drop PR, cache to disk.

    Deliberately not analysis.dashboard's shared pull_product(): that
    helper writes to disk BEFORE any per-row filtering runs, which would
    save Puerto Rico's rows into the cached file. This version filters
    first, so the file on disk (and everything cached-ok on a later rerun)
    is already PR-free.
    """
    expected_cols = set(download_vars) - {"NAME"}
    if out_path.exists() and out_path.stat().st_size > 0:
        cached = pd.read_parquet(out_path)
        if expected_cols.issubset(cached.columns):
            print(f"\nAlready on disk, skipping download: "
                  f"{out_path.relative_to(REPO_ROOT)} (delete to re-pull)")
            return cached
        print(f"\n{out_path.name} is missing columns from a newer variable "
              f"list -- re-pulling ...")

    print(f"\nDownloading {level_label} ...")
    try:
        df = ced.download(
            dataset, vintage, download_variables=download_vars,
            api_key=api_key, **geo_kwargs,
        )
    except Exception as exc:
        checks.append(f"FAIL [{level_label}] download error: {exc}")
        print(f"  FAILED: {exc}")
        return None

    df = drop_puerto_rico(df, level_label, checks)
    df.to_parquet(out_path, index=False)
    print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
          f"({out_path.stat().st_size / 1024:,.0f} KB, {len(df):,} rows)")
    return df


def main() -> None:
    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []

    print("Nationwide dashboard pull: ACS 5-yr (B01001 + B17001 + B19013 + "
          "USDASH_EXTRA_VARS), all states + counties, Puerto Rico excluded")
    for level, geo_kwargs in USDASH_ACS5_GEO_LEVELS.items():
        out_path = OUT_DIR / f"acs5_2024_usdash_{level}.parquet"
        df = pull_level(
            "acs/acs5", 2024, USDASH_ACS5_DOWNLOAD_VARS, geo_kwargs,
            out_path, level, checks, api_key,
        )
        if df is None:
            continue
        expected = EXPECTED_ROWS[level]
        ok = len(df) == expected
        checks.append(
            f"{'PASS' if ok else 'FAIL'} [{level}] row count {len(df):,} "
            f"(expected exactly {expected:,})"
        )
        acs_sanity(df, level, checks)
        extra_measures_sanity(df, level, checks)

    print("\nACS 1-year pull (acs/acs1), county level -- the returned rows "
          "ARE the exact 1-year-availability list, not a proxy")
    acs1_out_path = OUT_DIR / "acs1_2024_usdash_county.parquet"
    acs1_df = pull_level(
        "acs/acs1", 2024, ACS_DOWNLOAD_VARS, dict(state="*", county="*"),
        acs1_out_path, "acs1/county", checks, api_key,
    )
    if acs1_df is not None:
        lo, hi = ACS1_COUNTY_ROWS_EXPECTED_RANGE
        ok = lo <= len(acs1_df) <= hi
        checks.append(
            f"{'PASS' if ok else 'FAIL'} [acs1/county] row count {len(acs1_df):,} "
            f"(expected roughly {lo:,}-{hi:,} -- counties >= 65,000 population)"
        )
        acs_sanity(acs1_df, "acs1/county", checks)

    print(f"\n{'=' * 60}\nCheck summary:")
    for line in checks:
        print(f"  {line}")
    failures = [c for c in checks if c.startswith("FAIL")]
    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        raise SystemExit(f"{len(failures)} sanity check(s) FAILED -- see summary above.")
    print("All sanity checks passed.")


if __name__ == "__main__":
    main()
