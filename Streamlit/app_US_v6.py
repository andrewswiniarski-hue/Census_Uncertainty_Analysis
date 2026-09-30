"""Nationwide county demographic explorer -- state-first drill-down.

Version 4.1 (2026-09-29, Justus Long): render_welcome() replaced with the
goal-oriented Welcome page from app_US_v5_welcome.py (2026-09-28, Katie
Christiansen) -- same cards, sections, and ordering, with the facts
corrected for this app (Statistical peers is a tab, not a panel; the CV
rank is "Nth of N counties in the state"; the measure list includes v4's
employment/education/disability topics). The brand shell's chrome (_CSS,
_brand_header_html, _brand_footer_html) was repainted from Corporate
Identity navy/Azul (#112E51 / #265FCA) to v5's Welcome-page blue and gold
(#205493, hover #2f6fb3, gold rule #FFC222) on every tab, not just
Welcome. The map/card CV ramp (cv_color_blue_orange), the reliability
score bands, and the quadrant colors are unchanged.

Version 4 (2026-09-27, Justus Long): version 3 plus the v2.0 features
listed below, and three changes on top:
- County explorer layout: filters, geography search, and "Color the map
  by" in a fixed-height panel on the left (EXPLORER_PANEL_HEIGHT), level
  with a wider map on the right, in one fragment (_explorer_top_fragment).
- Card CV rank: "Nth of N counties in <state>" among every county in the
  selected county's state, replacing a percentile of the filter selection.
- Toggle / checkbox CSS: "Compare to state" track in Azul; the help-icon
  label no longer picks up the checkbox fill.

Version 3 (2026-09-27): version 2 (app_US_v2.py, kept unchanged as the
snapshot before this) plus the card reliability score, lead decision #19:
a band strip on every scored card and a sub-score breakdown in "Show me the
statistics" (score_for, _score_strip_html, _score_note_html,
_score_breakdown_html; scoring rules in analysis/composite.py). See
WORKLOG.md 2026-09-27 and point 6 below.

Also carried over from app_US_v2.0.py (Justus Long, 2026-09-17/18, ported
2026-09-27): Statistical peers on its own tab with its own display-only
map, sharing the county selection with County explorer
(render_peers_tab, _peer_geo_controls); map hover names (_map_tooltip);
thousands separators and a CV column in the peer table; the Census Bureau
branding shell (_brand_header_html, _brand_footer_html, Azul widget
chrome in _CSS); and the performance work (tabs render only when open,
map and card fragments, GeoJSON indexed by key, vectorized rates). Specs:
docs/superpowers/specs/2026-09-17-statistical-peers-tab-design.md and
2026-09-17-census-branding-shell-design.md. v3 keeps its own CV ramp
(cv_color_blue_orange) and the ACS 1-year captions, which v2.0 dropped.

Version 2 (2026-09-14). Combines three lines of work into one file, so
neither teammate's version is edited in place:
- app_US_v1.1.py (Justus Long): the nationwide explorer this file is built on.
- app_US_v1.2.py (Katie Christiansen): render_welcome(), the redesigned
  welcome page, taken verbatim. It is the only function v1.2 changed.
- Card redesign and scope expansion (Andrew Swiniarski, 2026-09-08 to
  2026-09-14): the interval graphic on a visible zero-anchored axis
  (_interval_svg), state reference markers including the modelled
  state-rate benchmark for counts, seven measures added under scope
  decision #18, and a guard that keeps the page usable when local data
  predates the code (_unavailable_measures).
See WORKLOG.md 2026-09-08 and 2026-09-14 and Streamlit/README.md.

The history notes below are v1.1's. Where they say app_NJ.py they mean
Streamlit/app.py (a planned rename that never landed), and app_US.py
means app_US_v1.1.py. Point 3's cv_color() is replaced in this file by
cv_color_blue_orange() (2026-09-16): the same blue and orange ends with a
visible purple midpoint in place of near-white. A single-hue blue ramp,
cv_color_sequential(), was used from 2026-09-14 to 2026-09-16.

Map-first, same interaction model as Streamlit/app_NJ.py: click a state to
see its counties, click a county (or search the panel to the left of the
map) to read its American Community Survey estimates and how much
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
   2026-08-12, see README's "Composite tier philosophy" open question):
   no TIER_SOLID/CARE/RISKY verdict chip, no "safe to cite" / "too risky"
   language. The card reliability score (point 6) therefore uses
   descriptive bands, "Higher / Moderate / Lower reliability", which
   describe the score and give no advice. The map colors on CV directly via a continuous
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
   explicit 90%-CI bounds, a CV rank among the counties in the county's
   own state ("12th of 67", 2026-09-27; was a percentile of the current
   filter selection), a county-vs-state significant-difference check, and (where
   available) an ACS 1-year vs 5-year precision comparison.
6. Card reliability score (lead decision #19, 2026-09-27): an equal-weight
   average of a sampling sub-score (from the CV, anchored to the ESRI 0.12
   and NCHS 0.30 lines) and, for income and poverty figures, an imputation
   sub-score relative to all US counties, with the band capped at the CV's
   own band. Built by analysis.composite.reliability_score(); spec in
   docs/superpowers/specs/2026-09-27-composite-reliability-score-cards-design.md.
   The composite tier question stays open for mentors; this is our
   methodology, not a Census Bureau product.

Run from the repo root:
    streamlit run Streamlit/app_US_v4.py

Needs data/raw/{acs5_2024_usdash,acs1_2024_usdash,geo_2024_usdash,
acs5_2024_usdash_alloc,rucc_2023}_* -- regenerate with:
    python ingestion/pull_usdash.py
    python ingestion/pull_us_geometry.py
    python ingestion/pull_usdash_alloc.py
    python ingestion/pull_rucc.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

from analysis import composite
from analysis.acs import flag_topcoded_income, income_cv, Z_90
from analysis.common import moe_to_cv
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
    acs_civilian_labor_force,
    acs_disability,
    acs_disability_universe,
    acs_education_universe,
    acs_low_income,
    acs_median_home_value,
    acs_no_diploma,
    acs_poverty_ratio_universe,
    acs_rent_burdened,
    acs_rent_computed_universe,
    acs_rent_severely_burdened,
    acs_unemployed,
    census_region,
    children_of,
    cv_color,
    cv_color_blue_orange,
    CV_COLOR_CONTROLLED,
    CV_COLOR_NO_DATA,
    cv_from_range,
    difference_is_significant,
    expected_at_rate,
    geo_key,
    load_alloc_us_county,
    load_level_data,
    load_level_geo,
    load_rucc,
    load_us_acs1_county,
    population_size_bin,
    proportion_rate,
    proportion_rate_series,
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


class ImputationSource(NamedTuple):
    """An ACS allocation (imputation) table a card's score can draw on."""
    column: str      # column in data["alloc_county"]
    label: str       # shown in the statistics panel
    is_proxy: bool   # True when the table does not measure the card's own item


# Card reliability score (lead decision #19, 2026-09-27). Only these two
# tables pair with dashboard measures; every other measure is scored on
# sampling alone and says imputation is not part of its score. Age bands are
# deliberately sampling only: age imputation is 1.1% at the median county,
# too small for a relative scale to mean anything.
IMPUTATION_SOURCES: dict[str, ImputationSource] = {
    "income": ImputationSource("income_alloc", "household income, Table B99192", False),
    "family_poverty": ImputationSource(
        "fam_pov_alloc", "family poverty status, Table B99172", True,
    ),
}


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
    # Reference-marker wiring (card redesign, 2026-09-08). See
    # reference_mode() below for the three cases and why they differ.
    # `state_reference` marks the DIRECT case: intensive quantities
    # (medians, percentages) whose state figure sits on the same scale as a
    # county's and can be drawn as-is.
    state_reference: bool = False
    # Universe for the RATE case, only where it differs from `universe`.
    # The age bands need one (their universe is total population) but must
    # not gain `universe`, which would switch on a rate line they never had.
    reference_universe: Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]] | None = None
    # True where a published estimate with no margin of error means a CONTROLLED
    # estimate (no sampling error), not missing data. Set only where verified:
    # for total population, 2024 5-year, every one of the 3,014 counties and 51
    # states without a numeric MOE carries the API annotation "*****"; none of
    # the 130 counties with a numeric MOE does (live API check, 2026-09-14).
    controlled_when_moe_missing: bool = False
    # Key into IMPUTATION_SOURCES, or None for a sampling-only score.
    imputation: str | None = None

    @property
    def reference_mode(self) -> str:
        """Which kind of reference marker this measure's card may carry.

        "direct" -- draw the state's own published value. Valid only for
        medians and percentages, where state and county share a scale.
        "rate"   -- draw the state's RATE applied to this county's universe
        (analysis.dashboard.expected_at_rate). Valid for counts, whose raw
        state value runs 10x to 25x a county's and would squash the
        zero-anchored axis to nothing. This is a MODELLED expectation and
        the card must say so.
        "none"   -- no defensible benchmark. Total population is the only
        such measure: a county's share of its state's population is a fact
        about relative size, not a reliability statement.
        """
        if self.state_reference:
            return "direct"
        if self.reference_universe is not None or self.universe is not None:
            return "rate"
        return "none"

    @property
    def rate_universe(self) -> Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]] | None:
        """The universe the "rate" mode divides by."""
        return self.reference_universe or self.universe


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


