"""Survey pull: a stratified sample of the WHOLE ACS 5-year table universe at US counties.

What it does
------------
Two products in one scripted pull, for EDA 14 (the ACS-wide error-bar survey,
a lead-directed proof of concept, 2026-08-16):

1. A **variable manifest**: classifies every name in the 2024 acs/acs5
   variables.json (~28,472) -- table id, subject family, measurement type
   (count / median / aggregate / ...), race-iteration flag, label depth --
   so the notebook can describe the whole dataset, not just what we pulled.
2. A **data pull** for a deterministic stratified sample of ~100 detailed
   tables at every US county (``for=county:*``; ~3,222 rows incl. Puerto
   Rico's 78 municipios), one API call per table, capturing estimate, MOE,
   and BOTH annotation columns for every variable in the table.

Two conventions are NEW to this repo and documented here deliberately:

* **``get=group(TABLE)`` transport.** One call returns every column of a
  table (E / EA / M / MA plus GEO_ID, NAME, state, county -- verified live
  2026-08-16), bypassing the API's 50-variable list limit. Every earlier
  script enumerated variables one by one; a ~100-table survey cannot.
* **MOE names are DERIVED, never inventoried.** The 2024 acs/acs5
  variables.json lists ZERO ``_M`` names out of 28,472 even though every
  MOE is individually queryable (documented metadata gap, HANDOFF.md and
  docs/data-dictionary.md). This script derives ``B19013_001M`` from
  ``B19013_001E`` by convention and then verifies which siblings actually
  arrive **empirically from each response header**, recording the result
  per variable in the manifest (``observed_*`` columns).

Transport is plain ``requests``, NOT censusdis: censusdis converts the
annotation jam values (``-666666666`` estimates, ``-555555555`` MOEs, ...)
to NaN, which destroys the distinction this survey exists to measure --
a "controlled, extremely reliable" blank vs. an "insufficient sample,
unreliable" blank. Raw API strings are stored verbatim (the raw-stays-raw
convention set by the SF1 pull); numeric coercion happens in the analysis
layer. Jam-value meanings follow the Bureau's "Notes on ACS Estimate and
Annotation Values" page (verified 2026-08-16). Precedent for a
non-censusdis pull with a documented reason: ingestion/pull_saipe_nj.py.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file -- REQUIRED here (~102 calls;
  free + instant: https://api.census.gov/data/key_signup.html)
- Internet access; packages from requirements.txt (requests via censusdis,
  pandas, python-dotenv, pyarrow)
- Optional, for one cross-pull identity check:
  data/raw/acs5_nj_county_income_2019_2024.parquet (regenerate with
  ``python ingestion/pull_acs_income_county_nj.py``); the check SKIPs
  with a hint if absent.

What it produces
----------------
Four parquets in data/raw/ (local-only, regenerable; values are raw API
strings unless noted):

- acswide_2024_variable_manifest.parquet   one row per variables.json name
- acswide_2024_us_county_long.parquet      one row per (county x variable)
  for the sampled tables: geoid, table_id, variable, estimate_raw,
  est_annot_raw, moe_raw, moe_annot_raw  (~2-3k variables x ~3,222
  counties; long format because the survey's questions are cross-table)
- acswide_2024_us_county_geos.parquet      county dimension (geoid, state,
  county, NAME_raw, GEO_ID_raw), stored once instead of per data row
- acswide_2024_us_county_pull_report.parquet  per-table status/receipts

The sample is a pure function of variables.json content and SEED -- run
``--plan-only`` twice and diff the output to see the determinism.

Run from the repo root:
    python ingestion/pull_acs_wide_us_county.py [--plan-only]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter
from pathlib import Path
from random import Random

import pandas as pd
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "raw"

DATASET = "acs/acs5"
VINTAGE = 2024
BASE_URL = f"https://api.census.gov/data/{VINTAGE}/{DATASET}"

SEED = 20260816          # the direction date; makes the sample reproducible
TARGET_TABLES = 100
FAMILY_CAP = 6           # keeps the huge B25 housing family from swamping
SLEEP_S = 0.5            # be polite to the API between calls

# B98 (quality measures) and B99 (allocation) publish no MOEs BY DESIGN --
# they are covariates about the data, not survey estimates (HANDOFF
# landmine: requesting a _M on them errors the whole query). They stay in
# the manifest, flagged, but are excluded from the data-pull frame.
EXCLUDE_PREFIXES = ("B98", "B99")

# Forced anchors: hand-verified tables that give the survey ground truth
# and make sure the hard cases are represented. reason -> shows up in the
# pull report and the printed plan.
FORCED_TABLES = {
    "B01003": "total population; controlled-estimate jam showcase (EDA 01/02 anchor)",
    "B19013": "median household income; scoped anchor; NJ cross-pull ground truth",
    "B17001": "poverty; scoped anchor; internal universe identity check",
    "C17002": "income-to-poverty ratio; scoped stack; collapsed-table exemplar",
    "B01001B": "Black age/sex; EDA 02 continuity; race-iteration exemplar",
    "B19013B": "median income, Black householder; median x small subgroup, hardest case",
    "B25064": "median gross rent; fresh median case outside income",
    "B25077": "median home value; fresh median case outside income",
    "B15003": "educational attainment; big count table",
    "B23025": "employment status; big count table",
    "B27001": "health insurance; big count table, many cells",
}

# Two-digit ACS subject family codes (chars 1:3 of a table id).
SUBJECT_FAMILIES = {
    "01": "Age & Sex", "02": "Race", "03": "Hispanic Origin", "04": "Ancestry",
    "05": "Citizenship & Foreign Born", "06": "Place of Birth", "07": "Migration",
    "08": "Commuting", "09": "Children & Relationship", "10": "Grandparents",
    "11": "Household & Family Type", "12": "Marital Status", "13": "Fertility",
    "14": "School Enrollment", "15": "Educational Attainment", "16": "Language at Home",
    "17": "Poverty", "18": "Disability", "19": "Income", "20": "Earnings",
    "21": "Veteran Status", "22": "Food Stamps/SNAP", "23": "Employment Status",
    "24": "Industry & Occupation", "25": "Housing", "26": "Group Quarters",
    "27": "Health Insurance", "28": "Computers & Internet",
    "29": "Voting-Age Citizens", "98": "Quality Measures (no MOEs)",
    "99": "Allocation Rates (no MOEs)",
}

# Official jam values, Census "Notes on ACS Estimate and Annotation
# Values" (verified 2026-08-16). Estimates and MOEs use different codes.
JAM_ESTIMATE = {
    "-999999999": "N: too few sample cases in this geography",
    "-888888888": "(X): not applicable / not available",
    "-666666666": "-: estimate not computable (insufficient sample, or median in open-ended interval)",
}
JAM_MOE = {
    "-999999999": "N: too few sample cases in this geography",
    "-888888888": "(X): not applicable / not available",
    "-555555555": "*****: estimate is controlled to an independent total; no sampling error",
    "-333333333": "***: MOE not computable (median in open-ended interval)",
    "-222222222": "**: MOE not computable (insufficient sample observations)",
}

# A standard detailed-table estimate name: B19013_001E, C17002_003E,
# B01001B_014E, B05006PR_001E ...
VAR_RE = re.compile(r"^([BC]\d{5}[A-I]?(?:PR)?)_(\d{3})E$")
TABLE_RE = re.compile(r"^([BC])(\d{2})(\d{3})([A-I])?(PR)?$")

EXPECTED_COUNTY_RANGE = (3140, 3260)   # ~3,222 incl. PR as of vintage 2024
EXPECTED_PR_MUNICIPIOS = 78
EXPECTED_NJ_COUNTIES = 21
NATIONAL_POP_RANGE = (320_000_000, 350_000_000)   # US + PR, loose bounds

COMPARATOR_PARQUET = OUT_DIR / "acs5_nj_county_income_2019_2024.parquet"

MANIFEST_PATH = OUT_DIR / "acswide_2024_variable_manifest.parquet"
LONG_PATH = OUT_DIR / "acswide_2024_us_county_long.parquet"
GEOS_PATH = OUT_DIR / "acswide_2024_us_county_geos.parquet"
REPORT_PATH = OUT_DIR / "acswide_2024_us_county_pull_report.parquet"


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def load_api_key() -> str:
    """Load CENSUS_API_KEY from .env; exit with guidance if missing."""
    load_dotenv(REPO_ROOT / ".env")
    import os

    key = os.getenv("CENSUS_API_KEY", "").strip()
    if not key or key in {"your_key_here", "paste_your_key_here"}:
        sys.exit(
            "CENSUS_API_KEY missing from .env -- this pull makes ~102 calls and "
            "requires one. Free + instant: https://api.census.gov/data/key_signup.html"
        )
    return key


def http_get_json(url: str, params: dict | None = None, timeout: int = 90,
                  retry: bool = True):
    """GET a JSON payload with one retry on transient failures.

    Retry semantics follow tools/product_scope.py::_http_get_json (the
    team's tracker): 5xx / timeouts / connection errors get one retry
    after a short sleep; 429 is retried too (rate limit); any other 4xx
    raises immediately (a malformed query will not fix itself).
    """
    for attempt in (1, 2):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 429 and retry and attempt == 1:
                time.sleep(1.0)
                continue
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except (requests.ConnectionError, requests.Timeout, ValueError,
                requests.HTTPError) as exc:
            is_client_error = (
                isinstance(exc, requests.HTTPError)
                and exc.response is not None
                and 400 <= exc.response.status_code < 500
                and exc.response.status_code != 429
            )
            if is_client_error or not retry or attempt == 2:
                raise
            time.sleep(0.75)


# ---------------------------------------------------------------------------
# Manifest: classify every variables.json name
# ---------------------------------------------------------------------------

def fetch_variables() -> dict:
    """One GET of the full variables.json (~28-30 MB)."""
    payload = http_get_json(f"{BASE_URL}/variables.json")
    variables = payload.get("variables", {})
    for pseudo in ("for", "in", "ucgid"):   # geography predicates, not variables
        variables.pop(pseudo, None)
    return variables


def fetch_group_metadata() -> dict:
    """Table id -> (description, universe) from groups.json.

    Some vintages publish the universe under a 'universe ' key with a
    trailing space -- handle both spellings.
    """
    payload = http_get_json(f"{BASE_URL}/groups.json")
    out = {}
    for g in payload.get("groups", []):
        universe = g.get("universe") or g.get("universe ") or None
        out[g.get("name", "")] = (g.get("description") or None, universe)
    return out


def classify_measurement(concept: str, label: str) -> str:
    """Keyword precedence on concept+label; first match wins.

    Median > Mean > Aggregate > Per capita > Ratio/Rate > count. 'count'
    is the default because detailed-table cells are person/household/
    housing-unit counts unless the label says otherwise. Deliberately NO
    'dollars' rule: income-bracket cells ("Less than $10,000") mention
    dollars in the concept but are counts of households, not dollar
    values (found live 2026-08-16 -- a dollars keyword mislabels ~2,900
    bracket counts).
    """
    text = f"{concept} {label}".lower()
    if "median" in text:
        return "median"
    if "mean " in text or text.startswith("mean"):
        return "mean"
    if "aggregate" in text:
        return "aggregate"
    if "per capita" in text:
        return "per_capita"
    if "ratio" in text or " rate" in text:
        return "ratio_or_rate"
    return "count"


def build_manifest(variables: dict, group_meta: dict) -> pd.DataFrame:
    """One row per variables.json name, standard-pattern or not."""
    rows = []
    for name, meta in variables.items():
        label = meta.get("label") or ""
        concept = meta.get("concept") or ""
        group = meta.get("group") or None
        m = VAR_RE.match(name)
        if m:
            table_id, line = m.group(1), m.group(2)
            tm = TABLE_RE.match(table_id)
            family_code = tm.group(2) if tm else None
            iteration = tm.group(4) if tm else None
            is_pr = bool(tm.group(5)) if tm else False
            desc, universe = group_meta.get(table_id, (None, None))
            rows.append({
                "name": name, "table_id": table_id, "line_number": line,
                "is_estimate": True,
                "family_code": family_code,
                "family_name": SUBJECT_FAMILIES.get(family_code,
                                                    f"Unknown ({family_code})"),
                "concept_raw": concept or None, "label_raw": label or None,
                "universe_raw": universe, "group_raw": group,
                "table_title_raw": desc,
                "label_depth": label.count("!!"),
                "is_total_row": line == "001",
                "measurement_type": classify_measurement(concept, label),
                "iteration_code": iteration,
                "is_iteration": iteration is not None,
                "is_collapsed": table_id.startswith("C"),
                "is_pr_table": is_pr,
                "is_alloc_or_quality": table_id.startswith(EXCLUDE_PREFIXES),
            })
        else:
            rows.append({
                "name": name, "table_id": group, "line_number": None,
                "is_estimate": False, "family_code": None, "family_name": None,
                "concept_raw": concept or None, "label_raw": label or None,
                "universe_raw": None, "group_raw": group, "table_title_raw": None,
                "label_depth": label.count("!!"), "is_total_row": False,
                "measurement_type": None, "iteration_code": None,
                "is_iteration": False, "is_collapsed": False,
                "is_pr_table": False, "is_alloc_or_quality": False,
            })
    df = pd.DataFrame(rows)
    df["in_sample"] = False
    df["sample_reason"] = None
    return df


# ---------------------------------------------------------------------------
# Deterministic stratified sample
# ---------------------------------------------------------------------------

def select_sample(manifest: pd.DataFrame) -> dict:
    """Pick ~TARGET_TABLES tables; pure function of the manifest + SEED.

    Returns {table_id: reason}. Order of operations (documented in the
    module docstring): forced anchors, then one per-family overview table,
    then a seeded round-robin fill across families (cap FAMILY_CAP each).
    Race-iteration and PR tables are excluded from the RANDOM frame only
    (iterations are structurally identical to their parents; two enter as
    forced exemplars instead).
    """
    est = manifest[manifest["is_estimate"]]
    eligible = (
        est[~est["is_alloc_or_quality"] & ~est["is_iteration"] & ~est["is_pr_table"]]
        .groupby("table_id")
        .agg(family=("family_code", "first"), n_vars=("name", "size"))
        .reset_index()
    )

    picks: dict[str, str] = {}
    for table, reason in FORCED_TABLES.items():
        picks[table] = f"forced: {reason}"

    # Family overviews: the lowest-numbered non-iterated, non-PR B-table.
    b_only = eligible[eligible["table_id"].str.startswith("B")]
    for family, sub in b_only.sort_values("table_id").groupby("family"):
        first = sub["table_id"].iloc[0]
        if first not in picks:
            picks[first] = f"overview: lowest-numbered base table of family {family}"

    # Seeded round-robin fill.
    rng = Random(SEED)
    fam_counts = Counter(
        (TABLE_RE.match(t).group(2) if TABLE_RE.match(t) else "??") for t in picks
    )
    remaining = {
        family: sorted(sub["table_id"][~sub["table_id"].isin(picks)])
        for family, sub in eligible.groupby("family")
    }
    families = sorted(remaining)
    while len(picks) < TARGET_TABLES:
        progressed = False
        for family in families:
            if len(picks) >= TARGET_TABLES:
                break
            pool = remaining[family]
            if not pool or fam_counts[family] >= FAMILY_CAP:
                continue
            choice = pool.pop(rng.randrange(len(pool)))
            picks[choice] = f"sampled: seeded round-robin, family {family}"
            fam_counts[family] += 1
            progressed = True
        if not progressed:   # every family exhausted or capped
            break
    return picks


def print_sample_plan(manifest: pd.DataFrame, picks: dict) -> None:
    est = manifest[manifest["is_estimate"] & manifest["table_id"].isin(picks)]
    n_vars = est.groupby("table_id")["name"].size()
    print(f"\nSample plan -- {len(picks)} tables, {int(n_vars.sum()):,} estimate "
          f"variables (SEED={SEED}, cap {FAMILY_CAP}/family):")
    by_family = sorted(picks, key=lambda t: (TABLE_RE.match(t).group(2), t))
    current = None
    for table in by_family:
        family = TABLE_RE.match(table).group(2)
        if family != current:
            current = family
            print(f"  -- family {family} ({SUBJECT_FAMILIES.get(family, '?')})")
        print(f"     {table:<10} {int(n_vars.get(table, 0)):>3} vars  {picks[table]}")


# ---------------------------------------------------------------------------
# The pull
# ---------------------------------------------------------------------------

def fetch_group_table(table: str, api_key: str) -> list[list]:
    return http_get_json(
        BASE_URL, params={"get": f"group({table})", "for": "county:*", "key": api_key}
    )


def parse_group_rows(table: str, rows: list[list]):
    """Header-driven melt of one group() response into long rows.

    Sibling M/EA/MA columns are found in the HEADER, never assumed from
    metadata (the variables.json gap countermeasure). Values are kept as
    the exact strings (or nulls) the API returned.
    """
    header, data = rows[0], rows[1:]
    idx = {col: i for i, col in enumerate(header)}
    i_state, i_county = idx["state"], idx["county"]
    geoids = [r[i_state] + r[i_county] for r in data]

    geo_df = pd.DataFrame({
        "geoid": geoids,
        "state": [r[i_state] for r in data],
        "county": [r[i_county] for r in data],
        "NAME_raw": [r[idx["NAME"]] for r in data] if "NAME" in idx else None,
        "GEO_ID_raw": [r[idx["GEO_ID"]] for r in data] if "GEO_ID" in idx else None,
    })

    frames, obs = [], {}
    for col in header:
        m = VAR_RE.match(col)
        if not m:
            continue
        stem = col[:-1]
        sib = {suffix: f"{stem}{suffix}" for suffix in ("M", "EA", "MA")}
        present = {s: name in idx for s, name in sib.items()}
        obs[f"{stem}E"] = {
            "observed_in_pull": True,
            "observed_m_col": present["M"],
            "observed_ea_col": present["EA"],
            "observed_ma_col": present["MA"],
        }
        take = lambda name: [r[idx[name]] for r in data]  # noqa: E731
        frames.append(pd.DataFrame({
            "geoid": geoids,
            "table_id": table,
            "variable": stem,
            "estimate_raw": take(col),
            "est_annot_raw": take(sib["EA"]) if present["EA"] else None,
            "moe_raw": take(sib["M"]) if present["M"] else None,
            "moe_annot_raw": take(sib["MA"]) if present["MA"] else None,
        }))
    long_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return geo_df, long_df, obs


def pull_all(picks: dict, api_key: str):
    """One group() call per table; per-table failures recorded, not fatal."""
    long_parts, report_rows, all_obs = [], [], {}
    geos_df, reference_geoids = None, None

    for n, table in enumerate(sorted(picks), start=1):
        t0 = time.perf_counter()
        row = {"table_id": table, "sample_reason": picks[table], "status": "ok",
               "http_code": 200, "error_msg": None, "n_rows": 0, "n_cols": 0,
               "n_e_vars": 0, "n_with_m_col": 0, "n_with_ea_col": 0,
               "n_with_ma_col": 0, "elapsed_s": 0.0,
               "pulled_at_utc": pd.Timestamp.now(tz="UTC").isoformat()}
        try:
            rows = fetch_group_table(table, api_key)
            geo_df, long_df, obs = parse_group_rows(table, rows)
            n_rows = len(geo_df)

            if reference_geoids is None:
                lo, hi = EXPECTED_COUNTY_RANGE
                if not lo <= n_rows <= hi:
                    sys.exit(
                        f"First table {table} returned {n_rows} counties, outside "
                        f"[{lo}, {hi}] -- fundamental geography problem, not a "
                        "per-table quirk. Bad pull?"
                    )
                reference_geoids = frozenset(geo_df["geoid"])
                geos_df = geo_df
            elif frozenset(geo_df["geoid"]) != reference_geoids:
                raise ValueError(
                    f"GEOID set differs from the reference table "
                    f"({n_rows} vs {len(reference_geoids)} counties)"
                )

            long_parts.append(long_df)
            all_obs.update(obs)
            row.update({
                "n_rows": n_rows, "n_cols": len(rows[0]), "n_e_vars": len(obs),
                "n_with_m_col": sum(o["observed_m_col"] for o in obs.values()),
                "n_with_ea_col": sum(o["observed_ea_col"] for o in obs.values()),
                "n_with_ma_col": sum(o["observed_ma_col"] for o in obs.values()),
            })
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            row.update({"status": "http_error", "http_code": code,
                        "error_msg": str(exc)[:200]})
        except (ValueError, KeyError, IndexError) as exc:
            status = "geoid_mismatch" if "GEOID" in str(exc) else "bad_shape"
            row.update({"status": status, "error_msg": str(exc)[:200]})

        row["elapsed_s"] = round(time.perf_counter() - t0, 2)
        report_rows.append(row)
        print(f"  [{n:>3}/{len(picks)}] {table:<10} {row['status']:<14}"
              f"{row['n_rows']:>5} rows  {row['n_e_vars']:>3} E-vars"
              f"  {row['elapsed_s']:>5.1f}s")
        time.sleep(SLEEP_S)

    long_df = pd.concat(long_parts, ignore_index=True)
    for col in ("geoid", "table_id", "variable"):
        long_df[col] = long_df[col].astype("category")
    return long_df, geos_df, pd.DataFrame(report_rows), all_obs


# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

def _num(series: pd.Series) -> pd.Series:
    """Numeric view of raw strings; jam values masked to NaN for math."""
    s = pd.to_numeric(series, errors="coerce")
    return s.where(s > -200_000_000)   # every jam code is <= -222222222


def sanity_report(manifest, picks, long_df, geos_df, report_df) -> None:
    print(f"\nSanity checks -- long file {len(long_df):,} rows; "
          f"{len(geos_df):,} counties; {len(report_df)} tables attempted")
    failures = []

    def check(ok: bool, label: str, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f" -- {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    n_est = int(manifest["is_estimate"].sum())
    check(len(manifest) >= 28_000, "manifest covers the variables.json universe",
          f"{len(manifest):,} names, {n_est:,} standard estimates")

    ok_tables = set(report_df.loc[report_df["status"] == "ok", "table_id"])
    check(all(t in ok_tables for t in FORCED_TABLES),
          "all 11 forced anchor tables pulled OK",
          ", ".join(sorted(t for t in FORCED_TABLES if t not in ok_tables)) or "all present")
    success = len(ok_tables) / len(report_df)
    check(success >= 0.90, "pull success rate >= 90%",
          f"{len(ok_tables)}/{len(report_df)} = {success:.1%}")

    lo, hi = EXPECTED_COUNTY_RANGE
    check(lo <= len(geos_df) <= hi, f"county count in [{lo}, {hi}]", f"{len(geos_df):,}")
    pr = int((geos_df["state"] == "72").sum())
    check(pr == EXPECTED_PR_MUNICIPIOS, "Puerto Rico municipios == 78 (kept, flagged)",
          str(pr))
    nj = int((geos_df["state"] == "34").sum())
    check(nj == EXPECTED_NJ_COUNTIES, "New Jersey counties == 21", str(nj))

    # Jam preservation: county total population is CONTROLLED, so its MOE
    # arrives as the -555555555 sentinel. This is the exact information
    # censusdis would have turned into NaN -- the transport choice's proof.
    pop = long_df[long_df["variable"] == "B01003_001"]
    n_controlled = int((pop["moe_raw"] == "-555555555").sum())
    check(n_controlled > 0, "controlled-estimate sentinel preserved on B01003 MOEs",
          f"{n_controlled:,}/{len(pop):,} counties carry -555555555")

    # Poverty universe identity on clean rows.
    pov = long_df[long_df["variable"].isin(["B17001_001", "B17001_002"])]
    wide = pov.pivot_table(index="geoid", columns="variable", values="estimate_raw",
                           aggfunc="first", observed=True)
    both = wide.dropna()
    below, universe = _num(both["B17001_002"]), _num(both["B17001_001"])
    clean = below.notna() & universe.notna()
    check(bool((below[clean] <= universe[clean]).all()),
          "poverty count <= poverty universe on every clean county",
          f"{int(clean.sum()):,} counties compared")

    total_pop = _num(pop["estimate_raw"]).sum()
    lo_p, hi_p = NATIONAL_POP_RANGE
    check(lo_p <= total_pop <= hi_p, "national population sum in range (US + PR)",
          f"{total_pop:,.0f}")

    expected_rows = int(
        (report_df.loc[report_df["status"] == "ok", "n_e_vars"]
         * report_df.loc[report_df["status"] == "ok", "n_rows"]).sum()
    )
    check(len(long_df) == expected_rows, "long row count == sum(E-vars x counties)",
          f"{len(long_df):,} == {expected_rows:,}")

    # Cross-pull ground truth: Mercer County NJ B19013 must equal the
    # verified censusdis pull, re-derived at runtime (never hardcoded).
    if COMPARATOR_PARQUET.exists():
        comp = pd.read_parquet(COMPARATOR_PARQUET)
        comp = comp[(comp["VINTAGE"] == VINTAGE) & (comp["STATE"] == "34")
                    & (comp["COUNTY"] == "021")]
        mine = long_df[(long_df["variable"] == "B19013_001")
                       & (long_df["geoid"] == "34021")]
        if len(comp) == 1 and len(mine) == 1:
            e_match = int(_num(mine["estimate_raw"]).iloc[0]) == int(comp["B19013_001E"].iloc[0])
            m_match = int(_num(mine["moe_raw"]).iloc[0]) == int(comp["B19013_001M"].iloc[0])
            check(e_match and m_match,
                  "Mercer County B19013 E and M match the verified NJ pull exactly",
                  f"E {int(comp['B19013_001E'].iloc[0]):,}, M {int(comp['B19013_001M'].iloc[0]):,}")
        else:
            check(False, "Mercer comparator rows located",
                  f"comparator rows {len(comp)}, survey rows {len(mine)}")
    else:
        print("  SKIP  Mercer cross-pull check -- comparator parquet absent; "
              "regenerate with: python ingestion/pull_acs_income_county_nj.py")

    if failures:
        sys.exit(f"{len(failures)} sanity check(s) FAILED: {failures} -- bad pull?")


def worked_examples(long_df: pd.DataFrame, geos_df: pd.DataFrame) -> None:
    """Close with two plain-English receipts (repo convention)."""
    names = geos_df.set_index("geoid")["NAME_raw"]
    la = long_df[(long_df["variable"] == "B19013_001") & (long_df["geoid"] == "06037")]
    if len(la) == 1:
        est = float(_num(la["estimate_raw"]).iloc[0])
        moe = float(_num(la["moe_raw"]).iloc[0])
        cv = (moe / 1.645) / est   # CV = (MOE/1.645)/estimate, ACS Accuracy of the Data
        print(f"\nWorked example: {names.get('06037', 'Los Angeles County')} median "
              f"household income ${est:,.0f} +/- ${moe:,.0f} (CV {cv:.3f}).")
    jam = long_df[(long_df["variable"] == "B19013_001")
                  & (long_df["estimate_raw"] == "-666666666")]
    if len(jam):
        g = jam["geoid"].iloc[0]
        print(f"Jam example: {names.get(g, g)} publishes B19013_001 = -666666666 -- "
              f"'{JAM_ESTIMATE['-666666666']}' -- with MOE "
              f"{jam['moe_raw'].iloc[0]}; the survey keeps both verbatim.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan-only", action="store_true",
                        help="build manifest + sample, print the plan, pull nothing")
    args = parser.parse_args()

    t0 = time.perf_counter()
    api_key = load_api_key()

    print(f"Fetching variables.json + groups.json for {VINTAGE} {DATASET} ...")
    variables = fetch_variables()
    group_meta = fetch_group_metadata()
    print(f"  {len(variables):,} names, {len(group_meta):,} table groups")

    manifest = build_manifest(variables, group_meta)
    picks = select_sample(manifest)
    manifest.loc[manifest["table_id"].isin(picks) & manifest["is_estimate"],
                 "in_sample"] = True
    manifest["sample_reason"] = manifest["table_id"].map(picks).where(manifest["in_sample"])
    print_sample_plan(manifest, picks)

    if args.plan_only:
        print("\n--plan-only: stopping before any data pull.")
        return

    print(f"\nPulling {len(picks)} tables at for=county:* ...")
    long_df, geos_df, report_df, obs = pull_all(picks, api_key)

    obs_df = pd.DataFrame.from_dict(obs, orient="index")
    manifest = manifest.merge(obs_df, left_on="name", right_index=True, how="left")
    for col in ("observed_in_pull", "observed_m_col", "observed_ea_col",
                "observed_ma_col"):
        manifest[col] = manifest[col].astype("boolean")

    sanity_report(manifest, picks, long_df, geos_df, report_df)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for df, path in ((manifest, MANIFEST_PATH), (long_df, LONG_PATH),
                     (geos_df, GEOS_PATH), (report_df, REPORT_PATH)):
        df.to_parquet(path, index=False)
        print(f"Saved {path.relative_to(REPO_ROOT)} "
              f"({path.stat().st_size / 1024:,.0f} KB)")

    worked_examples(long_df, geos_df)
    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")


if __name__ == "__main__":
    main()
