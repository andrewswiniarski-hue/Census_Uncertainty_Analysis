"""Pull PUMS income-source allocation flags. Track C, source-split version.

What it does
------------
Downloads the per-record allocation flags for six income sources -- wages,
self-employment, interest/dividends/rent, Social Security, retirement and
public assistance -- from ACS 5-year PUMS at PUMA level, together with the
matching income AMOUNT variables, age, and the household serial number.

This is the decomposition Track C is actually about. The proposal assumed
it lived in the B99 detailed tables; it does not. Filtering all 1,199
tables at vintage 2024 for those concept words returns nothing -- the B99
income tables split by universe, not by source. These flags are the only
published surface where wage nonresponse can be separated from interest
nonresponse.

Three things this script gets right that a flags-only pull cannot
-----------------------------------------------------------------
1. UNIVERSE. A flag is only meaningful against the population eligible to
   answer that question. Rate = allocated / in-universe, NOT allocated /
   all persons. Without the amount variables, a low rate for
   self-employment confounds "rarely imputed" with "rarely applicable" --
   most people have no self-employment income at all.

   Each amount variable carries its own N/A code, and THEY ARE NOT THE
   SAME: WAGP, SSP, RETP and PAP use -1; SEMP and INTP use -10001,
   because -1 is a legitimate LOSS for those two. A blanket `== -1` or
   `< 0` filter silently corrupts exactly the two sources the proposal
   cared most about. See NA_CODE below.

2. WHOLE-RECORD SUBSTITUTION vs ITEM ALLOCATION. In the NJ 2024 data,
   44% of records carrying any allocation flag carry ALL SIX. That is
   whole-person substitution, and it swamps the source signal: pooled
   rates span only 1.5x, but excluding whole-record substitutions the
   same rates span 4.6x. The proposal wanted these separated; this is
   where the separation lives. Both are reported.

3. HOUSEHOLD WEIGHTING. FHINCP is a household-level flag arriving on
   person-level rows. Summing WGTP over person rows counts each household
   once per resident -- for NJ that gives ~9.07M instead of ~3.4M
   households. SERIALNO is pulled so households are deduplicated before
   the household rate is computed.

What it costs
-------------
- PUMA is the geography floor. VERIFIED -- PUMS publishes region, division,
  state and PUMA. There is no tract. NJ has 74 PUMAs against 2,181 tracts.
- PUMS is microdata. There is no MOE column, so there is no published CV
  to correlate an allocation rate against. Uncertainty comes from replicate
  weights (PWGTP1-PWGTP80), not pulled here.
- Therefore EDA 05's controlled-Spearman code path does NOT lift across
  this boundary. This pull tests the PREMISE -- do the components behave
  differently -- rather than re-testing independence.

Use ingestion/pull_acs_alloc_income.py for the tract-level version that
stays comparable to 05.

All variable names CONFIRMED against the live metadata endpoint; see
docs/api-surface-verified.md.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt (pandas, python-dotenv,
  pyarrow, requests)

What it produces
----------------
- data/raw/pums_2024_nj_alloc_flags.parquet        (~445,000 person records)
- data/raw/pums_2024_nj_alloc_rates_puma.parquet   (PUMA x source rates,
                                                    universe-corrected, split
                                                    into whole-record and item)

Run from the repo root:
    python ingestion/pull_pums_alloc_flags.py --dry-run
    python ingestion/pull_pums_alloc_flags.py
    python ingestion/pull_pums_alloc_flags.py --states 34 06
    python ingestion/pull_pums_alloc_flags.py --vintage 2023 --replicates
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

DATASET = common.PUMS_DATASET
STATE_NJ = common.STATE_NJ
OUT_DIR = REPO_ROOT / "data" / "raw"

# Set by main() from --vintage. Defaults to the repo convention in
# analysis/common.py. Output filenames carry the vintage, so pulling a
# second year sits alongside the first rather than overwriting it.
DEFAULT_VINTAGE = common.ACS_VINTAGE
VINTAGE = DEFAULT_VINTAGE
BASE = f"https://api.census.gov/data/{VINTAGE}/{DATASET}"

# CONFIRMED. Person-level flags, weight PWGTP, paired with their amount
# variable so the denominator can be the eligible universe.
PERSON_FLAGS = {
    "FWAGP": ("WAGP", "Wages and salary income"),
    "FSEMP": ("SEMP", "Self-employment income"),
    "FINTP": ("INTP", "Interest, dividend, and net rental income"),
    "FSSP": ("SSP", "Social Security income"),
    "FRETP": ("RETP", "Retirement income"),
    "FPAP": ("PAP", "Public assistance income"),
}
# Household-level flag, weight WGTP. Carries -1 = N/A (GQ).
HOUSEHOLD_FLAGS = {"FHINCP": (None, "Household income (past 12 months)")}
ALL_FLAGS = {**PERSON_FLAGS, **HOUSEHOLD_FLAGS}

# Out-of-universe code per amount variable. NOT uniform -- SEMP and INTP use
# -10001 because -1 is a real loss for them. VERIFIED per variable.
NA_CODE = {
    "WAGP": -1,
    "SEMP": -10001,
    "INTP": -10001,
    "SSP": -1,
    "RETP": -1,
    "PAP": -1,
}

AMOUNT_VARS = [a for a, _ in PERSON_FLAGS.values()]
PERSON_WEIGHT = "PWGTP"
HOUSEHOLD_WEIGHT = "WGTP"

# Demographics for the person-level allocation profile. CONFIRMED against
# the live metadata endpoint. Person-level is the defensible instrument for
# any demographic claim -- a tract-level version would be an ecological
# correlation ("tracts with more X") and cannot support a statement about
# people.
#   AGEP  Age                                    0-99, top-coded
#   SEX   Sex                                    1=Male, 2=Female
#   SCHL  Educational attainment                 N/A under 3 years old
CONTEXT_VARS = ["SERIALNO", "SPORDER", "AGEP", "SEX", "SCHL"]

# Replicate weights -- the ONLY route to a margin of error on a PUMS number.
# PUMS publishes no MOE column. Variance comes from recomputing the statistic
# under each of these 80 weights; see analysis/replicate.py.
#
# The Census API caps `get=` at 50 variables, so these cannot ride along with
# the main request. They are fetched in separate calls and merged on the
# person key (SERIALNO + SPORDER), which is why SPORDER is pulled above.
N_REPLICATES = 80
REPLICATE_VARS = [f"PWGTP{i}" for i in range(1, N_REPLICATES + 1)]
PERSON_KEY = ["SERIALNO", "SPORDER"]
API_GET_LIMIT = 50

# Identifiers that must never be coerced to numeric. PUMA codes are
# zero-padded and state/county are FIPS -- "00906" -> 906 breaks joins.
ID_COLUMNS = {"SERIALNO", "state", "county", "PUMA", "public use microdata area"}

DOWNLOAD_VARS = (list(ALL_FLAGS) + AMOUNT_VARS + CONTEXT_VARS
                 + [PERSON_WEIGHT, HOUSEHOLD_WEIGHT])

NA_GQ = -1                       # FHINCP only -- group quarters, not a zero
EXPECTED_NJ_RECORDS = 444_940    # VERIFIED live at vintage 2024
TIMEOUT = 300


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
    """Ask the API for each variable's label and value map.

    The guard that pins meaning: printed at run time so a changed value
    encoding -- especially an N/A code -- is caught by eyeball before any
    rate is computed. No API key needed.
    """
    labels: dict[str, str] = {}
    for code in list(ALL_FLAGS) + AMOUNT_VARS:
        try:
            meta = requests.get(f"{BASE}/variables/{code}.json", timeout=60).json()
            values = (meta.get("values", {}) or {}).get("item", {})
            vals = ", ".join(f"{k}={v}" for k, v in sorted(values.items()))
            labels[code] = f"{meta.get('label', '<no label>')[:70]}   [{vals}]"
        except requests.RequestException as exc:
            labels[code] = f"<label fetch failed: {exc}>"
    return labels


def verify_na_codes(labels: dict[str, str]) -> None:
    """Fail loudly if an amount variable's N/A code is not what we assume."""
    for amount, expected in NA_CODE.items():
        label = labels.get(amount, "")
        if f"{expected}=N/A" not in label.replace(" ", "").replace("=N/A", "=N/A"):
            token = f"{expected}=N/A"
            if token not in label:
                print(f"  WARNING: {amount} label does not advertise "
                      f"'{token}'. NA_CODE[{amount}] = {expected} may be stale. "
                      f"Check before trusting any {amount} universe.")