def _total_population_values(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for total population. Also serves as the age bands'
    reference universe: their share-of-population is what the state-rate
    benchmark divides by. Note the MOE is NaN for most geographies, since
    total population is controlled to independent population estimates, so
    a benchmark built on it carries no propagated interval -- correctly,
    because none is published."""
    return df["B01001_001E"].astype(float), df["B01001_001M"].astype(float)


def _build_measures() -> dict[str, Measure]:
    registry: dict[str, Measure] = {
        "Total population": Measure(
            label="Total population", topic="Population", table_id="B01001",
            values=_total_population_values, controlled_when_moe_missing=True,
        ),
        "Median household income": Measure(
            label="Median household income", topic="Income", table_id="B19013",
            values=_income_values, state_reference=True, imputation="income",
        ),
        "Median gross rent": Measure(
            label="Median gross rent", topic="Housing", table_id="B25064",
            values=acs_median_rent, state_reference=True,
        ),
        "Rent burden (rent as % of income)": Measure(
            label="Rent burden (rent as % of income)", topic="Housing", table_id="B25071",
            values=acs_rent_burden, unit_suffix="%", state_reference=True,
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
        # Scope expansion (lead decision, 2026-09-14): Tiers A and B of
        # docs/dashboard-variable-shortlist.md, each traced to a named federal
        # program. Cell choices and universes are documented beside the
        # accessors in analysis/dashboard.py.
        "Low income (below 200% of poverty)": Measure(
            label="Low income (below 200% of poverty)", topic="Poverty", table_id="C17002",
            values=acs_low_income, universe=acs_poverty_ratio_universe,
            rate_label="of people below 200% of the poverty line",
            measure_label="population below 200% of the poverty line",
            imputation="family_poverty",
        ),
        "Unemployed": Measure(
            label="Unemployed", topic="Employment", table_id="B23025",
            values=acs_unemployed, universe=acs_civilian_labor_force,
            rate_label="of the civilian labor force unemployed",
            measure_label="unemployed population",
        ),
        "Cost-burdened renters (30%+ of income)": Measure(
            label="Cost-burdened renters (30%+ of income)", topic="Housing", table_id="B25070",
            values=acs_rent_burdened, universe=acs_rent_computed_universe,
            rate_label="of renters paying 30% or more of income in rent",
            measure_label="cost-burdened renter households",
        ),
        "Severely cost-burdened renters (50%+ of income)": Measure(
            label="Severely cost-burdened renters (50%+ of income)", topic="Housing", table_id="B25070",
            values=acs_rent_severely_burdened, universe=acs_rent_computed_universe,
            rate_label="of renters paying 50% or more of income in rent",
            measure_label="severely cost-burdened renter households",
        ),
        "Median home value": Measure(
            label="Median home value", topic="Housing", table_id="B25077",
            values=acs_median_home_value, state_reference=True,
        ),
        "No high school diploma (age 25+)": Measure(
            label="No high school diploma (age 25+)", topic="Education", table_id="B15003",
            values=acs_no_diploma, universe=acs_education_universe,
            rate_label="of adults 25 and over without a high school diploma",
            measure_label="adults 25 and over without a high school diploma",
        ),
        "With a disability": Measure(
            label="With a disability", topic="Disability", table_id="B18101",
            values=acs_disability, universe=acs_disability_universe,
            rate_label="of residents with a disability",
            measure_label="population with a disability",
        ),
    }

    for band in BANDS:
        registry[band] = Measure(
            label=band, topic="Population", table_id="B01001",
            values=partial(acs_sexage, band=band, sex="both"),
            measure_label=f"{band} population",
            # reference_universe, not universe: these cards never carried a
            # rate line and adding `universe` would switch one on.
            reference_universe=_total_population_values,
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
            imputation="family_poverty",
        )

    for band in INCOME_BANDS:
        label = _INCOME_BAND_TITLES[band]
        registry[label] = Measure(
            label=label, topic="Income", table_id="B19001",
            values=partial(acs_income_bracket, band=band),
            universe=acs_income_bracket_universe,
            rate_label=f"of households earning {band}",
            imputation="income",
        )

    return registry


MEASURES = _build_measures()
MEASURE_OPTIONS = list(MEASURES) + [IMPUTATION_INCOME]
DEFAULT_CARD_LABELS = ("Total population", "Median household income")
# The map opens on median household income, the anchor measure, which has a
# published margin of error in all but one county. Total population, the old
# default, is a controlled estimate in 96% of counties, so it opened as a
# nearly single-color map that taught the user nothing about reliability.
DEFAULT_MAP_MEASURE = "Median household income"


@st.cache_data
def _unavailable_measures_for_columns(
    county_cols: tuple[str, ...], state_cols: tuple[str, ...]
) -> frozenset[str]:
    """Column-keyed cache body for `_unavailable_measures`."""
    county_sample = pd.DataFrame({c: [0.0] for c in county_cols})
    state_sample = pd.DataFrame({c: [0.0] for c in state_cols})
    missing: set[str] = set()
    for key, m in MEASURES.items():
        for sample in (county_sample, state_sample):
            try:
                m.values(sample)
                if m.rate_universe is not None:
                    m.rate_universe(sample)
            except KeyError:
                missing.add(key)
                break
    return frozenset(missing)


def _unavailable_measures(data: dict) -> set[str]:
    """Registry measures the LOCAL data cannot render yet.

    The code can be newer than the parquet files: a teammate pulls a change
    that adds a measure but has not re-run ingestion/pull_usdash.py, or a
    re-pull succeeded for counties but failed for states. Before this guard,
    choosing such a card raised a KeyError that took down the entire explorer
    page, not just the card (verified headlessly 2026-09-14). A measure counts
    as unavailable if its own accessors raise KeyError on either the county or
    the state frame, so the check reads exactly the cells the card would read
    and cannot drift from them. The state frame is checked too because the
    card's reference marker reads the state row.
    """
    return set(_unavailable_measures_for_columns(
        tuple(sorted(data["county_df"].columns)),
        tuple(sorted(data["state_df"].columns)),
    ))


_REPULL_HINT = "`python ingestion/pull_usdash.py`"


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
# Visual styling -- app-local shell (not .streamlit/config.toml, which is
# shared with app_NJ.py). Palette matched to app_US_v5_welcome.py's Welcome
# page (2026-09-28, Katie Christiansen) so the same blue and gold read on
# every tab, not just Welcome: brand blue #205493 (header/footer/H1-H6,
# tabs, checkboxes/toggles, chips, radio, slider, buttons), a lighter
# gradient blue #2f6fb3 for hover states, tint #d7e2ef for light text/rules
# on the blue header and footer, and gold #FFC222 as a hairline accent rule
# on the header and footer (v5 uses it the same way: a rule/dot, not a
# fill). Map / card / interval fills, the reliability-score bands, and the
# quadrant colors stay on their own palettes (cv_color_blue_orange(),
# BAND_COLOR/BAND_TEXT, QUADRANT_COLOR) -- none of those are brand chrome.
# ---------------------------------------------------------------------------
_BRAND_BLUE = "#205493"
_BRAND_BLUE_HOVER = "#2f6fb3"
_BRAND_GOLD = "#FFC222"

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');

html, body, [class*="css"] { font-family: 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif; }
h1, h2, h3, h4, h5, h6 { font-family: 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif;
                          font-weight: 700; color: #205493; }
a, a:visited { color: #205493; }
a:hover { color: #2f6fb3; }

/* Streamlit 1.60 paints tabs and checkboxes from Emotion theme.colors.primary
   (default red) onto React Aria nodes. CSS variables do not reach those
   hashed classes; target the actual DOM instead. */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    --primary-color: #205493;
    --st-primary-color: #205493;
}

[data-testid="stTab"][data-selected],
[data-testid="stTab"][data-hovered],
[data-testid="stTab"][data-focus-visible] {
    color: #205493 !important;
}
[data-testid="stTab"][data-selected] .react-aria-SelectionIndicator {
    background-color: #205493 !important;
}
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {
    background-color: #205493 !important;
}

/* st.checkbox and st.toggle share stCheckbox. Only the box / track sits
   directly under the label; a deeper :has(svg) also matches the widget
   label when it carries a help icon and paints the text blue. */
[data-testid="stCheckbox"] label[data-selected] > div:has(> svg) {
    background-color: #205493 !important;
    border-color: #205493 !important;
}
[data-testid="stCheckbox"] label[data-selected]:has(input[role="switch"]) > div:not([data-testid="stWidgetLabel"]) {
    background-color: #205493 !important;
}
[data-baseweb="tag"] {
    background-color: #205493 !important;
}
[data-baseweb="radio"][aria-checked="true"] > div,
[data-baseweb="slider"] [role="slider"] {
    background-color: #205493 !important;
    border-color: #205493 !important;
}

.stButton > button, button[data-testid="stBaseButton-secondary"],
button[data-testid="stBaseButton-primary"] {
    background-color: #205493 !important; border-color: #205493 !important;
    color: #FFFFFF !important; font-weight: 600; border-radius: 999px;
}
.stButton > button:hover, button[data-testid="stBaseButton-secondary"]:hover,
button[data-testid="stBaseButton-primary"]:hover {
    background-color: #2f6fb3 !important; border-color: #2f6fb3 !important;
    color: #FFFFFF !important;
}
.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"] {
    background-color: #205493 !important; border-color: #205493 !important;
    color: #FFFFFF !important; font-weight: 600;
}
.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="stBaseButton-primary"]:hover {
    background-color: #2f6fb3 !important; border-color: #2f6fb3 !important;
    color: #FFFFFF !important;
}

.census-brand-bar {
    background: #205493; color: #FFFFFF; padding: 16px 20px 14px; margin: 0 0 12px 0;
    border-bottom: 4px solid #FFC222;
    border-radius: 12px;
    overflow: hidden;
}
.census-brand-bar--welcome { padding: 28px 30px 22px; }
.census-brand-bar__welcome {
    color: #FFFFFF; margin: 12px 0 0 0; font-size: 17px;
}
.census-brand-bar__top {
    display: flex; justify-content: space-between; align-items: flex-start;
    gap: 16px; flex-wrap: wrap;
}
.census-wordmark {
    font-weight: 700; font-size: 0.8rem; letter-spacing: 0.06em;
    text-transform: uppercase; color: #d7e2ef;
}
.census-app-title { font-weight: 700; font-size: 1.45rem; margin-top: 4px; color: #FFFFFF; }
.census-brand-bar__capstone {
    font-size: 0.8rem; font-weight: 500; color: #d7e2ef; white-space: nowrap;
}
.census-tagline { margin-top: 10px; font-size: 0.85rem; color: #d7e2ef; }
.census-footer {
    background: #205493; color: #FFFFFF; padding: 16px 20px; margin-top: 28px;
    font-size: 0.85rem; border-top: 4px solid #FFC222;
    border-radius: 12px;
    overflow: hidden;
}
.census-footer a, .census-footer a:visited { color: #d7e2ef; }
.census-footer a:hover { color: #FFFFFF; }
.census-footer p { margin: 0 0 6px 0; }

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
.score-strip { display: flex; justify-content: space-between; align-items: baseline;
               flex-wrap: wrap; gap: 2px 8px; padding-top: 6px; margin-bottom: 4px;
               font-size: 0.8rem; }
.score-band  { font-weight: 700; }
.score-num   { color: #5A5A5A; white-space: nowrap; }
.score-num b { color: #131313; }
.score-bar-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px;
                 align-items: center; padding: 5px 2px; font-size: 0.85rem;
                 border-bottom: 1px solid #E6E6E6; }
.score-bar-row .label { color: #5A5A5A; }
.score-bar-row .value { text-align: right; font-weight: 600; color: #222;
                        font-variant-numeric: tabular-nums; }
.score-bar { display: block; position: relative; height: 6px; background: #EEEEEE;
             border-radius: 3px; }
.score-bar > span { position: absolute; left: 0; top: 0; height: 6px;
                    background: #5A6672; border-radius: 3px; }

/* Welcome page (ported from app_US_v5_welcome.py, 2026-09-28, Katie
   Christiansen). Kept as its own block of classes, same as v5, rather than
   folded into the generic classes above -- render_welcome() is the only
   caller. */
.welcome-section {
    color: #205493; font-size: 23px; font-weight: 700;
    margin-top: 28px; margin-bottom: 10px;
    border-bottom: 3px solid #FFC222; padding-bottom: 5px;
}
.goal-card {
    border: 1px solid #d7e2ef; border-radius: 10px; padding: 18px;
    min-height: 142px; background: #f7faff; box-sizing: border-box;
}
.goal-card h4 { color: #205493; margin: 0 0 7px 0; font-size: 17px; }
.goal-card p { color: #3C3A3B; margin: 0; font-size: 14px; line-height: 1.45; }
.step-card {
    border: 1px solid #d7e2ef; border-top: 5px solid #205493;
    border-radius: 9px; padding: 17px; min-height: 145px;
    background: white; box-sizing: border-box;
}
.step-number {
    display: inline-block; background: #FFC222; color: #3C3A3B;
    font-weight: 800; border-radius: 50%; width: 29px; height: 29px;
    line-height: 29px; text-align: center; margin-bottom: 8px;
}
.step-card h4 { color: #205493; margin: 0 0 6px 0; font-size: 17px; }
.step-card p { color: #3C3A3B; margin: 0; font-size: 14px; line-height: 1.4; }
.example-box {
    background: #fff9e6; border-left: 6px solid #FFC222;
    border-radius: 8px; padding: 18px 20px; margin: 8px 0 14px 0;
}
.example-title { color: #205493; font-size: 18px; font-weight: 700; margin-bottom: 5px; }
.uncertainty-box {
    border: 1px solid #d7e2ef; border-radius: 9px;
    padding: 16px 18px; background: #f7faff;
}
.glossary-pill {
    display: inline-block; background: #eef4fb; color: #205493;
    border: 1px solid #d7e2ef; border-radius: 16px;
    padding: 5px 10px; margin: 3px; font-size: 13px; font-weight: 600;
}
.cv-legend-box {
    margin-top: 12px; padding: 12px 16px; border-radius: 8px;
    background: #f7faff; border: 1px solid #d7e2ef;
}
.cv-legend-box b.cv-low { color: #205493; }
.cv-legend-box b.cv-high { color: #d97706; }
.cv-legend-box span.cv-note { color: #3C3A3B; font-size: 13px; }
</style>
"""

_CENSUS_TAGLINE = "Measuring America: People, Places, and Economy"


def _brand_header_html(*, welcome: bool = False) -> str:
    """Blue census.gov-like banner. Wordmark only: no seal, no DOC lockup.

    On the Welcome tab, `welcome=True` folds the old welcome-hero copy into
    this same card so the page does not stack two blue titles.
    """
    extra_class = " census-brand-bar--welcome" if welcome else ""
    title = (
        "Welcome to the U.S. County Demographic Explorer"
        if welcome
        else "US County Demographic Explorer"
    )
    pitch = (
        '<p class="census-brand-bar__welcome">'
        "Find Census Bureau data, understand its uncertainty, and get the information "
        "you need for research, planning, and grant writing."
        "</p>"
        if welcome
        else ""
    )
    return (
        f'<div class="census-brand-bar{extra_class}" role="banner">'
        '<div class="census-brand-bar__top">'
        '<div>'
        '<div class="census-wordmark">U.S. Census Bureau</div>'
        f'<div class="census-app-title">{title}</div>'
        "</div>"
        '<div class="census-brand-bar__capstone">Capstone demonstration</div>'
        "</div>"
        f'<div class="census-tagline">{_CENSUS_TAGLINE}</div>'
        f"{pitch}"
        "</div>"
    )


def _brand_footer_html() -> str:
    """Capstone attribution so the blue header cannot be read as census.gov."""
    return (
        '<div class="census-footer" role="contentinfo">'
        f"<p>{_CENSUS_TAGLINE}</p>"
        f"<p>American Community Survey ({ACS_VINTAGE}).</p>"
        "<p>This is a student capstone demonstration. "
        "It is not an official Census Bureau product.</p>"
        '<p><a href="https://www.census.gov">census.gov</a></p>'
        "</div>"
    )


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
    county_geo = county_geo.assign(_key=geo_key(county_geo, "county", specs=US_LEVEL_SPECS))
    state_geo = state_geo.assign(_key=geo_key(state_geo, "state", specs=US_LEVEL_SPECS))

    alloc_county = load_alloc_us_county()
    alloc_county = alloc_county.assign(_key=geo_key(alloc_county, "county", specs=US_LEVEL_SPECS))

    rucc = load_rucc()
    rucc = rucc.assign(_key=geo_key(rucc, "county", specs=US_LEVEL_SPECS))

    acs1_keys = acs_1yr_available_keys()

    county_df = county_df.assign(
        pop_bin=population_size_bin(county_df["B01001_001E"].astype(float)),
    ).merge(rucc[["_key", "RUCC_2023", "RUCC_METRO"]], on="_key", how="left")

    alloc_by_key = alloc_county.set_index("_key")
    imputation_subs = {
        name: composite.imputation_subscores(alloc_by_key[src.column])
        for name, src in IMPUTATION_SOURCES.items()
    }

    return {
        "imputation_subs": imputation_subs,
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


def _map_tooltip() -> dict:
    """Hover label for both maps. pydeck substitutes `{tooltip_name}` from
    the hovered feature's properties -- the same NAME string the rest of
    the app uses (`Alabama` at state view, `Autauga County, Alabama` at
    county view). Keep the HTML to the name only: the cards below already
    carry the estimate and CV, and stuffing numbers into the tooltip
    would re-open the editorial-voice question the sponsor already closed.
    """
    return {
        "html": "<b>{tooltip_name}</b>",
        "style": {
            "backgroundColor": "white",
            "color": "#222",
            "fontSize": "13px",
        },
    }


@st.cache_resource
def _base_geojson(level: str) -> list[dict]:
    """Every feature for a level, built ONCE per process -- the fix for
    app_NJ.py's per-rerun to_json()/json.loads() round-trip (render_map's
    docstring there explains why that cost four full geometry
    serializations per render). Per render, render_map() below only
    SELECTS a subset of this prebuilt list and copies it before setting
    fill_color / border_width / border_color -- no re-serialization of
    geometry, ever, after this function's one-time cost. The copy is
    required: this list is a shared cache_resource object, and an
    in-place write would permanently corrupt tooltip_name for every later
    render.

    `tooltip_name` is baked in here (not per-render) because the Census
    NAME never changes with the selected measure. Hover then just reads
    that property.
    """
    if level not in ("county", "state"):
        raise ValueError(f"unknown geography level {level!r}")

    data = _load_all()
    gdf = data["county_geo"] if level == "county" else data["state_geo"]
    key_col = "county_key" if level == "county" else "state_key"
    labels = data["labels_county"] if level == "county" else data["labels_state"]
    gdf = gdf.to_crs(epsg=4326).copy()
    gdf[key_col] = gdf["_key"]
    gdf["tooltip_name"] = [labels.get(k, str(k)) for k in gdf["_key"]]
    geojson = json.loads(gdf[[key_col, "tooltip_name", "geometry"]].to_json())
    return geojson["features"]


@st.cache_resource
def _base_geojson_by_key(level: str) -> dict[str, dict]:
    """Index of `_base_geojson` features by FIPS key -- O(1) lookup so a
    state-scoped map copies only in-scope counties instead of scanning
    all 3,144 features on every render.
    """
    key_col = "county_key" if level == "county" else "state_key"
    return {feat["properties"][key_col]: feat for feat in _base_geojson(level)}


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
        rate_est, _rate_moe = proportion_rate_series(est, moe, univ_est, univ_moe)
        pct_by_key = rate_est.to_dict()

    est_by_key = est.to_dict()
    lo = est - moe
    hi = est + moe
    valid = est.notna() & moe.notna()
    cv = pd.Series(np.nan, index=est.index, dtype=float)
    positive = valid & (est > 0)
    cv.loc[positive] = ((hi - lo) / (2 * Z_90) / est).loc[positive]
    range_lo = np.where(valid, np.maximum(lo.to_numpy(dtype=float), 0.0), est.to_numpy(dtype=float))
    range_hi = np.where(valid, hi.to_numpy(dtype=float), est.to_numpy(dtype=float))
    range_by_key = dict(zip(est.index, zip(range_lo.tolist(), range_hi.tolist())))
    cv_by_key = cv.to_dict()
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
_PEER_MEDIANS = {"Median household income", "Median gross rent", "Rent burden (rent as % of income)",
                 "Median home value"}
PEER_MEASURES = [k for k, m in MEASURES.items() if m.universe is not None or k in _PEER_MEDIANS]


def _peer_values(df: pd.DataFrame, measure_key: str) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) on the scale statistical_peers() compares counties
    on, keyed by _key: the propagated RATE for rate-bearing measures (the
    same proportion_rate() call _measure_layer() makes for its pct_by_key
    output, redone here because that dict drops the rate's own MOE, which
    a peer comparison needs), or the raw value for the medians,
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
    return proportion_rate_series(est, moe, univ_est, univ_moe)


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

    Stacked vertically for the County explorer's left-hand panel beside
    the map (2026-09-27); it was a four-across row in an expander above it.

    Returns (filtered_county_df, search_slot): search_slot is an empty
    st.container the caller fills in AFTER the map is drawn, since the
    state/county search dropdowns' seed values depend on a map click that
    hasn't happened yet at this point in the script (see
    geography_search_control's docstring).
    """
    df = county_df
    back_clicked = st.button(
        "Back to national state view" if level == "county" else "Viewing: national (all states)",
        width="stretch",
    )
    if back_clicked and level == "county":
        geo.update(level="state", code=None, state_scope=None)
        st.session_state["_us_geo_version"] += 1
        st.rerun()

    search_slot = st.container()

    rucc_opts = ["All", "Metro", "Nonmetro"]
    rucc_choice = st.selectbox("Metro / nonmetro (USDA ERS RUCC 2023)", rucc_opts, key="filter_rucc")
    if rucc_choice != "All":
        df = df[df["RUCC_METRO"] == rucc_choice]

    pop_opts = ["All"] + [b for b in POPULATION_BIN_LABELS if b in df["pop_bin"].astype(str).unique()]
    pop_choice = st.selectbox("Population size", pop_opts, key="filter_pop")
    if pop_choice != "All":
        df = df[df["pop_bin"].astype(str) == pop_choice]

    st.markdown(f"<span class='filter-count'>{len(df):,} of {len(county_df):,} counties match these filters.</span>", unsafe_allow_html=True)
    if len(df) == 0:
        st.warning("No counties match this filter combination. Loosen a filter above.")

    with st.expander("Classification used: USDA ERS RUCC 2023"):
        st.caption(
            "Rural-Urban Continuum Codes: 9 levels (1-3 metro by area population size, "
            "4-9 nonmetro by urbanization and adjacency to a metro area), assigned by the "
            "U.S. Department of Agriculture's Economic Research Service. A published federal "
            "classification, not one this project defines."
        )
        if len(df):
            dist = df["RUCC_2023"].value_counts().sort_index()
            st.bar_chart(dist, height=160)

    return df, search_slot


# ---------------------------------------------------------------------------
# Distribution visual: dot + 90% CI whiskers + gradient band
# ---------------------------------------------------------------------------

# Interval-graphic palette, matching .streamlit/config.toml's light theme
# (backgroundColor #FFFFFF, textColor #131313, borderColor #D6D6D6) so the
# SVG sits on the card without a second, competing set of neutrals.
_SVG_INK = "#131313"
_SVG_RULE = "#D6D6D6"
_SVG_MUTED = "#5A6672"
_SVG_SURFACE = "#FFFFFF"
# Labels sit over the axis rule and the reference line; a surface-coloured
# halo keeps the text readable without breaking the line beneath it.
_SVG_HALO = (f'paint-order="stroke" stroke="{_SVG_SURFACE}" stroke-width="3.5" '
             f'stroke-linejoin="round"')
# State comparison row. Neutral grey so the county bar keeps the only CV
# colour on the card: the state row is context, not a second reliability
# reading. 2.6:1 on white, enough for a non-text mark (WCAG 1.4.11 asks 3:1
# of UI components; this is a data mark with a labelled value beside it).
_SVG_STATE = "#9AA3AD"


class StateReference(NamedTuple):
    """The state comparison drawn as its own row under a card's county bar.

    `modelled` separates the two kinds of claim (see Measure.reference_mode):
    False for the state's own published value (medians, percentages), drawn
    as a solid bar over its published MOE; True for our state-rate benchmark
    for counts (analysis.dashboard.expected_at_rate), drawn lighter with a
    dashed outline so a modelled figure never looks like a published one.
    `moe` None or non-finite draws the value as a dot with no bar.
    """
    value: float
    label: str
    moe: float | None
    modelled: bool


def _nice_ticks(d0: float, d1: float, n: int = 4) -> list[float]:
    """Rounded tick values spanning [d0, d1], roughly n of them.

    Standard 1/2/5/10 stepping, so an axis reads 0 / 20,000 / 40,000
    rather than 0 / 17,384 / 34,768.
    """
    raw = (d1 - d0) / max(n, 1)
    if not np.isfinite(raw) or raw <= 0:
        return [d0]
    mag = 10.0 ** np.floor(np.log10(raw))
    norm = raw / mag
    step = (1 if norm < 1.5 else 2 if norm < 3 else 5 if norm < 7 else 10) * mag
    out, t = [], float(np.ceil(d0 / step) * step)
    while t <= d1 + 1e-9:
        out.append(t)
        t += step
    return out


def _fmt_tick(v: float, unit_suffix: str) -> str:
    """Compact axis-tick label: 20K rather than 20,000, so four ticks fit
    without collision. Percentages stay unabbreviated (they never get big)."""
    if unit_suffix == "%":
        return f"{v:,.0f}%"
    if abs(v) >= 1000:
        return f"{v / 1000:,.0f}K{unit_suffix}"
    return f"{v:,.0f}{unit_suffix}"


def _interval_svg(
    est: float, low: float, high: float, cv: float, *,
    reference: StateReference | None = None,
    unit_suffix: str = "",
    compact: bool = False,
) -> str:
    """Uncertainty interval on a VISIBLE zero-anchored axis.

    Option A of the 2026-09-08 card redesign (lead decision). Replaces the
    matplotlib figure this file previously drew. The scale decision that
    figure documented is UNCHANGED; what changed is that it is now shown to
    the reader instead of living only in a docstring.

    Why the axis stays zero-anchored and fixed, carried over verbatim from
    the original rationale: an axis auto-fitted to each interval's OWN width
    made a razor-precise county and a wildly imprecise one produce visually
    IDENTICAL charts, normalising away the one thing a reliability visual
    most needs to show. Here the bar's WIDTH remains a real fraction of the
    chart, so a wide margin of error visibly eats most of the bar and a
    tight one is a thin sliver. The previous version then called
    ax.axis("off"), which hid the zero, the ticks and the units that make
    that width legible. They are now drawn.

    Fill colour comes from cv_color_blue_orange(), the same ramp the map uses, so a
    bar's color here means what a county's color means there.

    `reference`: the state comparison, drawn as its OWN labelled row under
    the county bar on the shared axis (option B, lead decision 2026-09-27,
    after Census Bureau feedback that a state line drawn across the county
    bar was hard to read). Until then it was a vertical line over the
    county bar. None draws the county alone and fits the axis to it, which
    is what a card shows while its "Compare to state" toggle is off.
    Two kinds, because they are not the same kind of claim (see
    Measure.reference_mode and StateReference):
    - A published state value (medians, percentages), which shares a
      county's scale: solid grey bar over the state's own published MOE.
    - A RATE reference, the state's rate applied to this county's own
      universe (analysis.dashboard.expected_at_rate), for counts, whose raw
      state value runs 10x to 25x a county's and would squash the
      zero-anchored axis to nothing. This one is OUR modelled expectation,
      not a Bureau publication, so it is drawn lighter with a dashed
      outline. The differing treatment is the point, not an inconsistency:
      the reader can see which row is a measurement and which is a model.

    Still no violin or density curve: ACS margins of error come from
    successive-difference replication, which yields a variance, not a known
    distributional family, and for small counts the true sampling
    distribution is skewed and bounded at zero. A normal density would draw
    probability mass at impossible negative counts on exactly the cases
    where uncertainty matters most. Clamped at zero for the same reason.

    `compact`: narrower viewBox for the four-across topic-card grid.
    Font sizes are viewBox UNITS, so a fixed-width viewBox squeezed into a
    narrower container shrinks the text with everything else: measured live
    at a 1270px page width, the same graphic renders 507px wide in the
    two-across headline row but only 222px in the four-across grid,
    dropping tick text from 10px to 6px, which is unreadable. The 240-unit
    compact box is sized against that measured 222px so both layouts land
    near 11px. Shrinking the viewBox
    instead of the container keeps the type at its intended size, because
    the same 11-unit tick now occupies a larger share of a smaller box.
    Tick count drops with it, since a narrow axis cannot carry five labels
    without collision. Passed by the CALLER, which knows its column count;
    the renderer cannot measure its own container server-side.

    Returns an SVG string for st.markdown(unsafe_allow_html=True): sharp at
    any card width, text stays selectable, and no matplotlib figure handle
    needs closing on every rerun.
    """
    display_low = max(0.0, low)
    show_ref = reference is not None and np.isfinite(reference.value)
    ref_moe = (reference.moe if show_ref and reference.moe is not None
               and np.isfinite(reference.moe) and reference.moe > 0 else None)
    ref_top = (reference.value + (ref_moe or 0.0)) if show_ref else 0.0
    upper = max(high, est, ref_top)
    if not np.isfinite(upper) or upper <= 0:
        return ""

    # The state row adds ROW_GAP units below the county row and pushes the
    # axis down by the same amount; the county row's geometry is unchanged.
    ROW_GAP = 42.0 if show_ref else 0.0
    W, H, PADL, PADR = (240.0 if compact else 560.0), 92.0 + ROW_GAP, 12.0, 12.0
    axis_y = 66.0 + ROW_GAP
    tick_target = 3 if compact else 4
    d1 = upper * 1.08
    span = W - PADL - PADR

    def x(v: float) -> float:
        return PADL + (min(max(v, 0.0), d1) / d1) * span

    def clamp(px: float, pad: float) -> float:
        return max(PADL + pad, min(W - PADR - pad, px))

    # Half a label's rendered width at font-size 12, estimated at 6.6 units
    # per character (Roboto digits and lowercase average ~0.55 em), so a
    # centred label is kept inside the card by its OWN length.
    def label_x(px: float, text: str) -> float:
        return clamp(px, len(text) * 3.3)

    r, g, b = cv_color_blue_orange(cv)[:3]
    bx, bw = x(display_low), max(2.0, x(high) - x(display_low))
    p = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" height="auto" '
         f'style="display:block;overflow:visible" role="img" '
         f'aria-label="Estimate {est:,.0f}{unit_suffix}, '
         f'{CONFIDENCE_LEVEL_PCT}% confidence interval {display_low:,.0f} to {high:,.0f}'
         + (f'; {reference.label} {reference.value:,.0f}{unit_suffix}' if show_ref else '')
         + '">']

    # County row. Its label gains a "County" prefix only when a state row
    # sits under it, so the two rows can be told apart without a legend.
    county_text = (("County " if show_ref else "")
                   + f"{display_low:,.0f}{unit_suffix} – {high:,.0f}{unit_suffix}")
    p.append(f'<text x="{label_x(bx + bw / 2, county_text):.1f}" y="33" '
             f'font-size="12" fill="{_SVG_MUTED}" text-anchor="middle" {_SVG_HALO}>'
             f'{county_text}</text>')
    p.append(f'<rect x="{bx:.1f}" y="39" width="{bw:.1f}" height="15" rx="4" '
             f'fill="rgb({r},{g},{b})"/>')
    p.append(f'<circle cx="{x(est):.1f}" cy="46.5" r="4.5" fill="{_SVG_INK}" '
             f'stroke="{_SVG_SURFACE}" stroke-width="2"/>')

    # State row: same geometry as the county row, ROW_GAP lower.
    if show_ref:
        sv = reference.value
        if ref_moe is not None:
            sl, sh = x(max(0.0, sv - ref_moe)), x(sv + ref_moe)
            style = (f'fill="{_SVG_STATE}" fill-opacity="0.35" stroke="{_SVG_MUTED}" '
                     f'stroke-width="1" stroke-dasharray="3 2"' if reference.modelled
                     else f'fill="{_SVG_STATE}"')
            p.append(f'<rect x="{sl:.1f}" y="{39 + ROW_GAP:.0f}" width="{max(2.0, sh - sl):.1f}" '
                     f'height="15" rx="4" {style}/>')
        p.append(f'<circle cx="{x(sv):.1f}" cy="{46.5 + ROW_GAP:.1f}" r="4.5" '
                 f'fill="{_SVG_INK}" stroke="{_SVG_SURFACE}" stroke-width="2"/>')
        state_text = f"{reference.label} {sv:,.0f}{unit_suffix}"
        if len(state_text) * 6.6 > span:
            # Too long for this card (e.g. "at District of Columbia's rate"
            # in a four-across card). The card's note names the state.
            state_text = f"{'at state rate' if reference.modelled else 'State'} {sv:,.0f}{unit_suffix}"
        p.append(f'<text x="{label_x(x(sv), state_text):.1f}" y="{33 + ROW_GAP:.0f}" font-size="12" '
                 f'fill="{_SVG_MUTED}" text-anchor="middle" {_SVG_HALO}>{state_text}</text>')

    p.append(f'<line x1="{PADL}" y1="{axis_y:.0f}" x2="{W - PADR}" y2="{axis_y:.0f}" '
             f'stroke="{_SVG_RULE}" stroke-width="1"/>')
    for t in _nice_ticks(0.0, d1, tick_target):
        px = x(t)
        anchor = "start" if px < PADL + 16 else "end" if px > W - PADR - 16 else "middle"
        p.append(f'<line x1="{px:.1f}" y1="{axis_y:.0f}" x2="{px:.1f}" y2="{axis_y + 4:.0f}" '
                 f'stroke="{_SVG_RULE}" stroke-width="1"/>')
        p.append(f'<text x="{px:.1f}" y="{axis_y + 16:.0f}" font-size="11" fill="{_SVG_MUTED}" '
                 f'text-anchor="{anchor}">{_fmt_tick(t, unit_suffix)}</text>')
    p.append("</svg>")
    return "".join(p)


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------

def _stats_panel(rows: list[tuple[str, str]], note: str | None = None) -> None:
    body = "".join(
        f"<div class='stat-row'><span class='label'>{label}</span>"
        f"<span class='value'>{value}</span></div>"
        for label, value in rows
    )
    st.markdown(body, unsafe_allow_html=True)
    if note:
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
            "the Census Bureau's own person-level allocation tables and are separate from the margin "
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


# Band colors reuse the Trenton prototype's tier colors (Streamlit/app.py
# TIER_COLOR), per the lead (2026-09-27). Label text uses a darker shade of
# each so it passes WCAG AA (4.5:1) on white; the bar keeps the brand color.
BAND_COLOR = {composite.BAND_HIGHER: "#0072B2", composite.BAND_MODERATE: "#E69F00",
              composite.BAND_LOWER: "#D55E00"}
BAND_TEXT = {composite.BAND_HIGHER: "#005A8C", composite.BAND_MODERATE: "#8A5A00",
             composite.BAND_LOWER: "#A34700"}
BAND_ICON = {composite.BAND_HIGHER: "●", composite.BAND_MODERATE: "▲",
             composite.BAND_LOWER: "■"}


def score_for(measure_key: str, code: str, cv: float,
              imputation_subs: dict[str, pd.Series]) -> composite.ReliabilityScore | None:
    """The card score for one measure in one county (None when CV is NaN)."""
    measure = MEASURES[measure_key]
    if measure.imputation is None:
        return composite.reliability_score(cv, note="not scored")
    src = IMPUTATION_SOURCES[measure.imputation]
    sub = imputation_subs[measure.imputation].get(code, float("nan"))
    if pd.isna(sub):
        return composite.reliability_score(cv, note="not available for this county")
    return composite.reliability_score(cv, float(sub), source=src.label, is_proxy=src.is_proxy)


def _score_strip_html(rs: composite.ReliabilityScore, compact: bool = False) -> str:
    """Band strip for the top of a card: colored bar, band label, score."""
    number = f"<b>{rs.score:.0f}</b> / 100"
    right = number if compact else f"Reliability score {number}"
    return (
        f"<div class='score-strip' style='border-top: 4px solid {BAND_COLOR[rs.band]};'>"
        f"<span class='score-band' style='color: {BAND_TEXT[rs.band]};'>"
        f"<span aria-hidden='true'>{BAND_ICON[rs.band]}</span> {rs.band}</span>"
        f"<span class='score-num'>{right}</span></div>"
    )


def _score_note_html(rs: composite.ReliabilityScore) -> str:
    """One neutral line under the card's dashed divider."""
    if rs.imputation_sub is not None:
        text = f"Sampling {rs.sampling_sub:.0f}, imputation {rs.imputation_sub:.0f}, averaged."
    elif rs.imputation_note == "not available for this county":
        text = "Sampling only: imputation rate not available for this county."
    else:
        text = "Sampling only: imputation is not part of this figure's score."
    return f"<div class='card-alloc'>{text}</div>"


def _score_breakdown_html(rs: composite.ReliabilityScore) -> str:
    """Sub-score bars and facts for 'Show me the statistics'."""
    def bar(label: str, value: float | None, missing: str) -> str:
        if value is None:
            return (f"<div class='score-bar-row'><span class='label'>{label}</span>"
                    f"<span></span><span class='value'>{missing}</span></div>")
        return (f"<div class='score-bar-row'><span class='label'>{label}</span>"
                f"<span class='score-bar'><span style='width: {value:.0f}%;'></span></span>"
                f"<span class='value'>{value:.0f}</span></div>")

    missing = rs.imputation_note or "not scored"
    band = rs.band + (" (capped by the CV)" if rs.capped_by_cv else "")
    source = "none used" if rs.imputation_source is None else (
        rs.imputation_source + (" [proxy]" if rs.imputation_is_proxy else ""))
    return (
        f"<div class='stat-row'><span class='label'>Reliability score</span>"
        f"<span class='value'>{rs.score:.0f} / 100</span></div>"
        f"<div class='stat-row'><span class='label'>Band</span>"
        f"<span class='value'>{band}</span></div>"
        + bar("Sampling", rs.sampling_sub, "")
        + bar("Imputation", rs.imputation_sub, missing)
        + f"<div class='stat-row'><span class='label'>Imputation source</span>"
        f"<span class='value'>{source}</span></div>"
    )


def render_card(
    title: str, est: float, low: float, high: float, *,
    caveat: str | None = None,
    rate: tuple[float, float] | None = None, rate_label: str = "of this group",
    alloc_pct: float | None = None, alloc_label: str = "this figure",
    alloc_denominator: str = "",
    alloc_threshold_pct: float | None = None, alloc_is_proxy: bool = False,
    cv_rank: int | None = None, rank_n: int | None = None,
    rank_scope: str | None = None,
    state_compare: tuple[float, float, str] | None = None,
    reference: StateReference | None = None,
    reference_note: str | None = None,
    toggle_key: str | None = None,
    acs1_compare: tuple[float, float] | None = None,
    geo_label: str | None = None, table_id: str | None = None,
    measure_label: str | None = None, unit_suffix: str = "",
    compact: bool = False,
    reliability: composite.ReliabilityScore | None = None,
) -> None:
    """Neutral-voice card: publishes the estimate, MOE, and CV; never
    recommends. See app_US.py's module docstring, point 3, for the
    de-editorialization direction this implements (sponsor, 2026-08-12).

    `cv_rank`/`rank_n`/`rank_scope`: this measure's CV rank (1 = lowest CV)
    among the `rank_n` counties in `rank_scope` (the county's state) that
    have a CV for it. Ranks the CV only, not the estimate, and is not the
    reliability score.
    `state_compare`: (state_est, state_moe, state_label), if given, adds a
    county-vs-state significant-difference line (90% confidence, Census
    handbook test) with the nested-geography caveat.
    `reference`: the state comparison row drawn under the county bar (see
    StateReference and _interval_svg). Separate from `state_compare` on
    purpose: `state_compare` drives a PROSE test and is safe for any
    measure, while the row shares the county's axis and is therefore only
    valid where the two sit on the same scale. Total population passes the
    former and not the latter.
    Whenever `reference` is given the card carries a "Compare to state"
    toggle, OFF by default (lead decision 2026-09-27, after Census Bureau
    feedback that county and state on one bar was hard to read). Off, the
    card is county only: no state row, the axis fits the county, and the
    reference note and the `state_compare` line are hidden too, since both
    describe the state comparison. Cards without a reference (total
    population) keep their `state_compare` line unconditionally.
    `toggle_key`: unique, stable widget key for that toggle, so each card
    remembers its own setting as the user moves between counties. Falls
    back to `title`, which is NOT unique across the age and poverty bands.
    `reference_note`: required disclosure whenever `reference` holds a
    MODELLED value rather than a published one, so the card never presents
    our arithmetic as a Census Bureau figure.
    `compact`: set by callers rendering into the four-across topic grid,
    where the interval graphic needs its own narrower geometry to keep
    its type legible. See _interval_svg's `compact` note.
    `reliability`: the card's score (lead decision #19); when given, a band
    strip opens the card, a one-line note follows the interval graphic, and
    the breakdown joins "Show me the statistics".
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
        r, g, b, _ = cv_color_blue_orange(cv, alpha=255)
        cv_badge = (
            f"<span class='card-cv-badge' style='background: rgba({r},{g},{b},0.16); "
            f"border-left: 3px solid rgb({r},{g},{b});'>CV {cv * 100:.1f}%</span>"
        )
    with st.container(border=True):
        if reliability is not None:
            st.markdown(_score_strip_html(reliability, compact=compact), unsafe_allow_html=True)
        st.markdown(f"**{title}**")
        st.markdown(
            f"<div class='card-main-row'>"
            f"<span class='card-range'>{est:,.0f}{unit_suffix}</span>"
            + cv_badge +
            f"</div>"
            + rate_line + alloc_line,
            unsafe_allow_html=True,
        )
        show_state = True
        if reference is not None:
            show_state = st.toggle(
                "Compare to state", value=False, key=f"cmp_state::{toggle_key or title}",
                help="Adds the state's figure as a grey row under this county's bar, "
                     "on the same axis. Off shows the county alone.",
            )
        if not np.isnan(cv):
            st.markdown(
                _interval_svg(est, low, high, cv,
                              reference=reference if show_state else None,
                              unit_suffix=unit_suffix, compact=compact),
                unsafe_allow_html=True,
            )
            if reference_note and show_state:
                st.caption(reference_note)
        if reliability is not None:
            st.markdown(_score_note_html(reliability), unsafe_allow_html=True)
        if caveat:
            st.caption(caveat)
        if low < 0:
            st.caption(
                f"The margin of error above the estimate exceeds the estimate itself -- "
                f"the true lower bound is {low:,.0f}{unit_suffix}, shown here as 0 since a "
                f"negative count cannot be cited."
            )
        if cv_rank is not None and rank_n:
            st.markdown(
                f"<div class='card-rank'>This county's CV ranks {_ordinal(cv_rank)} of the "
                f"{rank_n:,} counties in {rank_scope or 'its state'} (1st is the lowest CV)</div>",
                unsafe_allow_html=True,
            )
        if state_compare is not None and show_state:
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
            # Kept whatever the toggle says: this panel is the full breakdown.
            if reference is not None:
                ref_v, ref_lbl, ref_m, modelled = reference
                rows.append((
                    "Expected at the state rate (our estimate)" if modelled
                    else f"State value ({ref_lbl})",
                    f"{ref_v:,.0f}{unit_suffix}"
                    + (f" ± {ref_m:,.0f}{unit_suffix}" if ref_m and np.isfinite(ref_m) else ""),
                ))
            if rate is not None:
                pct, pct_moe = rate
                rows += [
                    ("Rate (estimate)", f"{pct:.1f}%"),
                    (f"Rate {CONFIDENCE_LEVEL_PCT}% CI", f"{rate_lo:.1f}% – {rate_hi:.1f}%"),
                ]
            if alloc_pct is not None:
                rows.append(("Share imputed (allocated)", f"{alloc_pct:.1f}%" + (" [proxy]" if alloc_is_proxy else "")))
                rows.append(("Share of", alloc_denominator))
                if alloc_threshold_pct is not None:
                    rows.append(("Nationwide flag line (75th pct., this denominator)", f"{alloc_threshold_pct:.1f}%"))
            # Methodology copy used to live here and repeated on every card.
            # It now sits once in _explorer_methodology_disclaimer() at the
            # bottom of the County explorer tab.
            _stats_panel(rows)
            if reliability is not None:
                st.markdown(_score_breakdown_html(reliability), unsafe_allow_html=True)

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

PEER_BORDER_COLOR = [136, 34, 196, 255]  # saturated violet, so a peer border never reads as a CV
                                          # signal (statistical peer counties, 2026-08-30). The CV
                                          # ramp now has a purple midpoint (2026-09-16); this violet
                                          # is still at least 0.18 OKLab away from every ramp step,
                                          # the same margin it had from the blue-only ramp.


def _controlled_keys(df: pd.DataFrame, measure: str) -> set[str]:
    """Keys whose estimate for `measure` is controlled: published, with no margin
    of error, for a measure verified to use that convention
    (Measure.controlled_when_moe_missing). Empty for every other measure."""
    m = MEASURES.get(measure)
    if m is None or not m.controlled_when_moe_missing or not len(df):
        return set()
    est, moe = m.values(df)
    mask = est.notna().to_numpy() & moe.isna().to_numpy()
    return set(df["_key"].to_numpy()[mask])


def render_map(
    level: str, keys_in_scope: list[str], cv_by_key: dict, title: str, *,
    selected_key: str | None = None,
    quadrant_by_key: dict | None = None,
    color_map: dict[str, str] | None = None,
    legend_order: tuple[str, ...] | None = None,
    peer_keys: set[str] | None = None,
    controlled_keys: set[str] | None = None,
    view_state: pdk.ViewState,
    map_key: str | None = None,
    interactive: bool = True,
    click_caption: str | None = None,
) -> str | None:
    """GeoJsonLayer choropleth, pickable directly (no separate click grid
    -- see module docstring, point 1). Selects a SUBSET of the prebuilt
    feature list (_base_geojson, cached once per level) rather than
    re-serializing geometry; this is what makes filtering cheap.

    `peer_keys`: counties statistically tied to the selected county on
    whichever measure the Statistical peers tab has chosen -- drawn with
    a violet border, a third state alongside "selected" and "plain,"
    never overriding the fill color, which stays keyed to `cv_by_key`/CV
    regardless of peer status. County explorer does not pass this.

    `map_key`: Streamlit widget key. Defaults to `geo_map_{level}` so the
    explorer map is unchanged. The peers tab passes `geo_map_peers` so
    the two charts cannot collide.

    `interactive=False` draws a display-only map: clicks do not change
    the selected county (no on_select, no click caption, returns None).
    The fill layer stays pickable so hover tooltips still work. Used on
    Statistical peers so a click cannot replace the county chosen by the
    State/County dropdowns.
    """
    key_col = "county_key" if level == "county" else "state_key"
    peer_keys = peer_keys or set()
    controlled = controlled_keys or set()
    by_key = _base_geojson_by_key(level)
    features = []
    for key in keys_in_scope:
        feat = by_key.get(key)
        if feat is None:
            continue
        # MUST copy: _base_geojson is cache_resource (shared object).
        feat = {**feat, "properties": dict(feat["properties"])}
        if quadrant_by_key is not None:
            label = quadrant_by_key.get(key, "No data")
            rgba = _hex_to_rgba(color_map.get(label, color_map["No data"]))
        elif key in controlled:
            rgba = list(CV_COLOR_CONTROLLED) + [200]
        else:
            rgba = cv_color_blue_orange(cv_by_key.get(key, float("nan")))
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
        # pickable stays True even when interactive=False: hover tooltips
        # need picking. Click-to-select is gated below via on_select, not
        # here. (app_NJ.py's "stuck on last row" tooltip failure was the
        # overlapping click-grid, which this file never builds.)
        pickable=True,
        auto_highlight=interactive,
    )
    st.caption(title)
    chart = pdk.Deck(
        layers=[fill_layer], initial_view_state=view_state,
        map_provider="carto", map_style="light",
        tooltip=_map_tooltip(),
    )
    chart_key = map_key if map_key is not None else f"geo_map_{level}"
    if interactive:
        event = st.pydeck_chart(
            chart,
            height=520,
            width="stretch",
            on_select="rerun",
            selection_mode="single-object",
            key=chart_key,
        )
    else:
        st.pydeck_chart(chart, height=520, width="stretch", key=chart_key)
        event = None
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
            for r, g, b, a in [cv_color_blue_orange(t) for t in np.linspace(0, 0.5, 12)]
        )
        st.markdown(
            f"<div>{swatches}</div><span class='legend-label'>CV 0% to 50%+, a continuous "
            f"scale from blue (lower CV) through purple to orange (higher CV, a larger margin "
            f"of error relative to the estimate)</span>",
            unsafe_allow_html=True,
        )
        # Explain every non-ramp color actually on the map, and only those.
        extra = []
        if any(k in controlled for k in keys_in_scope):
            extra.append((CV_COLOR_CONTROLLED, "controlled estimate: no sampling error"))
        if any(k not in controlled and not np.isfinite(cv_by_key.get(k, float("nan")))
               for k in keys_in_scope):
            extra.append((CV_COLOR_NO_DATA, "no margin of error published"))
        if extra:
            st.markdown(
                " &nbsp;&nbsp; ".join(
                    f"<span style='display:inline-block;width:14px;height:11px;"
                    f"background:rgb({c[0]},{c[1]},{c[2]});'></span> "
                    f"<span class='legend-label'>{label}</span>"
                    for c, label in extra
                ),
                unsafe_allow_html=True,
            )
        if peer_keys:
            r, g, b, _ = PEER_BORDER_COLOR
            st.markdown(
                f"<span style='display:inline-block;width:14px;height:11px;"
                f"border:2px solid rgb({r},{g},{b});'></span> "
                f"<span class='legend-label'>statistical peer on the measure chosen above "
                f"(fill color is still CV)</span>",
                unsafe_allow_html=True,
            )
    if click_caption is not None:
        st.caption(click_caption)
    elif interactive:
        st.caption(
            "Hover for the name. Click a state or county to inspect it below, "
            "or use the search box in the panel on the left."
        )

    if not interactive:
        return None
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
    st.session_state.setdefault(
        "us_geo", {"level": "state", "code": None, "state_scope": None}
    )
    st.session_state.setdefault("_us_geo_version", 0)
    st.session_state.setdefault("peer_map_visible", False)


_COUNTY_PLACEHOLDER = "Select a county"


def _current_state_key(geo: dict, data: dict) -> str | None:
    """State FIPS currently in scope: drilled state, selected state, or the
    selected county's parent. Shared by the explorer search and Statistical
    peers so the two tabs stay on the same place.
    """
    current_state = geo.get("state_scope")
    if not current_state and geo.get("level") == "county" and geo.get("code"):
        row = data["county_df"][data["county_df"]["_key"] == geo["code"]]
        if not row.empty:
            current_state = str(row["STATE"].iloc[0])
    if not current_state and geo.get("level") == "state" and geo.get("code"):
        current_state = geo["code"]
    return current_state


def geography_search_control(search_slot, data: dict, filtered_county_df: pd.DataFrame) -> None:
    """State search, then a county search scoped to that state.

    Renders into `search_slot` (a container reserved inside the
    explorer's left-hand panel by top_filters, see its docstring) rather
    than the sidebar (change B, 2026-08-18) -- called from
    _explorer_top_fragment AFTER the map/click handling, not from inside top_filters
    itself, so these dropdowns' seed values reflect a map click made
    earlier in the SAME rerun rather than lagging one click behind.

    County options come from `filtered_county_df` so Metro / population
    filters apply to the list.
    """
    geo = st.session_state["us_geo"]
    version = st.session_state["_us_geo_version"]

    state_items = sorted(
        {data["labels_state"].get(k, k): k for k in data["state_df"]["_key"]}.items()
    )
    state_display = [lbl for lbl, _ in state_items]
    state_key_by_label = dict(state_items)
    current_state = _current_state_key(geo, data)

    state_widget_key = f"us_geo_state_{version}"
    if state_widget_key not in st.session_state:
        seed = data["labels_state"].get(current_state) if current_state else None
        st.session_state[state_widget_key] = seed if seed in state_display else state_display[0]

    with search_slot:
        state_choice = st.selectbox("Search for a state", state_display, key=state_widget_key)

        state_code = state_key_by_label[state_choice]
        state_changed = state_code != current_state
        if state_changed:
            keep_code = geo.get("code") if geo.get("level") == "county" else None
            if keep_code:
                row = data["county_df"][data["county_df"]["_key"] == keep_code]
                if row.empty or str(row["STATE"].iloc[0]) != str(state_code):
                    keep_code = None
            if geo.get("level") == "county":
                geo.update(level="county", code=keep_code, state_scope=state_code)
            else:
                geo.update(level="state", code=state_code, state_scope=None)
            st.session_state["_us_geo_version"] += 1

        county_df = children_of("county", state_code, filtered_county_df, specs=US_LEVEL_SPECS)
        if len(county_df) == 0:
            county_display = ["(no counties match the current filters)"]
            county_key_by_label: dict[str, str] = {}
            disabled = True
        else:
            county_items = sorted(
                {data["labels_county"].get(k, k): k for k in county_df["_key"]}.items()
            )
            county_display = [_COUNTY_PLACEHOLDER] + [lbl for lbl, _ in county_items]
            county_key_by_label = dict(county_items)
            disabled = False

        county_widget_key = f"us_geo_county_{version}_{state_code}"
        if st.session_state.get(county_widget_key) not in county_display:
            seed = (
                data["labels_county"].get(geo.get("code"))
                if geo.get("level") == "county" and geo.get("code")
                else None
            )
            st.session_state[county_widget_key] = seed if seed in county_display else county_display[0]

        county_choice = st.selectbox(
            "Search for a county", county_display, key=county_widget_key, disabled=disabled,
        )

    # A leftover county widget from before Back / a state change must not
    # write the previous county back into us_geo on this same run.
    if state_changed:
        return

    if disabled or county_choice not in county_key_by_label:
        if geo.get("level") == "county" and geo.get("code") is not None:
            geo["code"] = None
            st.session_state["_us_geo_version"] += 1
        return

    chosen = county_key_by_label[county_choice]
    if chosen != geo.get("code") or geo.get("level") != "county":
        geo.update(level="county", code=chosen, state_scope=state_code)
        st.session_state["_us_geo_version"] += 1


# ---------------------------------------------------------------------------
# Welcome tab (change G, 2026-08-18) -- plain-language orientation, no
# statistics background assumed. First tab, selected by default (st.tabs'
# own behavior -- the first tab passed to it is the initial selection).
# Every term gets a one-line definition on first use, per CLAUDE.md, same
# rule _term() enforces on Streamlit/pages/1_Whose_data_is_this.py.
# ---------------------------------------------------------------------------

def render_welcome() -> None:
    """Goal-oriented Welcome page for nontechnical users and grant writers.

    Ported from app_US_v5_welcome.py's render_welcome() (2026-09-28, Katie
    Christiansen) -- layout, section order, and HTML cards carried over
    whole, with the facts corrected for what THIS app (v4) actually does:
    Statistical peers is its own tab (v5's draft text called it a panel),
    the CV rank is "Nth of N counties in the state" (v5's text still said
    a percentile of the current filter, the pre-2026-09-27 behavior), the
    measure list includes v4's employment/education/disability topics,
    and "Filter counties" is described as the panel beside the map
    (_explorer_top_fragment), since v4 has no separately-labelled filter
    panel of that name. Dollar amounts inside the HTML goal cards use the
    numeric character reference &#36; rather than a literal '$' -- a pair
    of literal '$' in one st.markdown() string is read as LaTeX math
    delimiters (see _INCOME_BAND_TITLES above for the same issue on plain
    markdown, where \\$ is used instead).
    """

    st.markdown('<div class="welcome-section">Where should I start?</div>', unsafe_allow_html=True)
    step1, step2, step3 = st.columns(3)
    for col, number, title, desc in [
        (step1, "1", "Choose a place",
         "Open <b>County explorer</b>, click a state and county on the map, or search for a state and county by name."),
        (step2, "2", "Choose your data",
         "Start with population or income, then add poverty, employment, education, housing, health "
         "insurance, disability, language, or transportation measures &mdash; 26 figures across ten "
         "topics in all."),
        (step3, "3", "Check uncertainty",
         "Every ACS estimate has a margin of error. Use the confidence interval and CV to understand how precise it is."),
    ]:
        with col:
            st.markdown(
                f'<div class="step-card"><div class="step-number">{number}</div>'
                f'<h4>{title}</h4><p>{desc}</p></div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div class="welcome-section">What can I do with the County explorer?</div>', unsafe_allow_html=True)
    goals = [
        ("\U0001F4CA Find a Census number",
         "Find population, income, poverty, employment, education, housing, health insurance, "
         "disability, language, or transportation figures for a county."),
        ("\U0001F4DD Write a grant application",
         "Find a statistic, review its uncertainty, and use <b>Show me the statistics</b> for a ready-to-copy citation sentence."),
        ("\U0001F50E Compare counties",
         "Turn on a card's <b>Compare to state</b> switch to see your county against the state, or open the "
         "<b>Statistical peers</b> tab to find counties that are statistically indistinguishable from yours."),
        ("\u26A0\uFE0F Check how reliable a number is",
         "Use the margin of error, 90% confidence interval, and coefficient of variation to understand uncertainty."),
    ]
    for row in (goals[:2], goals[2:]):
        cols = st.columns(2)
        for col, (title, desc) in zip(cols, row):
            with col:
                st.markdown(
                    f'<div class="goal-card"><h4>{title}</h4><p>{desc}</p></div>',
                    unsafe_allow_html=True,
                )

    st.markdown('<div class="welcome-section">How can I read uncertainty?</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="uncertainty-box">'
        "<b>Think about the margin of error relative to the estimate.</b> "
        "The same &#36;500 margin of error means something very different for a "
        "&#36;10,000 estimate than for a &#36;500,000 estimate."
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)

    a, b = st.columns(2)
    with a:
        st.markdown(
            '<div class="goal-card"><h4>&#36;10,000 estimate</h4>'
            "<p>A &plusmn;&#36;500 margin of error represents <b>5%</b> of the estimate.</p></div>",
            unsafe_allow_html=True,
        )
    with b:
        st.markdown(
            '<div class="goal-card"><h4>&#36;500,000 estimate</h4>'
            "<p>A &plusmn;&#36;500 margin of error represents only <b>0.1%</b> of the estimate.</p></div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="cv-legend-box">'
        '<b class="cv-low">Blue = lower CV / more certain</b>'
        "&nbsp;&nbsp;&nbsp;"
        '<b class="cv-high">Orange = higher CV / less certain</b><br>'
        '<span class="cv-note">Purple marks the middle of the scale. '
        "The color scale is continuous, not a pass/fail grade.</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)

    with st.expander("What is the coefficient of variation (CV)?"):
        st.markdown(
            "The **coefficient of variation (CV)** describes the margin of error relative to the "
            "estimate itself. A lower CV means less uncertainty relative to the estimate; a higher "
            "CV means more."
        )
    with st.expander("What is the margin of error (MOE)?"):
        st.markdown(
            "The **margin of error (MOE)** shows how much the Census estimate could vary due to "
            "sampling uncertainty. A smaller MOE means a more precise estimate."
        )
    with st.expander("What does the 90% confidence interval mean?"):
        st.markdown(
            "The **90% confidence interval** shown on each card is the range associated with the "
            "Census Bureau's published margin of error. In repeated sampling, about 90% of similarly "
            "constructed intervals would contain the true population value."
        )
    with st.expander("What other reliability information might I see?"):
        st.markdown(
            "Depending on the measure, the app may also show:\n"
            "- **CV rank** \u2014 where the county's uncertainty falls among all counties in its "
            "state, from 1st (lowest CV) to the last county.\n"
            "- **Reliability score** \u2014 a band (Higher / Moderate / Lower reliability) combining "
            "the CV with, for income and poverty figures, how much of the total was imputed.\n"
            "- **Share imputed (allocated)** \u2014 the portion for which Census filled in missing "
            "responses.\n"
            "- **Derived rate** \u2014 a percentage calculated from Census counts and their universe "
            "(poverty, low income, unemployment, renter cost burden, no high school diploma, "
            "disability, uninsured, limited-English, no-vehicle, and income-bracket cards). Rent "
            "burden is different: it is a rate published by the Census Bureau, not one calculated "
            "by this app.\n"
            "- **Controlled estimate** \u2014 total population has no margin of error in most "
            "counties, because the Census Bureau pins it to its official population estimates.\n"
            "- **Statistical peer tie-set size** \u2014 how many counties are statistically "
            "indistinguishable from the selected county."
        )

    st.markdown('<div class="welcome-section">What is a real-world example of using the tool?</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="example-box">'
        '<div class="example-title">Example: "To write a grant, I need my county\'s poverty rate."</div>'
        "<div>Use the steps below as a quick starting point for a grant-writing task.</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(4)
    for col, title, desc in zip(
        cols,
        ["1. Find your county", "2. Add Poverty", "3. Review uncertainty", "4. Get your citation"],
        [
            "Open County explorer and select your county.",
            "Choose the poverty measure you need.",
            "Look at the estimate, MOE, and confidence interval.",
            'Open "Show me the statistics" to copy the citation.',
        ],
    ):
        with col:
            st.markdown(f"**{title}**")
            st.caption(desc)

    st.info(
        "Tip: The citation helps document where a figure came from. Make sure the measure and "
        "geography match the claim you are making."
    )

    st.markdown('<div class="welcome-section">What is this data?</div>', unsafe_allow_html=True)
    with st.expander("What is the American Community Survey (ACS)?"):
        st.markdown(
            "The **American Community Survey (ACS)** is an ongoing national survey conducted by "
            "the U.S. Census Bureau. It provides information about population, income, poverty, "
            "employment, education, housing, health insurance, disability, language, transportation, "
            "and other characteristics. Because it surveys a sample rather than every household, its "
            "estimates include uncertainty."
        )
    with st.expander("Why does every number have a margin of error?"):
        st.markdown(
            "A **margin of error (MOE)** is a range around an ACS estimate that reflects sampling "
            "uncertainty. A wider margin of error means the estimate is less precise than one with "
            "a narrower margin."
        )
    with st.expander("What is a derived rate?"):
        st.markdown(
            "Some measures show a percentage calculated from Census counts and their universe, "
            "including poverty, low income, unemployment, renter cost burden, no high school "
            "diploma, disability, uninsured, limited-English, no-vehicle, and income-bracket rates. "
            "**Rent burden is different:** it is a rate published by the Census Bureau rather than "
            "calculated by this app."
        )

    st.markdown('<div class="welcome-section">How can I use the explorer?</div>', unsafe_allow_html=True)
    with st.expander("Find a state or county"):
        st.markdown(
            "Open **County explorer**. Click a state on the national map, then a county, or use "
            "**Search for a state** and **Search for a county**. Use **Back to national state view** to return."
        )
    with st.expander("Filter the counties shown on the map"):
        st.markdown(
            "The panel to the left of the map has **Metro / nonmetro**, **Population size**, "
            "**Search for a state**, **Search for a county**, and **Color the map by** to "
            "narrow or recolor the map."
        )
    with st.expander("Choose the figures you want to see"):
        st.markdown(
            "After selecting a county, use the checklist to choose measures. The app starts with "
            "**total population** and **median household income**, then lets you add poverty, "
            "employment, education, income brackets, health insurance, disability, language, "
            "housing, and transportation \u2014 26 figures across ten topics."
        )

    st.markdown('<div class="welcome-section">What questions can this tool help me answer?</div>', unsafe_allow_html=True)
    with st.expander("Does my county really differ from the state?"):
        st.markdown(
            "Most cards have a **Compare to state** switch. Turn it on and a grey bar for the "
            "state appears under your county's bar; for counts, that bar is this tool's own "
            "calculation (the state's rate applied to your county), drawn with a dashed outline. "
            "The **Total population** card, and the **Median household income** card with the "
            "switch on, also say whether your county's estimate differs from the state's at 90% "
            "confidence, when both have a published margin of error."
        )
    with st.expander("Which counties are statistically similar to mine?"):
        st.markdown(
            "The **Statistical peers** tab identifies counties whose estimates are statistically "
            "indistinguishable from yours at 90% confidence. That group is still a tie set. "
            "**Rank** and **Similarity** only order those counties by how close the published "
            "estimates are."
        )
        st.markdown(
            "The size of that group is itself a reliability signal. A small group means the measure "
            "is precise enough to set your county apart from similar ones; a large group means it "
            "cannot, at this county's size. That describes the measure, not a flaw in this tool."
        )
    with st.expander("Can I use these numbers in a grant application?"):
        st.markdown(
            "The app is designed to help users locate and document Census estimates for research, "
            "planning, and grant-writing tasks. Before using a number, check the geography, measure, "
            "estimate, margin of error, and confidence interval. Use **Show me the statistics** for "
            "the detailed breakdown and citation."
        )

    st.markdown('<div class="welcome-section">What are the limits of this explorer?</div>', unsafe_allow_html=True)
    with st.expander("Know what this tool does not do"):
        st.markdown(
            "**This tool does not:**\n"
            "- provide neighborhood-level estimates;\n"
            "- show year-over-year trends;\n"
            "- predict whether a measure will rise or fall;\n"
            "- create new Census estimates; or\n"
            '- rank counties as "best" or "worst."\n\n'
            "The explorer currently works at the **county level** and uses **2020\u20132024 5-year "
            "estimates**. Newer measures can cover smaller populations, so small counties may have "
            "wider margins of error."
        )

    st.markdown('<div class="welcome-section">Need a definition?</div>', unsafe_allow_html=True)
    st.markdown(
        "<div>"
        '<span class="glossary-pill">ACS \u2014 American Community Survey</span>'
        '<span class="glossary-pill">MOE \u2014 Margin of Error</span>'
        '<span class="glossary-pill">CV \u2014 Coefficient of Variation</span>'
        '<span class="glossary-pill">90% CI \u2014 90% Confidence Interval</span>'
        '<span class="glossary-pill">Statistical Peer \u2014 90% Tie Set</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
    st.success(
        "Ready to explore? Open the **County explorer** tab, choose a place, select a measure, "
        "and use the uncertainty information to put the number in context."
    )


# ---------------------------------------------------------------------------
# Statistical peer counties panel (2026-08-30)
# ---------------------------------------------------------------------------

def _peer_moe_column_name() -> str:
    return f"\u00b1 margin of error ({CONFIDENCE_LEVEL_PCT}% CI)"


# How many ranked tied counties the table and the peer map list.
PEER_LIST_CHOICES = ("10", "25", "50", "100", "All")


def _peer_list_limit(choice: str | None = None) -> int | None:
    """Row cap for the ranked peer list. None means every tied county."""
    if choice is None:
        choice = st.session_state.get("peer_list_n", "25")
    if choice == "All":
        return None
    try:
        return int(choice)
    except (TypeError, ValueError):
        return 25


def _peer_display_table(
    peers: pd.DataFrame, *, labels: dict, self_est: float
) -> pd.DataFrame:
    """Ranked peer rows. Index stays the county `_key`.

    Rank 1 is the published estimate closest to the selected county.
    Identical estimates share a rank (min). Similarity is 100 when the
    estimates match and falls toward 0 as the absolute gap grows relative
    to the selected county's estimate. CV is the 0-1 coefficient of
    variation ((MOE / 1.645) / estimate), same convention as the cards
    and map.
    """
    table = peers.copy()
    table["County"] = [labels.get(k, k) for k in table.index]
    table["Distance"] = (table["est"] - self_est).abs()
    table["Rank"] = table["Distance"].rank(method="min").astype("int64")
    denom = abs(float(self_est))
    if not np.isfinite(denom) or denom == 0.0:
        denom = float(np.finfo(float).tiny)
    table["Similarity"] = (100.0 * (1.0 - table["Distance"] / denom)).clip(0.0, 100.0)
    table["CV"] = moe_to_cv(table["est"], table["moe"])
    table = table.sort_values(["Distance", "County"], kind="mergesort")
    moe_col = _peer_moe_column_name()
    return table[["Rank", "County", "Similarity", "est", "moe", "CV"]].rename(
        columns={"est": "Estimate", "moe": moe_col}
    )


def _listed_peer_table(
    peers: pd.DataFrame, *, labels: dict, self_est: float, limit: int | None,
) -> pd.DataFrame:
    """Ranked peer rows, capped at `limit` (None = all). Index is county `_key`."""
    table = _peer_display_table(peers, labels=labels, self_est=self_est)
    if limit is None:
        return table
    return table.head(limit)


def _peer_display_column_config() -> dict:
    """Thousands separators on Estimate/MOE; CV as a percent.

    NumberColumn formats the display; the values stay numeric so column
    sort still works. `localized` adds locale commas (110884 -> 110,884)
    without rounding rates to integers.
    """
    moe_col = _peer_moe_column_name()
    return {
        "Rank": st.column_config.NumberColumn(format="%d"),
        "Similarity": st.column_config.NumberColumn(
            format="%.1f",
            help="100 = identical published estimate to the selected county.",
        ),
        "Estimate": st.column_config.NumberColumn(format="localized"),
        moe_col: st.column_config.NumberColumn(format="localized"),
        "CV": st.column_config.NumberColumn(
            format="percent",
            help="Coefficient of variation: (margin of error / 1.645) / estimate.",
        ),
    }


def render_peer_panel(data: dict, code: str, label: str) -> PeerResult | None:
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

    Renders the measure selectbox, structural checkboxes, headline, and
    table. Returns the PeerResult (including an empty tie set) so
    render_peers_tab() can own show/hide and the map. Returns None when
    no comparison can be run (no measure chosen, or the selected county
    has no estimate / no published margin of error).
    """
    st.caption(
        "Peers are drawn from all U.S. counties (optionally narrowed by the checkboxes "
        "below), not County explorer's map filters. Those filters exist to narrow the "
        "explorer map, and reusing them here would make the peer count depend on a "
        "control set for an unrelated reason."
    )
    measure_col, rucc_col, pop_col = st.columns([2, 1, 1])
    with measure_col:
        peer_options = [k for k in PEER_MEASURES if k not in _unavailable_measures(data)]
        if st.session_state.get("peer_measure") not in (None, *peer_options):
            del st.session_state["peer_measure"]
        peer_measure = st.selectbox(
            "Find counties statistically tied to this one on...", peer_options,
            index=None, format_func=_measure_display, key="peer_measure",
            placeholder="Choose a measure to find statistical peers",
        )
    with rucc_col:
        same_rucc = st.checkbox("Same metro/nonmetro class", value=True, key="peer_same_rucc")
    with pop_col:
        same_popbin = st.checkbox("Same population-size bin", value=True, key="peer_same_popbin")

    if not peer_measure:
        st.info("Choose a measure above to find this county's statistical peers.")
        return None

    result = _compute_peers(data["county_df"], code, peer_measure, same_rucc, same_popbin)
    if result is None or pd.isna(result.self_est) or pd.isna(result.self_moe):
        st.caption(
            f"{label}'s estimate for {_measure_display(peer_measure)} is not available, or has "
            "no published margin of error, so no peer comparison can be run for it."
        )
        return None

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
        list_choice = st.selectbox(
            "Listed counties",
            list(PEER_LIST_CHOICES),
            index=list(PEER_LIST_CHOICES).index("25"),
            key="peer_list_n",
            help="How many of the closest tied counties to show in the table and on the map.",
        )
        display = _listed_peer_table(
            result.peers,
            labels=data["labels_county"],
            self_est=result.self_est,
            limit=_peer_list_limit(list_choice),
        )
        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            column_config=_peer_display_column_config(),
        )
        st.caption(
            f"Showing {len(display):,} of {n_tied:,} statistically tied counties, ranked by "
            "closeness of the published estimate. Every county listed is still statistically "
            f"indistinguishable at {CONFIDENCE_LEVEL_PCT}% confidence."
        )
    return result


def _peer_geo_controls(data: dict) -> str | None:
    """Cascading State, then County dropdowns that read/write shared us_geo.

    Returns the selected county key, or None until a county is chosen.
    Widget keys include `_us_geo_version` so a County explorer map click
    or search re-seeds these controls instead of fighting them.
    """
    geo = st.session_state["us_geo"]
    version = st.session_state["_us_geo_version"]

    state_items = sorted(
        {data["labels_state"].get(k, k): k for k in data["state_df"]["_key"]}.items()
    )
    state_display = [lbl for lbl, _ in state_items]
    state_key_by_label = dict(state_items)

    current_state = _current_state_key(geo, data)

    state_widget_key = f"peer_tab_state_{version}"
    if state_widget_key not in st.session_state:
        seed = data["labels_state"].get(current_state) if current_state else None
        if seed in state_display:
            st.session_state[state_widget_key] = seed

    state_col, county_col = st.columns(2)
    with state_col:
        state_choice = st.selectbox(
            "State", state_display, index=None,
            placeholder="Select a state", key=state_widget_key,
        )
    if not state_choice:
        with county_col:
            st.selectbox(
                "County", [_COUNTY_PLACEHOLDER], index=0,
                key=f"peer_tab_county_{version}_none", disabled=True,
            )
        return None

    state_code = state_key_by_label[state_choice]
    # Compare to the derived seed, not geo["state_scope"]. Visiting this tab
    # while County explorer is still at state level (code is a state key,
    # state_scope is None) must not auto-drill the explorer map.
    if state_code != current_state:
        keep_code = geo.get("code") if geo.get("level") == "county" else None
        if keep_code:
            row = data["county_df"][data["county_df"]["_key"] == keep_code]
            if row.empty or str(row["STATE"].iloc[0]) != str(state_code):
                keep_code = None
        geo.update(level="county", code=keep_code, state_scope=state_code)
        st.session_state["_us_geo_version"] += 1
        st.rerun()

    county_df = children_of("county", state_code, data["county_df"], specs=US_LEVEL_SPECS)
    county_items = sorted(
        {data["labels_county"].get(k, k): k for k in county_df["_key"]}.items()
    )
    county_display = [_COUNTY_PLACEHOLDER] + [lbl for lbl, _ in county_items]
    county_key_by_label = dict(county_items)

    county_widget_key = f"peer_tab_county_{version}_{state_code}"
    if county_widget_key not in st.session_state:
        seed = data["labels_county"].get(geo.get("code")) if geo.get("code") else None
        st.session_state[county_widget_key] = seed if seed in county_display else _COUNTY_PLACEHOLDER

    with county_col:
        county_choice = st.selectbox("County", county_display, key=county_widget_key)

    if county_choice == _COUNTY_PLACEHOLDER:
        # Only clear a county selection. A state-level geo["code"] is a
        # state key from County explorer; wiping it would deselect that
        # state just by opening this tab.
        if geo.get("level") == "county" and geo.get("code") is not None:
            geo["code"] = None
            st.session_state["_us_geo_version"] += 1
            st.rerun()
        return None

    chosen = county_key_by_label[county_choice]
    if chosen != geo.get("code") or geo.get("level") != "county":
        geo.update(level="county", code=chosen, state_scope=state_code)
        st.session_state["_us_geo_version"] += 1
        st.rerun()
    return chosen


def render_peers_tab(data: dict) -> None:
    """Statistical peers: pick a county, list the tie set, optionally map it.

    Own tab so the County explorer map is no longer a second job for this
    comparison. Selection is the shared us_geo record; the map on this
    tab is display-only.
    """
    _init_geo_state()
    st.markdown("##### Statistical peers")
    st.caption(
        "Counties whose American Community Survey estimate is statistically "
        "indistinguishable from the selected county at 90% confidence. "
        "The map on this tab shows the counties listed in the table. It does not replace "
        "County explorer's state-to-county drill-down."
    )

    code = _peer_geo_controls(data)
    if not code:
        if st.session_state.get("peer_map_visible"):
            st.session_state["peer_map_visible"] = False
        st.info("Select a state and county above to find statistical peers.")
        return

    label = data["labels_county"].get(code, code)
    result = render_peer_panel(data, code, label)
    n_tied = 0 if result is None else len(result.peers)
    if n_tied == 0 and st.session_state.get("peer_map_visible"):
        st.session_state["peer_map_visible"] = False

    if result is None:
        return

    show_col, hide_col = st.columns(2)
    with show_col:
        if st.button(
            "Show these counties on the map",
            disabled=n_tied == 0,
            key="peer_map_show",
        ):
            st.session_state["peer_map_visible"] = True
            st.rerun()
    with hide_col:
        if st.session_state.get("peer_map_visible") and st.button(
            "Hide peer map", key="peer_map_hide",
        ):
            st.session_state["peer_map_visible"] = False
            st.rerun()

    if not st.session_state.get("peer_map_visible") or n_tied == 0:
        return

    listed = _listed_peer_table(
        result.peers,
        labels=data["labels_county"],
        self_est=result.self_est,
        limit=_peer_list_limit(),
    )
    if listed.empty:
        return
    listed_keys = set(listed.index)
    subset_keys = {code} | listed_keys
    geo_df = data["county_df"][data["county_df"]["_key"].isin(subset_keys)]
    geo_gdf = data["county_geo"][data["county_geo"]["_key"].isin(subset_keys)]
    view = _state_view(geo_gdf) if len(geo_gdf) else NATIONAL_VIEW
    cv_by_key, _, _, _, quadrant_by_key, color_map, legend_order, title = _measure_layer(
        geo_df, result.measure_key, data["alloc_county"], data["income_alloc_threshold"]
    )
    render_map(
        "county", geo_df["_key"].tolist(), cv_by_key, title,
        selected_key=code, quadrant_by_key=quadrant_by_key,
        color_map=color_map, legend_order=legend_order, view_state=view,
        peer_keys=listed_keys,
        controlled_keys=_controlled_keys(geo_df, result.measure_key),
        map_key="geo_map_peers",
        interactive=False,
        click_caption="Hover a county for its name. Clicks do not change the selected county.",
    )


# ---------------------------------------------------------------------------
# County explorer -- map, filters, and per-county cards. This was the
# entire main() body before change G (2026-08-18) moved it under its own
# tab so a first-time visitor lands on Welcome instead.
# ---------------------------------------------------------------------------

# Left panel height, matched to the map column (title caption + 520px
# pydeck chart) plus the stacked state and county search dropdowns.
EXPLORER_PANEL_HEIGHT = 640


@st.fragment
def _explorer_top_fragment(data: dict, unavailable: set[str]) -> None:
    """Filters, geography search, and map colour in a panel on the left;
    the choropleth, wider, on the right. Isolated so a filter or colour
    change redraws only this block and not the cards. Anything that moves
    the selected geography (map pick, search, back button) reruns the
    whole app so the cards follow.
    """
    geo = st.session_state["us_geo"]
    level = geo["level"]
    start = (geo["level"], geo["code"], geo["state_scope"])

    controls_col, map_col = st.columns([1, 2.6], gap="medium")
    with controls_col:
        panel = st.container(border=True, height=EXPLORER_PANEL_HEIGHT)
    with panel:
        filtered_county_df, search_slot = top_filters(data["county_df"], level, geo)
        map_options = [o for o in MEASURE_OPTIONS if o not in unavailable]
        # A value saved in an earlier session can outlive its data; clear it
        # rather than hand Streamlit an option that is no longer in the list.
        if st.session_state.get("acs_map_measure") not in (None, *map_options):
            del st.session_state["acs_map_measure"]
        measure = st.selectbox(
            "Color the map by", map_options, key="acs_map_measure",
            index=map_options.index(DEFAULT_MAP_MEASURE) if DEFAULT_MAP_MEASURE in map_options else 0,
            format_func=_measure_display,
        )
        if unavailable:
            st.caption(
                f"{len(unavailable)} measure(s) are not in your local data yet and are hidden "
                f"from this list. Re-run {_REPULL_HINT} to add them."
            )

    if level == "county" and geo["state_scope"]:
        geo_df = children_of("county", geo["state_scope"], filtered_county_df, specs=US_LEVEL_SPECS)
        geo_gdf = data["county_geo"][data["county_geo"]["_key"].isin(set(geo_df["_key"]))]
        view = _state_view(geo_gdf) if len(geo_gdf) else NATIONAL_VIEW
    elif level == "county":
        geo_df = filtered_county_df
        view = NATIONAL_VIEW
    else:
        geo_df = data["state_df"]
        view = NATIONAL_VIEW

    with map_col:
        picked = _explorer_map(data, level, geo, geo_df, view, measure)

    if picked and picked != st.session_state.get("_us_map_last_picked"):
        st.session_state["_us_map_last_picked"] = picked
        if level == "state":
            geo.update(level="county", code=None, state_scope=picked)
        else:
            geo["code"] = picked
        st.session_state["_us_geo_version"] += 1
        st.rerun()

    geography_search_control(search_slot, data, filtered_county_df)
    if (geo["level"], geo["code"], geo["state_scope"]) != start:
        st.rerun()


def _explorer_map(
    data: dict, level: str, geo: dict, geo_df: pd.DataFrame, view: pdk.ViewState, measure: str,
) -> str | None:
    """The explorer choropleth for `measure`; returns the clicked key, if any."""
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

    if not len(geo_df):
        st.info("No geographies match the current filter selection. Loosen a filter in the panel on the left.")
        return None
    return render_map(
        level, geo_df["_key"].tolist(), cv_by_key, title,
        selected_key=geo["code"], quadrant_by_key=quadrant_by_key,
        color_map=color_map, legend_order=legend_order, view_state=view,
        controlled_keys=_controlled_keys(geo_df, measure),
    )


@st.fragment
def _explorer_cards_fragment(
    data: dict, code: str, label: str, row: pd.DataFrame, state_row: pd.DataFrame,
    unavailable: set[str],
) -> None:
    """Checklist + card grid. Isolated so adding a card does not rebuild
    the explorer map.

    Each card's CV rank is among every county in the selected county's
    state, not the explorer's filter selection, so the rank and its
    "of N" always describe the same group.
    """
    rank_pool = data["county_df"][data["county_df"]["STATE"] == row["STATE"].iloc[0]]
    rank_scope = str(state_row["NAME"].iloc[0]) if len(state_row) else "this state"
    _layer_cache: dict[str, pd.Series] = {}

    def _cv_series_for(measure_name: str) -> pd.Series:
        cached = _layer_cache.get(measure_name)
        if cached is not None:
            return cached
        result = _measure_layer(
            rank_pool, measure_name, data["alloc_county"], data["income_alloc_threshold"]
        )
        series = pd.Series(result[0], dtype=float)
        _layer_cache[measure_name] = series
        return series

    def _rank_and_n(measure_name: str, key: str) -> tuple[int | None, int]:
        """1-based CV rank (1 = lowest CV) and the number of ranked counties."""
        series = _cv_series_for(measure_name).dropna()
        n = len(series)
        if key not in series.index:
            return None, n
        return int(series.rank(method="min")[key]), n

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
        if measure_label in unavailable:
            with st.container(border=True):
                st.markdown(f"**{measure.label}**")
                st.caption(
                    f"This measure is not in your local data yet. Re-run {_REPULL_HINT} "
                    f"to add it, then restart the app."
                )
            return
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

        # Reference marker. Which KIND depends on the measure: a published
        # state value for medians/percentages, our modelled state-rate
        # expectation for counts. See Measure.reference_mode.
        ref, ref_note = None, None
        state_name = str(state_row["NAME"].iloc[0]) if len(state_row) else ""
        mode = measure.reference_mode
        if len(state_row) and mode == "direct":
            state_est, state_moe = (float(v.iloc[0]) for v in measure.values(state_row))
            if pd.notna(state_est):
                ref = StateReference(state_est, state_name,
                                     state_moe if pd.notna(state_moe) else None, modelled=False)
        elif len(state_row) and mode == "rate":
            uni = measure.rate_universe
            s_est, s_moe = (float(v.iloc[0]) for v in measure.values(state_row))
            su_est, su_moe = (float(v.iloc[0]) for v in uni(state_row))
            cu_est, cu_moe = (float(v.iloc[0]) for v in uni(row))
            exp, exp_moe = expected_at_rate(s_est, s_moe, su_est, su_moe, cu_est, cu_moe)
            if np.isfinite(exp):
                ref = StateReference(exp, f"at {state_name}'s rate",
                                     exp_moe if np.isfinite(exp_moe) else None, modelled=True)
                pct_of_state = 100.0 * s_est / su_est if su_est else float("nan")
                # Short on the card face; the full methodology lives in the
                # tab-level disclaimer at the bottom of County explorer.
                ref_note = (
                    f"The dashed grey bar is not a published figure: it is what this county "
                    f"would show at {state_name}'s rate of {pct_of_state:.1f}%"
                    + (", with a dot and no bar, because its margin of error could not be computed."
                       if ref.moe is None else
                       f". Its width is that expectation's own margin of error, ±{ref.moe:,.0f}.")
                )

        rank, n = _rank_and_n(measure_label, code)
        render_card(
            measure.label, e, *acs_range(e, m),
            rate=rate, rate_label=measure.rate_label,
            cv_rank=rank, rank_n=n, rank_scope=rank_scope, reference=ref, reference_note=ref_note,
            toggle_key=measure_label,
            geo_label=label, table_id=measure.table_id,
            measure_label=measure.measure_label, unit_suffix=measure.unit_suffix,
            compact=True,
            reliability=score_for(measure_label, code, cv_from_range(e, *acs_range(e, m)),
                                  data["imputation_subs"]),
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
                            "No margin of error, by design: the Census Bureau controls this estimate "
                            "to its official population estimates, so it has no sampling error. It is "
                            "the most reliable kind of ACS figure."
                        )
                else:
                    pop_low, pop_high = acs_range(pop_est, pop_moe)
                    state_pop = state_row["B01001_001E"].iloc[0] if len(state_row) else None
                    state_pop_moe = state_row["B01001_001M"].iloc[0] if len(state_row) else None
                    acs1_pop = (float(acs1_row["B01001_001E"].iloc[0]), float(acs1_row["B01001_001M"].iloc[0])) if len(acs1_row) else None
                    pop_rank, pop_n = _rank_and_n("Total population", code)
                    render_card(
                        "Total population", pop_est, pop_low, pop_high,
                        cv_rank=pop_rank, rank_n=pop_n, rank_scope=rank_scope,
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
                        cv_rank=income_rank, rank_n=income_n, rank_scope=rank_scope,
                        state_compare=(float(state_income), float(state_income_moe), "the state median")
                        if state_income is not None and pd.notna(state_income_moe) and not pd.isna(income_moe) else None,
                        reference=StateReference(
                            float(state_income), str(state_row["NAME"].iloc[0]),
                            float(state_income_moe) if pd.notna(state_income_moe) else None,
                            modelled=False,
                        ) if state_income is not None and pd.notna(state_income) else None,
                        toggle_key="Median household income",
                        acs1_compare=acs1_income,
                        geo_label=label, table_id="B19013",
                        reliability=score_for(
                            "Median household income", code,
                            cv_from_range(income_est, *acs_range(income_est, income_moe)),
                            data["imputation_subs"],
                        ),
                    )

    # Every other selected measure, grouped by topic and chunked into
    # 4-column rows -- replaces the old two hardcoded sections ("Population
    # by age", "Living below the poverty line, by age") with one loop that
    # scales to however many topics a county's selection touches.
    other_labels = [lbl for lbl in selected_labels if lbl not in ("Total population", "Median household income")]
    by_topic: dict[str, list[str]] = {}
    for lbl in other_labels:
        by_topic.setdefault(MEASURES[lbl].topic, []).append(lbl)

    # Hardcoded, so a measure whose topic is missing here never renders and
    # nothing errors. Employment, Education and Disability added with the
    # scope expansion (2026-09-14).
    TOPIC_ORDER = ["Population", "Poverty", "Income", "Employment", "Education", "Housing",
                   "Health", "Disability", "Language", "Transportation"]
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


def _explorer_methodology_disclaimer() -> None:
    """One collapsible copy of the methodology that used to repeat under
    every card's 'Show me the statistics' expander."""
    st.divider()
    with st.expander("Disclaimer: how these figures are calculated"):
        st.caption("Applies to every card on this tab.")
        st.markdown(
            f"**Coefficient of variation (CV).** "
            f"CV = (margin of error / {Z_90:.3f}) / estimate \u2014 the margin of error's "
            f"share of the estimate. ACS margins of error are published at "
            f"{CONFIDENCE_LEVEL_PCT}% confidence."
        )
        st.markdown(
            "**Derived rates.** Rate uses the Census ratio-MOE formula against "
            "this measure's own universe (its true denominator), not total population."
        )
        st.markdown(
            "**State-rate benchmark.** The state-rate benchmark is OUR calculation, "
            "not a Census Bureau publication: the state's rate for this measure, applied "
            "to this county's own universe, because a county count and a state count are "
            "not on the same scale. Its margin of error combines the state rate's and the "
            "county universe's, and treats them as independent, which makes it conservative "
            "since the county is part of the state."
        )
        st.markdown(
            "**Share imputed (allocated).** Allocation is a separate signal from CV \u2014 "
            "a county can have a low CV and still have most of this figure imputed."
        )
        st.markdown(
            "**Reliability score** (our methodology, pending mentor review): the average "
            "of a sampling sub-score set from the CV (100 at 0, 75 at 0.12, the ESRI "
            "high-reliability line, 50 at 0.30, the NCHS caution line, and 0 where the "
            "margin of error equals the estimate) and, for income and poverty figures, "
            "an imputation sub-score comparing this county with all US counties (100 at "
            "or below the national median, 50 at the 75th percentile). The band is never "
            "higher than the CV alone gives."
        )


def render_explorer(data: dict) -> None:
    _init_geo_state()
    geo = st.session_state["us_geo"]
    unavailable = _unavailable_measures(data)

    st.markdown("##### Map")
    _explorer_top_fragment(data, unavailable)
    st.divider()

    level = geo["level"]
    code = geo["code"]
    if not code:
        st.info("Select a geography from the map, or search in the panel beside it, to see its statistics.")
    else:
        labels_lookup = data["labels_state"] if level == "state" else data["labels_county"]
        label = labels_lookup.get(code, code)
        if level == "state":
            st.subheader(f"{label} -- select a county to see American Community Survey estimates")
        else:
            row = data["county_df"][data["county_df"]["_key"] == code]
            if row.empty:
                st.warning("This county isn't in the current data. Search for it in the panel beside the map.")
            else:
                state_row = data["state_df"][data["state_df"]["_key"] == row["STATE"].iloc[0]]
                _explorer_cards_fragment(data, code, label, row, state_row, unavailable)

    _explorer_methodology_disclaimer()


# ---------------------------------------------------------------------------
# App entry point -- Welcome tab first and selected by default, County
# explorer second (change G, 2026-08-18), Statistical peers third
# (2026-09-17: own tab and map, no longer coupled to the explorer map).
# ---------------------------------------------------------------------------

def main() -> None:
    on_welcome = st.session_state.get("main_tabs", "Welcome") == "Welcome"
    st.html(_CSS + _brand_header_html(welcome=on_welcome))
    if not on_welcome:
        st.caption(
            "Census Bureau American Community Survey estimates and their margins of error, "
            "for every county in the United States. New here? Start with the Welcome tab below."
        )

    data = _load_all()
    welcome_tab, explorer_tab, peers_tab = st.tabs(
        ["Welcome", "County explorer", "Statistical peers"],
        on_change="rerun",
        key="main_tabs",
    )
    if welcome_tab.open:
        with welcome_tab:
            render_welcome()
    if explorer_tab.open:
        with explorer_tab:
            render_explorer(data)
    if peers_tab.open:
        with peers_tab:
            render_peers_tab(data)

    st.html(_brand_footer_html())


if __name__ == "__main__":
    main()
