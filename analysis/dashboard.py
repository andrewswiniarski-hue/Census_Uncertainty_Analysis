"""Formulas and thresholds behind the Trenton dashboard prototype (Streamlit/app.py).

What it does
------------
Everything the app needs that isn't presentation: the four grant-relevant
age bands (mapped onto ACS's B01001/B17001 cells), range-first uncertainty,
and the plain-language reliability tier. Keeping this here means the
Streamlit file only renders -- every number it shows traces to a tested
function.

Reuses rather than reinvents: analysis.acs (aggregate_estimate,
aggregate_moe, Z_90 -- the same handbook zero-cell MOE rule every ACS
notebook uses).

What it needs
-------------
data/raw/acs5_2024_trenton_{place,county,tract}.parquet
(regenerate with: python ingestion/pull_trenton_dashboard.py)

Methodology choice made here, approved before building:
--------------------------------------------------------------
Tiers (Solid / Use with care / Too risky) use the ESRI 0.12 and NCHS
0.30 CV conventions already cited in analysis/viz.py -- labeled in the
app as OUR proposed tiers, not adopted Census thresholds (HANDOFF.md
decision #8: our tiers are a Weeks 4-6 call with mentors, not decided).

DHC was dropped from this app 2026-08-01 (HANDOFF.md decision #17): income
does not exist in decennial products, so DHC cannot carry the anchor
variable under the Phase 2 income & poverty scope. The DHC/DP1 modeled-noise
analysis (analysis/noise_model.py, notebooks 10-12) remains valid report
evidence; it no longer feeds this app.

The imputation axis (added 2026-08-01, HANDOFF.md decision #17): reliability
tiers here are CV-only and stay that way -- allocation is a SECOND, separate
signal shown beside the tier, not folded into it (the mentor-gated composite
tier-philosophy question, README Open Questions, is not pre-empted by this
app). Rates come from analysis.alloc (already tested); the flag threshold is
this app's own NJ-statewide 75th percentile (analysis.composite), not
Trenton's own tracts -- judging a city against its own tracts would flag
exactly a quarter of them by construction and carry no information.

The SAIPE comparator (added 2026-08-01, HANDOFF.md decision #17, Phase 3):
one county-level-only element comparing ACS median household income against
SAIPE's for Mercer County. SAIPE stops at the county level, so it never
appears on the tract view. See notebooks/13-saipe-vs-acs-county.ipynb for
the full methodological point (a SAIPE interval is model error, not ACS
sampling error) and the interval-coherence check.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

from analysis import alloc, common
from analysis.acs import Z_90, aggregate_estimate, aggregate_moe

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"

LEVELS = ["place", "county", "tract"]
GEO_LABELS = {"place": "Trenton (whole city)", "county": "Mercer County", "tract": "Tract"}


# ---------------------------------------------------------------------------
# Geography level registry -- the map-first dashboard's drill-down ladder
# ---------------------------------------------------------------------------
#
# One entry per level the map can show. Adding a level (e.g. a future US
# state) means adding a LevelSpec plus a data pull -- every function below
# (load_level_data, load_level_geo, geo_key, children_of) is written against
# this shape, not against "county" or "tract" by name. Kept a plain dict of
# NamedTuple, not a class hierarchy: there is nothing here that varies in
# behavior, only in which files and columns to read.

class LevelSpec(NamedTuple):
    label: str
    data_file: str
    geo_file: str
    key_cols: tuple[str, ...]
    parent: str | None


LEVEL_SPECS: dict[str, LevelSpec] = {
    "county": LevelSpec(
        label="County",
        data_file="acs5_2024_njdash_county.parquet",
        geo_file="geo_2024_nj_county.parquet",
        key_cols=("COUNTY",),
        parent=None,
    ),
    "tract": LevelSpec(
        label="Tract",
        data_file="acs5_2024_njdash_tract.parquet",
        geo_file="geo_2024_nj_tract.parquet",
        key_cols=("COUNTY", "TRACT"),
        parent="county",
    ),
}

# Nationwide county app's OWN registry (Streamlit/app_US.py) -- deliberately
# separate from LEVEL_SPECS above, not a replacement of it. NJ's "county"
# key_cols is bare COUNTY (no STATE) because NJ only ever pulls one state,
# so a 3-digit county code is already unique within that data. Nationwide,
# county FIPS "001" exists in ~50 different states, so US_LEVEL_SPECS's
# county entry MUST include STATE in its key -- changing NJ's own entry to
# match would have been unnecessary (NJ's data never collides) and would
# have changed every existing NJ key's string format for no reason. Every
# function below that reads a registry takes an optional `specs` argument
# (default LEVEL_SPECS) so app_NJ.py's calls are completely unaffected;
# app_US.py passes specs=US_LEVEL_SPECS explicitly.
US_LEVEL_SPECS: dict[str, LevelSpec] = {
    "state": LevelSpec(
        label="State",
        data_file="acs5_2024_usdash_state.parquet",
        geo_file="geo_2024_usdash_state_simple.parquet",
        key_cols=("STATE",),
        parent=None,
    ),
    "county": LevelSpec(
        label="County",
        data_file="acs5_2024_usdash_county.parquet",
        geo_file="geo_2024_usdash_county_simple.parquet",
        key_cols=("STATE", "COUNTY"),
        parent="state",
    ),
}


def _join_key_cols(df: pd.DataFrame, cols: tuple[str, ...]) -> pd.Series:
    return df[list(cols)].astype(str).agg("".join, axis=1)


# Every ACS table this project's loaders know how to coerce to numeric --
# shared by load_level_data() and load_us_acs1_county() so a new table only
# needs to be added here once (variable expansion, 2026-08-30). The last six
# prefixes are US-app-only (see ingestion/pull_usdash.py); NJ/Trenton parquet
# files simply have no columns matching them, so sharing this list with
# load_level_data() (used by both apps) is harmless.
VALUE_COL_PREFIXES = (
    "B01001_", "B17001_", "B19013_",
    "B27001_", "B25064_", "B25071_", "B25003_", "C16002_", "B08201_", "B19001_",
)


def load_level_data(level: str, specs: dict[str, LevelSpec] = LEVEL_SPECS) -> pd.DataFrame:
    """ACS B01001 (age x sex) + B17001 (poverty) + B19013 (income) -- plus,
    for the nationwide app only, health insurance/rent/language/vehicles/
    income-brackets (VALUE_COL_PREFIXES) -- for every geography at this
    level, for whichever registry (`specs`) is passed: NJ's LEVEL_SPECS by
    default, or US_LEVEL_SPECS for the nationwide app."""
    spec = specs[level]
    path = RAW_DIR / spec.data_file
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_njdash.py "
            f"(NJ) or python ingestion/pull_usdash.py (nationwide)"
        )
    df = pd.read_parquet(path)
    value_cols = [c for c in df.columns if c[:-1].startswith(VALUE_COL_PREFIXES)]
    df[value_cols] = df[value_cols].apply(pd.to_numeric, errors="coerce")
    return df


def load_level_geo(level: str, specs: dict[str, LevelSpec] = LEVEL_SPECS):
    """Boundary geometry (GeoParquet) for this level, from whichever
    registry (`specs`) is passed."""
    import geopandas as gpd

    spec = specs[level]
    path = RAW_DIR / spec.geo_file
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_nj_geometry.py "
            f"(NJ) or python ingestion/pull_us_geometry.py (nationwide)"
        )
    return gpd.read_parquet(path)


def geo_key(df: pd.DataFrame, level: str, specs: dict[str, LevelSpec] = LEVEL_SPECS) -> pd.Series:
    """Single string join key for a level's geography.

    What the map click, the search dropdown, and every data lookup address
    a geography by -- e.g. tract key = COUNTY + TRACT concatenated, so the
    same string identifies a tract everywhere in the app. `specs` selects
    which geography ladder's key_cols to use (NJ's LEVEL_SPECS by default).
    """
    return _join_key_cols(df, specs[level].key_cols)


def children_of(
    level: str, parent_key: str, df: pd.DataFrame | None = None,
    specs: dict[str, LevelSpec] = LEVEL_SPECS,
) -> pd.DataFrame:
    """Rows of `level` inside the geography identified by `parent_key`.

    `parent_key` is the PARENT level's own geo_key value (e.g. a county's
    key, to get that county's tracts, or a state's key, to get that
    state's counties) -- this is the drill-down primitive: at US scale, a
    county layer scoped to one selected state is far smaller than every US
    county at once (62 median, 254 max in Texas, vs. 3,144 nationwide).
    """
    spec = specs[level]
    if spec.parent is None:
        raise ValueError(f"{level!r} has no parent level to filter by")
    if df is None:
        df = load_level_data(level, specs=specs)
    parent_cols = specs[spec.parent].key_cols
    return df[_join_key_cols(df, parent_cols) == parent_key]


# ---------------------------------------------------------------------------
# Nationwide geography filters (Streamlit/app_US.py's filter stack) -- these
# are FILTERS on the county view, not new geography levels. Selecting a
# region/division/RUCC-tier/population-bin narrows which counties are shown;
# none of them needs its own geometry file.
# ---------------------------------------------------------------------------

# State FIPS -> (region, division). Fixed groupings that do not change
# year to year, so a hardcoded lookup beats a data pull. Source: U.S.
# Census Bureau, "Census Regions and Divisions of the United States"
# (https://www2.census.gov/geo/docs/maps-data/maps/reg_div.txt), verified
# live 2026-08-12. 51 entries: 50 states + DC (Puerto Rico is excluded
# from every nationwide pull in this project -- see pull_usdash.py).
CENSUS_DIVISIONS: dict[str, tuple[str, str]] = {
    "09": ("Northeast", "New England"), "23": ("Northeast", "New England"),
    "25": ("Northeast", "New England"), "33": ("Northeast", "New England"),
    "44": ("Northeast", "New England"), "50": ("Northeast", "New England"),
    "34": ("Northeast", "Middle Atlantic"), "36": ("Northeast", "Middle Atlantic"),
    "42": ("Northeast", "Middle Atlantic"),
    "17": ("Midwest", "East North Central"), "18": ("Midwest", "East North Central"),
    "26": ("Midwest", "East North Central"), "39": ("Midwest", "East North Central"),
    "55": ("Midwest", "East North Central"),
    "19": ("Midwest", "West North Central"), "20": ("Midwest", "West North Central"),
    "27": ("Midwest", "West North Central"), "29": ("Midwest", "West North Central"),
    "31": ("Midwest", "West North Central"), "38": ("Midwest", "West North Central"),
    "46": ("Midwest", "West North Central"),
    "10": ("South", "South Atlantic"), "11": ("South", "South Atlantic"),
    "12": ("South", "South Atlantic"), "13": ("South", "South Atlantic"),
    "24": ("South", "South Atlantic"), "37": ("South", "South Atlantic"),
    "45": ("South", "South Atlantic"), "51": ("South", "South Atlantic"),
    "54": ("South", "South Atlantic"),
    "01": ("South", "East South Central"), "21": ("South", "East South Central"),
    "28": ("South", "East South Central"), "47": ("South", "East South Central"),
    "05": ("South", "West South Central"), "22": ("South", "West South Central"),
    "40": ("South", "West South Central"), "48": ("South", "West South Central"),
    "04": ("West", "Mountain"), "08": ("West", "Mountain"),
    "16": ("West", "Mountain"), "30": ("West", "Mountain"),
    "32": ("West", "Mountain"), "35": ("West", "Mountain"),
    "49": ("West", "Mountain"), "56": ("West", "Mountain"),
    "02": ("West", "Pacific"), "06": ("West", "Pacific"),
    "15": ("West", "Pacific"), "41": ("West", "Pacific"),
    "53": ("West", "Pacific"),
}


def census_region(state_fips: str) -> str | None:
    entry = CENSUS_DIVISIONS.get(state_fips)
    return entry[0] if entry else None


def census_division(state_fips: str) -> str | None:
    entry = CENSUS_DIVISIONS.get(state_fips)
    return entry[1] if entry else None


# Round-number bin edges for legibility, not a statistically derived
# cutpoint. The sponsor's own rationale for wanting this filter is the
# right one to state directly: population size drives MOE magnitude --
# smaller population implies a smaller ACS sample, which implies a larger
# RELATIVE margin of error, all else equal.
POPULATION_BINS = [0, 10_000, 50_000, 250_000, 1_000_000, float("inf")]
POPULATION_BIN_LABELS = [
    "Under 10,000", "10,000-50,000", "50,000-250,000", "250,000-1,000,000", "1,000,000+",
]


def population_size_bin(pop_est: pd.Series) -> pd.Series:
    """Population-size bin per geography, for the nationwide app's filter
    stack. `pop_est` is expected to be B01001_001E (total population)."""
    return pd.cut(pop_est, bins=POPULATION_BINS, labels=POPULATION_BIN_LABELS, right=False)


def load_us_acs1_county() -> pd.DataFrame:
    """ACS 1-year, county level (Streamlit/app_US.py's precision comparison).

    The 1-year product only publishes above a 65,000-population floor, so
    the row set THIS PULL RETURNS is the exact answer to "does this county
    have 1-year data," not a threshold applied after the fact -- see
    pull_usdash.py's module docstring for why deriving this from
    B01001_001E >= 65000 instead would be wrong at the boundary (the
    Bureau's threshold applies to its own population estimate for the
    geography, not to the 5-year ACS figure this project otherwise uses).
    """
    path = RAW_DIR / "acs1_2024_usdash_county.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_usdash.py"
        )
    df = pd.read_parquet(path)
    value_cols = [c for c in df.columns if c[:-1].startswith(VALUE_COL_PREFIXES)]
    df[value_cols] = df[value_cols].apply(pd.to_numeric, errors="coerce")
    return df


def acs_1yr_available_keys() -> set[str]:
    """STATE+COUNTY keys with ACS 1-year data -- see load_us_acs1_county's
    docstring for why this is the pulled row set itself, not a threshold."""
    return set(geo_key(load_us_acs1_county(), "county", specs=US_LEVEL_SPECS))


def load_rucc() -> pd.DataFrame:
    """USDA ERS Rural-Urban Continuum Codes, 2023 vintage, county level.

    See ingestion/pull_rucc.py for the source, encoding, and format quirks
    already handled at ingestion time -- this loader just reads the
    already-cleaned parquet.
    """
    path = RAW_DIR / "rucc_2023_county.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_rucc.py"
        )
    return pd.read_parquet(path)


def load_alloc_us_county() -> pd.DataFrame:
    """Nationwide county allocation (imputation) rates -- see
    ingestion/pull_usdash_alloc.py. Estimates only; allocation tables
    publish no margin of error (same as load_alloc_nj_county/tract)."""
    path = RAW_DIR / "acs5_2024_usdash_alloc_county.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_usdash_alloc.py"
        )
    return alloc.derive_rates(pd.read_parquet(path))


BANDS = ["Under 5", "5-17", "18-64", "65+"]
SEXES = ["male", "female", "both"]

# Cell numbers (no table prefix, no E/M/N suffix) -- verified live against
# both APIs during planning. B01001 and P12 share this exact layout;
# B17001 uses different age brackets, mapped onto the same four bands.
_SEXAGE_CELLS = {
    "Under 5": {"male": ["003"], "female": ["027"]},
    "5-17": {"male": ["004", "005", "006"], "female": ["028", "029", "030"]},
    "18-64": {
        "male": [f"{i:03d}" for i in range(7, 20)],
        "female": [f"{i:03d}" for i in range(31, 44)],
    },
    "65+": {
        "male": ["020", "021", "022", "023", "024", "025"],
        "female": ["044", "045", "046", "047", "048", "049"],
    },
}
_POVERTY_CELLS = {
    "Under 5": {"male": ["004"], "female": ["018"]},
    "5-17": {"male": ["005", "006", "007", "008", "009"], "female": ["019", "020", "021", "022", "023"]},
    "18-64": {"male": ["010", "011", "012", "013", "014"], "female": ["024", "025", "026", "027", "028"]},
    "65+": {"male": ["015", "016"], "female": ["029", "030"]},
}
# The mirror "at or above poverty level" branch -- same age cells, offset
# +29 from _POVERTY_CELLS. Below + at-or-above = the true poverty-universe
# total per band (verified live in planning). This is NOT the same universe
# as B01001's total population -- B17001 excludes some group quarters
# populations from poverty-status determination -- so it must be pulled
# and summed, not approximated from the population bands.
_POVERTY_ABOVE_CELLS = {
    "Under 5": {"male": ["033"], "female": ["047"]},
    "5-17": {"male": ["034", "035", "036", "037", "038"], "female": ["048", "049", "050", "051", "052"]},
    "18-64": {"male": ["039", "040", "041", "042", "043"], "female": ["053", "054", "055", "056", "057"]},
    "65+": {"male": ["044", "045"], "female": ["058", "059"]},
}


def _sexes(sex: str) -> list[str]:
    if sex not in SEXES:
        raise ValueError(f"sex must be one of {SEXES}, got {sex!r}")
    return ["male", "female"] if sex == "both" else [sex]


def _codes(prefix: str, cells: dict, band: str, sex: str) -> list[str]:
    if band not in BANDS:
        raise ValueError(f"band must be one of {BANDS}, got {band!r}")
    return [f"{prefix}_{n}" for s in _sexes(sex) for n in cells[band][s]]


# ---------------------------------------------------------------------------
# US dashboard extra measures -- health insurance, language, vehicles,
# income brackets, rent (variable expansion, 2026-08-30). County/state only
# (see ingestion/pull_usdash.py); NJ/Trenton never gain these columns. Each
# table has its own cell shape, not the BANDS/SEXES layout above, so these
# get their own small cell lists rather than reusing _codes(). Cell numbers
# verified live against the ACS 2024 variables-group endpoint during
# planning (all seven tables publish in both acs/acs5 and acs/acs1).
# ---------------------------------------------------------------------------

# B27001 health insurance coverage by sex by age -- a repeating
# (bracket total, with coverage, no coverage) triple per age bracket, two
# sexes, nine brackets each. These are the "no coverage" cells, all ages.
# Universe is B27001_001, the CIVILIAN NONINSTITUTIONALIZED population --
# not the same universe as B01001's total population.
_UNINSURED_CELLS = [
    "005", "008", "011", "014", "017", "020", "023", "026", "029",  # male brackets
    "033", "036", "039", "042", "045", "048", "051", "054", "057",  # female brackets
]

# C16002 household language by limited-English-speaking status -- one
# "Limited English speaking household" cell per language group (Spanish,
# other Indo-European, Asian/Pacific Island, other). Universe is
# C16002_001, total households.
_LIMITED_ENGLISH_CELLS = ["004", "007", "010", "013"]

# B19001 household income, collapsed from 16 published brackets onto 4
# grant-relevant bands -- boundaries verified live against the brackets
# themselves (e.g. "$25,000 to $29,999" through "$45,000 to $49,999" for
# the $25k-$50k band), not assumed from the band names.
INCOME_BANDS = ["Under $25k", "$25k-$50k", "$50k-$100k", "$100k+"]
_INCOME_BRACKET_CELLS = {
    "Under $25k": ["002", "003", "004", "005"],
    "$25k-$50k": ["006", "007", "008", "009", "010"],
    "$50k-$100k": ["011", "012", "013"],
    "$100k+": ["014", "015", "016", "017"],
}


def acs_uninsured(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for the civilian noninstitutionalized population
    with no health insurance coverage, all ages combined -- B27001."""
    codes = [f"B27001_{n}" for n in _UNINSURED_CELLS]
    return aggregate_estimate(df, codes), aggregate_moe(df, codes)


def acs_insurance_universe(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for B27001's own universe cell -- the civilian
    noninstitutionalized population acs_uninsured() is a share of."""
    return df["B27001_001E"].astype(float), df["B27001_001M"].astype(float)


def acs_limited_english(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for households in a limited-English-speaking
    household, any language group combined -- C16002."""
    codes = [f"C16002_{n}" for n in _LIMITED_ENGLISH_CELLS]
    return aggregate_estimate(df, codes), aggregate_moe(df, codes)


def acs_language_universe(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for C16002's total-households cell -- the universe
    acs_limited_english() is a share of."""
    return df["C16002_001E"].astype(float), df["C16002_001M"].astype(float)


def acs_no_vehicle(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for households with no vehicle available -- B08201,
    a single published cell, no aggregation needed."""
    return df["B08201_002E"].astype(float), df["B08201_002M"].astype(float)


def acs_vehicle_universe(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for B08201's total-households cell -- the universe
    acs_no_vehicle() is a share of."""
    return df["B08201_001E"].astype(float), df["B08201_001M"].astype(float)


def acs_income_bracket(df: pd.DataFrame, band: str) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for households in an income band -- B19001,
    collapsed from its published brackets per band (see INCOME_BANDS)."""
    if band not in INCOME_BANDS:
        raise ValueError(f"band must be one of {INCOME_BANDS}, got {band!r}")
    codes = [f"B19001_{n}" for n in _INCOME_BRACKET_CELLS[band]]
    return aggregate_estimate(df, codes), aggregate_moe(df, codes)


def acs_income_bracket_universe(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for B19001's total-households cell -- the universe
    acs_income_bracket() bands are a share of."""
    return df["B19001_001E"].astype(float), df["B19001_001M"].astype(float)


def acs_median_rent(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for median gross rent -- B25064, a single published
    cell, no aggregation needed."""
    return df["B25064_001E"].astype(float), df["B25064_001M"].astype(float)


def acs_rent_burden(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for the Census Bureau's OWN median gross rent as a
    percentage of household income -- B25071. NOT the same as dividing
    median rent by median income by hand: dividing two published medians
    is not a valid derived statistic (the median of a ratio is not the
    ratio of two medians). This is the Bureau's own answer, computed
    household by household before taking the median of that ratio."""
    return df["B25071_001E"].astype(float), df["B25071_001M"].astype(float)


def acs_renter_occupied(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for renter-occupied housing units -- B25003, the
    universe rent and rent burden are measured against. Surfaced as
    context on the rent card, not its own card -- explains why rent MOEs
    widen in counties with few renters."""
    return df["B25003_003E"].astype(float), df["B25003_003M"].astype(float)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_acs(level: str) -> pd.DataFrame:
    """ACS 5-year B01001 (sex x age) + B17001 (poverty) for Trenton/Mercer."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    path = RAW_DIR / f"acs5_2024_trenton_{level}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_trenton_dashboard.py"
        )
    df = pd.read_parquet(path)
    value_cols = [c for c in df.columns if c[:-1].startswith(("B01001_", "B17001_"))]
    df[value_cols] = df[value_cols].apply(pd.to_numeric, errors="coerce")
    return df


def load_saipe_county(state: str, county: str, year: int = common.ACS_VINTAGE) -> pd.Series:
    """SAIPE's median household income + poverty row for any US county
    (generalizes the Mercer-only Phase 3 comparator, HANDOFF #17, to the
    nationwide app -- Streamlit/app_US.py). saipe_counties_2019_2024.parquet
    already covers every US county nationwide (pull_saipe_counties.py's own
    docstring: `for=county:*` with no state qualifier serves all 3,144 --
    confirmed 2026-08-12, this needed no new pull).

    Looked up by FIPS (state, county), NOT by county name: county names
    repeat nationwide -- "Mercer County" alone exists in NJ, IL, KY, and MO
    (confirmed live), so a name-only lookup would silently return the wrong
    county's row outside NJ.

    SAIPE is a MODEL-based interval (sampling variance of its inputs plus
    model uncertainty), not an ACS-style sampling-only margin of error --
    see notebooks/13-saipe-vs-acs-county.ipynb, which is where the two are
    checked against each other and where the interval-coherence assert
    ((UB90-LB90)/2 == published MOE) lives. This loader does no derivation
    of its own, so it needs no separate check beyond that notebook's.
    """
    path = RAW_DIR / "saipe_counties_2019_2024.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_saipe_counties.py"
        )
    df = pd.read_parquet(path)
    row = df[(df["STATE"] == state) & (df["COUNTY"] == county) & (df["year"] == year)]
    if row.empty:
        raise ValueError(f"No SAIPE row for STATE={state} COUNTY={county}, {year}")
    return row.iloc[0]


def load_saipe_mercer(year: int = common.ACS_VINTAGE) -> pd.Series:
    """Mercer County, NJ's SAIPE row (Phase 3, HANDOFF #17) -- kept for the
    existing NJ app; a thin wrapper over the generalized load_saipe_county
    so there's exactly one lookup implementation, not two."""
    return load_saipe_county(common.STATE_NJ, "021", year)


def load_pums_profile() -> pd.DataFrame:
    """NJ statewide person-level allocation profile (EDA 09, analysis.alloc_profile).

    Reads only the columns the profile needs -- the six income allocation
    flags plus person weight, age, sex, education -- out of the ~46 MB / 102
    column PUMS file, most of which are the 80 replicate weights this profile
    does not use. `analysis.alloc_profile.prepare()`/`profile_all()` do the
    actual work; this loader only gets the right slice of data to them.
    """
    from analysis.alloc_denominator import FLAG_TO_AMOUNT
    from analysis.alloc_profile import PERSON_WEIGHT, prepare, profile_all

    path = RAW_DIR / f"pums_{common.ACS_VINTAGE}_nj_alloc_flags.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: "
            "python ingestion/pull_pums_alloc_flags.py --replicates"
        )
    columns = list(FLAG_TO_AMOUNT) + [PERSON_WEIGHT, "AGEP", "SEX", "SCHL"]
    raw = pd.read_parquet(path, columns=columns)
    return profile_all(prepare(raw))


def load_pums_puma_profile() -> pd.DataFrame:
    """Same person-level outcomes as load_pums_profile, aggregated by PUMA.

    EDA 09 section 5: supports a map/table of AREAS, not a demographic claim
    about the people in them (aggregating erases the person-level link that
    licenses that claim -- the ecological fallacy). Present with that caption.
    """
    from analysis.alloc_denominator import FLAG_TO_AMOUNT
    from analysis.alloc_profile import PERSON_WEIGHT, prepare, profile

    path = RAW_DIR / f"pums_{common.ACS_VINTAGE}_nj_alloc_flags.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: "
            "python ingestion/pull_pums_alloc_flags.py --replicates"
        )
    puma_col = "public use microdata area"
    columns = list(FLAG_TO_AMOUNT) + [PERSON_WEIGHT, "AGEP", "SEX", "SCHL", puma_col]
    raw = pd.read_parquet(path, columns=columns).rename(columns={puma_col: "puma"})
    return profile(prepare(raw), by="puma").drop(columns="characteristic")


def load_trenton_tracts() -> pd.DataFrame:
    """25 Mercer tracts inside the Trenton place polygon (with geometry)."""
    import geopandas as gpd

    path = RAW_DIR / "trenton_tracts.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_trenton_dashboard.py"
        )
    return gpd.read_parquet(path)


# ---------------------------------------------------------------------------
# Allocation (imputation) -- the second, separate reliability signal
# ---------------------------------------------------------------------------

def load_alloc_nj_tract() -> pd.DataFrame:
    """NJ statewide tract allocation rates (analysis.alloc).

    Used both for the Mercer/Trenton tract-level lookups and for the
    NJ-wide 75th-percentile flag threshold -- the same dataframe serves
    both so the threshold and the rates it's judging are never computed
    from different pulls.
    """
    return alloc.derive_rates(alloc.load_level("tract"))


def load_alloc_nj_county() -> pd.DataFrame:
    """NJ statewide county allocation rates -- for the Mercer County card."""
    return alloc.derive_rates(alloc.load_level("county"))


def alloc_place_rate(
    alloc_tract_df: pd.DataFrame,
    tract_codes,
    numerator_cols: str | list[str],
    denominator_col: str,
    *,
    complement: bool = False,
) -> float:
    """Denominator-weighted allocation rate across a set of tracts.

    Trenton has no published "place" row in the allocation tables (they
    stop at county/tract/block group), so its citywide rate is derived by
    summing raw counts over the 25 constituent tracts and dividing -- never
    by averaging the 25 tracts' own rates, per the "no bare allocation rate
    without its denominator" rule. Allocation tables carry no MOE, so
    summing their counts introduces no approximation, unlike the modeled
    DHC place range this app used to build by root-sum-of-squares.
    """
    if isinstance(numerator_cols, str):
        numerator_cols = [numerator_cols]
    rows = alloc_tract_df[alloc_tract_df["TRACT"].isin(tract_codes)]
    numerator = rows[numerator_cols].sum().sum()
    denominator = rows[denominator_col].sum()
    rate = numerator / denominator
    return 1 - rate if complement else rate


# ---------------------------------------------------------------------------
# ACS estimate + measured range
# ---------------------------------------------------------------------------

def acs_sexage(df: pd.DataFrame, band: str, sex: str) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for an ACS sex/age band -- row-aligned with df."""
    codes = _codes("B01001", _SEXAGE_CELLS, band, sex)
    return aggregate_estimate(df, codes), aggregate_moe(df, codes)


def acs_poverty(df: pd.DataFrame, band: str, sex: str) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for the below-poverty-level count in an age/sex band."""
    codes = _codes("B17001", _POVERTY_CELLS, band, sex)
    return aggregate_estimate(df, codes), aggregate_moe(df, codes)


def acs_poverty_universe(df: pd.DataFrame, band: str, sex: str) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for the poverty UNIVERSE (below + at-or-above) in a band.

    The correct denominator for a poverty rate -- not B01001's total
    population, which is a different (larger) universe. See module
    docstring and ingestion/pull_trenton_dashboard.py.
    """
    codes = _codes("B17001", _POVERTY_CELLS, band, sex) + _codes(
        "B17001", _POVERTY_ABOVE_CELLS, band, sex
    )
    return aggregate_estimate(df, codes), aggregate_moe(df, codes)


def acs_range(est: float, moe: float) -> tuple[float, float]:
    """MOE is already a 90%-confidence half-width -- the range is est +/- moe."""
    return est - moe, est + moe


def poverty_rate(
    below_est: float, below_moe: float, universe_est: float, universe_moe: float
) -> tuple[float, float]:
    """Percent below poverty (0-100) and its MOE, via the ACS ratio-MOE formula.

    `below` is a SUBSET of `universe` (poverty count within the poverty
    universe for the same age band), so this is a proportion, not two
    independent estimates -- summing MOEs in quadrature (aggregate_moe)
    would be wrong here.

    SE(p) = (1/Y) * sqrt(SE(X)^2 - p^2 * SE(Y)^2), where p = X/Y; if the
    term under the root is negative, the handbook's fallback is to ADD
    instead of subtract (this happens when X and Y are highly correlated,
    which is common for small universes). Source: U.S. Census Bureau,
    "Understanding and Using American Community Survey Data: What All Data
    Users Need to Know," Appendix on calculating MOEs for derived
    proportions (the same handbook cited in analysis/acs.py for the
    zero-cell MOE-aggregation rule).
    """
    if universe_est <= 0:
        return float("nan"), float("nan")
    p = below_est / universe_est
    se_x = below_moe / Z_90
    se_y = universe_moe / Z_90
    term = se_x**2 - (p**2) * se_y**2
    if term < 0:
        term = se_x**2 + (p**2) * se_y**2
    se_p = (1 / universe_est) * term**0.5
    return p * 100, se_p * Z_90 * 100


# Same Census proportion-MOE formula, generic name -- used by the US
# dashboard's new rate-bearing measures (uninsured, limited English,
# no vehicle), where "poverty" would be the wrong word for the numerator.
proportion_rate = poverty_rate


# ---------------------------------------------------------------------------
# Reliability tier
# ---------------------------------------------------------------------------

TIER_SOLID = "Solid"
TIER_CARE = "Use with care"
TIER_RISKY = "Too risky"

TIER_LINES = {
    TIER_SOLID: "Safe to cite in the grant.",
    TIER_CARE: "Fine for a citywide total. Too risky for one neighborhood alone.",
    TIER_RISKY: "Don't cite this number alone. Combine tracts, or use the city total.",
}

# Cited in analysis/viz.py::CV_REFERENCE_LINES (ESRI 0.12 high-reliability
# cutoff, NCHS 0.30 flag/caution cutoff). These are OUR proposed tiers built
# on those conventions, not adopted Census thresholds (HANDOFF.md #8).
TIER_CV_SOLID_MAX = 0.12
TIER_CV_CARE_MAX = 0.30


def cv_from_range(est: float, low: float, high: float) -> float:
    """Recover an implied CV from any est +/- range built at 90% confidence."""
    if est <= 0 or np.isnan(est):
        return float("nan")
    se = (high - low) / (2 * Z_90)
    return se / est


def tier(cv: float) -> tuple[str, str]:
    """(tier label, plain-English line) for a coefficient of variation.

    Kept for the NJ app, analysis/composite.py, and the notebooks --
    Streamlit/app_US.py deliberately stops calling this (see its module
    docstring): the nationwide app colors its map on the CV value directly
    via cv_color(), a continuous ramp, rather than a 3-tier verdict, per
    the sponsor's neutral-voice direction (2026-08-12, see WORKLOG and
    README's "Composite tier philosophy" open question). The tier labels
    and thresholds below are unchanged either way.
    """
    if np.isnan(cv):
        return TIER_RISKY, "No reliable estimate available for this figure."
    if cv <= TIER_CV_SOLID_MAX:
        label = TIER_SOLID
    elif cv <= TIER_CV_CARE_MAX:
        label = TIER_CARE
    else:
        label = TIER_RISKY
    return label, TIER_LINES[label]


# Diverging blue->orange sequential ramp endpoints for cv_color() below.
# Originally a single-hue light-to-dark blue ramp (rationale: "colour
# carries magnitude not identity," same hue as
# Streamlit/pages/1_Whose_data_is_this.py's BLUE_450). Replaced per live
# design feedback (2026-08-13): a single hue that only varies in lightness
# reads as "different amounts of the same thing" but doesn't pop -- a low-
# CV and a high-CV county both being "a shade of blue" makes them too easy
# to eyeball as similar. The two endpoints are Okabe-Ito's blue (#0072B2)
# and orange (#E69F00) -- already used elsewhere in this app for the
# imputation quadrant chart, so the ramp reuses colors already vetted
# colorblind-safe rather than introducing a new pair. Blue-vs-orange
# specifically (rather than the more common red-vs-green diverging scheme)
# is one of the standard colorblind-safe substitutions: the two hues differ
# enough in perceived lightness and cone response that protanopia/
# deuteranopia viewers (the common forms) still separate them, which a
# red-green diverging ramp would not survive.
# Tradeoff worth stating plainly: this is a diverging-style ramp applied to
# a variable (CV) that has no meaningful zero-centered midpoint -- CV=25%
# isn't "the opposite of" CV=0% and CV=50% the way a temperature anomaly's
# negative and positive halves are opposites of a real zero. The midpoint
# color here means nothing on its own; it exists only so the two endpoints
# don't blend into a muddy brown/purple in between. It also means the ramp
# is no longer monotonic in lightness alone -- a hue-blind (achromatopsia,
# very rare, unlike red-green colorblindness) or true-grayscale reading of
# this legend would see the middle as lightest and both ends as similarly
# dark, and couldn't tell "low CV" from "high CV" by lightness alone. That
# failure mode is accepted here as a rare edge case in exchange for the
# common case (hue-perceiving viewers, including most colorblind viewers)
# reading the difference faster.
CV_COLOR_LOW = (0, 114, 178)     # Okabe-Ito blue -- low CV
CV_COLOR_MID = (247, 247, 245)   # near-white transition point, not a meaningful value
CV_COLOR_HIGH = (230, 159, 0)    # Okabe-Ito orange -- high CV
CV_COLOR_NO_DATA = (200, 200, 200)


def cv_color(cv: float, *, cv_cap: float = 0.5, alpha: int = 200) -> list[int]:
    """RGBA on a continuous blue(low)->orange(high) ramp for a coefficient
    of variation, for Streamlit/app_US.py's map and card uncertainty bars
    (no tier bins -- see tier()'s docstring for why). `cv_cap`: CV is
    unbounded above, so without a cap the vast majority of counties (CVs
    well under 0.5 for most measures at county scale) would compress into
    a narrow band near the blue end; CVs at or above the cap render as the
    ramp's full orange, not an off-scale color -- there is no "verdict"
    color, only "more/less."
    """
    if cv is None or np.isnan(cv):
        return list(CV_COLOR_NO_DATA) + [alpha]
    t = min(max(cv, 0.0), cv_cap) / cv_cap
    if t <= 0.5:
        lo, hi, local_t = CV_COLOR_LOW, CV_COLOR_MID, t / 0.5
    else:
        lo, hi, local_t = CV_COLOR_MID, CV_COLOR_HIGH, (t - 0.5) / 0.5
    rgb = [int(lo[i] + local_t * (hi[i] - lo[i])) for i in range(3)]
    return rgb + [alpha]


def difference_is_significant(est1: float, moe1: float, est2: float, moe2: float) -> float:
    """Whether two ACS estimates differ at 90% confidence (Census Bureau's
    own two-sample difference test -- "Understanding and Using American
    Community Survey Data," Appendix on comparing estimates):

        Z = (X1 - X2) / sqrt(SE1^2 + SE2^2),  significant if |Z| > 1.645

    Returns NaN if any input is NaN (no MOE published) -- never silently
    treats "no test possible" as "not significant." Returns 1.0/0.0 rather
    than a bool so it composes cleanly with pandas aggregation.

    CAVEAT, and it belongs in any caption using this: if one geography
    NESTS inside the other (e.g. a county compared to its own state), the
    two estimates share sample and are not independent -- this formula
    then OVERSTATES their combined variance, since it assumes independence
    it doesn't have. The Census Bureau does not publish the covariance
    needed to correct for it. A "significant" result from this formula in
    the nested case is therefore CONSERVATIVE: a true difference could be
    significant even when this test says no, never the reverse.
    """
    if any(pd.isna(x) for x in (est1, moe1, est2, moe2)):
        return float("nan")
    se1, se2 = moe1 / Z_90, moe2 / Z_90
    z = (est1 - est2) / (se1**2 + se2**2) ** 0.5
    return float(abs(z) > 1.645)


def statistical_peers(est: pd.Series, moe: pd.Series, key: str) -> pd.DataFrame:
    """Every candidate's relation to `key`'s own estimate at 90% confidence,
    via the same Census two-sample test as difference_is_significant()
    above -- vectorized here since Streamlit/app_US.py's peer panel runs
    it against every other row in a candidate pool (up to ~3,143 counties)
    rather than one pair at a time (statistical peer counties, 2026-08-30).

    Unlike difference_is_significant()'s own docstring caveat -- that a
    NESTED comparison (e.g. a county vs. its own state) shares sample and
    understates combined variance -- TWO DIFFERENT COUNTIES do not nest
    and are drawn from disjoint ACS samples. This is the test's clean,
    independent case: no conservative-bias caveat applies to a
    county-vs-county comparison the way it does to county-vs-state.

    `est`/`moe` must share an index (typically county `_key`) and include
    `key` itself. Returns a DataFrame on that same index with columns
    `est`, `moe`, `relation`, where `relation` is one of:
    - "self": `key`'s own row.
    - "tied": not significantly different from `key`'s estimate.
    - "higher"/"lower": this candidate's estimate is significantly
      higher/lower than `key`'s.
    - "untestable": `key`'s or the candidate's estimate or MOE is NaN --
      never silently folded into "tied" (same principle as
      difference_is_significant() returning NaN rather than False).
    """
    if key not in est.index:
        raise KeyError(f"{key!r} not found in est index")
    e_sel, m_sel = float(est[key]), float(moe[key])
    se_sel, se = m_sel / Z_90, moe / Z_90
    with np.errstate(invalid="ignore"):
        z = (e_sel - est) / np.sqrt(se_sel**2 + se**2)
    # z > 0 means the SELECTED county's estimate is the higher one, so the
    # CANDIDATE is "lower" -- and vice versa. Untestable rows land here as
    # "tied" first (NaN comparisons are always False) and get overwritten
    # below by the untestable mask, which is evaluated independently.
    relation = pd.Series(
        np.where(z > 1.645, "lower", np.where(z < -1.645, "higher", "tied")),
        index=est.index,
    )
    untestable = est.isna() | moe.isna() | pd.isna(e_sel) | pd.isna(m_sel)
    relation = relation.mask(untestable, "untestable")
    relation.loc[key] = "self"
    return pd.DataFrame({"est": est, "moe": moe, "relation": relation})


if __name__ == "__main__":
    # ponytail: smallest check that band membership, ranges, and tiers hold
    # together, using the real pulled data if present.
    assert TIER_LINES.keys() == {TIER_SOLID, TIER_CARE, TIER_RISKY}
    assert tier(0.05)[0] == TIER_SOLID
    assert tier(0.20)[0] == TIER_CARE
    assert tier(0.50)[0] == TIER_RISKY
    lo, hi = acs_range(1000.0, 200.0)
    assert (lo, hi) == (800.0, 1200.0)
    assert abs(cv_from_range(1000.0, 800.0, 1200.0) - (200.0 / Z_90 / 1000.0)) < 1e-9

    # poverty_rate: a clean case (independent-ish) and a forced-negative-term case.
    rate, rate_moe = poverty_rate(100.0, 20.0, 1000.0, 50.0)
    assert abs(rate - 10.0) < 1e-9 and rate_moe > 0
    # below_moe way bigger than what an independent combination could support
    # forces the sqrt term negative -> the handbook's add-instead-of-subtract
    # fallback must still return a real, positive MOE, not a NaN from sqrt(-x).
    rate2, rate2_moe = poverty_rate(100.0, 500.0, 1000.0, 50.0)
    assert rate2_moe > 0 and not np.isnan(rate2_moe)

    if (RAW_DIR / "acs5_2024_trenton_place.parquet").exists():
        place = load_acs("place")
        total = 0.0
        for band in BANDS:
            est, _ = acs_sexage(place, band, "both")
            total += float(est.iloc[0])
        assert abs(total - float(place["B01001_001E"].iloc[0])) < 1.0, (
            f"band sum {total} != published total {place['B01001_001E'].iloc[0]}"
        )

        # Poverty universe should be close to (never wildly off from) total
        # population for the same band -- a real but bounded gap, since the
        # two tables use slightly different universes (B17001 excludes some
        # group quarters). More than a 20% gap would mean a wiring mistake,
        # not a real universe difference.
        for band in BANDS:
            pop_est, _ = acs_sexage(place, band, "both")
            univ_est, univ_moe = acs_poverty_universe(place, band, "both")
            below_est, below_moe = acs_poverty(place, band, "both")
            gap = abs(float(univ_est.iloc[0]) - float(pop_est.iloc[0])) / float(pop_est.iloc[0])
            assert gap < 0.20, f"{band}: poverty universe vs. population gap {gap:.1%} looks wrong"
            rate, rate_moe = poverty_rate(
                float(below_est.iloc[0]), float(below_moe.iloc[0]),
                float(univ_est.iloc[0]), float(univ_moe.iloc[0]),
            )
            assert 0.0 <= rate <= 100.0 and rate_moe > 0

    if (RAW_DIR / "acs5_2024_nj_alloc_tract.parquet").exists():
        nj_tract = load_alloc_nj_tract()
        trenton = load_trenton_tracts()
        trenton_codes = trenton["TRACT"]
        rows = nj_tract[nj_tract["TRACT"].isin(trenton_codes)]
        city_income_alloc = alloc_place_rate(
            nj_tract, trenton_codes, "B99192_002E", "B99192_001E", complement=True
        )
        # A weighted aggregate must land inside its own inputs' range -- if it
        # doesn't, the denominators are wrong (e.g. summed the wrong column).
        assert rows["income_alloc"].min() <= city_income_alloc <= rows["income_alloc"].max(), (
            f"Trenton city income_alloc {city_income_alloc:.3f} falls outside its own "
            f"25 tracts' range [{rows['income_alloc'].min():.3f}, {rows['income_alloc'].max():.3f}]"
        )
    if (RAW_DIR / "saipe_counties_2019_2024.parquet").exists():
        mercer_saipe = load_saipe_mercer()
        assert mercer_saipe["NAME"] == "Mercer County"
        assert mercer_saipe["SAEMHI_LB90"] <= mercer_saipe["SAEMHI_PT"] <= mercer_saipe["SAEMHI_UB90"]
        derived = common.half_width(mercer_saipe["SAEMHI_LB90"], mercer_saipe["SAEMHI_UB90"])
        assert abs(derived - mercer_saipe["SAEMHI_MOE"]) < 1.0, (
            f"Mercer SAIPE half-width {derived:.1f} vs published MOE {mercer_saipe['SAEMHI_MOE']:.1f}"
        )

    print("dashboard self-check OK")