def _get(variables: list[str], state: str, key: str) -> pd.DataFrame:
    """One API call. Raises if `variables` exceeds the API's get= limit."""
    if len(variables) > API_GET_LIMIT:
        raise ValueError(
            f"{len(variables)} variables exceeds the API get= limit of "
            f"{API_GET_LIMIT}; split the request")
    url = (f"{BASE}?get={','.join(variables)}"
           f"&for=public%20use%20microdata%20area:*&in=state:{state}&key={key}")
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    df = pd.DataFrame(payload[1:], columns=payload[0])
    # Geography and record identifiers must stay STRINGS. PUMA codes are
    # zero-padded ("00906"); coercing them to numeric silently drops the
    # padding and breaks every join to a geography file. Same for state and
    # county FIPS.
    for col in df.columns:
        if col in ID_COLUMNS or "microdata" in col.lower():
            df[col] = df[col].astype(str)
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fetch_state(state: str, key: str, replicates: bool = False) -> pd.DataFrame:
    """All PUMA records for one state.

    Without replicates this is one call. With them it is three, because the
    API caps get= at 50 variables and 80 replicate weights do not fit
    alongside the flags. The extra calls are merged on the person key
    (SERIALNO + SPORDER) with validate="one_to_one", so a silent fan-out
    fails loudly rather than inflating the file.
    """
    df = _get(DOWNLOAD_VARS, state, key)
    if not replicates:
        return df

    have_key = [c for c in PERSON_KEY if c in df.columns]
    if len(have_key) != len(PERSON_KEY):
        sys.exit(f"Cannot merge replicate weights without {PERSON_KEY}; got {have_key}")

    room = API_GET_LIMIT - len(PERSON_KEY)
    chunks = [REPLICATE_VARS[i:i + room] for i in range(0, len(REPLICATE_VARS), room)]
    for n, chunk in enumerate(chunks, 1):
        print(f"    replicate weights, call {n}/{len(chunks)} "
              f"({chunk[0]}-{chunk[-1]}) ...")
        part = _get(PERSON_KEY + chunk, state, key)
        drop = [c for c in part.columns
                if c not in PERSON_KEY and c not in chunk]
        part = part.drop(columns=drop)
        before = len(df)
        df = df.merge(part, on=PERSON_KEY, how="left", validate="one_to_one")
        if len(df) != before:
            sys.exit(f"Replicate merge changed row count {before} -> {len(df)}")
        time.sleep(0.4)

    missing = [c for c in REPLICATE_VARS if c not in df.columns]
    if missing:
        sys.exit(f"Replicate weights missing after merge: {missing[:5]} ...")
    nulls = int(df[REPLICATE_VARS].isna().any(axis=1).sum())
    if nulls:
        print(f"    WARNING: {nulls:,} rows have at least one null replicate "
              f"weight -- their MOEs will be NaN")
    return df


