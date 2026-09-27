"""Pull the ACS income ALLOCATION tables at tract. Track C, tract version.

What it does
------------
Downloads the five B99 allocation tables whose concept mentions income,
DISCOVERED by filtering the live metadata endpoint rather than hardcoded
from memory, at county, tract and block group for New Jersey.

What the discovery actually found matters, and it is not what the proposal
assumed. The five tables split allocation by UNIVERSE -- individuals,
households, families, nonfamily households, and earnings -- NOT by income
source. Filtering all 1,199 tables in vintage 2024 for the concept words
INTEREST, SOCIAL SECURITY, RETIREMENT, PUBLIC ASSISTANCE and WAGE returned
NOTHING. The six-component decomposition the proposal describes is not
published in the ACS detailed tables at any geography.

It exists only in PUMS, at PUMA -- see ingestion/pull_pums_alloc_flags.py.
That version cannot be joined to a tract CV, which is why both exist.

So this script supports the question EDA 05 can actually be extended with:
does the near-independence of allocation rate and CV survive splitting by
universe, and by allocation INTENSITY? Each table publishes 8 cells -- a
percent-of-income-allocated distribution, not a single rate -- so intensity
is available even though source is not.

The proposal predicted some B99 tables would be county-only, and called
that a Q1 lifecycle finding. All five were VERIFIED to publish at county,
tract AND block group in NJ. Record the negative.

ALLOCATION TABLES PUBLISH NO MARGINS OF ERROR -- VERIFIED, no _M variables
exist for any of the five. Requesting one errors the whole query.

What it needs
-------------
- CENSUS_API_KEY in the repo-root .env file
- Internet access; packages from requirements.txt (censusdis, pandas,
  python-dotenv, pyarrow, requests)

What it produces
----------------
- data/raw/acs5_2024_nj_alloc_income_county.parquet       (21 rows -- hard-checked)
- data/raw/acs5_2024_nj_alloc_income_tract.parquet        (~2,000 rows)
- data/raw/acs5_2024_nj_alloc_income_block_group.parquet  (~6,600 rows)
- docs/api-surface-b99-income.md                          (discovered table list)

Run from the repo root:
    python ingestion/pull_acs_alloc_income.py --dry-run
    python ingestion/pull_acs_alloc_income.py
    python ingestion/pull_acs_alloc_income.py --levels tract
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
STATE_NJ = common.STATE_NJ
OUT_DIR = REPO_ROOT / "data" / "raw"
DOCS_PATH = REPO_ROOT / "docs" / "api-surface-b99-income.md"

# The proposal's filter, verbatim. Widen it here and nowhere else.
INCOME_WORDS = ("INCOME", "EARNINGS", "WAGE", "INTEREST",
                "SOCIAL SECURITY", "RETIREMENT", "PUBLIC ASSISTANCE")

# VERIFIED at vintages 2023 and 2024. Used only to check the discovery
# against a known-good answer -- the pull uses whatever discovery returns.
EXPECTED_TABLES = ["B99191", "B99192", "B99193", "B99194", "B99201"]

GEO_LEVELS = {
    "county": dict(state=STATE_NJ, county="*"),
    "tract": dict(state=STATE_NJ, county="*", tract="*"),
    "block_group": dict(state=STATE_NJ, county="*", tract="*", block_group="*"),
}

EXPECTED_NJ_COUNTIES = 21  # fixed fact -- any other count means a bad query
ANNOTATION_CUTOFF = common.ANNOTATION_CUTOFF
KNOWN_ANNOTATIONS = common.KNOWN_ANNOTATIONS
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


def discover_tables() -> list[dict]:
    """Which B99 tables concern income? Ask the API, never remember.

    groups.json is ~1 MB against variables.json's tens of MB and carries
    exactly what the filter needs.
    """
    url = f"https://api.census.gov/data/{VINTAGE}/{DATASET}/groups.json"
    print(f"Discovering B99 income tables from {url} ...")
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        groups = resp.json().get("groups", [])
    except requests.RequestException as exc:
        sys.exit(
            f"Could not reach the metadata endpoint: {exc}\n"
            f"Discovery is not optional -- the table list IS the thing being\n"
            f"verified, and hardcoding it would be exactly the substitution the\n"
            f"brief forbids. Note that --dry-run also needs network for this\n"
            f"reason. Retry when the endpoint is reachable."
        )
    except ValueError as exc:
        sys.exit(f"Metadata endpoint returned non-JSON: {exc}")
    print(f"  {len(groups):,} tables in {DATASET} {VINTAGE}")

    found = []
    for g in groups:
        name = g.get("name", "")
        concept = g.get("description", "") or ""
        # B99 is allocation. B98 is coverage and response rates -- a different
        # quality surface entirely, and easy to conflate when skimming.
        if name.startswith("B99") and any(w in concept.upper() for w in INCOME_WORDS):
            found.append({"table": name, "concept": concept})
    found.sort(key=lambda h: h["table"])

    if not found:
        sys.exit("No B99 table matched the income filter. That is a real result "
                 "or a broken filter -- check INCOME_WORDS against a few concept "
                 "strings before trusting it. Nothing pulled.")

    print(f"  {len(found)} matched:")
    for f in found:
        print(f"    {f['table']}  {f['concept']}")

    discovered = [f["table"] for f in found]
    if discovered != EXPECTED_TABLES:
        print(f"\n  NOTE: discovery returned {discovered}")
        print(f"        previous verification found {EXPECTED_TABLES}")
        print(f"        The pull uses DISCOVERY, not the expectation. If these")
        print(f"        differ, the surface moved -- update docs before analysing.")

    if any(w in " ".join(f["concept"].upper() for f in found)
           for w in ("SOCIAL SECURITY", "RETIREMENT", "PUBLIC ASSISTANCE")):
        print("\n  A source-level table appeared that was absent at last check. "
              "Track C's original design may now be possible at tract.")
    else:
        print("\n  As previously verified: these split by UNIVERSE, not by income")
        print("  source. The source split lives only in PUMS at PUMA level --")
        print("  see ingestion/pull_pums_alloc_flags.py.")
    return found


def fetch_cells(table: str) -> tuple[list[str], dict[str, str]]:
    """Estimate cells and official labels for one discovered table."""
    url = f"https://api.census.gov/data/{VINTAGE}/{DATASET}/groups/{table}.json"
    try:
        variables = requests.get(url, timeout=TIMEOUT).json().get("variables", {})
    except requests.RequestException as exc:
        print(f"  {table}: cell fetch FAILED: {exc}")
        return [], {}
    cells, labels = [], {}
    for name, meta in variables.items():
        if len(name) > 4 and name.endswith("E") and not name.endswith("EA") \
                and "_" in name and name.split("_")[-1][:-1].isdigit():
            cells.append(name)
            labels[name] = meta.get("label", "")
    if any(n.endswith("M") and not n.endswith("MA") and "_" in n for n in variables):
        print(f"  {table}: WARNING -- MOE cells present. Contradicts the "
              f"'allocation tables have no _M' assumption; check before excluding.")
    return sorted(cells), labels


def annotation_mask(s: pd.Series) -> pd.Series:
    """True where a value is an ACS annotation code rather than real data."""
    return s.notna() & (s <= ANNOTATION_CUTOFF)


def sanity_report(df: pd.DataFrame, level: str, cells: list[str],
                  tables: list[str]) -> None:
    """Per-column checks, plus each table's cells summing to its own total."""
    print(f"\n  Sanity checks -- {level}: {len(df):,} rows x {len(df.columns)} columns")
    print(f"  {'column':<16} {'nulls':>12} {'annotations':>12}   clean min / max")
    codes_seen: dict[int, int] = {}
    for col in cells:
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

    clean_df = common.clean_sentinels(df, columns=cells)
    for table in tables:
        detail = sorted(c for c in cells
                        if c.startswith(table) and not c.endswith("001E"))
        total_col = f"{table}_001E"
        if not detail or total_col not in clean_df.columns:
            continue
        s = clean_df[detail].sum(axis=1, min_count=len(detail))
        total = clean_df[total_col]
        comparable = s.notna() & total.notna()
        bad = int((s[comparable] != total[comparable]).sum())
        print(f"  {'PASS' if not bad else 'FAIL'}  {table}: {len(detail)} detail "
              f"cells sum to {total_col} on {int(comparable.sum()):,} rows "
              f"({bad} mismatches)")


