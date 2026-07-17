"""Parser for the 2010 DHC Demonstration Data Product summary file (NJ).

What it does
------------
Reads the demonstration file downloaded by ingestion/pull_das_demo_nj.py
-- privacy-protected 2010 counts produced by the 2020 Disclosure Avoidance
System's TopDown Algorithm -- directly from the zip (never extracted, so
data/raw/ stays exactly as downloaded). Provides the geo header, selected
table cells, and a joined per-geography table of demonstration counts,
plus a quality panel that proves the parse is correct before any analysis
touches the numbers.

The demonstration data exists ONLY to evaluate privacy noise. It must
never be analyzed as real 2010 populations (see docs/data-dictionary.md).

What it needs
-------------
data/raw/das_demo/nj2010.dhc.zip on disk
(regenerate with: python ingestion/pull_das_demo_nj.py).

File layout and sources
-----------------------
All files inside the zip are pipe-delimited UTF-8 with no header row
(2022-08-25 README). Layout constants below are transcribed from the
release's companion documents and then PROVEN at run time by
quality_panel() -- an empirical check is stronger evidence than
re-parsing the layout files:

- Geo header field positions: Geoheader_State.xlsx (97 fields; we carry
  the ones we use). Verified 2026-07-16 against the data itself.
- Segment structure: fields 1-5 are FILEID, STUSAB, CHARITER, CIFSN,
  LOGRECNO; table cells start at field 6, concatenated in
  TABLE_SORT_ORDER (2022-08-25 Technical Document).
- Table -> segment assignment and cell counts: Table_Matrix.xlsx,
  "Table_Segments" sheet. Segment 5 opens with P1 (1 cell); segment 8 is
  P12AF, P12AG, P12AH, P12B, P12C (49 cells each), putting P12B at
  fields 153-201.
- DHC table names map 1:1 to 2010 SF1 table names (Table_Matrix.xlsx,
  "Table ID Crosswalk"), so cells are exposed here under their SF1 API
  codes (P001001, P012B001..P012B049) and join directly against the
  published baseline from ingestion/pull_sf1_2010_nj.py.

Invariants (2022-08-25 Technical Document, verbatim): "The total
population for each state is held invariant, used exactly as enumerated
and with no noise added. Similarly, the total number of housing units in
each census block and the number and major type of each occupied group
quarters unit in each census block are also held invariant." Everything
else is noisy -- and the state invariant doubles as our parser check:
the demonstration NJ total must equal published 8,791,894 EXACTLY.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = REPO_ROOT / "data" / "raw" / "das_demo" / "nj2010.dhc.zip"

GEO_MEMBER = "njgeo2010.dhc"
N_MEMBERS = 45          # 44 table segments + 1 geo header
N_GEO_RECORDS = 219_847  # every geography record in the state file

# Published 2010 total population of New Jersey -- the state invariant.
NJ_POP_2010 = 8_791_894

# Geo header: 1-based pipe-field positions (Geoheader_State.xlsx).
GEO_FIELDS = {
    3: "SUMLEV",     # summary level, e.g. 050 = county
    4: "GEOVAR",     # geographic variant ('00' = standard)
    5: "GEOCOMP",    # geographic component ('00' = complete geography)
    8: "LOGRECNO",   # logical record number -- the join key to segments
    9: "GEOID",      # e.g. 1400000US34001000100
    10: "GEOCODE",   # bare code, e.g. 34001000100 -- joins to the API pull
    13: "STATE",
    15: "COUNTY",
    33: "TRACT",
    34: "BLKGRP",
    35: "BLOCK",
    88: "NAME",
    91: "POP100",    # total population count carried on the geo record
    92: "HU100",     # total housing unit count
}

# The five nesting levels EDA 04 compares, and their record counts after
# filtering to standard geography (GEOVAR '00', GEOCOMP '00') -- fixed
# 2010 Census facts, identical to the SF1 baseline pull's row counts.
LEVELS = {
    "state": "040",
    "county": "050",
    "tract": "140",
    "block_group": "150",
    "block": "100",
}
EXPECTED_RECORDS = {
    "state": 1,
    "county": 21,
    "tract": 2_010,
    "block_group": 6_320,
    "block": 169_588,
}

# Tables we extract: name -> (segment, first 1-based pipe field, n cells,
# SF1-style column codes). Cell order within P12B: 1 total, 2 male total,
# 3-25 male age bins, 26 female total, 27-49 female age bins -- same
# shell as SF1 P12B, per the crosswalk.
TABLES = {
    "P1": (5, 6, 1, ["P001001"]),
    "P12B": (8, 153, 49, [f"P012B{i:03d}" for i in range(1, 50)]),
}

# The twelve P12B cells that sum to "Black alone, 65+" (male 65-66
# through 85+, female 65-66 through 85+) -- same cells the SF1 baseline
# pull downloads by these exact codes.
BLACK_65PLUS_CELLS = [f"P012B{i:03d}" for i in list(range(20, 26)) + list(range(44, 50))]


def _segment_member(segment: int) -> str:
    """Zip member name for a table segment, e.g. 5 -> nj000052010.dhc."""
    return f"nj{segment:05d}2010.dhc"


def read_geoheader(
    levels: list[str] | None = None, zip_path: Path = ZIP_PATH
) -> pd.DataFrame:
    """Read the geo header, filtered to standard geography at these levels.

    `levels` are keys of LEVELS (default: all five). Returns one row per
    geography with the GEO_FIELDS columns plus `level`; POP100/HU100
    numeric, everything else string (zero-padding preserved). Filtering
    to GEOVAR '00' and GEOCOMP '00' drops variant/component records
    (e.g. "urban part of") that would otherwise double-count.
    """
    levels = list(LEVELS) if levels is None else levels
    unknown = set(levels) - set(LEVELS)
    if unknown:
        raise ValueError(f"unknown levels {sorted(unknown)}; choose from {list(LEVELS)}")
    if not zip_path.exists():
        raise FileNotFoundError(
            f"{zip_path} not found -- regenerate with: python ingestion/pull_das_demo_nj.py"
        )
    positions = sorted(GEO_FIELDS)
    with ZipFile(zip_path) as zf, zf.open(GEO_MEMBER) as f:
        geo = pd.read_csv(
            f,
            sep="|",
            header=None,
            usecols=[p - 1 for p in positions],
            names=[GEO_FIELDS[p] for p in positions],
            dtype=str,
            keep_default_na=False,
            encoding="utf-8",
        )
    geo = geo[(geo["GEOVAR"] == "00") & (geo["GEOCOMP"] == "00")]
    sumlev_to_level = {v: k for k, v in LEVELS.items()}
    geo["level"] = geo["SUMLEV"].map(sumlev_to_level)
    geo = geo[geo["SUMLEV"].isin([LEVELS[lv] for lv in levels])].copy()
    geo[["POP100", "HU100"]] = geo[["POP100", "HU100"]].apply(pd.to_numeric)
    return geo.reset_index(drop=True)


def read_table(table: str, zip_path: Path = ZIP_PATH) -> pd.DataFrame:
    """Read one table's cells for every geography record in the file.

    `table` is a key of TABLES. Returns LOGRECNO (string) plus one integer
    column per cell, named with the SF1 API codes. Join to read_geoheader()
    on LOGRECNO to attach geography.
    """
    if table not in TABLES:
        raise ValueError(f"table must be one of {list(TABLES)}, got {table!r}")
    segment, first_field, n_cells, codes = TABLES[table]
    positions = [5] + list(range(first_field, first_field + n_cells))
    with ZipFile(zip_path) as zf, zf.open(_segment_member(segment)) as f:
        df = pd.read_csv(
            f,
            sep="|",
            header=None,
            usecols=[p - 1 for p in positions],
            names=["LOGRECNO"] + codes,
            dtype={"LOGRECNO": str},
            keep_default_na=False,
            encoding="utf-8",
        )
    df[codes] = df[codes].apply(pd.to_numeric)
    return df


def demo_counts(
    levels: list[str] | None = None,
    tables: list[str] = ("P1", "P12B"),
    zip_path: Path = ZIP_PATH,
) -> pd.DataFrame:
    """Demonstration counts per geography: geo header joined to table cells.

    One row per standard-geography record at the requested levels, with
    geography identifiers plus every requested table's cells (SF1-style
    codes). Raises if any geography record fails to find its cells -- a
    partial join would silently bias every downstream noise statistic.
    """
    geo = read_geoheader(levels, zip_path)
    for table in tables:
        cells = read_table(table, zip_path)
        geo = geo.merge(cells, on="LOGRECNO", how="left", validate="one_to_one")
    cell_cols = [c for t in tables for c in TABLES[t][3]]
    missing = geo[cell_cols].isna().any(axis=1)
    if missing.any():
        raise AssertionError(
            f"{int(missing.sum())} geography records found no table cells -- "
            "LOGRECNO join is broken; do not analyze this output."
        )
    return geo


def quality_panel(zip_path: Path = ZIP_PATH) -> None:
    """Prove the parse before analysis. Prints checks; raises on failure.

    Checks, in order: zip inventory, record counts, LOGRECNO uniqueness,
    the state-population invariant, P1 against the geo header's POP100
    (proves P1's location), P12B internal additivity (proves P12B's
    offsets -- tabulated microdata must be exactly self-consistent), join
    coverage, and non-negativity.
    """
    def check(ok: bool, label: str) -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            raise AssertionError(f"quality panel failed: {label}")

    print(f"Quality panel -- {zip_path.name}")

    with ZipFile(zip_path) as zf:
        members = zf.namelist()
    check(len(members) == N_MEMBERS and GEO_MEMBER in members,
          f"zip has {N_MEMBERS} members incl. {GEO_MEMBER} (found {len(members)})")

    geo = read_geoheader()
    check(geo["LOGRECNO"].is_unique, "LOGRECNO unique in geo header")
    for level, expected in EXPECTED_RECORDS.items():
        n = int((geo["level"] == level).sum())
        check(n == expected, f"{level}: {n:,} standard records (expected {expected:,})")

    df = demo_counts()  # raises on any join gap
    check(True, f"P1 + P12B cells joined 1:1 for all {len(df):,} records")

    state_pop = int(df.loc[df["level"] == "state", "P001001"].iloc[0])
    check(state_pop == NJ_POP_2010,
          f"state invariant: demo total {state_pop:,} == published {NJ_POP_2010:,}")

    check((df["P001001"] == df["POP100"]).all(),
          "P1 equals geo-header POP100 on every record (P1 location proven)")

    p12b = read_table("P12B", zip_path)
    male = [f"P012B{i:03d}" for i in range(3, 26)]
    female = [f"P012B{i:03d}" for i in range(27, 50)]
    check(
        bool(
            (p12b["P012B001"] == p12b["P012B002"] + p12b["P012B026"]).all()
            and (p12b["P012B002"] == p12b[male].sum(axis=1)).all()
            and (p12b["P012B026"] == p12b[female].sum(axis=1)).all()
        ),
        f"P12B additivity holds on all {len(p12b):,} records (offsets proven)",
    )

    cell_cols = [c for t in ("P1", "P12B") for c in TABLES[t][3] if c in df.columns]
    check(bool((df[cell_cols] >= 0).all().all()), "all extracted cells non-negative")

    print("Quality panel: all checks passed.")


if __name__ == "__main__":
    quality_panel()