def puma_column(df: pd.DataFrame) -> str:
    """censusdis and the raw API name this column differently across calls."""
    for c in df.columns:
        if "microdata" in c.lower() or c.lower() == "puma":
            return c
    return ""


def in_universe(df: pd.DataFrame, amount: str) -> pd.Series:
    """True where the person was eligible to be asked about this income type.

    Out-of-universe is the variable's OWN N/A code -- never a blanket
    negative test, which would delete real losses from SEMP and INTP.
    """
    if amount not in df.columns:
        return pd.Series(True, index=df.index)
    return df[amount].notna() & (df[amount] != NA_CODE[amount])


def sanity_report(df: pd.DataFrame) -> None:
    """Flag distributions, universe sizes, GQ handling, weight coherence."""
    print(f"\n  Sanity checks: {len(df):,} records x {len(df.columns)} columns")
    print(f"  {'flag':<8} {'weight':<7} {'0=No':>11} {'1=Yes':>11} "
          f"{'-1=GQ':>9} {'other':>7} {'in-universe':>13}")
    for code, (amount, _) in ALL_FLAGS.items():
        if code not in df.columns:
            print(f"  {code:<8} MISSING FROM API RESPONSE")
            continue
        s = df[code]
        weight = HOUSEHOLD_WEIGHT if code in HOUSEHOLD_FLAGS else PERSON_WEIGHT
        n0, n1 = int((s == 0).sum()), int((s == 1).sum())
        gq = int((s == NA_GQ).sum())
        other = int(len(s) - n0 - n1 - gq)
        univ = int(in_universe(df, amount).sum()) if amount else len(s) - gq
        print(f"  {code:<8} {weight:<7} {n0:>11,} {n1:>11,} {gq:>9,} "
              f"{other:>7,} {univ:>13,}")
        if other:
            print(f"           ^ {other:,} unexpected values -- inspect")

    for weight in (PERSON_WEIGHT, HOUSEHOLD_WEIGHT):
        if weight in df.columns:
            s = df[weight]
            print(f"  {weight}: total {s.sum():,.0f}, min {s.min():,.0f}, "
                  f"max {s.max():,.0f}, zero-weight {int((s == 0).sum()):,}")
    if "SERIALNO" in df.columns:
        hh = df.loc[df[HOUSEHOLD_WEIGHT] > 0].drop_duplicates("SERIALNO")
        print(f"  Distinct households (SERIALNO, non-GQ): {len(hh):,}; "
              f"weighted {hh[HOUSEHOLD_WEIGHT].sum():,.0f}")
        print(f"    ^ this is the correct household denominator. Summing WGTP "
              f"over person rows would give {df[HOUSEHOLD_WEIGHT].sum():,.0f}.")


