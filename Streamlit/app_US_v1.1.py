"""Nationwide county demographic explorer -- state-first drill-down.

Map-first, same interaction model as Streamlit/app_NJ.py: click a state to
see its counties, click a county (or search the filter panel at the top of
the page) to read its American Community Survey estimates and how much
uncertainty each one carries. The layout below intentionally mirrors
app_NJ.py's card/map structure -- see that file's module docstring for the
original design. (Filters and search moved from the sidebar to a top-of-
page expander, and the sidebar itself was removed, 2026-08-18.)

What changed from app_NJ.py, and why
-------------------------------------
1. Performance: NJ's map became unusable at 3,143-tract statewide scale.
   Root cause (confirmed live 2026-08-12, see WORKLOG): an invisible
   ScatterplotLayer click-grid built as a workaround for a GeoJsonLayer
   picking bug -- at NJ's own 2.5km grid step, nationwide scale would
   generate ~1.46 MILLION pickable points. Also confirmed live: the
   picking bug is FIXED in the currently installed Streamlit 1.60.0 /
   pydeck 0.9.1 (a plain GeoJsonLayer(pickable=True) click reaches
   on_select correctly). So the fix here is a deletion, not a rewrite:
   the click-grid is gone, the fill layer itself is the click target, and
   the base GeoJSON feature list is built ONCE per level via
   cache_resource rather than re-serialized on every rerun.
2. Geography ladder: state -> county (US_LEVEL_SPECS in
   analysis/dashboard.py), not county -> tract. National choropleth of all
   3,144 counties at once is never rendered; the county view is always
   scoped to one selected state (62 median, 254 max in Texas).
3. Neutral federal-statistical-agency voice (sponsor direction,
   2026-08-12, see WORKLOG and README's "Composite tier philosophy" open
   question): no TIER_SOLID/CARE/RISKY verdict chip, no "safe to cite" /
   "too risky" language. The map colors on CV directly via a continuous
   blue-to-orange ramp (cv_color(), see analysis/dashboard.py for the
   colorblind-safety rationale); cards show the CV as a number, the CI
   bounds explicitly labeled 90%, and a dot-plot-plus-gradient-band
   distribution visual instead of a tier chip. analysis.dashboard.tier()
   is UNCHANGED and still used by app_NJ.py and the notebooks -- this app
   just never calls it.
4. Cascading geography filters (state, RUCC rural-urban tier,
   population-size bin) -- the sponsor's concrete ask. These narrow the
   TYPICAL case; the performance fix above is what makes the UNFILTERED
   default case (a whole state's counties) survivable, since filters do
   nothing for that case. (Census region/division filters were removed
   from this app's surface, 2026-08-18 -- state-level filtering already
   covers the same narrowing use case at finer granularity.)
5. New card content: CV on the face (was expander-only in app_NJ.py),
   explicit 90%-CI bounds, a percentile-rank-within-the-current-filter
   line, a county-vs-state significant-difference check, and (where
   available) an ACS 1-year vs 5-year precision comparison.
6. The composite score question (README "Composite tier philosophy",
   still open for mentors) is NOT resolved by this app. The two competing
   candidate formulas in analysis.composite (equal_weight_score,
   worst_component_score) remain available there for the notebooks, but
   this app no longer surfaces either on its cards (2026-08-18) -- the one
   unambiguous number (a measure's own CV percentile rank within the
   current filter set) is what drives sorting/filtering here instead.

Run from the repo root:
    streamlit run Streamlit/app_US.py

Needs data/raw/{acs5_2024_usdash,acs1_2024_usdash,geo_2024_usdash,
acs5_2024_usdash_alloc,rucc_2023}_* -- regenerate with:
    python ingestion/pull_usdash.py
    python ingestion/pull_us_geometry.py
    python ingestion/pull_usdash_alloc.py
    python ingestion/pull_rucc.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

from analysis import composite
from analysis.acs import flag_topcoded_income, income_cv
from analysis.dashboard import (
    BANDS,
    INCOME_BANDS,
    US_LEVEL_SPECS,
    acs_1yr_available_keys,
    acs_income_bracket,
    acs_income_bracket_universe,
    acs_insurance_universe,
    acs_language_universe,
    acs_limited_english,
    acs_median_rent,
    acs_no_vehicle,
    acs_poverty,
    acs_poverty_universe,
    acs_range,
    acs_rent_burden,
    acs_renter_occupied,
    acs_sexage,
    acs_uninsured,
    acs_vehicle_universe,
    census_region,
    children_of,
    cv_color,
    cv_from_range,
    difference_is_significant,
    geo_key,
    load_alloc_us_county,
    load_level_data,
    load_level_geo,
    load_rucc,
    load_us_acs1_county,
    population_size_bin,
    proportion_rate,
    statistical_peers,
    POPULATION_BIN_LABELS,
)

st.set_page_config(page_title="US County Demographic Explorer", layout="wide")

QUADRANT_LABELS_PLAIN = {
    "low_cv_low_alloc": "Low sampling risk, low share of records imputed",
    # "Blind spot:" prefix dropped from the app surface only (sponsor
    # de-editorialization direction, 2026-08-12) -- CLAUDE.md protects the
    # term itself as an EDA 06 term of art, so it stays in the report and
    # notebooks (docs/phase1-findings-report.md, notebooks/06-*). The
    # remaining text is a plain description, not a verdict.
    "low_cv_high_alloc": "Low sampling risk, high share of records imputed",
    "high_cv_low_alloc": "High sampling risk, low share of records imputed",
    "high_cv_high_alloc": "High sampling risk, high share of records imputed",
}
QUADRANT_COLOR = {
    # Kept categorical (unlike the CV map below) -- a continuous ramp
    # cannot express a two-by-two classification. Okabe-Ito palette,
    # matching app_NJ.py, since this is a description of two crossed
    # conditions, not a ranking.
    QUADRANT_LABELS_PLAIN["low_cv_low_alloc"]: "#0072B2",
    QUADRANT_LABELS_PLAIN["low_cv_high_alloc"]: "#CC79A7",
    QUADRANT_LABELS_PLAIN["high_cv_low_alloc"]: "#E69F00",
    QUADRANT_LABELS_PLAIN["high_cv_high_alloc"]: "#D55E00",
    "No data": "#999999",
}
QUADRANT_ORDER = tuple(QUADRANT_COLOR)

IMPUTATION_INCOME = "Imputation: household income"


@dataclass(frozen=True)
class Measure:
    """One card-and-map-able ACS measure (variable expansion, 2026-08-30).

    `values`/`universe` each take a geography dataframe (one row per
    county/state, or a single-row slice for one county) and return
    (estimate, moe) row-aligned Series -- the same shape acs_sexage() and
    acs_poverty() already returned, so _measure_layer() below and the
    per-county card loop treat every measure identically regardless of
    which Census table backs it. `universe`, when given, turns on a
    proportion_rate() rate line using the same Census ratio-MOE formula
    for every rate-bearing measure, not just poverty.

    IMPUTATION_INCOME is deliberately NOT a Measure: its quadrant/color-map
    output shape is fundamentally different (a category, not a CV), so it
    stays its own branch in _measure_layer(), same as before this registry
    existed.
    """
    label: str
    topic: str
    table_id: str
    values: Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]]
    universe: Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]] | None = None
    rate_label: str = ""
    measure_label: str | None = None
    unit_suffix: str = ""  # e.g. "%" for rent burden, which is a rate itself, not a count


_INCOME_BAND_TITLES = {
    # Dollar signs escaped (\$) -- Streamlit's markdown renderer treats a
    # PAIR of literal "$" in the same string as LaTeX math delimiters (a
    # single one is harmless, but "$25,000-$50,000" has two, which
    # silently ate both dollar signs and rendered "25,000-" in KaTeX's
    # serif math font instead of plain text). Escaping avoids that in
    # every downstream st.markdown() call using these labels as card
    # titles (2026-08-30).
    "Under $25k": "Households earning under \\$25,000",
    "$25k-$50k": "Households earning \\$25,000\u2013\\$50,000",
    "$50k-$100k": "Households earning \\$50,000\u2013\\$100,000",
    "$100k+": "Households earning \\$100,000+",
}


def _income_values(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for median household income -- MOE masked to NaN
    for top-coded counties, matching analysis.acs.income_cv()'s
    treatment: a top-coded value is censored, not measured, so it must
    not produce a spuriously low CV on the map or in a percentile rank.
    Only needed for the map-dropdown/checklist use of this measure --
    the hand-written income card below keeps computing its own rank via
    IMPUTATION_INCOME's income_cv() call, unchanged, for that reason."""
    est = df["B19013_001E"].astype(float)
    moe = df["B19013_001M"].astype(float).mask(flag_topcoded_income(df))
    return est, moe


def _build_measures() -> dict[str, Measure]:
    registry: dict[str, Measure] = {
        "Total population": Measure(
            label="Total population", topic="Population", table_id="B01001",
            values=lambda df: (df["B01001_001E"].astype(float), df["B01001_001M"].astype(float)),
        ),
        "Median household income": Measure(
            label="Median household income", topic="Income", table_id="B19013",
            values=_income_values,
        ),
        "Median gross rent": Measure(
            label="Median gross rent", topic="Housing", table_id="B25064",
            values=acs_median_rent,
        ),
        "Rent burden (rent as % of income)": Measure(
            label="Rent burden (rent as % of income)", topic="Housing", table_id="B25071",
            values=acs_rent_burden, unit_suffix="%",
        ),
        "Uninsured (all ages)": Measure(
            label="Uninsured (all ages)", topic="Health", table_id="B27001",
            values=acs_uninsured, universe=acs_insurance_universe,
            rate_label="of the population uninsured",
        ),
        "Limited English speaking households": Measure(
            label="Limited English speaking households", topic="Language", table_id="C16002",
            values=acs_limited_english, universe=acs_language_universe,
            rate_label="of households limited-English-speaking",
        ),
        "Households with no vehicle available": Measure(
            label="Households with no vehicle available", topic="Transportation", table_id="B08201",
            values=acs_no_vehicle, universe=acs_vehicle_universe,
            rate_label="of households with no vehicle available",
        ),
    }

    for band in BANDS:
        registry[band] = Measure(
            label=band, topic="Population", table_id="B01001",
            values=partial(acs_sexage, band=band, sex="both"),
            measure_label=f"{band} population",
        )

    for band in BANDS:
        # Registry KEY is "Poverty: {band}" (disjoint from the population
        # band's bare-band key just above); Measure.label stays the bare
        # band name so the CARD TITLE matches the pre-registry behavior
        # ("5-17", not "Poverty: 5-17") -- the "Poverty" section header
        # already disambiguates it from the population card of the same
        # name, same as before this registry existed.
        registry[f"Poverty: {band}"] = Measure(
            label=band, topic="Poverty", table_id="B17001",
            values=partial(acs_poverty, band=band, sex="both"),
            universe=partial(acs_poverty_universe, band=band, sex="both"),
            rate_label=f"of {band} residents in poverty",
            measure_label=f"{band} population in poverty",
        )

    for band in INCOME_BANDS:
        label = _INCOME_BAND_TITLES[band]
        registry[label] = Measure(
            label=label, topic="Income", table_id="B19001",
            values=partial(acs_income_bracket, band=band),
            universe=acs_income_bracket_universe,
            rate_label=f"of households earning {band}",
        )

    return registry


