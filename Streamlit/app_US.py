"""Nationwide county demographic explorer -- state-first drill-down.

Map-first, same interaction model as Streamlit/app_NJ.py: click a state to
see its counties, click a county (or search the sidebar) to read its
American Community Survey estimates and how much uncertainty each one
carries. The layout below intentionally mirrors app_NJ.py's card/map
structure -- see that file's module docstring for the original design.

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
4. Cascading geography filters (region/division/state, RUCC rural-urban
   tier, population-size bin) -- the sponsor's concrete ask. These narrow
   the TYPICAL case; the performance fix above is what makes the
   UNFILTERED default case (a whole state's counties) survivable, since
   filters do nothing for that case.
5. New card content: CV on the face (was expander-only in app_NJ.py),
   explicit 90%-CI bounds, a percentile-rank-within-the-current-filter
   line, a county-vs-state significant-difference check, and (where
   available) an ACS 1-year vs 5-year precision comparison.
6. The composite score question (README "Composite tier philosophy",
   still open for mentors) is NOT resolved by this app. analysis.composite
   has two competing candidate formulas (equal_weight_score,
   worst_component_score) that disagree on ~15% of top-risk-quartile
   membership -- this app surfaces BOTH, labeled as competing candidates
   under mentor review, rather than silently picking one. The one
   unambiguous number (a measure's own CV percentile rank within the
   current filter set) is what drives sorting/filtering.

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
from pathlib import Path

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
    US_LEVEL_SPECS,
    acs_1yr_available_keys,
    acs_poverty,
    acs_poverty_universe,
    acs_range,
    acs_sexage,
    census_division,
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
    load_saipe_county,
    load_us_acs1_county,
    population_size_bin,
    poverty_rate,
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

POVERTY_OPTIONS = [f"Poverty: {b}" for b in BANDS]
IMPUTATION_INCOME = "Imputation: household income"
MEASURE_OPTIONS = ["Total population"] + BANDS + POVERTY_OPTIONS + [IMPUTATION_INCOME]

CONFIDENCE_LEVEL_PCT = 90  # ACS MOEs are 90%-confidence half-widths -- stated explicitly everywhere a range appears


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


_CSS = """
<style>
.card-range  { font-size: clamp(1.15rem, 2.2vw, 1.6rem); font-weight: 700; margin: 2px 0; }
.card-sub    { color: #5A5A5A; font-size: 1.05rem; font-weight: 500; }
.card-cv     { color: #222; font-size: 0.95rem; font-weight: 600; margin-top: 2px; }
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
        region=county_df["STATE"].map(census_region),
        division=county_df["STATE"].map(census_division),
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

    is_poverty = measure in POVERTY_OPTIONS
    if measure == "Total population":
        est, moe = df["B01001_001E"].astype(float), df["B01001_001M"].astype(float)
    elif is_poverty:
        est, moe = acs_poverty(df, measure.removeprefix("Poverty: "), "both")
    else:
        est, moe = acs_sexage(df, measure, "both")
    est = pd.Series(est.to_numpy(dtype=float), index=keys)
    moe = pd.Series(moe.to_numpy(dtype=float), index=keys)

    pct_by_key = None
    if is_poverty:
        univ_est, univ_moe = acs_poverty_universe(df, measure.removeprefix("Poverty: "), "both")
        univ_est = pd.Series(univ_est.to_numpy(dtype=float), index=keys)
        univ_moe = pd.Series(univ_moe.to_numpy(dtype=float), index=keys)
        pct_by_key = {
            k: poverty_rate(e, m, ue, um)[0]
            for k, e, m, ue, um in zip(keys, est, moe, univ_est, univ_moe)
        }

    cv_by_key, est_by_key, range_by_key = {}, {}, {}
    for k, e, m in zip(keys, est, moe):
        est_by_key[k] = e
        if pd.isna(m):
            cv_by_key[k] = float("nan")
            range_by_key[k] = (e, e)
            continue
        lo, hi = acs_range(e, m)
        cv_by_key[k] = cv_from_range(e, lo, hi)
        range_by_key[k] = (max(0.0, lo), hi)
    return cv_by_key, est_by_key, range_by_key, pct_by_key, None, None, None, f"ACS reliability: {measure}"


# ---------------------------------------------------------------------------
# Filter stack
# ---------------------------------------------------------------------------

def sidebar_filters(county_df: pd.DataFrame) -> pd.DataFrame:
    """Cascading region -> division -> state -> RUCC -> population-bin
    filter, showing N remaining at every step. Every selectbox handles a
    filtered-to-zero upstream selection without breaking (e.g. Wyoming has
    zero metro counties -- see the RUCC step below): st.selectbox always
    gets "All" plus whatever OPTIONS REMAIN, never an empty option list.
    """
    st.sidebar.header("Filter counties")
    df = county_df

    region_opts = ["All"] + sorted(df["region"].dropna().unique().tolist())
    region = st.sidebar.selectbox("Census region", region_opts, key="filter_region")
    if region != "All":
        df = df[df["region"] == region]

    division_opts = ["All"] + sorted(df["division"].dropna().unique().tolist())
    division = st.sidebar.selectbox("Census division", division_opts, key="filter_division")
    if division != "All":
        df = df[df["division"] == division]

    rucc_opts = ["All", "Metro", "Nonmetro"]
    rucc_choice = st.sidebar.selectbox("Metro / nonmetro (USDA ERS RUCC 2023)", rucc_opts, key="filter_rucc")
    if rucc_choice != "All":
        df = df[df["RUCC_METRO"] == rucc_choice]

    pop_opts = ["All"] + [b for b in POPULATION_BIN_LABELS if b in df["pop_bin"].astype(str).unique()]
    pop_choice = st.sidebar.selectbox("Population size", pop_opts, key="filter_pop")
    if pop_choice != "All":
        df = df[df["pop_bin"].astype(str) == pop_choice]

    st.sidebar.markdown(f"<span class='filter-count'>{len(df):,} of {len(county_df):,} counties match these filters.</span>", unsafe_allow_html=True)
    if len(df) == 0:
        st.sidebar.warning("No counties match this filter combination. Loosen a filter above.")

    with st.sidebar.expander("Classification used: USDA ERS Rural-Urban Continuum Codes, 2023"):
        st.caption(
            "9 levels (1-3 metro by area population size, 4-9 nonmetro by urbanization "
            "and adjacency to a metro area), assigned by the U.S. Department of "
            "Agriculture's Economic Research Service. A published federal classification, "
            "not one this project defines."
        )
        if len(df):
            dist = df["RUCC_2023"].value_counts().sort_index()
            st.bar_chart(dist)

    return df


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

    cv_line = f"<div class='card-cv'>CV = {cv * 100:.1f}%</div>" if not np.isnan(cv) else ""
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.markdown(
            f"<div class='card-range'>{est:,.0f}</div>"
            f"<div class='card-sub'>range: {display_low:,.0f} &ndash; {high:,.0f} &nbsp;|&nbsp; "
            f"{CONFIDENCE_LEVEL_PCT}% confidence interval</div>"
            + cv_line + rate_line + alloc_line,
            unsafe_allow_html=True,
        )
        if not np.isnan(cv):
            st.pyplot(_distribution_fig(est, low, high, cv), clear_figure=True)
        if caveat:
            st.caption(caveat)
        if low < 0:
            st.caption(
                f"The margin of error above the estimate exceeds the estimate itself -- "
                f"the true lower bound is {low:,.0f}, shown here as 0 since a negative "
                f"count cannot be cited."
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
                ("Estimate", f"{est:,.0f}"),
                (f"{CONFIDENCE_LEVEL_PCT}% CI", f"{display_low:,.0f} – {high:,.0f}"),
                ("± margin of error", f"± {(high - low) / 2:,.0f}"),
                ("Coefficient of variation (CV)", f"{cv * 100:.1f}%" if cv == cv else "n/a"),
            ]
            if low < 0:
                rows.append(("True CI lower bound (unclamped)", f"{low:,.0f} – {high:,.0f}"))
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


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

def render_map(
    level: str, keys_in_scope: list[str], cv_by_key: dict, title: str, *,
    selected_key: str | None = None,
    quadrant_by_key: dict | None = None,
    color_map: dict[str, str] | None = None,
    legend_order: tuple[str, ...] | None = None,
    view_state: pdk.ViewState,
) -> str | None:
    """GeoJsonLayer choropleth, pickable directly (no separate click grid
    -- see module docstring, point 1). Selects a SUBSET of the prebuilt
    feature list (_base_geojson, cached once per level) rather than
    re-serializing geometry; this is what makes filtering cheap.
    """
    key_col = "county_key" if level == "county" else "state_key"
    scope_set = set(keys_in_scope)
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
        feat["properties"]["border_width"] = 3 if key == selected_key else 1
        feat["properties"]["border_color"] = [20, 20, 20, 255] if key == selected_key else [255, 255, 255, 200]
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
    st.caption("Click a state or county to inspect it below, or search in the sidebar.")

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
# dict, two writers: map click and sidebar search).
# ---------------------------------------------------------------------------

def _init_geo_state() -> None:
    st.session_state.setdefault("us_geo", {"level": "state", "code": None, "state_scope": None})
    st.session_state.setdefault("_us_geo_version", 0)


def sidebar_search_control(data: dict, level: str, filtered_county_df: pd.DataFrame) -> None:
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
    choice = st.sidebar.selectbox("Search for a geography", display_labels, key=dropdown_key)
    chosen_key = key_by_label.get(choice)
    if chosen_key and chosen_key != geo["code"]:
        geo["code"] = chosen_key


# ---------------------------------------------------------------------------
# App body
# ---------------------------------------------------------------------------

def main() -> None:
    st.html(_CSS)
    st.title("US County Demographic Explorer")
    st.caption(
        "Click a state, then a county, or search the sidebar, to see American Community "
        "Survey estimates and their margins of error. Every range shown is a 90% confidence "
        "interval, published by the Census Bureau -- not a model."
    )

    data = _load_all()
    _init_geo_state()
    geo = st.session_state["us_geo"]
    level = geo["level"]

    filtered_county_df = sidebar_filters(data["county_df"])

    if level == "county" and geo["state_scope"]:
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
    if st.sidebar.button("Back to national state view" if level == "county" else "Viewing: national (all states)"):
        if level == "county":
            geo.update(level="state", code=None, state_scope=None)
            st.rerun()

    measure = st.selectbox("Color the map by", MEASURE_OPTIONS, key="acs_map_measure")
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
        )
    else:
        st.info("No geographies match the current filter selection. Loosen a filter in the sidebar.")
        picked = None

    if picked and picked != st.session_state.get("_us_map_last_picked"):
        st.session_state["_us_map_last_picked"] = picked
        if level == "state":
            geo.update(level="county", code=None, state_scope=picked)
        else:
            geo["code"] = picked
        st.session_state["_us_geo_version"] += 1

    sidebar_search_control(data, geo["level"], filtered_county_df)
    st.divider()

    level = geo["level"]  # may have just changed via the state click above
    code = geo["code"]
    if not code:
        st.info("Select a geography from the map or the sidebar search to see its statistics.")
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
        st.warning("This county isn't in the current data. Search for it in the sidebar.")
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

    st.subheader(f"{label} -- American Community Survey (2020-2024, 5-year)")
    st.info(
        "ACS surveys a *sample* of households, not everyone. Every number below ships "
        "with a real, measured margin of error -- the range comes directly from the "
        "Census Bureau, not a model."
    )

    pop_est = float(row["B01001_001E"].iloc[0])
    pop_moe = float(row["B01001_001M"].iloc[0])
    acs1_county = _load_acs1_county()
    acs1_row = acs1_county[acs1_county["_key"] == code]

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
        )

    st.markdown("##### Median household income")
    if bool(flag_topcoded_income(row).iloc[0]):
        st.info(
            f"{label}'s median household income is top-coded at $250,001 -- the Census "
            "Bureau censors values at this cap. Not shown as a range; the true median is "
            "at least $250,001."
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
        )
        try:
            saipe = load_saipe_county(row["STATE"].iloc[0], row["COUNTY"].iloc[0])
            st.markdown("###### Bureau comparison: SAIPE for the same variable")
            st.caption(
                f"SAIPE (a separate Census Bureau program that models income rather than "
                f"surveying it) puts {label}'s {saipe['year']} median household income at "
                f"{saipe['SAEMHI_PT']:,.0f}, 90% interval "
                f"{saipe['SAEMHI_LB90']:,.0f}-{saipe['SAEMHI_UB90']:,.0f} (ACS above: "
                f"{income_est:,.0f}, range {income_est - income_moe:,.0f}-{income_est + income_moe:,.0f}). "
                "SAIPE's interval blends sampling error with model uncertainty; ACS's is "
                "sampling error only. A wider SAIPE interval does not mean SAIPE is less reliable."
            )
        except (FileNotFoundError, ValueError):
            pass

    st.markdown("##### Population by age")
    cols = st.columns(4, gap="medium")
    for col, band in zip(cols, BANDS):
        est, moe = acs_sexage(row, band, "both")
        with col:
            e, m = float(est.iloc[0]), float(moe.iloc[0])
            if pd.isna(m):
                with st.container(border=True):
                    st.markdown(f"**{band}**")
                    st.markdown(f"<div class='card-range'>{e:,.0f}</div>", unsafe_allow_html=True)
                    st.caption("No margin of error published for this figure.")
            else:
                band_rank, band_n = _rank_and_n(band, code)
                render_card(band, e, *acs_range(e, m), percentile_rank=band_rank, filter_n=band_n)

    st.markdown("##### Living below the poverty line, by age")
    cols = st.columns(4, gap="medium")
    for col, band in zip(cols, BANDS):
        est, moe = acs_poverty(row, band, "both")
        univ_est, univ_moe = acs_poverty_universe(row, band, "both")
        e, m = float(est.iloc[0]), float(moe.iloc[0])
        rate = poverty_rate(e, m, float(univ_est.iloc[0]), float(univ_moe.iloc[0]))
        pov_rank, pov_n = _rank_and_n(f"Poverty: {band}", code)
        with col:
            render_card(
                band, e, *acs_range(e, m), rate=rate, rate_label=f"of {band} residents in poverty",
                percentile_rank=pov_rank, filter_n=pov_n,
            )

    with st.expander("Reliability score candidates (methodology under mentor review)"):
        st.caption(
            "This project has two candidate formulas for collapsing INCOME sampling risk (CV) "
            "and income imputation into a single score -- they agree on roughly 85% of the "
            "highest-risk quartile nationwide, and the choice between them is an open question "
            "for the Census mentors (see README 'Composite tier philosophy'). Neither is "
            "presented as the answer here; both are shown so the disagreement itself is visible."
        )
        # Deliberately income_cv paired with income_alloc, NOT whatever
        # measure happens to be selected for map coloring -- composite.py's
        # quadrant classification (_measure_layer's IMPUTATION_INCOME
        # branch) pairs these two axes for the SAME variable, and mixing a
        # different measure's CV with income's allocation rate would be a
        # real methodological error, not just a cosmetic one.
        income_cv_series = _cv_series_for(IMPUTATION_INCOME)
        alloc_row = data["alloc_county"].set_index("_key")
        alloc_series = pd.Series(
            filtered_county_df["_key"].map(alloc_row["income_alloc"]).to_numpy(),
            index=filtered_county_df["_key"],
        )
        if code in income_cv_series.index and code in alloc_series.index:
            eq = composite.equal_weight_score(income_cv_series, alloc_series)
            wc = composite.worst_component_score(income_cv_series, alloc_series)
            st.markdown(
                f"- Equal-weight candidate: {_ordinal(eq.get(code, float('nan')) * 100)} percentile risk\n"
                f"- Worst-component candidate: {_ordinal(wc.get(code, float('nan')) * 100)} percentile risk"
            )


if __name__ == "__main__":
    main()