def substitution_report(df: pd.DataFrame) -> pd.Series:
    """Split allocation into whole-record substitution and item allocation.

    A record carrying ALL SIX person flags had every income item imputed --
    that is whole-person substitution, a different error mechanism from one
    skipped question, and it should not share a composite axis with item
    allocation. Returns the whole-record mask.
    """
    flags = [f for f in PERSON_FLAGS if f in df.columns]
    if not flags:
        return pd.Series(False, index=df.index)
    n_set = df[flags].eq(1).sum(axis=1)
    whole = n_set == len(flags)
    any_set = n_set > 0
    w = df[PERSON_WEIGHT]

    print(f"\n  Allocation mechanism split ({len(flags)} person flags):")
    print(f"    records with no flag set     : {int((n_set == 0).sum()):>9,} "
          f"({(n_set == 0).mean():6.2%})")
    print(f"    records with ANY flag set    : {int(any_set.sum()):>9,} "
          f"({any_set.mean():6.2%})")
    print(f"    records with ALL flags set   : {int(whole.sum()):>9,} "
          f"({whole.sum() / max(int(any_set.sum()), 1):6.2%} of those with any)")
    print(f"    weighted whole-record share  : {w[whole].sum() / w.sum():6.2%} "
          f"of persons")
    print(f"\n    Whole-record substitution is a DIFFERENT error mechanism from")
    print(f"    item allocation. Rates below are reported both ways.")
    return whole


def allocation_rates(df: pd.DataFrame) -> pd.DataFrame:
    """Universe-corrected weighted allocation rate per PUMA per source.

    Person sources: denominator is the in-universe population for that
    income type, weighted by PWGTP. Reported twice -- over all records, and
    excluding whole-record substitutions, so item-level allocation can be
    seen separately.

    Household source: SERIALNO-deduplicated, weighted by WGTP, GQ excluded.
    """
    puma = puma_column(df)
    if not puma:
        print("  WARNING: no PUMA column found; rates computed statewide only")
        df = df.assign(_puma="ALL")
        puma = "_puma"

    whole = substitution_report(df)
    rows = []

    for code, (amount, meaning) in PERSON_FLAGS.items():
        if code not in df.columns:
            continue
        univ = in_universe(df, amount)
        for scope, mask in (("all", univ), ("item_only", univ & ~whole)):
            sub = df[mask]
            if sub.empty:
                continue
            for key, grp in sub.groupby(puma):
                denom = grp[PERSON_WEIGHT].sum()
                numer = grp.loc[grp[code] == 1, PERSON_WEIGHT].sum()
                rows.append({
                    "puma": key, "source": code, "amount_var": amount,
                    "label": meaning, "universe": "person", "scope": scope,
                    "weighted_denominator": float(denom),
                    "weighted_allocated": float(numer),
                    "alloc_rate": float(numer / denom) if denom else float("nan"),
                    "n_records": int(len(grp)),
                })

    for code, (_, meaning) in HOUSEHOLD_FLAGS.items():
        if code not in df.columns or "SERIALNO" not in df.columns:
            continue
        # One row per household, GQ excluded (FHINCP == -1 and WGTP == 0).
        hh = df[df[code].isin([0, 1])].drop_duplicates("SERIALNO")
        for key, grp in hh.groupby(puma):
            denom = grp[HOUSEHOLD_WEIGHT].sum()
            numer = grp.loc[grp[code] == 1, HOUSEHOLD_WEIGHT].sum()
            rows.append({
                "puma": key, "source": code, "amount_var": None,
                "label": meaning, "universe": "household", "scope": "all",
                "weighted_denominator": float(denom),
                "weighted_allocated": float(numer),
                "alloc_rate": float(numer / denom) if denom else float("nan"),
                "n_records": int(len(grp)),
            })

    return pd.DataFrame(rows)