def write_docs(found: list[dict], cells: dict[str, list[str]],
               labels: dict[str, str]) -> None:
    """Record the discovered surface as a team artifact, utf-8 explicit."""
    L = [
        "# B99 income allocation tables -- discovered surface",
        "",
        f"**Dataset:** `{DATASET}` vintage **{VINTAGE}**",
        "**Discovered by:** `ingestion/pull_acs_alloc_income.py` "
        "(filters the live `groups.json`)",
        "",
        "These split allocation by **universe**, not by income source. The",
        "concept words `INTEREST`, `SOCIAL SECURITY`, `RETIREMENT`,",
        "`PUBLIC ASSISTANCE` and `WAGE` match nothing in the B99 series.",
        "The source split exists only in PUMS at PUMA level.",
        "",
        "Allocation tables publish **no margins of error**.",
        "",
        f"**{len(found)} tables matched.**",
        "",
        "| Table | Concept | Cells |",
        "|---|---|---|",
    ]
    for f in found:
        L.append(f"| `{f['table']}` | {f['concept']} | "
                 f"{len(cells.get(f['table'], []))} |")
    L += ["", "## Cells", ""]
    for f in found:
        L.append(f"### {f['table']}")
        L.append("")
        L.append("| Cell | Label |")
        L.append("|---|---|")
        for c in cells.get(f["table"], []):
            L.append(f"| `{c}` | {labels.get(c, '')} |")
        L.append("")
    DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_PATH.write_text("\n".join(L), encoding="utf-8")
    print(f"\n  Wrote {DOCS_PATH.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull discovered B99 income allocation tables for Track C (tract).")
    parser.add_argument("--levels", nargs="+", default=list(GEO_LEVELS),
                        choices=list(GEO_LEVELS),
                        help="geography levels to pull (default all three)")
    parser.add_argument("--dry-run", action="store_true",
                        help="discover tables and print the plan, fetch no data")
    args = parser.parse_args()

    t0 = time.perf_counter()
    found = discover_tables()

    print("\nFetching cell lists ...")
    cells: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for f in found:
        c, lab = fetch_cells(f["table"])
        cells[f["table"]] = c
        labels.update(lab)
        print(f"  {f['table']}: {len(c)} estimate cells")

    all_cells = [c for t in cells.values() for c in t]
    download_vars = ["NAME"] + all_cells
    write_docs(found, cells, labels)

    if args.dry_run:
        print("\nDRY RUN -- no data will be fetched.\n")
        print(f"  Dataset       {DATASET} vintage {VINTAGE}")
        print(f"  Tables        {', '.join(cells)}")
        print(f"  Variables     {len(download_vars)} columns "
              f"({len(all_cells)} estimates + NAME; no MOEs exist)")
        rows = {"county": 21, "tract": 2_181, "block_group": 6_600}
        total = 0
        for level in args.levels:
            n = rows.get(level, 0)
            total += n
            print(f"    {level:<12} ~{n:,} rows "
                  f"(~{n * len(download_vars):,} cells)")
        print(f"\n  Expected rows ~{total:,}")
        for level in args.levels:
            print(f"  Output        "
                  f"{(OUT_DIR / f'acs5_{VINTAGE}_nj_alloc_income_{level}.parquet').relative_to(REPO_ROOT)}")
        return

    api_key = load_api_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\nOfficial cell labels -- verify the intensity bins match intent:")
    for c in all_cells:
        print(f"  {c}  {labels.get(c, '')}")

    failures: list[str] = []
    for level in args.levels:
        print(f"\nDownloading {level} level ...")
        try:
            df = ced.download(DATASET, VINTAGE, download_variables=download_vars,
                              api_key=api_key, **GEO_LEVELS[level])
        except Exception as exc:  # report and keep going; fail loudly at the end
            failures.append(level)
            print(f"  FAILED: {exc}")
            continue

        if level == "county" and len(df) != EXPECTED_NJ_COUNTIES:
            sys.exit(f"County query returned {len(df)} rows, but New Jersey has "
                     f"exactly {EXPECTED_NJ_COUNTIES} counties. Aborting -- "
                     f"check the query.")

        out_path = OUT_DIR / f"acs5_{VINTAGE}_nj_alloc_income_{level}.parquet"
        df.to_parquet(out_path, index=False)
        sanity_report(df, level, all_cells, list(cells))
        print(f"  Saved {out_path.relative_to(REPO_ROOT)} "
              f"({out_path.stat().st_size / 1024:,.0f} KB)")

    print(f"\nDone in {time.perf_counter() - t0:,.1f}s.")
    if failures:
        sys.exit(f"One or more geography levels FAILED: {', '.join(failures)}")


if __name__ == "__main__":
    main()