MEASURES = _build_measures()
MEASURE_OPTIONS = list(MEASURES) + [IMPUTATION_INCOME]
DEFAULT_CARD_LABELS = ("Total population", "Median household income")


def _measure_display(key: str) -> str:
    """'Topic: label' for selectbox/multiselect format_func -- built from
    Measure.label, NOT the raw registry key, since the poverty bands' own
    keys ("Poverty: 5-17") already contain a topic-like prefix and would
    double up ("Poverty: Poverty: 5-17") if the key were reused directly.
    The underlying returned VALUE is still the bare registry key either
    way, so every downstream comparison against a measure string
    (_measure_layer, IMPUTATION_INCOME checks, _rank_and_n) is unaffected."""
    return f"{MEASURES[key].topic}: {MEASURES[key].label}" if key in MEASURES else key


CONFIDENCE_LEVEL_PCT = 90  # ACS MOEs are 90%-confidence half-widths -- stated explicitly everywhere a range appears
ACS_VINTAGE = "2020-2024, 5-year"  # single source for the subheader and the publishable-sentence citation


def _hex_to_rgba(hex_color: str, alpha: int = 170) -> list[int]:
    h = hex_color.lstrip("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)] + [alpha]


def _ordinal(n: float) -> str:
    """'71st', '2nd', '3rd', '4th', ... -- integer English ordinal suffix.
    'n/a' for NaN (e.g. a topcoded-income county has no income CV)."""
    if n is None or np.isnan(n):
        return "n/a"
    i = int(round(n))
    if 11 <= (i % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(i % 10, "th")
    return f"{i}{suffix}"


# ---------------------------------------------------------------------------
# Census Bureau visual styling -- single consolidated block (change A).
# census.gov's own stylesheets (census-fonts.min.css, census-css.min.css,
# fetched and inspected live 2026-08-18) declare Roboto as the site font,
# so this is a direct match, not a substitute -- no fallback typeface was
# needed. Palette sampled from the reference screenshot: hero/primary blue
# #0D54B0, gold call-to-action accent #FCBE2D, link blue #1A6BB5, body ink
# #131313, white background. The @import below is what actually loads the
# Roboto webfont into the page; .streamlit/config.toml's theme.font/
# headingFont/primaryColor/linkColor/etc. (native theming, applied wherever
# Streamlit's own theme engine reaches, e.g. widget chrome and st.button)
# point at the same family/palette so the two layers agree. Everything
# CSS can reach that native theming can't (card/legend/stat-row classes,
# which predate this change and are pure custom HTML) lives here instead
# of being scattered across multiple st.markdown calls.
# ---------------------------------------------------------------------------
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');

html, body, [class*="css"] { font-family: 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif; }
h1, h2, h3, h4, h5, h6 { font-family: 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif;
                          font-weight: 700; color: #131313; }
a, a:visited { color: #1A6BB5; }
a:hover { color: #0D54B0; }

.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"] {
    background-color: #FCBE2D; border-color: #FCBE2D; color: #131313; font-weight: 600;
}
.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="stBaseButton-primary"]:hover {
    background-color: #E8AC1F; border-color: #E8AC1F;
}

.card-main-row { display: flex; align-items: baseline; justify-content: space-between;
                 flex-wrap: wrap; gap: 6px 10px; margin: 2px 0; }
.card-range  { font-size: clamp(1.15rem, 2.2vw, 1.6rem); font-weight: 700; color: #131313; }
.card-cv-badge { display: inline-block; font-size: 0.85rem; font-weight: 700; color: #131313;
                 padding: 3px 10px; border-radius: 999px; white-space: nowrap; }
.card-rate   { color: #333; font-size: 0.9rem; margin-top: 2px; }
.card-alloc  { color: #333; font-size: 0.85rem; margin-top: 6px; padding-top: 6px;
               border-top: 1px dashed #DDD; }
.card-rank   { color: #5A5A5A; font-size: 0.82rem; margin-top: 4px; }
.stat-row    { display: flex; justify-content: space-between; padding: 5px 2px;
               border-bottom: 1px solid #E6E6E6; font-size: 0.85rem; }
.stat-row .label { color: #5A5A5A; }
.stat-row .value { font-weight: 600; color: #222; font-variant-numeric: tabular-nums; }
.legend-swatch { display: inline-block; width: 11px; height: 11px; border-radius: 2px;
                 margin-right: 4px; vertical-align: middle; }
.legend-label  { font-size: 0.78rem; color: #5A5A5A; }
.filter-count  { color: #5A5A5A; font-size: 0.8rem; }
</style>
"""


# ---------------------------------------------------------------------------
# Cached data loading
# ---------------------------------------------------------------------------

def _geo_label(row) -> str:
    """Full 'X County, State' -- deliberately NOT split on the first comma
    (app_NJ.py's _geo_label does that for NJ, where every row is already
    "X County, New Jersey" so splitting to "X County" is unambiguous).
    Nationwide, county names repeat across states (confirmed live: "Mercer
    County" alone exists in NJ, IL, KY, MO) -- splitting would collapse
    ~30 different "Washington County"s into one indistinguishable label."""
    return row["NAME"]


@st.cache_resource
def _load_all() -> dict:
    """Every dataset the app reads from, loaded once per process.

    cache_resource, not cache_data -- see app_NJ.py's _load_all docstring
    for why (nothing here is ever mutated after this returns).
    """
    state_df = load_level_data("state", specs=US_LEVEL_SPECS)
    county_df = load_level_data("county", specs=US_LEVEL_SPECS)
    state_geo = load_level_geo("state", specs=US_LEVEL_SPECS)
    county_geo = load_level_geo("county", specs=US_LEVEL_SPECS)

    county_df = county_df.assign(_key=geo_key(county_df, "county", specs=US_LEVEL_SPECS))
    state_df = state_df.assign(_key=geo_key(state_df, "state", specs=US_LEVEL_SPECS))

    alloc_county = load_alloc_us_county()
    alloc_county = alloc_county.assign(_key=geo_key(alloc_county, "county", specs=US_LEVEL_SPECS))

    rucc = load_rucc()
    rucc = rucc.assign(_key=geo_key(rucc, "county", specs=US_LEVEL_SPECS))

    acs1_keys = acs_1yr_available_keys()

    county_df = county_df.assign(
        pop_bin=population_size_bin(county_df["B01001_001E"].astype(float)),
    ).merge(rucc[["_key", "RUCC_2023", "RUCC_METRO"]], on="_key", how="left")

    return {
        "state_df": state_df,
        "county_df": county_df,
        "state_geo": state_geo,
        "county_geo": county_geo,
        "alloc_county": alloc_county,
        "acs1_keys": acs1_keys,
        "labels_state": {row["_key"]: _geo_label(row) for _, row in state_df.iterrows()},
        "labels_county": {row["_key"]: _geo_label(row) for _, row in county_df.iterrows()},
        # National (all-counties) threshold, per lead decision 2026-08-12 --
        # this is ONE nationwide app, not 51 separate ones, so a county's
        # flag line means the same thing regardless of which state it's in.
        "income_alloc_threshold": composite.allocation_flag_threshold(
            alloc_county["income_alloc"]
        ),
    }


@st.cache_resource
def _load_acs1_county() -> pd.DataFrame:
    """ACS 1-year county data, cached separately from _load_all() -- kept
    out of that function's returned dict so nothing there is ever mutated
    after it returns (see _load_all's docstring)."""
    df = load_us_acs1_county()
    return df.assign(_key=geo_key(df, "county", specs=US_LEVEL_SPECS))


@st.cache_resource
def _base_geojson(level: str) -> list[dict]:
    """Every feature for a level, built ONCE per process -- the fix for
    app_NJ.py's per-rerun to_json()/json.loads() round-trip (render_map's
    docstring there explains why that cost four full geometry
    serializations per render). Per render, render_map() below only
    SELECTS a subset of this prebuilt list and sets one property
    (fill_color) -- no re-serialization of geometry, ever, after this
    function's one-time cost.
    """
    import json

    data = _load_all()
    gdf = data["county_geo"] if level == "county" else data["state_geo"]
    key_col = "county_key" if level == "county" else "state_key"
    keys = geo_key(gdf, level, specs=US_LEVEL_SPECS)
    gdf = gdf.to_crs(epsg=4326).copy()
    gdf[key_col] = keys
    geojson = json.loads(gdf[[key_col, "geometry"]].to_json())
    return geojson["features"]


# ---------------------------------------------------------------------------
# Measure -> per-geography values
# ---------------------------------------------------------------------------

def _measure_layer(df: pd.DataFrame, measure: str, alloc_df: pd.DataFrame, income_alloc_threshold: float):
    """Per-county values for the chosen measure, keyed by _key.

    Same shape as app_NJ.py's _measure_layer, minus the reliability-TIER
    output (this app colors on CV directly, not a 3-tier verdict -- see
    module docstring). Returns (cv_by_key, est_by_key, range_by_key,
    pct_by_key, quadrant_by_key, color_map, legend_order, title).
    quadrant_by_key/color_map/legend_order are only non-None for the
    imputation measure (the one categorical view left).

    Dispatches through the MEASURES registry for every other measure
    (variable expansion, 2026-08-30) -- this is what makes _rank_and_n()
    further down work identically for a brand-new measure with zero
    changes to that function, since it only ever calls back into here.
    """
    keys = df["_key"]

    if measure == IMPUTATION_INCOME:
        income_df = df[["B19013_001E", "B19013_001M"]].set_index(keys)
        alloc_by_key = alloc_df.set_index("_key")["income_alloc"].reindex(income_df.index)
        cv_series = income_cv(income_df)
        quadrant = composite.classify_quadrant(
            cv_series, alloc_by_key, alloc_threshold=income_alloc_threshold,
        )
        plain = quadrant.map(QUADRANT_LABELS_PLAIN)
        quadrant_by_key = {k: (v if isinstance(v, str) else "No data") for k, v in plain.items()}
        est_by_key = income_df["B19013_001E"].to_dict()
        range_by_key = {
            k: (max(0.0, e - m), e + m)
            for k, e, m in zip(income_df.index, income_df["B19013_001E"], income_df["B19013_001M"])
        }
        cv_by_key = cv_series.to_dict()
        return (
            cv_by_key, est_by_key, range_by_key, None, quadrant_by_key,
            QUADRANT_COLOR, QUADRANT_ORDER, "Income reliability: sampling risk x imputation",
        )

    measure_def = MEASURES[measure]
    est, moe = measure_def.values(df)
    est = pd.Series(est.to_numpy(dtype=float), index=keys)
    moe = pd.Series(moe.to_numpy(dtype=float), index=keys)

    pct_by_key = None
    if measure_def.universe is not None:
        univ_est, univ_moe = measure_def.universe(df)
        univ_est = pd.Series(univ_est.to_numpy(dtype=float), index=keys)
        univ_moe = pd.Series(univ_moe.to_numpy(dtype=float), index=keys)
        pct_by_key = {
            k: proportion_rate(e, m, ue, um)[0]
            for k, e, m, ue, um in zip(keys, est, moe, univ_est, univ_moe)
        }

    cv_by_key, est_by_key, range_by_key = {}, {}, {}
    for k, e, m in zip(keys, est, moe):
        est_by_key[k] = e
        if pd.isna(m) or pd.isna(e):
            cv_by_key[k] = float("nan")
            range_by_key[k] = (e, e)
            continue
        lo, hi = acs_range(e, m)
        cv_by_key[k] = cv_from_range(e, lo, hi)
        range_by_key[k] = (max(0.0, lo), hi)
    return cv_by_key, est_by_key, range_by_key, pct_by_key, None, None, None, f"ACS reliability: {measure}"


# ---------------------------------------------------------------------------
# Statistical peer counties (2026-08-30) -- which counties are, on one
# chosen measure, statistically indistinguishable from a selected county
# at 90% confidence. See render_peer_panel()'s docstring for the full
# rationale; this section is just the comparison-scale values and the
# eligibility list it runs against.
# ---------------------------------------------------------------------------

# Counts are deliberately excluded: "similar total population" is just
# "similar size," which the structural population-bin gate in
# _compute_peers() already handles more directly. Eligible measures are
# every rate-bearing registry entry (has a `universe`) plus the three
# medians, which need no propagation.
_PEER_MEDIANS = {"Median household income", "Median gross rent", "Rent burden (rent as % of income)"}
PEER_MEASURES = [k for k, m in MEASURES.items() if m.universe is not None or k in _PEER_MEDIANS]


def _peer_values(df: pd.DataFrame, measure_key: str) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) on the scale statistical_peers() compares counties
    on, keyed by _key: the propagated RATE for rate-bearing measures (the
    same proportion_rate() call _measure_layer() makes for its pct_by_key
    output, redone here because that dict drops the rate's own MOE, which
    a peer comparison needs), or the raw value for the three medians,
    which need no propagation. Restricted to PEER_MEASURES.
    """
    measure = MEASURES[measure_key]
    keys = df["_key"]
    est, moe = measure.values(df)
    est = pd.Series(est.to_numpy(dtype=float), index=keys)
    moe = pd.Series(moe.to_numpy(dtype=float), index=keys)
    if measure.universe is None:
        return est, moe
    univ_est, univ_moe = measure.universe(df)
    univ_est = pd.Series(univ_est.to_numpy(dtype=float), index=keys)
    univ_moe = pd.Series(univ_moe.to_numpy(dtype=float), index=keys)
    rate_est, rate_moe = {}, {}
    for k, e, m, ue, um in zip(keys, est, moe, univ_est, univ_moe):
        rate_est[k], rate_moe[k] = proportion_rate(e, m, ue, um)
    return pd.Series(rate_est), pd.Series(rate_moe)


@dataclass
class PeerResult:
    """Everything render_peer_panel() needs to describe one county's
    statistical peers on one measure -- see _compute_peers()."""
    measure_key: str
    pool_n: int              # structurally-gated pool size, before dropping missing
    dropped_n: int            # candidates (excluding self) dropped for a missing est/moe
    peers: pd.DataFrame       # TIED rows only, index=_key, columns=[est, moe] -- excludes self
    n_higher: int
    n_lower: int
    self_est: float
    self_moe: float

    @property
    def tested_n(self) -> int:
        return len(self.peers) + self.n_higher + self.n_lower


def _compute_peers(
    county_df: pd.DataFrame, code: str, measure_key: str,
    same_rucc: bool, same_popbin: bool,
) -> PeerResult | None:
    """Statistical-peer computation for one county on one measure, gated
    to structurally comparable counties.

    `county_df` is deliberately the FULL, unfiltered county table (see
    render_peer_panel()'s docstring for why this must not be
    filtered_county_df) -- the two checkboxes here are the ONLY narrowing
    applied before statistical_peers() runs.
    """
    if code not in set(county_df["_key"]):
        return None
    pool = county_df
    if same_rucc:
        rucc_class = county_df.loc[county_df["_key"] == code, "RUCC_METRO"].iloc[0]
        pool = pool[pool["RUCC_METRO"] == rucc_class]
    if same_popbin:
        pop_bin = county_df.loc[county_df["_key"] == code, "pop_bin"].astype(str).iloc[0]
        pool = pool[pool["pop_bin"].astype(str) == pop_bin]
    if code not in set(pool["_key"]):
        return None  # defensive: the selected county should never be gated out of its own pool
    pool_n = len(pool)
    est, moe = _peer_values(pool, measure_key)
    peers_df = statistical_peers(est, moe, code)
    self_row = peers_df.loc[code]
    n_higher = int((peers_df["relation"] == "higher").sum())
    n_lower = int((peers_df["relation"] == "lower").sum())
    dropped_n = int((peers_df["relation"] == "untestable").sum())
    return PeerResult(
        measure_key=measure_key, pool_n=pool_n, dropped_n=dropped_n,
        peers=peers_df[peers_df["relation"] == "tied"],
        n_higher=n_higher, n_lower=n_lower,
        self_est=float(self_row["est"]), self_moe=float(self_row["moe"]),
    )


# ---------------------------------------------------------------------------
# Filter stack
# ---------------------------------------------------------------------------

def top_filters(county_df: pd.DataFrame, level: str, geo: dict):
    """Cascading RUCC -> population-bin filter, showing N remaining at
    every step, plus the "back to national view" control -- moved from
    the sidebar into a collapsible panel at the top of the page (change
    B, 2026-08-18); the sidebar itself is gone (change D). Census
    region/division filters that used to precede RUCC in this cascade
    were removed in the same pass (change C) -- state-level filtering
    (the map's own state-first drill-down) already covers that narrowing
    use case at finer granularity. Every selectbox handles a
    filtered-to-zero upstream selection without breaking (e.g. Wyoming
    has zero metro counties -- see the RUCC step below): st.selectbox
    always gets "All" plus whatever OPTIONS REMAIN, never an empty
    option list.

    Returns (filtered_county_df, search_slot): search_slot is an empty
    st.container the caller fills in AFTER the map is drawn, since the
    geography-search dropdown's seed value depends on a map click that
    hasn't happened yet at this point in the script (see main()'s call
    to geography_search_control, and that function's docstring).
    """
    df = county_df
    with st.expander("Filter counties", expanded=True):
        back_col, rucc_col, pop_col, search_col = st.columns(4)

        with back_col:
            st.markdown("&nbsp;")  # vertical alignment with the selectbox labels alongside it
            back_clicked = st.button(
                "Back to national state view" if level == "county" else "Viewing: national (all states)"
            )
            if back_clicked and level == "county":
                geo.update(level="state", code=None, state_scope=None, peer_focus=False)
                st.rerun()

        with rucc_col:
            rucc_opts = ["All", "Metro", "Nonmetro"]
            rucc_choice = st.selectbox("Metro / nonmetro (USDA ERS RUCC 2023)", rucc_opts, key="filter_rucc")
            if rucc_choice != "All":
                df = df[df["RUCC_METRO"] == rucc_choice]

        with pop_col:
            pop_opts = ["All"] + [b for b in POPULATION_BIN_LABELS if b in df["pop_bin"].astype(str).unique()]
            pop_choice = st.selectbox("Population size", pop_opts, key="filter_pop")
            if pop_choice != "All":
                df = df[df["pop_bin"].astype(str) == pop_choice]

        search_slot = search_col.container()

        st.markdown(f"<span class='filter-count'>{len(df):,} of {len(county_df):,} counties match these filters.</span>", unsafe_allow_html=True)
        if len(df) == 0:
            st.warning("No counties match this filter combination. Loosen a filter above.")

        with st.expander("Classification used: USDA ERS Rural-Urban Continuum Codes, 2023"):
            st.caption(
                "9 levels (1-3 metro by area population size, 4-9 nonmetro by urbanization "
                "and adjacency to a metro area), assigned by the U.S. Department of "
                "Agriculture's Economic Research Service. A published federal classification, "
                "not one this project defines."
            )
            if len(df):
                dist = df["RUCC_2023"].value_counts().sort_index()
                st.bar_chart(dist)

    return df, search_slot


# ---------------------------------------------------------------------------
# Distribution visual: dot + 90% CI whiskers + gradient band
# ---------------------------------------------------------------------------

def _distribution_fig(est: float, low: float, high: float, cv: float):
    """Uncertainty bar, drawn to scale against the estimate itself.

    Two changes from the earlier gradient-band version, both aimed at the
    same problem: that version auto-fit its x-axis to each interval's OWN
    width, so a razor-precise county and a wildly imprecise one produced
    visually IDENTICAL charts (same shape, filling the same width) -- the
    one thing a risk visual most needs to show was normalized away.
    1. Fixed scale: the axis always runs from 0 to a bit past
       max(estimate, high), so the filled bar's WIDTH is now a real
       fraction of the chart -- a wide margin of error visibly eats most
       of the bar; a tight one is a thin sliver near the estimate dot.
    2. Shared color: the bar is filled with cv_color(), the same
       continuous ramp the map uses, so a dark/saturated bar here means
       the same thing a dark/saturated county means on the map. Width and
       color now reinforce the same signal instead of one lone abstract
       gradient trying to carry it.

    Still no violin/density curve: ACS MOEs come from successive-difference
    replication, which yields a variance, not a known distributional
    family, and for small counts the true sampling distribution is skewed
    and bounded at zero -- a normal density would draw probability mass at
    impossible negative counts on exactly the cases where uncertainty
    matters most. Clamped at zero for the same reason:
    `display_low = max(0.0, low)`, never a symmetric fade below zero.
    """
    display_low = max(0.0, low)
    ref = max(high, est, 1e-9) * 1.08
    fill = tuple(c / 255 for c in cv_color(cv)[:3])

    fig, ax = plt.subplots(figsize=(4.0, 0.62))
    ax.axhline(0.5, color="#DCDCDC", linewidth=1.5, zorder=1)
    ax.barh(
        0.5, high - display_low, left=display_low, height=0.5,
        color=fill, edgecolor="#1A1A1A", linewidth=0.8, zorder=2,
    )
    ax.plot([est], [0.5], marker="o", markersize=6, color="#1A1A1A", zorder=3)
    if low < 0:
        ax.axvline(0, color="#1A1A1A", linewidth=1, linestyle=":", zorder=2)
    ax.annotate(
        f"{display_low:,.0f}", (display_low, 0.5), xytext=(-6, 0), textcoords="offset points",
        ha="right", va="center", fontsize=7.5, color="#333333",
    )
    ax.annotate(
        f"{high:,.0f}", (high, 0.5), xytext=(6, 0), textcoords="offset points",
        ha="left", va="center", fontsize=7.5, color="#333333",
    )
    ax.set_xlim(-ref * 0.02, ref * 1.02)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.subplots_adjust(left=0.02, right=0.98, top=0.95, bottom=0.05)
    return fig


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------

def _stats_panel(rows: list[tuple[str, str]], note: str) -> None:
    body = "".join(
        f"<div class='stat-row'><span class='label'>{label}</span>"
        f"<span class='value'>{value}</span></div>"
        for label, value in rows
    )
    st.markdown(body, unsafe_allow_html=True)
    st.caption(note)


def _pct_or_na(value: float) -> str:
    return "n/a" if value is None or np.isnan(value) else f"{value * 100:.1f}%"


def _population_quality_panel(alloc_county: pd.DataFrame, code: str) -> None:
    """Fills the space under the Total population card with data-quality
    context that doesn't depend on a population MOE (see design spec
    docs/superpowers/specs/2026-08-18-population-data-quality-card-design.md)
    -- population itself usually has no published MOE (it's calibrated to
    independent population controls, see the caption above), so CV is not
    available here the way it is for income. These allocation (imputation)
    rates are a separate, always-available signal: published directly by
    the Census Bureau's own person-level allocation tables (B98031,
    B99011, B99012, B99021), not derived from ACS sampling error. Shown
    for every county, not just the no-MOE case, so a county's data-quality
    context doesn't vanish just because population happened to publish a
    MOE (deliberate consistency choice -- see the design spec's
    "Alternatives considered" section).
    """
    alloc_row = alloc_county.set_index("_key")
    if code not in alloc_row.index:
        return
    r = alloc_row.loc[code]
    with st.container(border=True):
        st.markdown("**Population data quality**")
        _stats_panel(
            [
                ("Overall person-level imputation (Bureau-published)", _pct_or_na(r.get("overall_alloc"))),
                ("Sex imputed", _pct_or_na(r.get("sex_alloc"))),
                ("Age imputed", _pct_or_na(r.get("age_alloc"))),
                ("Race imputed", _pct_or_na(r.get("race_alloc"))),
            ],
            "Imputed: filled in by the Census Bureau's statistical methods when a household "
            "didn't answer that question, rather than reported directly. These rates come from "
            "the Bureau's own person-level allocation tables and are separate from the margin "
            "of error above -- a county can have a very precise population count and still have "
            "some characteristics imputed, or vice versa.",
        )


def _rent_context_panel(row: pd.DataFrame) -> None:
    """Renter-occupied housing units for this county, shown under the
    Median gross rent card (variable expansion, 2026-08-30) -- rent and
    rent burden are only measured against renter-occupied units, so a
    county with few renters has a small universe and a correspondingly
    wide rent MOE. Context, not its own selectable card, following the
    _population_quality_panel precedent above."""
    renter_est, _renter_moe = acs_renter_occupied(row)
    re_ = float(renter_est.iloc[0])
    if pd.isna(re_):
        return
    with st.container(border=True):
        st.markdown("**Renter-occupied housing units**")
        st.markdown(f"<div class='card-range'>{re_:,.0f}</div>", unsafe_allow_html=True)
        st.caption(
            "The universe rent and rent burden are measured against, out of this "
            "county's total occupied housing units. Rent estimates carry a wider "
            "margin of error where fewer households rent."
        )


def render_card(
    title: str, est: float, low: float, high: float, *,
    caveat: str | None = None,
    rate: tuple[float, float] | None = None, rate_label: str = "of this group",
    alloc_pct: float | None = None, alloc_label: str = "this figure",
    alloc_denominator: str = "",
    alloc_threshold_pct: float | None = None, alloc_is_proxy: bool = False,
    percentile_rank: float | None = None, filter_n: int | None = None,
    state_compare: tuple[float, float, str] | None = None,
    acs1_compare: tuple[float, float] | None = None,
    geo_label: str | None = None, table_id: str | None = None,
    measure_label: str | None = None, unit_suffix: str = "",
) -> None:
    """Neutral-voice card: publishes the estimate, MOE, and CV; never
    recommends. See app_US.py's module docstring, point 3, for the
    de-editorialization direction this implements (sponsor, 2026-08-12).

    `percentile_rank`/`filter_n`: this measure's CV percentile rank among
    the geographies in the CURRENT filter selection -- not a composite
    score (see module docstring point 6 for why no single collapsed score
    is shown here).
    `state_compare`: (state_est, state_moe, state_label), if given, adds a
    county-vs-state significant-difference line (90% confidence, Census
    handbook test) with the nested-geography caveat.
    `acs1_compare`: (acs1_est, acs1_moe), if given and this county has
    ACS 1-year data for this measure, adds a 1-year-vs-5-year precision
    comparison line.

    `geo_label`/`table_id`/`measure_label`: feed the publishable-sentence
    generator inside "Show me the statistics" (pressure-tested against
    acs-user-needs-and-functions.pptx, 2026-08-30 -- planners'/journalists'/
    community groups' footnote need, slides 4, 7, 10, 14). No sentence is
    generated when `geo_label` is omitted -- the two call sites that render
    a card without a real interval (no-MOE population, top-coded income)
    don't pass one.     `measure_label` overrides `title` in the sentence only,
    for call sites (the two BANDS loops) where the visible card title
    ("Under 5") is ambiguous out of context.
    `unit_suffix`: appended to every formatted number on the card (e.g.
    "%" for rent burden, which the Census Bureau publishes as a rate
    itself, not a count -- distinct from `rate`/`rate_label` above, which
    add a SECOND, derived rate line onto a count-based card).
    """
    if alloc_pct is not None and not alloc_denominator:
        raise ValueError("alloc_denominator is required whenever alloc_pct is given")
    cv = cv_from_range(est, low, high)
    display_low = max(0.0, low)

    rate_line = ""
    rate_lo = rate_hi = None
    if rate is not None:
        pct, pct_moe = rate
        rate_lo, rate_hi = max(0.0, pct - pct_moe), min(100.0, pct + pct_moe)
        rate_line = (
            f"<div class='card-rate'>{pct:.1f}% {rate_label} "
            f"({CONFIDENCE_LEVEL_PCT}% CI: {rate_lo:.1f}%&ndash;{rate_hi:.1f}%)</div>"
        )

    alloc_line = ""
    if alloc_pct is not None:
        alloc_flagged = alloc_threshold_pct is not None and alloc_pct > alloc_threshold_pct
        if alloc_flagged:
            proxy_note = " (a family-income proxy, not measured person by person)" if alloc_is_proxy else ""
            alloc_line = (
                f"<div class='card-alloc'>{alloc_pct:.0f}% of {alloc_label} "
                f"were filled in by the Census Bureau rather than reported{proxy_note} -- "
                f"a share of {alloc_denominator}. The margin of error above does not "
                f"account for this.</div>"
            )

    # CV badge, not a separate "range: X-Y | 90% CI" line -- the range is
    # still visible in the distribution bar just below and the full
    # breakdown in "Show me the statistics"; on the card face itself the
    # estimate and CV are the two numbers that matter, so they sit on one
    # row together (2026-08-30, per sponsor/user feedback that the range
    # line was redundant clutter). Badge is tinted with the SAME
    # cv_color() ramp the map and distribution bar use, so its color
    # means the same thing everywhere in the app, not a new signal.
    cv_badge = ""
    if not np.isnan(cv):
        r, g, b, _ = cv_color(cv, alpha=255)
        cv_badge = (
            f"<span class='card-cv-badge' style='background: rgba({r},{g},{b},0.16); "
            f"border-left: 3px solid rgb({r},{g},{b});'>CV {cv * 100:.1f}%</span>"
        )
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.markdown(
            f"<div class='card-main-row'>"
            f"<span class='card-range'>{est:,.0f}{unit_suffix}</span>"
            + cv_badge +
            f"</div>"
            + rate_line + alloc_line,
            unsafe_allow_html=True,
        )
        if not np.isnan(cv):
            st.pyplot(_distribution_fig(est, low, high, cv), clear_figure=True)
        if caveat:
            st.caption(caveat)
        if low < 0:
            st.caption(
                f"The margin of error above the estimate exceeds the estimate itself -- "
                f"the true lower bound is {low:,.0f}{unit_suffix}, shown here as 0 since a "
                f"negative count cannot be cited."
            )
        if percentile_rank is not None and filter_n:
            st.markdown(
                f"<div class='card-rank'>CV percentile rank: {_ordinal(percentile_rank)} of "
                f"{filter_n:,} counties in the current filter selection "
                f"(higher percentile = higher CV)</div>",
                unsafe_allow_html=True,
            )
        if state_compare is not None:
            state_est, state_moe, state_label = state_compare
            sig = difference_is_significant(est, high - est, state_est, state_moe)
            if not np.isnan(sig):
                verb = "differs from" if sig else "is not distinguishable from"
                st.caption(
                    f"This county's estimate {verb} {state_label}'s ({state_est:,.0f}) "
                    f"at {CONFIDENCE_LEVEL_PCT}% confidence. This test treats the two "
                    f"estimates as independent; a county's estimate is part of its "
                    f"state's, so it is conservative -- a real difference could be "
                    f"significant even when this test says no."
                )
        if acs1_compare is not None:
            acs1_est, acs1_moe = acs1_compare
            acs1_lo, acs1_hi = acs_range(acs1_est, acs1_moe)
            st.caption(
                f"ACS 1-year estimate for the same variable: {acs1_est:,.0f} "
                f"({CONFIDENCE_LEVEL_PCT}% CI: {max(0.0, acs1_lo):,.0f}&ndash;{acs1_hi:,.0f}). "
                f"The 1-year and 5-year products describe different periods (one year vs. "
                f"a five-year average); this compares their PRECISION, not a change over time."
            )
        with st.expander("Show me the statistics"):
            rows = [
                ("Estimate", f"{est:,.0f}{unit_suffix}"),
                (f"{CONFIDENCE_LEVEL_PCT}% CI", f"{display_low:,.0f}{unit_suffix} – {high:,.0f}{unit_suffix}"),
                ("± margin of error", f"± {(high - low) / 2:,.0f}{unit_suffix}"),
                ("Coefficient of variation (CV)", f"{cv * 100:.1f}%" if cv == cv else "n/a"),
            ]
            if low < 0:
                rows.append(("True CI lower bound (unclamped)", f"{low:,.0f}{unit_suffix} – {high:,.0f}{unit_suffix}"))
            note = (
                f"CV = (margin of error / {1.645:.3f}) / estimate -- the margin of error's "
                f"share of the estimate. ACS margins of error are published at "
                f"{CONFIDENCE_LEVEL_PCT}% confidence."
            )
            if rate is not None:
                pct, pct_moe = rate
                rows += [
                    ("Rate (estimate)", f"{pct:.1f}%"),
                    (f"Rate {CONFIDENCE_LEVEL_PCT}% CI", f"{rate_lo:.1f}% – {rate_hi:.1f}%"),
                ]
                note += (
                    " Rate uses the Census ratio-MOE formula against the true "
                    "poverty-universe denominator, not total population."
                )
            if alloc_pct is not None:
                rows.append(("Share imputed (allocated)", f"{alloc_pct:.1f}%" + (" [proxy]" if alloc_is_proxy else "")))
                rows.append(("Share of", alloc_denominator))
                if alloc_threshold_pct is not None:
                    rows.append(("Nationwide flag line (75th pct., this denominator)", f"{alloc_threshold_pct:.1f}%"))
                note += (
                    " Allocation is a separate signal from CV -- a county can have a low "
                    "CV and still have most of this figure imputed."
                )
            _stats_panel(rows, note)

            if geo_label:
                sentence = (
                    f"{geo_label}'s {(measure_label or title).lower()} was {est:,.0f}{unit_suffix} "
                    f"({CONFIDENCE_LEVEL_PCT}% CI: {display_low:,.0f}{unit_suffix}-{high:,.0f}{unit_suffix}"
                    + (f", CV {cv * 100:.1f}%" if not np.isnan(cv) else "")
                    + f") per the U.S. Census Bureau's {ACS_VINTAGE} American Community "
                    f"Survey"
                    + (f", Table {table_id}" if table_id else "")
                    + "."
                )
                st.caption("Publishable sentence, for a footnote or citation:")
                st.code(sentence, language=None)


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

PEER_BORDER_COLOR = [136, 34, 196, 255]  # saturated violet -- outside the blue/orange CV ramp, so
                                          # a peer border never reads as a CV signal (statistical
                                          # peer counties, 2026-08-30)


def render_map(
    level: str, keys_in_scope: list[str], cv_by_key: dict, title: str, *,
    selected_key: str | None = None,
    quadrant_by_key: dict | None = None,
    color_map: dict[str, str] | None = None,
    legend_order: tuple[str, ...] | None = None,
    peer_keys: set[str] | None = None,
    view_state: pdk.ViewState,
) -> str | None:
    """GeoJsonLayer choropleth, pickable directly (no separate click grid
    -- see module docstring, point 1). Selects a SUBSET of the prebuilt
    feature list (_base_geojson, cached once per level) rather than
    re-serializing geometry; this is what makes filtering cheap.

    `peer_keys`: counties statistically tied to the selected county on
    whichever measure the peer panel has chosen (render_peer_panel()) --
    drawn with a violet border, a third state alongside "selected" and
    "plain," never overriding the fill color, which stays keyed to
    `cv_by_key`/CV regardless of peer status.
    """
    key_col = "county_key" if level == "county" else "state_key"
    scope_set = set(keys_in_scope)
    peer_keys = peer_keys or set()
    features = []
    for feat in _base_geojson(level):
        key = feat["properties"][key_col]
        if key not in scope_set:
            continue
        feat = {**feat, "properties": dict(feat["properties"])}
        if quadrant_by_key is not None:
            label = quadrant_by_key.get(key, "No data")
            rgba = _hex_to_rgba(color_map.get(label, color_map["No data"]))
        else:
            rgba = cv_color(cv_by_key.get(key, float("nan")))
        feat["properties"]["fill_color"] = rgba
        if key == selected_key:
            feat["properties"]["border_width"] = 3
            feat["properties"]["border_color"] = [20, 20, 20, 255]
        elif key in peer_keys:
            feat["properties"]["border_width"] = 2
            feat["properties"]["border_color"] = PEER_BORDER_COLOR
        else:
            feat["properties"]["border_width"] = 1
            feat["properties"]["border_color"] = [255, 255, 255, 200]
        features.append(feat)
    geojson = {"type": "FeatureCollection", "features": features}

    fill_layer = pdk.Layer(
        "GeoJsonLayer",
        geojson,
        id="geo-fill",
        opacity=0.78,
        stroked=True,
        filled=True,
        get_fill_color="properties.fill_color",
        get_line_color="properties.border_color",
        get_line_width="properties.border_width",
        line_width_min_pixels=1,
        # Confirmed live 2026-08-12: GeoJsonLayer clicks reach on_select
        # correctly in Streamlit 1.60.0 / pydeck 0.9.1 -- no separate
        # invisible click layer needed (contrast app_NJ.py's _click_grid).
        pickable=True,
        auto_highlight=True,
    )
    st.caption(title)
    event = st.pydeck_chart(
        pdk.Deck(
            layers=[fill_layer], initial_view_state=view_state,
            map_provider="carto", map_style="light",
        ),
        height=520,
        width="stretch",
        on_select="rerun",
        selection_mode="single-object",
        key=f"geo_map_{level}",
    )
    if quadrant_by_key is not None:
        legend = " &nbsp;&nbsp; ".join(
            f"<span class='legend-swatch' style='background:{color_map[label]};'></span>"
            f"<span class='legend-label'>{label}</span>"
            for label in legend_order
        )
        st.markdown(legend, unsafe_allow_html=True)
    else:
        # Continuous colorbar legend, not tier swatches -- "a scale, not a
        # verdict" (sponsor direction). Range shown, not labels like
        # Good/Fair/Poor.
        swatches = "".join(
            f"<span style='display:inline-block;width:14px;height:11px;"
            f"background:rgba({r},{g},{b},{a});'></span>"
            for r, g, b, a in [cv_color(t) for t in np.linspace(0, 0.5, 12)]
        )
        st.markdown(
            f"<div>{swatches}</div><span class='legend-label'>CV 0% "
            f"&nbsp;&mdash;&nbsp; scale &nbsp;&mdash;&nbsp; CV 50%+ "
            f"(blue = lower CV, orange = higher CV, i.e. a larger margin of error "
            f"relative to the estimate)</span>",
            unsafe_allow_html=True,
        )
        if peer_keys:
            r, g, b, _ = PEER_BORDER_COLOR
            st.markdown(
                f"<span style='display:inline-block;width:14px;height:11px;"
                f"border:2px solid rgb({r},{g},{b});'></span> "
                f"<span class='legend-label'>statistical peer on the measure chosen below "
                f"(fill color is still CV)</span>",
                unsafe_allow_html=True,
            )
    st.caption("Click a state or county to inspect it below, or use the search box in the filter panel above.")

    objs = []
    if event and event.get("selection"):
        objs = event["selection"].get("objects", {}).get("geo-fill", [])
    return objs[0].get("properties", {}).get(key_col) if objs else None


# ---------------------------------------------------------------------------
# View state -- fixes app_NJ.py's total_bounds-midpoint approach, which
# breaks at national scale: the Aleutian Islands cross the antimeridian
# (confirmed live 2026-08-12: nationwide county bounds span -179.15 to
# 179.78 degrees longitude), so a naive midpoint lands in the Pacific.
# ---------------------------------------------------------------------------

NATIONAL_VIEW = pdk.ViewState(latitude=39.5, longitude=-98.5, zoom=3.3, pitch=0)


def _state_view(geo_gdf) -> pdk.ViewState:
    """Bounds-based view for ONE state's counties. Handles the antimeridian
    case (Alaska's Aleutians West Census Area spans ~172E to ~163W -- part
    of why nationwide county bounds were confirmed live to span -179.15 to
    179.78 degrees longitude) by shifting negative longitudes into 0-360
    space before averaging whenever the combined span suggests a crossing,
    then un-shifting the result. A plain total_bounds midpoint would put
    the center in the Pacific for that one borough, same failure as the
    national case above.
    """
    bounds = geo_gdf.geometry.bounds  # minx, miny, maxx, maxy per row
    minx, maxx = bounds["minx"], bounds["maxx"]
    crosses = (maxx.max() - minx.min()) > 180
    if crosses:
        minx_s = minx.where(minx >= 0, minx + 360)
        maxx_s = maxx.where(maxx >= 0, maxx + 360)
        cx = (minx_s.min() + maxx_s.max()) / 2
        cx = cx - 360 if cx > 180 else cx
        lon_span = maxx_s.max() - minx_s.min()
    else:
        cx = (minx.min() + maxx.max()) / 2
        lon_span = maxx.max() - minx.min()
    cy = (bounds["miny"].min() + bounds["maxy"].max()) / 2
    lat_span = bounds["maxy"].max() - bounds["miny"].min()
    span = max(lon_span, lat_span, 0.5)
    zoom = max(3.5, min(9.0, 8.5 - np.log2(span)))
    return pdk.ViewState(latitude=cy, longitude=cx, zoom=zoom, pitch=0)


# ---------------------------------------------------------------------------
# Geography selection state -- same pattern as app_NJ.py (one session_state
# dict, two writers: map click and the top-of-page geography search).
# ---------------------------------------------------------------------------

def _init_geo_state() -> None:
    # peer_focus (statistical peer counties, 2026-08-30): three writers --
    # the "Show these counties on the map" / "Exit peer view" buttons in
    # render_peer_panel(), the "Back to national state view" button above
    # (clears it), and the state-click handler below (clears it, since a
    # freshly-drilled-into state has no county selected yet to have peers).
    st.session_state.setdefault(
        "us_geo", {"level": "state", "code": None, "state_scope": None, "peer_focus": False}
    )
    st.session_state.setdefault("_us_geo_version", 0)


def geography_search_control(search_slot, data: dict, level: str, filtered_county_df: pd.DataFrame) -> None:
    """Renders into `search_slot` (a container reserved inside the
    top-of-page filter panel by top_filters, see its docstring) rather
    than the sidebar (change B, 2026-08-18) -- still called from main()
    AFTER the map/click handling below, not from inside top_filters
    itself, so this dropdown's seed value reflects a map click made
    earlier in the SAME rerun rather than lagging one click behind.
    """
    geo = st.session_state["us_geo"]
    if level == "state":
        opts_df = data["state_df"]
        labels_lookup = data["labels_state"]
    elif geo["state_scope"]:
        opts_df = children_of("county", geo["state_scope"], filtered_county_df, specs=US_LEVEL_SPECS)
        labels_lookup = data["labels_county"]
    else:
        opts_df = filtered_county_df
        labels_lookup = data["labels_county"]

    keys = opts_df["_key"]
    by_label = sorted({labels_lookup.get(k, k): k for k in keys}.items())
    display_labels = [lbl for lbl, _ in by_label] or ["(no counties match the current filters)"]
    key_by_label = dict(by_label)

    dropdown_key = f"us_geo_dropdown_{level}_{geo['state_scope'] or 'all'}_{st.session_state['_us_geo_version']}"
    if dropdown_key not in st.session_state:
        seed = labels_lookup.get(geo["code"])
        st.session_state[dropdown_key] = seed if seed in display_labels else display_labels[0]
    choice = search_slot.selectbox("Search for a geography", display_labels, key=dropdown_key)
    chosen_key = key_by_label.get(choice)
    if chosen_key and chosen_key != geo["code"]:
        geo["code"] = chosen_key


# ---------------------------------------------------------------------------
# Welcome tab (change G, 2026-08-18) -- plain-language orientation, no
# statistics background assumed. First tab, selected by default (st.tabs'
# own behavior -- the first tab passed to it is the initial selection).
# Every term gets a one-line definition on first use, per CLAUDE.md, same
# rule _term() enforces on Streamlit/pages/1_Whose_data_is_this.py.
# ---------------------------------------------------------------------------

def render_welcome() -> None:
    st.markdown("### Welcome")
    st.markdown(
        """
This tool shows population, income, poverty, housing, health insurance,
language, and transportation figures for every county in the United
States, pulled from the Census Bureau's **American Community Survey
(ACS)** -- an ongoing national survey, not a full head count like the
once-a-decade Census. Because ACS only surveys a *sample* of households,
every number it publishes comes with a **margin of error (MOE)**: a
measured range around the estimate that reflects how much the number could
shift if a different sample of households had been surveyed. A number with
a wide margin of error is less certain than one with a narrow margin, even
if both are labeled "the estimate" -- that uncertainty is real and
published by the Bureau itself, not something this app adds on top.

**How to use the app**

Open the "County explorer" tab above to get started. A collapsible
**"Filter counties"** panel sits at the top of that tab, with:

- **Metro / nonmetro** -- narrows counties to the U.S. Department of
  Agriculture's rural-urban classification (metro area vs. not).
- **Population size** -- narrows counties to a population-size bracket.
- **Search for a geography** -- jump straight to a state or county by name.
- **Back to national state view** -- returns from a county back to the
  full-country state map.

Below the filter panel is a **map** you can click: click a state to see its
counties, then click a county to see its statistics below the map. The
"Color the map by" dropdown changes which measure the map's colors
represent.

**Choose what you want to see**

Once you've picked a county, a **checklist** lets you choose which figures
to show -- it starts with just two (total population and median household
income) rather than every figure at once, on purpose: with roughly twenty
measures now available across seven topics, showing all of them
unconditionally would bury the two or three numbers you actually came for.
Add topics as you need them -- income brackets, health insurance, language,
housing costs, or transportation -- and remove any you don't. Every card
shows its estimate in bold, with the confidence range and other detail
underneath, and a "Show me the statistics" section with the full numeric
breakdown and a ready-to-copy citation sentence for footnotes.

**Find your starting point**

- *I need a poverty figure I can cite in a grant application* -- check a
  "Poverty: [age band]" card. The rate line and its confidence interval are
  built for exactly this; open "Show me the statistics" for a copyable
  citation sentence.
- *I want to know whether my county really differs from the state* -- the
  Total population and Median household income cards include a
  county-vs-state comparison line automatically; no other card computes
  this yet.
- *I need to know if a number is too imprecise to use* -- look at its CV
  and confidence interval before you cite it (see below). A wide interval
  relative to the estimate is a real signal from the Bureau, not a flaw in
  this tool.
- *I want a single derived rate, not a raw count* -- Rent burden (rent as a
  percent of income) is the Bureau's own published rate, not something
  computed here by dividing two medians (see below for why that matters).
  Uninsured, limited-English, and no-vehicle cards also show a rate line
  alongside their raw count.
- *I need to know whether my county is really different from the ones
  that got funded* -- scroll to **"Statistical peers"** below the cards
  and pick a measure. It finds every county whose estimate is
  statistically indistinguishable from yours at 90% confidence, rather
  than a ranked "most similar" list -- see below for why a ranking isn't
  something a margin of error can support.

**How to read the reliability indicators**

- **Coefficient of variation (CV)** is the margin of error's share of the
  estimate -- a single number that says how big the uncertainty is
  *relative to* the estimate itself, so a \\$500 margin of error means very
  different things for a \\$10,000 estimate versus a \\$500,000 one. Both the
  map and each card's uncertainty bar use the same color scale: **blue for
  a lower CV (more certain), orange for a higher CV (less certain)**. This
  is a continuous scale, not a pass/fail grade -- there is no "safe" or
  "risky" cutoff built into the color itself.
- The **90% confidence interval** shown on every card is the range the
  Census Bureau itself publishes: if the same survey were repeated many
  times, about 90% of the resulting ranges would contain the true value.
- The **CV percentile rank** on a card tells you where that county's
  uncertainty falls compared to every other county in your current filter
  selection -- a higher percentile means a higher (worse) CV relative to
  its peers.
- A **share imputed (allocated)** line, when shown, means the Census
  Bureau filled in that portion of the figure because a household didn't
  report it -- a separate signal from CV, describing how much of the
  underlying data was inferred rather than answered directly.
- Some cards -- poverty, uninsured, limited-English, no-vehicle, income
  brackets -- also show a **derived rate**: a percentage computed FROM two
  Bureau numbers (a count and its universe), each with its own sampling
  error. That rate carries its own separately-computed margin of error,
  not the raw count's margin -- a rate is not automatically as precise as
  the count it came from. **Rent burden** is different: it is the Bureau's
  *own* published rate, not one computed here. Dividing median rent by
  median income by hand would NOT give the same answer -- the median of a
  ratio is not the ratio of two medians -- which is exactly why the Bureau
  publishes rent burden as its own measure rather than leaving users to
  compute it themselves.
- The **statistical peers** panel's tie-set size is itself a reliability
  signal, not just a list: a SMALL tie set means this measure is sharp
  enough to separate your county from similar ones; a LARGE tie set means
  the measure can't distinguish your county from its structural peers at
  this precision -- that's information about the measure at this
  county's size, not a defect in this tool. The counties inside a tie set
  are never ranked, because the margin of error doesn't support ranking
  them against each other.

**Where this stops working**

- This app stops at the **county** level. It cannot answer a
  neighborhood-scale question -- a county's numbers can mask very
  different conditions in different parts of that county.
- Every figure is a single **2020-2024, 5-year** estimate. There is no
  year-over-year trend here, so this app cannot tell you whether a number
  is rising, falling, or holding steady.
- The newer measures (health insurance, rent, language, vehicles, income
  brackets) cover smaller populations than total population or median
  income, so expect **visibly wider margins of error** on them, especially
  in small counties -- that is the data being honest about a smaller
  sample, not a defect in this tool.
        """
    )


# ---------------------------------------------------------------------------
# Statistical peer counties panel (2026-08-30)
# ---------------------------------------------------------------------------

def render_peer_panel(data: dict, geo: dict, code: str, label: str) -> None:
    """Which counties are, on one chosen measure, statistically
    indistinguishable from `label` at 90% confidence -- pressure-tested
    against a grant-writing use case: a county with (say) an 18% poverty
    rate doesn't need a list of counties near 18%, any spreadsheet does
    that, and the ORDER inside such a list is noise the margin of error
    doesn't support. What it can't get anywhere else is the answer to
    "which counties could a funder legitimately treat as different from
    mine?" -- so the headline here is the TIE-SET SIZE, not a ranking.
    See statistical_peers() in analysis/dashboard.py for the underlying
    test and why county-vs-county comparisons don't carry that function's
    nested-geography caveat.

    The measure selectbox and two checkboxes defined here are also read
    SPECULATIVELY, by key, near the top of render_explorer() -- before
    the map is drawn -- so the same peer set can highlight map borders
    and drive peer_focus mode. This function is the only place that
    actually CREATES those widgets; the early read just peeks at last
    render's value, the same trick geography_search_control() uses for
    its dropdown seed. Recomputing here (rather than threading the early
    result through as a parameter) keeps the two call sites independent
    at the cost of one extra pass over a pool of at most ~3,143 rows,
    which is cheap next to the per-render map/filter work this app
    already does at that scale.
    """
    st.divider()
    st.markdown("##### Statistical peers")
    st.caption(
        "Peers are drawn from all U.S. counties (optionally narrowed by the checkboxes "
        "below), not the map filters above -- those exist to narrow the MAP, and reusing "
        "them here would make the peer count depend on a control set for an unrelated reason."
    )
    measure_col, rucc_col, pop_col = st.columns([2, 1, 1])
    with measure_col:
        peer_measure = st.selectbox(
            "Find counties statistically tied to this one on...", PEER_MEASURES,
            index=None, format_func=_measure_display, key="peer_measure",
            placeholder="Choose a measure to find statistical peers",
        )
    with rucc_col:
        same_rucc = st.checkbox("Same metro/nonmetro class", value=True, key="peer_same_rucc")
    with pop_col:
        same_popbin = st.checkbox("Same population-size bin", value=True, key="peer_same_popbin")

    if not peer_measure:
        st.info("Choose a measure above to find this county's statistical peers.")
        return

    result = _compute_peers(data["county_df"], code, peer_measure, same_rucc, same_popbin)
    if result is None or pd.isna(result.self_est) or pd.isna(result.self_moe):
        st.caption(
            f"{label}'s estimate for {_measure_display(peer_measure)} is not available, or has "
            "no published margin of error, so no peer comparison can be run for it."
        )
        return

    st.caption(
        f"Pool: {result.pool_n:,} structurally comparable counties "
        f"({result.dropped_n:,} dropped for a missing estimate or margin of error)."
    )

    n_tied = len(result.peers)
    if n_tied == 0:
        st.success(
            f"No counties in this pool are statistically indistinguishable from {label}'s "
            f"estimate at {CONFIDENCE_LEVEL_PCT}% confidence -- this measure separates {label} "
            "sharply from its structural peers."
        )
    else:
        pct = n_tied / result.tested_n * 100 if result.tested_n else float("nan")
        st.markdown(
            f"**{n_tied:,} of {result.tested_n:,} testable counties ({pct:.0f}%) are "
            f"statistically indistinguishable from {label}** on "
            f"{_measure_display(peer_measure)} at {CONFIDENCE_LEVEL_PCT}% confidence."
        )
    st.caption(
        f"{result.n_higher:,} counties are significantly higher, "
        f"{result.n_lower:,} are significantly lower."
    )

    if n_tied:
        labels_lookup = data["labels_county"]
        table = result.peers.copy()
        table["County"] = [labels_lookup.get(k, k) for k in table.index]
        table["Distance"] = (table["est"] - result.self_est).abs()
        table = table.sort_values("Distance")
        display = table[["County", "est", "moe"]].rename(
            columns={"est": "Estimate", "moe": f"\u00b1 margin of error ({CONFIDENCE_LEVEL_PCT}% CI)"}
        )
        st.dataframe(display, hide_index=True, width="stretch")
        st.caption(
            "Ordered by distance for readability only -- the order is not meaningful. Every "
            "county listed is statistically indistinguishable from yours; none is \"more\" or "
            "\"less\" similar in a way this test can support."
        )

    focus_col1, focus_col2 = st.columns(2)
    with focus_col1:
        if st.button("Show these counties on the map", disabled=n_tied == 0, key="peer_focus_on"):
            geo["state_scope"] = None
            geo["peer_focus"] = True
            st.rerun()
    with focus_col2:
        if geo.get("peer_focus") and st.button("Exit peer view, back to state map", key="peer_focus_off"):
            geo["peer_focus"] = False
            st.rerun()


# ---------------------------------------------------------------------------
# County explorer -- map, filters, and per-county cards. This was the
# entire main() body before change G (2026-08-18) moved it under its own
# tab so a first-time visitor lands on Welcome instead.
# ---------------------------------------------------------------------------

def render_explorer(data: dict) -> None:
    _init_geo_state()
    geo = st.session_state["us_geo"]
    level = geo["level"]

    filtered_county_df, search_slot = top_filters(data["county_df"], level, geo)

    # Statistical peers (2026-08-30) -- computed here, BEFORE geo_df/the
    # map, from session_state values keyed to the peer-panel widgets that
    # are actually CREATED later in this function, once a county is
    # selected and the panel renders below the cards. Peeking at a
    # not-yet-drawn widget's already-set session_state value is the same
    # trick geography_search_control()'s dropdown seed relies on (that
    # dropdown's seed depends on a map click made earlier in the SAME
    # rerun; this depends on a widget drawn LATER in the same rerun, using
    # ITS value from the PREVIOUS rerun -- either way, nothing here writes
    # session_state, so there is no conflict with the actual widget
    # creation in render_peer_panel()). Before that panel has ever been
    # used, these keys don't exist yet and .get() below returns "no peers"
    # -- peers are off by default.
    code_peek = geo["code"]
    peer_result: PeerResult | None = None
    if level == "county" and code_peek:
        peeked_measure = st.session_state.get("peer_measure")
        if peeked_measure:
            peer_result = _compute_peers(
                data["county_df"], code_peek, peeked_measure,
                st.session_state.get("peer_same_rucc", True),
                st.session_state.get("peer_same_popbin", True),
            )
    peer_keys = set(peer_result.peers.index) if peer_result is not None else set()

    if level == "county" and geo.get("peer_focus") and peer_keys:
        # Restricted to selected + peers, from the FULL county table, not
        # filtered_county_df -- the peer set was already gated by its own
        # structural checkboxes, not the unrelated top-of-page filters, so
        # this view should show exactly what the panel just promised.
        subset_keys = {code_peek} | peer_keys
        geo_df = data["county_df"][data["county_df"]["_key"].isin(subset_keys)]
        geo_gdf = data["county_geo"][geo_key(data["county_geo"], "county", specs=US_LEVEL_SPECS).isin(subset_keys)]
        view = _state_view(geo_gdf) if len(geo_gdf) else NATIONAL_VIEW
    elif level == "county" and geo["state_scope"]:
        geo_df = children_of("county", geo["state_scope"], filtered_county_df, specs=US_LEVEL_SPECS)
        geo_gdf = data["county_geo"][geo_key(data["county_geo"], "county", specs=US_LEVEL_SPECS).isin(set(geo_df["_key"]))]
        view = _state_view(geo_gdf) if len(geo_gdf) else NATIONAL_VIEW
    elif level == "county":
        geo_df = filtered_county_df
        geo_gdf = data["county_geo"]
        view = NATIONAL_VIEW
    else:
        geo_df = data["state_df"]
        geo_gdf = data["state_geo"]
        view = NATIONAL_VIEW

    st.markdown("##### Map")
    measure = st.selectbox(
        "Color the map by", MEASURE_OPTIONS, key="acs_map_measure",
        format_func=_measure_display,
    )
    if level == "county" and len(geo_df):
        cv_by_key, _, _, _, quadrant_by_key, color_map, legend_order, title = _measure_layer(
            geo_df, measure, data["alloc_county"], data["income_alloc_threshold"]
        )
    elif level == "state" and measure != IMPUTATION_INCOME:
        # State-level ACS estimates are published directly by the API (not
        # derived from counties), so this needs no state-level allocation
        # pull -- imputation is the one measure that does (county-only,
        # see module docstring), so it falls to the else branch below.
        cv_by_key, _, _, _, quadrant_by_key, color_map, legend_order, title = _measure_layer(
            data["state_df"], measure, data["alloc_county"], data["income_alloc_threshold"]
        )
    else:
        cv_by_key, quadrant_by_key, color_map, legend_order, title = {}, None, None, None, (
            "Imputation is shown at county level only -- click a state to see its counties"
            if level == "state" else "No counties match the current filters"
        )

    if len(geo_df):
        picked = render_map(
            level, geo_df["_key"].tolist(), cv_by_key, title,
            selected_key=geo["code"], quadrant_by_key=quadrant_by_key,
            color_map=color_map, legend_order=legend_order, view_state=view,
            peer_keys=peer_keys,
        )
    else:
        st.info("No geographies match the current filter selection. Loosen a filter in the panel above.")
        picked = None

    if picked and picked != st.session_state.get("_us_map_last_picked"):
        st.session_state["_us_map_last_picked"] = picked
        if level == "state":
            geo.update(level="county", code=None, state_scope=picked, peer_focus=False)
        else:
            geo["code"] = picked
        st.session_state["_us_geo_version"] += 1

    geography_search_control(search_slot, data, geo["level"], filtered_county_df)
    st.divider()

    level = geo["level"]  # may have just changed via the state click above
    code = geo["code"]
    if not code:
        st.info("Select a geography from the map, or search in the filter panel above, to see its statistics.")
        return

    labels_lookup = data["labels_state"] if level == "state" else data["labels_county"]
    label = labels_lookup.get(code, code)

    if level == "state":
        st.subheader(f"{label} -- select a county to see American Community Survey estimates")
        return

    row = filtered_county_df[filtered_county_df["_key"] == code]
    if row.empty:
        row = data["county_df"][data["county_df"]["_key"] == code]
    if row.empty:
        st.warning("This county isn't in the current data. Search for it in the filter panel above.")
        return

    state_row = data["state_df"][data["state_df"]["_key"] == row["STATE"].iloc[0]]

    # Percentile rank must come from THIS card's own measure's CV
    # distribution across the filtered county set, NOT whatever measure
    # happens to be selected for map coloring -- computed once per measure
    # actually shown below (population, income, each age band, each
    # poverty band), each a cheap call on at most 254 rows (one state).
    def _cv_series_for(measure_name: str) -> pd.Series:
        if not len(geo_df):
            return pd.Series(dtype=float)
        result = _measure_layer(geo_df, measure_name, data["alloc_county"], data["income_alloc_threshold"])
        return pd.Series(result[0])

    def _rank_and_n(measure_name: str, key: str) -> tuple[float | None, int]:
        series = _cv_series_for(measure_name)
        n = int(series.notna().sum())
        if key not in series.index or series.dropna().empty:
            return None, n
        return float(series.rank(pct=True)[key] * 100), n

    st.subheader(f"{label} -- American Community Survey ({ACS_VINTAGE})")
    st.info(
        "ACS surveys a *sample* of households, not everyone. Every number below ships "
        "with a real, measured margin of error -- the range comes directly from the "
        "Census Bureau, not a model."
    )

    acs1_county = _load_acs1_county()
    acs1_row = acs1_county[acs1_county["_key"] == code]

    def _render_measure_card(measure_label: str) -> None:
        """Generic card render for any MEASURES-registry entry except
        Total population and Median household income (hand-written below
        for their extra state/ACS-1yr/allocation wiring). Mirrors the
        no-MOE guard the age-band and poverty-band loops already used,
        plus a NaN-ESTIMATE guard those loops never needed -- population
        and income never suppress their estimate; median rent and rent
        burden do, in counties with too few renters for the Census
        Bureau to publish a median. Three mutually exclusive branches,
        each its own bordered container -- never nested inside another.
        """
        measure = MEASURES[measure_label]
        est_s, moe_s = measure.values(row)
        e, m = float(est_s.iloc[0]), float(moe_s.iloc[0])

        if pd.isna(e):
            with st.container(border=True):
                st.markdown(f"**{measure.label}**")
                st.caption(
                    "The Census Bureau suppressed this estimate for this county -- usually "
                    "because too few sampled households fall in the relevant category."
                )
            return

        if pd.isna(m):
            with st.container(border=True):
                st.markdown(f"**{measure.label}**")
                st.markdown(
                    f"<div class='card-range'>{e:,.0f}{measure.unit_suffix}</div>",
                    unsafe_allow_html=True,
                )
                st.caption("No margin of error published for this figure.")
            return

        rate = None
        if measure.universe is not None:
            univ_est_s, univ_moe_s = measure.universe(row)
            ue, um = float(univ_est_s.iloc[0]), float(univ_moe_s.iloc[0])
            rate = proportion_rate(e, m, ue, um)

        rank, n = _rank_and_n(measure_label, code)
        render_card(
            measure.label, e, *acs_range(e, m),
            rate=rate, rate_label=measure.rate_label,
            percentile_rank=rank, filter_n=n,
            geo_label=label, table_id=measure.table_id,
            measure_label=measure.measure_label, unit_suffix=measure.unit_suffix,
        )

    # Card checklist (variable expansion, 2026-08-30 -- MSBA capstone) --
    # every county now has ~19 selectable measures; rendering all of them
    # unconditionally would be the "too much data, too hard to use" wall
    # of cards this was built to avoid. Starts with just the two headline
    # figures; everything else is opt-in. format_func changes only the
    # DISPLAYED option text -- st.multiselect still returns bare MEASURES
    # keys, so nothing downstream needs to know about the topic prefix.
    st.markdown("##### Choose what to show")
    selected_labels = st.multiselect(
        "Cards to display for this county",
        options=list(MEASURES),
        default=list(DEFAULT_CARD_LABELS),
        format_func=_measure_display,
        key="card_checklist",
        help="Starts with two so this page isn't a wall of cards -- add topics "
             "(income brackets, health, language, rent, transportation) as you need them.",
    )

    # Total population and Median household income side by side -- two
    # top-level headline figures for the county, so they share a row
    # instead of stacking full-width one above the other. Still
    # hand-written, not routed through _render_measure_card(), for their
    # state-compare/ACS-1yr/allocation-panel wiring the generic path
    # doesn't have.
    pop_selected = "Total population" in selected_labels
    income_selected = "Median household income" in selected_labels
    if pop_selected or income_selected:
        pop_col, income_col = st.columns(2, gap="medium")

        if pop_selected:
            with pop_col:
                pop_est = float(row["B01001_001E"].iloc[0])
                pop_moe = float(row["B01001_001M"].iloc[0])
                if pd.isna(pop_moe):
                    with st.container(border=True):
                        st.markdown("**Total population**")
                        st.markdown(f"<div class='card-range'>{pop_est:,.0f}</div>", unsafe_allow_html=True)
                        st.caption(
                            "The Census Bureau published no margin of error for this figure -- this "
                            "usually means the estimate is calibrated to independent population controls."
                        )
                else:
                    pop_low, pop_high = acs_range(pop_est, pop_moe)
                    state_pop = state_row["B01001_001E"].iloc[0] if len(state_row) else None
                    state_pop_moe = state_row["B01001_001M"].iloc[0] if len(state_row) else None
                    acs1_pop = (float(acs1_row["B01001_001E"].iloc[0]), float(acs1_row["B01001_001M"].iloc[0])) if len(acs1_row) else None
                    pop_rank, pop_n = _rank_and_n("Total population", code)
                    render_card(
                        "Total population", pop_est, pop_low, pop_high,
                        percentile_rank=pop_rank, filter_n=pop_n,
                        state_compare=(float(state_pop), float(state_pop_moe), f"{census_region(row['STATE'].iloc[0]) or ''} state total".strip())
                        if state_pop is not None and pd.notna(state_pop_moe) else None,
                        acs1_compare=acs1_pop,
                        geo_label=label, table_id="B01001",
                    )
                _population_quality_panel(data["alloc_county"], code)

        if income_selected:
            with income_col:
                if bool(flag_topcoded_income(row).iloc[0]):
                    st.info(
                        f"{label}'s median household income is top-coded at \\$250,001 -- the Census "
                        "Bureau censors values at this cap. Not shown as a range; the true median is "
                        "at least \\$250,001."
                    )
                else:
                    income_est = float(row["B19013_001E"].iloc[0])
                    income_moe = float(row["B19013_001M"].iloc[0])
                    income_alloc = float(
                        data["alloc_county"].set_index("_key")["income_alloc"].get(code, float("nan")) * 100
                    )
                    state_income = state_row["B19013_001E"].iloc[0] if len(state_row) else None
                    state_income_moe = state_row["B19013_001M"].iloc[0] if len(state_row) else None
                    acs1_income = (float(acs1_row["B19013_001E"].iloc[0]), float(acs1_row["B19013_001M"].iloc[0])) if len(acs1_row) else None
                    income_rank, income_n = _rank_and_n(IMPUTATION_INCOME, code)
                    render_card(
                        "Median household income", income_est, *acs_range(income_est, income_moe),
                        alloc_pct=income_alloc, alloc_label="household incomes",
                        alloc_denominator="households reporting any income",
                        alloc_threshold_pct=data["income_alloc_threshold"] * 100,
                        percentile_rank=income_rank, filter_n=income_n,
                        state_compare=(float(state_income), float(state_income_moe), "the state median")
                        if state_income is not None and pd.notna(state_income_moe) and not pd.isna(income_moe) else None,
                        acs1_compare=acs1_income,
                        geo_label=label, table_id="B19013",
                    )

    # Every other selected measure, grouped by topic and chunked into
    # 4-column rows -- replaces the old two hardcoded sections ("Population
    # by age", "Living below the poverty line, by age") with one loop that
    # scales to however many topics a county's selection touches.
    other_labels = [lbl for lbl in selected_labels if lbl not in ("Total population", "Median household income")]
    by_topic: dict[str, list[str]] = {}
    for lbl in other_labels:
        by_topic.setdefault(MEASURES[lbl].topic, []).append(lbl)

    TOPIC_ORDER = ["Population", "Poverty", "Income", "Housing", "Health", "Language", "Transportation"]
    for topic in TOPIC_ORDER:
        labels_here = by_topic.get(topic)
        if not labels_here:
            continue
        st.markdown(f"##### {topic}")
        for i in range(0, len(labels_here), 4):
            chunk = labels_here[i:i + 4]
            cols = st.columns(4, gap="medium")
            for col, lbl in zip(cols, chunk):
                with col:
                    _render_measure_card(lbl)
                    if lbl == "Median gross rent":
                        _rent_context_panel(row)

    render_peer_panel(data, geo, code, label)


# ---------------------------------------------------------------------------
# App entry point -- Welcome tab first and selected by default, County
# explorer second (change G, 2026-08-18).
# ---------------------------------------------------------------------------

def main() -> None:
    st.html(_CSS)
    st.title("US County Demographic Explorer")
    st.caption(
        "American Community Survey estimates and their margins of error, for every "
        "county in the United States. New here? Start with the Welcome tab below."
    )

    data = _load_all()
    welcome_tab, explorer_tab = st.tabs(["Welcome", "County explorer"])
    with welcome_tab:
        render_welcome()
    with explorer_tab:
        render_explorer(data)


if __name__ == "__main__":
    main()