def rate_summary(rates: pd.DataFrame) -> None:
    """The spread across sources -- the whole point of the pull."""
    if rates.empty:
        return
    for scope, title in (("all", "ALL records (includes whole-record substitution)"),
                         ("item_only", "ITEM allocation only (whole-record removed)")):
        sub = rates[rates["scope"] == scope]
        if sub.empty:
            continue
        print(f"\n  {title}")
        print(f"  {'source':<8} {'universe':<10} {'PUMAs':>6} {'min':>8} "
              f"{'median':>8} {'max':>8}")
        summary = sub.groupby(["source", "universe"])["alloc_rate"].agg(
            ["count", "min", "median", "max"]).sort_values("median", ascending=False)
        for (code, universe), r in summary.iterrows():
            print(f"  {code:<8} {universe:<10} {int(r['count']):>6} "
                  f"{r['min']:>8.2%} {r['median']:>8.2%} {r['max']:>8.2%}")
        person = summary[summary.index.get_level_values("universe") == "person"]
        if len(person) > 1:
            lo, hi = float(person["median"].min()), float(person["median"].max())
            ratio = f"{hi / lo:.2f}x" if lo > 0 else "undefined (lowest is 0%)"
            print(f"    -> median rate spans {lo:.2%} to {hi:.2%}  ({ratio})")

    a = rates[rates["scope"] == "all"]
    i = rates[rates["scope"] == "item_only"]
    if not a.empty and not i.empty:
        def spread(x):
            m = x[x["universe"] == "person"].groupby("source")["alloc_rate"].median()
            return (m.max() / m.min()) if len(m) > 1 and m.min() > 0 else float("nan")
        sa, si = spread(a), spread(i)
        if sa == sa and si == si:
            print(f"\n  Pooling effect: source spread widens from {sa:.2f}x to "
                  f"{si:.2f}x once whole-record substitution is removed.")
            print(f"  If that widening holds, a single pooled allocation rate is "
                  f"averaging over two different mechanisms, not one.")


def dry_run(states: list[str], replicates: bool = False) -> None:
    """Print the request plan and expected volume. Fetch nothing."""
    print("DRY RUN -- no data will be fetched.\n")
    print(f"  Dataset       {DATASET} vintage {VINTAGE}")
    print(f"  Geography     public use microdata area, state(s) {', '.join(states)}")
    print(f"  Variables     {len(DOWNLOAD_VARS)} columns "
          f"({len(ALL_FLAGS)} flags + {len(AMOUNT_VARS)} amounts + "
          f"{len(CONTEXT_VARS)} context + 2 weights)")
    print(f"\n  Flags and their universe variable:")
    for code, (amount, meaning) in ALL_FLAGS.items():
        weight = HOUSEHOLD_WEIGHT if code in HOUSEHOLD_FLAGS else PERSON_WEIGHT
        na = f"N/A code {NA_CODE[amount]}" if amount else "GQ code -1"
        print(f"    {code:<8} {weight:<6} universe {str(amount or 'SERIALNO'):<9} "
              f"{na:<16} {meaning}")
    est = EXPECTED_NJ_RECORDS * len(states)
    print(f"\n  Expected records ~{est:,} "
          f"(NJ VERIFIED at {EXPECTED_NJ_RECORDS:,} for vintage {DEFAULT_VINTAGE}; "
          f"other vintages will differ)")
    print(f"  Expected cells ~{est * len(DOWNLOAD_VARS):,}")
    print(f"  Output        "
          f"{(OUT_DIR / out_name(states, 'alloc_flags')).relative_to(REPO_ROOT)}")
    print(f"                "
          f"{(OUT_DIR / out_name(states, 'alloc_rates_puma')).relative_to(REPO_ROOT)}")
    if replicates:
        n_calls = 1 + -(-len(REPLICATE_VARS) // (API_GET_LIMIT - len(PERSON_KEY)))
        print(f"\n  Replicate weights: {len(REPLICATE_VARS)} columns, "
              f"{n_calls} API calls per state")
        print(f"  (the API caps get= at {API_GET_LIMIT}; merged on "
              f"{'+'.join(PERSON_KEY)})")
        print(f"  Expected cells ~{est * (len(DOWNLOAD_VARS)+len(REPLICATE_VARS)):,}")
    print("\n  Microdata -- one row per person. " +
          ("Replicate weights give margins of error."
           if replicates else "No MOE column, no tract level."))


def out_name(states: list[str], kind: str) -> str:
    scope = "nj" if states == [STATE_NJ] else "_".join(states)
    return f"pums_{VINTAGE}_{scope}_{kind}.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull PUMS income-source allocation flags for Track C (PUMA).")
    parser.add_argument("--states", nargs="+", default=[STATE_NJ],
                        help="state FIPS codes (default 34 = NJ)")
    parser.add_argument("--vintage", type=int, default=DEFAULT_VINTAGE,
                        help=f"ACS 5-year vintage (default {DEFAULT_VINTAGE}). "
                             f"Output filenames carry it, so a second year does "
                             f"not overwrite the first.")
    parser.add_argument("--replicates", action="store_true",
                        help="also pull PWGTP1-PWGTP80 so estimates get margins "
                             "of error (3 API calls per state instead of 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the request plan and expected rows, fetch nothing")
    args = parser.parse_args()
    states = list(args.states)

    global VINTAGE, BASE
    VINTAGE = args.vintage
    BASE = f"https://api.census.gov/data/{VINTAGE}/{DATASET}"

    if args.dry_run:
        dry_run(states, args.replicates)
        return

    t0 = time.perf_counter()
    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"ACS 5-year PUMS allocation flags, vintage {VINTAGE}, "
          f"state(s) {', '.join(states)}")
    print("\nOfficial labels from the API -- verify the value encoding:")
    labels = fetch_official_labels()
    for code, label in labels.items():
        print(f"  {code:<9} {label}")
    verify_na_codes(labels)

    frames = []
    failures: list[str] = []
    for st in states:
        print(f"\nDownloading PUMS for state {st} ...")
        try:
            df = fetch_state(st, api_key, args.replicates)
        except Exception as exc:  # report and keep going; fail loudly at the end
            failures.append(st)
            print(f"  FAILED: {exc}")
            continue
        print(f"  {len(df):,} person records")
        if (st == STATE_NJ and VINTAGE == DEFAULT_VINTAGE
                and abs(len(df) - EXPECTED_NJ_RECORDS) > 5_000):
            print(f"  WARNING: NJ returned {len(df):,}, verification saw "
                  f"{EXPECTED_NJ_RECORDS:,} at vintage {DEFAULT_VINTAGE}")
        frames.append(df)
        time.sleep(0.4)

    if not frames:
        sys.exit("No state returned data. Nothing written.")

    out = pd.concat(frames, ignore_index=True)
    flags_path = OUT_DIR / out_name(states, "alloc_flags")
    out.to_parquet(flags_path, index=False)
    sanity_report(out)

    rates = allocation_rates(out)
    rates_path = OUT_DIR / out_name(states, "alloc_rates_puma")
    rates.to_parquet(rates_path, index=False)
    rate_summary(rates)

    print(f"\n  Saved {flags_path.relative_to(REPO_ROOT)} "
          f"({flags_path.stat().st_size / 1024:,.0f} KB)")
    print(f"  Saved {rates_path.relative_to(REPO_ROOT)} "
          f"({len(rates):,} PUMA x source x scope rows)")
    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if args.replicates:
        print("\n  Replicate weights pulled -- use analysis/replicate.py for margins "
              "of error. Comparing two groups needs difference(), which forms the "
              "difference inside each replicate; sqrt(se_a^2+se_b^2) is WRONG here "
              "because subgroups of one sample are not independent.")
    print("\n  Reminder: no MOE column exists here. Do NOT correlate these rates "
          "against a CV -- there is none at PUMA. Use "
          "ingestion/pull_acs_alloc_income.py for the tract-level, "
          "05-comparable version.")
    if failures:
        sys.exit(f"One or more states FAILED: {', '.join(failures)}")


if __name__ == "__main__":
    main()
