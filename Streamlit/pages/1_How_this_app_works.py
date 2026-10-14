"""How this app works -- visual map from Census tables to explorer cards.

Replaces the NJ PUMS "Whose data is this?" page. The diagrams describe the
same formulas County explorer already runs (cv_from_range / moe_to_cv,
analysis.composite.reliability_score, and the peer similarity expression in
app_US_v6._peer_display_table). The card explorer and the charts read the
same county parquet the app reads, through the same analysis.dashboard
accessors, so a CV shown here matches the CV on that county's card.
app_US_v6 itself is not imported: it calls set_page_config at import time.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
import streamlit as st

from analysis import composite
from analysis.acs import Z_90, flag_topcoded_income
from analysis.dashboard import (
    BANDS,
    INCOME_BANDS,
    US_LEVEL_SPECS,
    acs_civilian_labor_force,
    acs_disability,
    acs_disability_universe,
    acs_education_universe,
    acs_income_bracket,
    acs_income_bracket_universe,
    acs_insurance_universe,
    acs_language_universe,
    acs_limited_english,
    acs_low_income,
    acs_median_home_value,
    acs_median_rent,
    acs_no_diploma,
    acs_no_vehicle,
    acs_poverty,
    acs_poverty_ratio_universe,
    acs_poverty_universe,
    acs_rent_burden,
    acs_rent_burdened,
    acs_rent_computed_universe,
    acs_rent_severely_burdened,
    acs_sexage,
    acs_uninsured,
    acs_unemployed,
    acs_vehicle_universe,
    cv_color_blue_orange,
    geo_key,
    load_alloc_us_county,
    load_level_data,
    proportion_rate_series,
)

st.set_page_config(page_title="How this app works", layout="wide")

# Worked example for the peers section. Inputs are fixed so the page can be
# checked against the function; the numbers printed are computed, not typed in.
_EXAMPLE_SELF_EST = 80_000.0
_EXAMPLE_PEER_EST = 78_400.0

_BAND_COLOR = {
    composite.BAND_HIGHER: "#0072B2",
    composite.BAND_MODERATE: "#E69F00",
    composite.BAND_LOWER: "#D55E00",
}
_BAND_TEXT = {
    composite.BAND_HIGHER: "#005A8C",
    composite.BAND_MODERATE: "#8A5A00",
    composite.BAND_LOWER: "#A34700",
}

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');

.how-page, .how-page p, .how-page li, .how-page td, .how-page th {
    font-family: 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif;
}
.census-brand-bar {
    background: #205493; color: #FFFFFF; padding: 16px 20px 14px; margin: 0 0 16px 0;
    border-bottom: 4px solid #FFC222; border-radius: 12px; overflow: hidden;
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
    font-size: 0.85rem; border-top: 4px solid #FFC222; border-radius: 12px;
}
.census-footer a, .census-footer a:visited { color: #d7e2ef; }
.census-footer p { margin: 0 0 6px 0; }
.how-page h1 {
    color: #205493; font-size: 1.7rem; font-weight: 700; margin: 0 0 8px 0;
}
.how-section {
    color: #205493; font-size: 23px; font-weight: 700;
    margin-top: 28px; margin-bottom: 10px;
    border-bottom: 3px solid #FFC222; padding-bottom: 5px;
}
.how-lead, .how-note {
    color: #3C3A3B; font-size: 15px; line-height: 1.55; margin: 0 0 14px 0;
}
.how-note strong, .how-lead strong { color: #131313; }
.flow {
    display: flex; flex-wrap: wrap; align-items: stretch; gap: 8px;
    margin: 4px 0 14px 0;
}
.flow-step {
    flex: 1 1 190px;
    border: 1px solid #d7e2ef; border-top: 5px solid #205493;
    border-radius: 9px; padding: 14px 14px 12px; background: #f7faff;
    box-sizing: border-box;
}
.flow-step h3 {
    color: #205493; margin: 0 0 6px 0; font-size: 16px; font-weight: 700;
}
.flow-step p { color: #3C3A3B; margin: 0; font-size: 13.5px; line-height: 1.45; }
.flow-kicker {
    font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; color: #5A6672; margin-bottom: 4px;
}
.flow-arrow {
    align-self: center; color: #205493; font-weight: 700; font-size: 22px;
    flex: 0 0 auto; line-height: 1;
}
.group {
    border: 1px solid #d7e2ef; border-radius: 10px;
    padding: 16px 16px 6px; margin: 0 0 14px 0; background: #ffffff;
}
.group h3 {
    margin: 0 0 6px 0; color: #205493; font-size: 18px; font-weight: 700;
}
.group .how-note { margin-bottom: 8px; }
.card-list { margin: 4px 0 12px 0; padding: 0; list-style: none; }
.card-list li {
    padding: 7px 0; border-top: 1px solid #e6e6e6;
    font-size: 14px; color: #3C3A3B; line-height: 1.4;
}
.card-list strong { color: #131313; }
.table-id { color: #5A6672; font-size: 12.5px; font-variant-numeric: tabular-nums; }
.callout {
    border-left: 4px solid #205493; background: #f7faff; border-radius: 8px;
    padding: 12px 14px; margin: 0 0 16px 0; color: #131313;
    font-size: 15px; line-height: 1.55;
}
.formula {
    background: #ffffff; border: 1px solid #d7e2ef; border-radius: 8px;
    padding: 10px 14px; margin: 0 0 14px 0; color: #131313;
    font-weight: 600; font-size: 15px;
}
.anchor-table { width: 100%; border-collapse: collapse; margin: 0 0 14px 0; font-size: 14px; }
.anchor-table th {
    text-align: left; color: #5A6672; font-weight: 700; font-size: 12px;
    letter-spacing: 0.04em; text-transform: uppercase;
    padding: 6px 8px; border-bottom: 2px solid #d7e2ef;
}
.anchor-table td {
    padding: 7px 8px; border-bottom: 1px solid #e6e6e6; color: #131313;
    vertical-align: top;
}
.pair {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 10px; margin: 0 0 10px 0;
}
.worked {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 10px; margin: 8px 0 12px 0;
}
.worked-cell {
    background: #f7faff; border: 1px solid #d7e2ef; border-radius: 8px; padding: 10px 12px;
}
.worked-k {
    font-size: 11px; font-weight: 700; letter-spacing: 0.04em;
    text-transform: uppercase; color: #5A6672;
}
.worked-v {
    font-size: 20px; font-weight: 700; color: #131313; margin-top: 3px;
    font-variant-numeric: tabular-nums;
}
.score-strip {
    display: flex; justify-content: space-between; align-items: baseline;
    gap: 8px; padding: 8px 2px 4px; margin: 4px 0 8px;
    border-top: 4px solid #0072B2; font-size: 14px;
}
.score-band { font-weight: 700; }
.score-num { color: #5A5A5A; }
.score-num b { color: #131313; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 12px 0; }
.chip {
    display: inline-block; padding: 3px 10px; border-radius: 999px;
    border: 1px solid #d7e2ef; background: #f7faff; color: #205493;
    font-size: 12.5px; font-weight: 500;
}
.chip.strong { background: #205493; border-color: #205493; color: #FFFFFF; }
.chip.warn { background: #fff7e0; border-color: #FFC222; color: #6b4b00; }
.chart-box {
    border: 1px solid #d7e2ef; border-radius: 10px; padding: 14px 16px 10px;
    margin: 0 0 14px 0; background: #ffffff;
}
.chart-box h3 { margin: 0 0 4px 0; color: #205493; font-size: 17px; font-weight: 700; }
.chart-box svg { display: block; width: 100%; height: auto; }
.chart-cap { color: #5A6672; font-size: 13px; line-height: 1.45; margin: 6px 0 0 0; }
.matrix { width: 100%; border-collapse: collapse; margin: 0 0 14px 0; font-size: 14px; }
.matrix th {
    text-align: left; color: #5A6672; font-weight: 700; font-size: 12px;
    letter-spacing: 0.04em; text-transform: uppercase;
    padding: 6px 10px; border-bottom: 2px solid #d7e2ef;
}
.matrix td {
    padding: 9px 10px; border-bottom: 1px solid #e6e6e6; color: #131313;
    vertical-align: top; line-height: 1.45;
}
.matrix .yes { color: #005A8C; font-weight: 700; }
.matrix .care { color: #8A5A00; font-weight: 700; }
.matrix .no { color: #A34700; font-weight: 700; }
.faq details {
    border: 1px solid #d7e2ef; border-radius: 8px; padding: 10px 14px;
    margin: 0 0 8px 0; background: #ffffff;
}
.faq summary { cursor: pointer; font-weight: 700; color: #205493; font-size: 15px; }
.faq details p { margin: 8px 0 2px 0; color: #3C3A3B; font-size: 14.5px; line-height: 1.5; }
.step-list { margin: 0 0 12px 0; padding: 0; list-style: none; counter-reset: step; }
.step-list li {
    counter-increment: step; position: relative; padding: 9px 0 9px 38px;
    border-top: 1px solid #e6e6e6; font-size: 14.5px; color: #3C3A3B; line-height: 1.45;
}
.step-list li::before {
    content: counter(step); position: absolute; left: 0; top: 9px;
    width: 26px; height: 26px; border-radius: 50%; background: #205493;
    color: #fff; font-weight: 700; font-size: 13px; text-align: center; line-height: 26px;
}
[data-testid="stExpander"] {
    border: 1px solid #d7e2ef; border-radius: 10px; margin: 0 0 12px 0; background: #ffffff;
}
[data-testid="stExpander"] summary { border-bottom: 3px solid #FFC222; padding: 12px 16px; }
[data-testid="stExpander"] details:not([open]) > summary { border-bottom-color: transparent; }
[data-testid="stExpander"] summary p {
    color: #205493; font-size: 20px; font-weight: 700;
    font-family: 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif;
}
[data-testid="stExpander"] details > div { padding-top: 12px; }
.step-list strong { color: #131313; }
.step-list .num { font-variant-numeric: tabular-nums; font-weight: 700; color: #131313; }
</style>
"""


def _fmt_sub(value: float) -> str:
    """One decimal for a fractional sub-score, none for a whole number."""
    rounded = round(float(value), 1)
    if abs(rounded - round(rounded)) < 1e-9:
        return f"{rounded:.0f}"
    return f"{rounded:.1f}"


def _peer_similarity(self_est: float, peer_est: float) -> float:
    """Same expression as app_US_v6._peer_display_table: 100 when the
    estimates match, falling toward 0 as the gap grows relative to the
    selected county's estimate, clipped to 0-100."""
    distance = abs(peer_est - self_est)
    denom = abs(float(self_est))
    if not np.isfinite(denom) or denom == 0.0:
        denom = float(np.finfo(float).tiny)
    return float(np.clip(100.0 * (1.0 - distance / denom), 0.0, 100.0))


def _flow(steps: list[tuple[str, str, str]]) -> str:
    parts: list[str] = []
    for i, (kicker, title, body) in enumerate(steps):
        if i:
            parts.append('<div class="flow-arrow" aria-hidden="true">&#8594;</div>')
        parts.append(
            f'<div class="flow-step"><div class="flow-kicker">{kicker}</div>'
            f"<h3>{title}</h3><p>{body}</p></div>"
        )
    return '<div class="flow">' + "".join(parts) + "</div>"


def _li(name: str, detail: str) -> str:
    return f"<li><strong>{name}</strong> <span class='table-id'>{detail}</span></li>"


def _header() -> str:
    return (
        '<div class="census-brand-bar" role="banner">'
        '<div class="census-brand-bar__top">'
        "<div>"
        '<div class="census-wordmark">U.S. Census Bureau</div>'
        '<div class="census-app-title">US County Demographic Explorer</div>'
        "</div>"
        '<div class="census-brand-bar__capstone">Capstone demonstration</div>'
        "</div>"
        '<div class="census-tagline">Measuring America: People, Places, and Economy</div>'
        "</div>"
    )


def _footer() -> str:
    return (
        '<div class="census-footer" role="contentinfo">'
        "<p>Measuring America: People, Places, and Economy</p>"
        "<p>American Community Survey (2020-2024, 5-year).</p>"
        "<p>This is a student capstone demonstration. "
        "It is not an official Census Bureau product.</p>"
        '<p><a href="https://www.census.gov">census.gov</a></p>'
        "</div>"
    )


def _worked_cell(label: str, value: str) -> str:
    return (
        f'<div class="worked-cell"><div class="worked-k">{label}</div>'
        f'<div class="worked-v">{value}</div></div>'
    )


def _overview() -> str:
    flow = _flow([
        (
            "1 · Source files",
            "Census tables and RUCC",
            "ACS 2020–2024 5-year county and state tables, allocation tables "
            "for income and family poverty, and USDA ERS Rural-Urban Continuum "
            "Codes for 2023. Downloaded by pull_usdash.py, pull_usdash_alloc.py, "
            "and pull_rucc.py.",
        ),
        (
            "2 · Loaded once",
            "Read at startup",
            "County explorer loads those files a single time when the app "
            "starts, then every card and the peer tab read from that copy.",
        ),
        (
            "3 · County card",
            "What the card shows",
            "The published estimate, its margin of error, the CV, a 90% "
            "interval from zero, and — when the measure has them — a rate "
            "line and a reliability strip.",
        ),
    ])
    return (
        '<p class="how-lead">Every number on a County explorer card starts as a '
        "published Census figure. The app does not create a new estimate. It "
        "attaches the uncertainty the Census Bureau already published, then "
        "adds a reliability score and, on a separate tab, a peer list.</p>"
        f"{flow}"
        '<p class="how-note"><strong>Margin of error (MOE).</strong> The half-width '
        "the Census Bureau publishes at 90% confidence. The interval drawn on a "
        "card is the estimate plus that margin and the estimate minus that margin.</p>"
    )


def _cards_glance() -> str:
    """One row per card, built from CARDS so it cannot drift from the explorer."""
    rows = []
    for c in CARDS.values():
        if c.build == BUILD_CONTROLLED:
            score = "No CV in most counties"
        else:
            score = "Sampling + imputation" if c.imputation else "Sampling only"
        rows.append(
            f"<tr><td><strong>{_esc(c.label)}</strong></td><td>{c.table}</td>"
            f"<td>{c.build_label}</td><td>{'Yes' if c.universe is not None else '—'}</td>"
            f"<td>{score}</td></tr>"
        )
    return (
        "<div class='faq'><details><summary>All cards at a glance</summary>"
        "<table class='anchor-table'><thead><tr><th>Card</th><th>Table</th>"
        "<th>Built from</th><th>Rate line</th><th>Score uses</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></details></div>"
    )


def _cv_section() -> str:
    return (
        '<p class="formula">CV = (margin of error / 1.645) / estimate'
        "&nbsp;&nbsp;·&nbsp;&nbsp;90% interval = estimate ± margin of error</p>"
        '<p class="how-note"><strong>Coefficient of variation (CV).</strong> The margin of '
        "error divided by 1.645 is the standard error. Dividing that by the estimate gives the "
        "CV. A lower CV means the margin is small relative to the number. The CV on the card, "
        "the map color, and the reliability score all use only the published estimate and its "
        "published margin of error.</p>"
        '<div class="group"><h3>A median, a percent, or a number of people</h3>'
        '<p class="how-note">These cards publish the figure itself. The CV is that figure’s '
        "own margin of error, scaled by the formula above.</p></div>"
        '<div class="group"><h3>Number of people or households, plus a derived rate</h3>'
        '<p class="how-note">For example uninsured people, or renter households paying 30% or '
        "more of income. The CV is the CV of that number. The percentage under it is a "
        "separate calculation with the Census Bureau’s proportion formula in "
        "<span class='table-id'>proportion_rate</span>, and it is not the CV.</p></div>"
        '<div class="group"><h3>Imputation is not part of the CV</h3>'
        '<p class="how-note"><strong>Imputation (allocation).</strong> When a household skips '
        "a question, the Census Bureau fills the blank with a statistically plausible value. "
        "That share is a data-quality fact. It enters the reliability score on income and "
        "poverty cards, listed in the next section, and nowhere else.</p></div>"
        + _cards_glance()
    )


def _reliability_section() -> str:
    flow = (
        '<div class="pair">'
        '<div class="flow-step"><div class="flow-kicker">Input A · every scored card</div>'
        "<h3>Sampling sub-score</h3>"
        "<p>The card’s CV is converted to a 0–100 score, linear between the "
        "anchors in the table below. Higher means a smaller CV.</p></div>"
        '<div class="flow-step"><div class="flow-kicker">Input B · income and poverty only</div>'
        "<h3>Imputation sub-score</h3>"
        "<p>The county’s allocation rate is ranked against every U.S. county. "
        "100 at or below the median rate, 50 at the 75th percentile, 0 for the "
        "most-imputed county. Other cards skip this input.</p></div>"
        "</div>"
        + _flow([
            (
                "Average",
                "Equal weight, then round",
                "The two sub-scores are averaged. A card with no imputation input "
                "keeps the sampling sub-score alone. The result is rounded half up "
                "to a whole number. That whole number is the score on the card.",
            ),
            (
                "Band",
                "The worse of two labels",
                "One label comes from the score (75 or above, 50 or above, else lower). "
                "The other comes from the CV (at most 0.12, at most 0.30, else lower). "
                "The card shows the worse of the two.",
            ),
        ])
    )
    anchors = (
        "<table class='anchor-table'><thead><tr>"
        "<th>Card CV</th><th>Sampling sub-score</th><th>Why this line</th>"
        "</tr></thead><tbody>"
        "<tr><td>0</td><td>100</td><td>No sampling error.</td></tr>"
        "<tr><td>0.12</td><td>75</td><td>ESRI high-reliability line.</td></tr>"
        "<tr><td>0.30</td><td>50</td><td>NCHS caution line.</td></tr>"
        "<tr><td>About 0.61</td><td>0</td><td>The margin of error is as large as the estimate. The 90% interval reaches zero.</td></tr>"
        "</tbody></table>"
    )
    sources = (
        "<ul class='card-list'>"
        + _li(
            "Household income, table B99192 — direct",
            "Median household income and the four income-bracket cards.",
        )
        + _li(
            "Family poverty status, table B99172 — a proxy",
            "The poverty age-band cards and low income. The table describes family poverty status, not the card’s exact item, so the card marks it as a proxy.",
        )
        + _li(
            "Every other card",
            "Sampling only. The strip says imputation is not part of that figure’s score. Age imputation is left out on purpose: the rate is too small for a national ranking to mean much.",
        )
        + "</ul>"
    )
    return (
        '<p class="how-lead">The score is an equal-weight combination of sampling '
        "error and, for income and poverty, imputation. This is our method for "
        "reading those two facts together. It is not a Census Bureau product.</p>"
        f"{flow}{anchors}"
        "<h3 style='color:#205493;font-size:16px;margin:0 0 6px;'>Which cards include imputation</h3>"
        f"{sources}"
    )


def _peers_section(similarity: float) -> str:
    gap = abs(_EXAMPLE_PEER_EST - _EXAMPLE_SELF_EST)
    flow = _flow([
        (
            "1 · Pool",
            "Every U.S. county",
            "The list starts from the full county file. The explorer’s other "
            "filters do not apply here.",
        ),
        (
            "2 · Optional gates",
            "Same kind of place",
            "Two switches can keep counties in the same metro or nonmetro class "
            "(RUCC 2023) and the same population-size bin. Those are the only gates.",
        ),
        (
            "3 · Comparison value",
            "Rate, or the published median",
            "Cards with a universe are compared on the derived rate. Median "
            "income, median rent, rent burden, and median home value are compared "
            "on the published value. Total population and the age bands are not peer measures.",
        ),
        (
            "4 · 90% test",
            "Tie, higher, or lower",
            "Counties not significantly different from the selected one form "
            "the tie set. A missing estimate or margin of error is untestable, "
            "and is not called a tie.",
        ),
        (
            "5 · Rank the ties",
            "Closest estimate first",
            "Rank 1 is the tied county whose published estimate is closest. "
            "The same estimate shares a rank. Similarity scores that closeness.",
        ),
    ])
    return (
        '<p class="how-lead">A statistical peer is a county whose estimate cannot '
        "be told apart from the selected county’s at 90% confidence.</p>"
        f"{flow}"
        '<p class="how-note"><strong>The 90% test.</strong> Standard error equals '
        "the margin of error divided by 1.645. The counties differ when the "
        "absolute z-score is greater than 1.645. Two different counties are drawn "
        "from separate samples, so this is the test’s independent case. Comparing "
        "a county with its own state is a nested case, and that caveat does not "
        "apply to peers.</p>"
        '<p class="formula">Similarity = 100 × (1 − |gap| / |selected estimate|), '
        "clipped to 0–100</p>"
        '<p class="how-note">100 means the published estimates match. The score '
        "falls as the gap grows relative to the selected county’s estimate. "
        "The “Listed counties” dropdown (10, 25, 50, 100, or All) limits the "
        "table and the peer map. The headline still counts the full tie set.</p>"
        '<div class="group"><h3>Worked similarity</h3>'
        '<p class="how-note">The same expression the peer table uses. Rank would be 1 '
        "if no tied county is closer.</p>"
        '<div class="worked">'
        + _worked_cell("Selected estimate", f"{_EXAMPLE_SELF_EST:,.0f}")
        + _worked_cell("Tied county", f"{_EXAMPLE_PEER_EST:,.0f}")
        + _worked_cell("Gap", f"{gap:,.0f}")
        + _worked_cell("Similarity", f"{similarity:.1f}")
        + "</div></div>"
    )


# ---------------------------------------------------------------------------
# Card registry: what each explorer card is built from
#
# Mirrors app_US_v6._build_measures (same accessors, same tables). The
# metadata strings (cells, universe) are documentation of what those
# accessors read; the numbers always come from calling the accessors.
# ---------------------------------------------------------------------------

BUILD_PUBLISHED = "published"   # a published median
BUILD_ONE_CELL = "one_cell"     # a number of people or households, one table cell
BUILD_SUMMED = "summed"         # a number of people or households, cells added up
BUILD_CONTROLLED = "controlled"

_IMPUTATION = {
    "income": ("income_alloc", "household income, Table B99192", False),
    "family_poverty": ("fam_pov_alloc", "family poverty status, Table B99172", True),
}


@dataclass(frozen=True)
class Card:
    key: str
    topic: str
    label: str
    table: str
    build: str
    cells: str
    values: Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]]
    universe: Callable[[pd.DataFrame], tuple[pd.Series, pd.Series]] | None = None
    universe_text: str = ""
    fmt: str = "count"  # count | usd | pct
    n_cells: int = 1
    imputation: str | None = None
    topcoded: bool = False
    note: str = ""
    unit: str = "people"  # what the number counts: people, households, renter households

    @property
    def build_label(self) -> str:
        if self.build == BUILD_CONTROLLED:
            return f"Controlled estimate of {self.unit}"
        if self.build == BUILD_PUBLISHED:
            return "Published median"
        kind = "one published cell" if self.build == BUILD_ONE_CELL else "published cells summed"
        return f"Number of {self.unit}: {kind}"


def _build_cards() -> dict[str, Card]:
    cards: list[Card] = [
        Card("Total population", "Population", "Total population", "B01001", BUILD_CONTROLLED,
             "B01001_001, the total-population cell", lambda d: (
                 d["B01001_001E"].astype(float), d["B01001_001M"].astype(float)),
             note="Census controls this total to its own population estimates, so most "
                  "counties have no margin of error published."),
        Card("Median household income", "Income", "Median household income", "B19013",
             BUILD_PUBLISHED, "B19013_001, the published median",
             lambda d: (d["B19013_001E"].astype(float),
                        d["B19013_001M"].astype(float).mask(flag_topcoded_income(d))),
             fmt="usd", imputation="income", topcoded=True,
             note="A county whose median is top-coded (250,001) has its margin set aside: "
                  "the value is censored, so a CV from it would look falsely precise."),
        Card("Median gross rent", "Housing", "Median gross rent", "B25064", BUILD_PUBLISHED,
             "B25064_001, the published median", acs_median_rent, fmt="usd"),
        Card("Rent burden", "Housing", "Rent burden (median rent as % of income)", "B25071",
             BUILD_PUBLISHED, "B25071_001, the Bureau’s own median of rent ÷ income",
             acs_rent_burden, fmt="pct",
             note="The Bureau computes this household by household, then takes the median. "
                  "It is not the median rent divided by the median income."),
        Card("Median home value", "Housing", "Median home value", "B25077", BUILD_PUBLISHED,
             "B25077_001, the published median", acs_median_home_value, fmt="usd"),
    ]
    age_cells = {"Under 5": 2, "5-17": 6, "18-64": 26, "65+": 12}
    pov_cells = {"Under 5": 2, "5-17": 10, "18-64": 10, "65+": 4}
    for band in BANDS:
        cards.append(Card(
            f"Age {band}", "Population", f"Population, age {band}", "B01001", BUILD_SUMMED,
            f"B01001 male and female cells for ages {band} ({age_cells[band]} cells)",
            partial(acs_sexage, band=band, sex="both"), n_cells=age_cells[band],
        ))
    for band in BANDS:
        cards.append(Card(
            f"Poverty {band}", "Poverty", f"In poverty, age {band}", "B17001", BUILD_SUMMED,
            f"B17001 below-poverty cells for ages {band} ({pov_cells[band]} cells)",
            partial(acs_poverty, band=band, sex="both"),
            partial(acs_poverty_universe, band=band, sex="both"),
            f"people age {band} with poverty status determined (below + at-or-above cells, "
            f"{pov_cells[band] * 2} cells)",
            n_cells=pov_cells[band], imputation="family_poverty",
        ))
    cards += [
        Card("Low income", "Poverty", "Low income (below 200% of poverty)", "C17002",
             BUILD_SUMMED, "C17002_002 to 007, every ratio band under 2.00 (6 cells)",
             acs_low_income, acs_poverty_ratio_universe,
             "people for whom poverty status is determined (C17002_001)",
             n_cells=6, imputation="family_poverty"),
        Card("Unemployed", "Employment", "Unemployed", "B23025", BUILD_ONE_CELL,
             "B23025_005, unemployed civilians 16 and over", acs_unemployed,
             acs_civilian_labor_force, "the civilian labor force (B23025_003)"),
        Card("Cost-burdened renters", "Housing", "Cost-burdened renters (30%+ of income)",
             "B25070", BUILD_SUMMED, "B25070_007 to 010, rent at 30% of income or more (4 cells)",
             acs_rent_burdened, acs_rent_computed_universe,
             "renters whose burden can be computed (B25070_002 to 010, 9 cells)", n_cells=4,
             unit="renter households"),
        Card("Severely cost-burdened renters", "Housing",
             "Severely cost-burdened renters (50%+ of income)", "B25070", BUILD_ONE_CELL,
             "B25070_010, rent at 50% of income or more", acs_rent_severely_burdened,
             acs_rent_computed_universe,
             "renters whose burden can be computed (B25070_002 to 010, 9 cells)",
             unit="renter households"),
        Card("No diploma", "Education", "No high school diploma (age 25+)", "B15003",
             BUILD_SUMMED, "B15003_002 to 016, no schooling through 12th grade (15 cells)",
             acs_no_diploma, acs_education_universe, "adults 25 and over (B15003_001)",
             n_cells=15),
        Card("Disability", "Disability", "With a disability", "B18101", BUILD_SUMMED,
             "the 12 “with a disability” cells in B18101 (every sex and age band)",
             acs_disability, acs_disability_universe,
             "civilian noninstitutionalized population (B18101_001)", n_cells=12),
        Card("Uninsured", "Health", "Uninsured (all ages)", "B27001", BUILD_SUMMED,
             "the 18 “no health insurance coverage” cells in B27001", acs_uninsured,
             acs_insurance_universe, "civilian noninstitutionalized population (B27001_001)",
             n_cells=18),
        Card("Limited English", "Language", "Limited English speaking households", "C16002",
             BUILD_SUMMED, "C16002_004, 007, 010, 013, one per language group (4 cells)",
             acs_limited_english, acs_language_universe, "total households (C16002_001)",
             n_cells=4, unit="households"),
        Card("No vehicle", "Transportation", "Households with no vehicle", "B08201",
             BUILD_ONE_CELL, "B08201_002, households with no vehicle available",
             acs_no_vehicle, acs_vehicle_universe, "total households (B08201_001)",
             unit="households"),
    ]
    income_cells = {"Under $25k": 4, "$25k-$50k": 5, "$50k-$100k": 3, "$100k+": 4}
    for band in INCOME_BANDS:
        cards.append(Card(
            f"Income {band}", "Income", f"Households earning {band}", "B19001", BUILD_SUMMED,
            f"B19001 brackets collapsed to {band} ({income_cells[band]} cells)",
            partial(acs_income_bracket, band=band), acs_income_bracket_universe,
            "total households (B19001_001)", n_cells=income_cells[band],
            imputation="income", unit="households",
        ))
    return {c.key: c for c in cards}


CARDS = _build_cards()


# ---------------------------------------------------------------------------
# Data: same parquet files and accessors the explorer reads
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Loading county data…")
def _load() -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    df = load_level_data("county", specs=US_LEVEL_SPECS)
    df = df.assign(_key=geo_key(df, "county", specs=US_LEVEL_SPECS))
    df = df.assign(state_name=df["NAME"].str.rsplit(", ", n=1).str[-1])
    alloc = load_alloc_us_county()
    alloc = alloc.assign(_key=geo_key(alloc, "county", specs=US_LEVEL_SPECS)).set_index("_key")
    subs = {
        name: composite.imputation_subscores(alloc[col])
        for name, (col, _label, _proxy) in _IMPUTATION.items()
    }
    return df, subs


@st.cache_data(show_spinner=False)
def _card_frame(key: str) -> pd.DataFrame:
    """Estimate, MOE and CV for one card in every county (indexed by _key).

    CV = (MOE / 1.645) / estimate, NaN when the estimate is not positive or
    the MOE is missing -- the same rule as cv_from_range in the explorer."""
    df, subs = _load()
    card = CARDS[key]
    est, moe = card.values(df)
    est, moe = est.astype(float), moe.astype(float)
    cv = ((moe / Z_90) / est).where((est > 0) & moe.notna())
    out = pd.DataFrame(
        {"NAME": df["NAME"], "state": df["state_name"], "est": est, "moe": moe, "cv": cv}
    )
    if card.universe is not None:
        uest, umoe = card.universe(df)
        rate, rate_moe = proportion_rate_series(est, moe, uest, umoe)
        out["uest"], out["rate"], out["rate_moe"] = uest.astype(float), rate, rate_moe
    out["imp_sub"] = df["_key"].map(subs[card.imputation]) if card.imputation else np.nan
    return out.set_index(df["_key"])


# ---------------------------------------------------------------------------
# Formatting + chart helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _fmt_val(value: float, fmt: str) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    if fmt == "usd":
        return f"${value:,.0f}"
    if fmt == "pct":
        return f"{value:.1f}%"
    return f"{value:,.0f}"


def _cv_band(cv: float) -> str:
    if cv <= composite.CV_BAND_EDGES[0]:
        return composite.BAND_HIGHER
    if cv <= composite.CV_BAND_EDGES[1]:
        return composite.BAND_MODERATE
    return composite.BAND_LOWER


def _rgb(cv: float) -> str:
    r, g, b = cv_color_blue_orange(cv)[:3]
    return f"rgb({r},{g},{b})"


_AXIS = "#9AA3AD"
_INK = "#3C3A3B"
_MUTED = "#5A6672"
_FONT = "font-family=\"Roboto, Helvetica, Arial, sans-serif\""


def _t(x: float, y: float, text: str, size: int = 12, anchor: str = "start",
       fill: str = _INK, weight: int = 400) -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'fill="{fill}" font-weight="{weight}" {_FONT}>{text}</text>')


def _interval_chart(est: float, moe: float, cv: float, fmt: str) -> str:
    """Zero-anchored 90% interval for one county, colored by its CV."""
    w, h, left, right = 760, 120, 20, 20
    lo, hi = est - moe, est + moe
    top = max(hi, est) * 1.1
    x = lambda v: left + (w - left - right) * (max(v, 0.0) / top)
    bar_y, bar_h = 50, 26
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="90% interval for the selected card">']
    parts.append(f'<line x1="{x(0)}" y1="{bar_y + bar_h + 8}" x2="{w - right}" y2="{bar_y + bar_h + 8}" '
                 f'stroke="{_AXIS}" stroke-width="1"/>')
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        v = top * frac
        parts.append(f'<line x1="{x(v):.1f}" y1="{bar_y + bar_h + 8}" x2="{x(v):.1f}" '
                     f'y2="{bar_y + bar_h + 13}" stroke="{_AXIS}"/>')
        parts.append(_t(x(v), bar_y + bar_h + 28, _fmt_val(v, fmt), 11, "middle", _MUTED))
    parts.append(f'<rect x="{x(lo):.1f}" y="{bar_y}" width="{max(x(hi) - x(lo), 2):.1f}" '
                 f'height="{bar_h}" rx="4" fill="{_rgb(cv)}" fill-opacity="0.55" '
                 f'stroke="{_rgb(cv)}" stroke-width="1.5"/>')
    parts.append(f'<circle cx="{x(est):.1f}" cy="{bar_y + bar_h / 2}" r="7" fill="#131313" '
                 f'stroke="#fff" stroke-width="2"/>')
    parts.append(_t(x(est), bar_y - 22, f"estimate {_fmt_val(est, fmt)}", 12, "middle", "#131313", 700))
    parts.append(f'<line x1="{x(est):.1f}" y1="{bar_y - 16}" x2="{x(est):.1f}" y2="{bar_y + 4}" '
                 f'stroke="#131313" stroke-dasharray="2 2"/>')
    parts.append(_t(x(lo) , bar_y - 6, f"low {_fmt_val(max(lo, 0), fmt)}", 11, "start", _MUTED))
    parts.append(_t(x(hi), bar_y - 6, f"high {_fmt_val(hi, fmt)}", 11, "end", _MUTED))
    parts.append("</svg>")
    return "".join(parts)


_HIST_STEP = 0.03
_HIST_BINS = 20  # 0 to 0.60; one overflow bin after


def _hist_chart(cvs: pd.Series, sel_cv: float | None, state: str) -> str:
    """CV distribution for one card across a state's counties."""
    vals = cvs.dropna().to_numpy()
    idx = np.minimum((vals // _HIST_STEP).astype(int), _HIST_BINS)
    counts = np.bincount(idx, minlength=_HIST_BINS + 1)
    w, h, left, right, base, top = 760, 230, 40, 14, 180, 24
    bw = (w - left - right) / (_HIST_BINS + 1)
    ymax = max(int(counts.max()), 1)
    sy = lambda c: base - (base - top) * c / ymax
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="CV across counties in {_esc(state)}">']
    for i, c in enumerate(counts):
        mid = (i + 0.5) * _HIST_STEP
        color = _rgb(min(mid, 0.6)) if i < _HIST_BINS else _rgb(0.6)
        parts.append(f'<rect x="{left + i * bw + 1:.1f}" y="{sy(c):.1f}" width="{bw - 2:.1f}" '
                     f'height="{base - sy(c):.1f}" fill="{color}" fill-opacity="0.8"/>')
    for edge, label in ((0.12, "0.12"), (0.30, "0.30")):
        xe = left + bw * edge / _HIST_STEP
        parts.append(f'<line x1="{xe:.1f}" y1="{top - 8}" x2="{xe:.1f}" y2="{base}" '
                     f'stroke="#131313" stroke-dasharray="4 3"/>')
        parts.append(_t(xe, top - 12, f"CV {label}", 11, "middle", "#131313", 700))
    parts.append(f'<line x1="{left}" y1="{base}" x2="{w - right}" y2="{base}" stroke="{_AXIS}"/>')
    for v in (0, 0.12, 0.30, 0.45, 0.60):
        xv = left + bw * v / _HIST_STEP
        parts.append(_t(xv, base + 17, f"{v:.2f}", 11, "middle", _MUTED))
    parts.append(_t(left + bw * _HIST_BINS + bw / 2, base + 17, "0.60+", 11, "middle", _MUTED))
    parts.append(_t((w + left) / 2, base + 38, "CV of this card, county by county", 12, "middle", _MUTED))
    parts.append(_t(left - 6, base, "0", 11, "end", _MUTED))
    parts.append(_t(left - 6, top + 4, f"{ymax}", 11, "end", _MUTED))
    parts.append(_t(12, (base + top) / 2, "counties", 11, "middle", _MUTED).replace(
        "<text ", f'<text transform="rotate(-90 12 {(base + top) / 2})" ', 1))
    if sel_cv is not None and np.isfinite(sel_cv):
        i = min(int(sel_cv // _HIST_STEP), _HIST_BINS)
        cx = left + i * bw + bw / 2
        cy = sy(counts[i]) - 4
        parts.append(f'<polygon points="{cx - 7:.1f},{cy - 12:.1f} {cx + 7:.1f},{cy - 12:.1f} '
                     f'{cx:.1f},{cy:.1f}" fill="#131313"/>')
        parts.append(_t(cx, cy - 16, "this county", 11, "middle", "#131313", 700))
    parts.append("</svg>")
    return "".join(parts)


def _scatter_chart(frame: pd.DataFrame, sel_key: str, fmt: str) -> str:
    """CV against estimate size for every U.S. county, one dot per county."""
    pts = frame[(frame["cv"].notna()) & (frame["est"] > 0)]
    w, h, left, right, top, bottom = 760, 300, 46, 14, 14, 250
    lo_exp = np.floor(np.log10(pts["est"].min()))
    hi_exp = np.ceil(np.log10(pts["est"].max()))
    if hi_exp <= lo_exp:
        hi_exp = lo_exp + 1
    sx = lambda v: left + (w - left - right) * (np.log10(v) - lo_exp) / (hi_exp - lo_exp)
    sy = lambda c: bottom - (bottom - top) * min(c, 1.0)
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="CV against estimate size">']
    for edge in (0.12, 0.30):
        parts.append(f'<line x1="{left}" y1="{sy(edge):.1f}" x2="{w - right}" y2="{sy(edge):.1f}" '
                     f'stroke="#131313" stroke-dasharray="4 3"/>')
        parts.append(_t(w - right, sy(edge) - 4, f"CV {edge:.2f}", 11, "end", "#131313", 700))
    parts.append(f'<line x1="{left}" y1="{bottom}" x2="{w - right}" y2="{bottom}" stroke="{_AXIS}"/>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="{_AXIS}"/>')
    for v in (0, 0.5, 1.0):
        parts.append(_t(left - 6, sy(v) + 4, f"{v:.1f}" + ("+" if v == 1.0 else ""), 11, "end", _MUTED))
    e = int(lo_exp)
    while e <= hi_exp:
        parts.append(_t(sx(10 ** e), bottom + 16, _fmt_val(10 ** e, fmt), 11, "middle", _MUTED))
        e += 1
    parts.append(_t((w + left) / 2, bottom + 38, "Estimate (log scale)", 12, "middle", _MUTED))
    for key, row in pts.iterrows():
        if key == sel_key:
            continue
        parts.append(f'<circle cx="{sx(row.est):.1f}" cy="{sy(row.cv):.1f}" r="2.4" '
                     f'fill="{_rgb(row.cv)}" fill-opacity="0.45"/>')
    if sel_key in pts.index:
        r = pts.loc[sel_key]
        parts.append(f'<circle cx="{sx(r.est):.1f}" cy="{sy(r.cv):.1f}" r="7" fill="#131313" '
                     f'stroke="#FFC222" stroke-width="3"/>')
        anchor = "end" if sx(r.est) > w * 0.7 else "start"
        dx = -12 if anchor == "end" else 12
        parts.append(_t(sx(r.est) + dx, sy(r.cv) - 10, "this county", 11, anchor, "#131313", 700))
    parts.append("</svg>")
    return "".join(parts)


def _cross_chart(rows: list[tuple[str, float, str]], sel_card: str) -> str:
    """CV of every card for one county, sorted, with the value behind each."""
    rows = sorted(rows, key=lambda r: r[1])
    w, left, right, rh, top = 760, 270, 130, 24, 22
    h = top + rh * len(rows) + 28
    cap = 0.6
    sx = lambda c: left + (w - left - right) * min(c, cap) / cap
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="CV of every card for the selected county">']
    for edge in (0.12, 0.30):
        parts.append(f'<line x1="{sx(edge):.1f}" y1="{top - 6}" x2="{sx(edge):.1f}" '
                     f'y2="{h - 22}" stroke="#131313" stroke-dasharray="4 3"/>')
        parts.append(_t(sx(edge), top - 10, f"{edge:.2f}", 11, "middle", "#131313", 700))
    for i, (label, cv, val) in enumerate(rows):
        y = top + i * rh
        is_sel = label == CARDS[sel_card].label
        parts.append(_t(left - 8, y + 16, _esc(label[:44]), 12, "end",
                        "#131313" if is_sel else _INK, 700 if is_sel else 400))
        parts.append(f'<rect x="{left}" y="{y + 4}" width="{max(sx(cv) - left, 2):.1f}" '
                     f'height="{rh - 8}" rx="3" fill="{_rgb(cv)}" '
                     f'stroke="{"#131313" if is_sel else "none"}" stroke-width="2"/>')
        over = ">" if cv > cap else ""
        parts.append(_t(sx(cv) + 6, y + 16, f"{over}{cv:.3f}", 11, "start", _INK, 700))
        parts.append(_t(w - right + 40, y + 16, _esc(val), 11, "start", _MUTED))
    parts.append(_t(w - right + 40, top - 10, "Value", 11, "start", _MUTED, 700))
    parts.append(f'<line x1="{left}" y1="{top - 6}" x2="{left}" y2="{h - 22}" stroke="{_AXIS}"/>')
    parts.append("</svg>")
    return "".join(parts)


def _score_curve(cv: float, rs: composite.ReliabilityScore | None) -> str:
    """Sampling sub-score against CV, the anchor lines the score uses."""
    w, h, left, right, top, bottom = 760, 250, 44, 14, 14, 200
    xmax = 0.70
    sx = lambda c: left + (w - left - right) * min(c, xmax) / xmax
    sy = lambda s: bottom - (bottom - top) * s / 100
    xs, ys = zip(*composite.CV_SUBSCORE_ANCHORS)
    pts = [(x, y) for x, y in zip(xs, ys)] + [(xmax, 0.0)]
    path = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Sampling sub-score against CV">']
    parts.append(f'<line x1="{left}" y1="{bottom}" x2="{w - right}" y2="{bottom}" stroke="{_AXIS}"/>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="{_AXIS}"/>')
    for s in (0, 50, 75, 100):
        parts.append(_t(left - 6, sy(s) + 4, str(s), 11, "end", _MUTED))
        parts.append(f'<line x1="{left}" y1="{sy(s):.1f}" x2="{w - right}" y2="{sy(s):.1f}" '
                     f'stroke="#e6e6e6"/>')
    for v in (0, 0.12, 0.30, 0.61):
        parts.append(_t(sx(v), bottom + 16, f"{v:.2f}", 11, "middle", _MUTED))
    parts.append(_t((w + left) / 2, bottom + 38, "Card CV", 12, "middle", _MUTED))
    parts.append(f'<polyline points="{path}" fill="none" stroke="#205493" stroke-width="2.5"/>')
    for x, y in zip(xs, ys):
        parts.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" fill="#205493"/>')
    if rs is not None:
        parts.append(f'<circle cx="{sx(cv):.1f}" cy="{sy(rs.sampling_sub):.1f}" r="8" '
                     f'fill="{_BAND_COLOR[rs.band]}" stroke="#131313" stroke-width="2"/>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# New sections
# ---------------------------------------------------------------------------

_SCOPE_CALLOUT = (
    '<div class="callout"><strong>What level is the data?</strong> Every card is built '
    "from <strong>whole-county</strong> ACS 5-year tables (2020–2024). Nothing is a separate "
    "survey of a subgroup. A card about an age band, an income bracket or poverty status "
    "adds up published table cells for the whole county. The state figures come from the "
    "matching state tables.</div>"
)


def _chips(card: Card) -> str:
    items = [
        f'<span class="chip strong">Table {card.table}</span>',
        f'<span class="chip">{card.build_label}</span>',
        '<span class="chip">Whole county</span>',
    ]
    if card.universe is not None:
        items.append('<span class="chip">Has a rate line</span>')
    if card.imputation:
        _col, label, proxy = _IMPUTATION[card.imputation]
        items.append(f'<span class="chip warn">Score uses imputation: {label}'
                     f'{" (proxy)" if proxy else ""}</span>')
    else:
        items.append('<span class="chip">Sampling-only score</span>')
    return '<div class="chips">' + "".join(items) + "</div>"


def _compare_note(card: Card) -> str:
    if card.build == BUILD_CONTROLLED:
        return ("In most counties there is no CV to compare. Where Census does publish a "
                "margin, treat the CV like any other card.")
    if card.build == BUILD_PUBLISHED:
        return ("Compare this CV with <strong>the same card in other counties</strong>. "
                "Against a card that counts people or households, it only says which number "
                "is pinned down better. A median is estimated from the whole income, rent or "
                "value distribution, so its CV is not the same kind of precision as the CV of a number of people.")
    return (f"Compare this CV with <strong>the same card in other counties</strong>. A small "
            f"number of {card.unit} has a high CV even when the place is not unusual, so a high "
            f"CV here means “few {card.unit} behind this number”, not “a worse county”. "
            f"Compare the rate line, not the number of {card.unit}, when you compare places of "
            f"different size.")


def _explorer_panel(card: Card, key: str, frame: pd.DataFrame) -> str:
    row = frame.loc[key]
    est, moe, cv = float(row.est), float(row.moe), float(row.cv)
    fmt = card.fmt
    chips = _chips(card)
    if not np.isfinite(est):
        body = ('<div class="callout">Census publishes no estimate for this card in this '
                "county (not enough sample), so there is nothing to calculate.</div>")
        return chips + body
    if not np.isfinite(moe):
        why = ("Census controls the total-population figure to its own estimates, so "
               "no margin of error is published. A controlled estimate has no sampling "
               "error to measure. It is not missing data."
               if card.build == BUILD_CONTROLLED else
               "Census published no margin of error for this card in this county.")
        return (chips + f'<div class="callout"><strong>No CV for this county.</strong> {why} '
                "The card shows the estimate without a CV or a reliability score.</div>")
    se = moe / Z_90
    if card.build == BUILD_SUMMED:
        s1 = (f"<strong>Add up the published cells.</strong> {card.cells}. The county’s "
              f"number of {card.unit} is the sum, <span class='num'>{_fmt_val(est, fmt)}</span>. The "
              f"margin is the square root of the sum of the squared cell margins "
              f"(Census handbook rule, with its zero-cell refinement), "
              f"<span class='num'>±{_fmt_val(moe, fmt)}</span>.")
    elif card.build == BUILD_ONE_CELL:
        s1 = (f"<strong>Read one published cell.</strong> {card.cells}. Number of {card.unit}: "
              f"<span class='num'>{_fmt_val(est, fmt)}</span>, margin "
              f"<span class='num'>±{_fmt_val(moe, fmt)}</span>, straight from the table.")
    else:
        s1 = (f"<strong>Read the published figure.</strong> {card.cells}. Estimate "
              f"<span class='num'>{_fmt_val(est, fmt)}</span>, margin "
              f"<span class='num'>±{_fmt_val(moe, fmt)}</span>, straight from the table.")
    band = _cv_band(cv)
    steps = [
        s1,
        f"<strong>Standard error.</strong> Margin ÷ 1.645 = "
        f"<span class='num'>{_fmt_val(se, fmt)}</span> (1.645 is the 90% factor).",
        f"<strong>CV.</strong> Standard error ÷ estimate = <span class='num'>{cv:.3f}</span> "
        f"({cv * 100:.1f}%), which falls in <span class='num' style='color:{_BAND_TEXT[band]};'>"
        f"{band}</span> on CV alone.",
    ]
    if card.universe is not None and np.isfinite(row.rate):
        r_cv = (row.rate_moe / Z_90) / row.rate if row.rate > 0 else float("nan")
        r_cv_txt = f"{r_cv:.3f}" if np.isfinite(r_cv) else "n/a"
        steps.append(
            f"<strong>Rate line (a separate calculation, not the CV).</strong> Universe: "
            f"{card.universe_text}, <span class='num'>{_fmt_val(row.uest, 'count')}</span>. "
            f"Rate = {card.unit} on the card ÷ universe = <span class='num'>{row.rate:.1f}%</span>, 90% interval "
            f"{max(row.rate - row.rate_moe, 0):.1f}% to {min(row.rate + row.rate_moe, 100):.1f}% "
            f"(Census proportion formula, which also uses the universe’s margin). The rate’s own "
            f"CV would be <span class='num'>{r_cv_txt}</span>, against the card’s "
            f"<span class='num'>{cv:.3f}</span>, which is the CV of the number of {card.unit}."
        )
    imp = row.imp_sub if card.imputation else None
    rs = composite.reliability_score(cv, None if imp is None or pd.isna(imp) else float(imp))
    if rs is not None:
        if rs.imputation_sub is not None:
            steps.append(
                f"<strong>Reliability score.</strong> Sampling sub-score "
                f"<span class='num'>{_fmt_sub(rs.sampling_sub)}</span> (from the CV) and imputation "
                f"sub-score <span class='num'>{_fmt_sub(rs.imputation_sub)}</span> (this county’s "
                f"imputation rate ranked against every U.S. county) average to "
                f"<span class='num'>{rs.score:.0f}</span>."
            )
        else:
            steps.append(
                f"<strong>Reliability score.</strong> Sampling only: the CV converts to "
                f"<span class='num'>{rs.score:.0f}</span> / 100. Imputation is not part of this card’s score."
            )
    cells = (
        '<div class="worked">'
        + _worked_cell("Estimate", _fmt_val(est, fmt))
        + _worked_cell("± Margin of error", _fmt_val(moe, fmt))
        + _worked_cell("CV", f"{cv:.3f}")
        + (_worked_cell("Score", f"{rs.score:.0f}") if rs else "")
        + "</div>"
    )
    strip = ""
    if rs is not None:
        strip = (
            f'<div class="score-strip" style="border-top-color: {_BAND_COLOR[rs.band]};">'
            f'<span class="score-band" style="color: {_BAND_TEXT[rs.band]};">{rs.band}'
            f'{" (capped by the CV)" if rs.capped_by_cv else ""}</span>'
            f'<span class="score-num">Reliability score <b>{rs.score:.0f}</b> / 100</span></div>'
        )
    note = f'<p class="how-note">{card.note}</p>' if card.note else ""
    return (
        chips + cells + strip
        + "<ol class='step-list'>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol>"
        + note
        + f'<div class="callout"><strong>What to compare this CV with.</strong> '
        f"{_compare_note(card)}</div>"
    )


def _chart_box(title: str, svg: str, caption: str) -> str:
    return (f'<div class="chart-box"><h3>{title}</h3>{svg}'
            f'<p class="chart-cap">{caption}</p></div>')


def _county_explorer() -> None:
    st.html(
        '<div class="how-page">'
        '<p class="how-lead">Pick a card and a county. Everything below is computed from the '
        "same Census files and the same functions the County explorer uses, so the "
        "numbers match that county’s card.</p>"
        f"{_SCOPE_CALLOUT}</div>"
    )
    df, _subs = _load()
    states = sorted(df["state_name"].unique())
    c1, c2, c3 = st.columns([1, 1.2, 1.4])
    with c1:
        state = st.selectbox("State", states,
                             index=states.index("New Jersey") if "New Jersey" in states else 0,
                             key="how_state")
    counties = df.loc[df["state_name"] == state, ["_key", "NAME"]].sort_values("NAME")
    names = counties["NAME"].tolist()
    default = names.index("Mercer County, New Jersey") if "Mercer County, New Jersey" in names else 0
    with c2:
        county = st.selectbox("County", names, index=default, key=f"how_county_{state}")
    with c3:
        card_key = st.selectbox(
            "Card", list(CARDS),
            index=list(CARDS).index("Median household income"),
            format_func=lambda k: f"{CARDS[k].topic} · {CARDS[k].label}",
            key="how_card",
        )
    key = counties.loc[counties["NAME"] == county, "_key"].iloc[0]
    card = CARDS[card_key]
    frame = _card_frame(card_key)

    st.html('<div class="how-page">' + _explorer_panel(card, key, frame) + "</div>")

    row = frame.loc[key]
    est, moe, cv = float(row.est), float(row.moe), float(row.cv)
    if not (np.isfinite(est) and np.isfinite(moe) and np.isfinite(cv)):
        return

    in_state = frame[frame["state"] == state]["cv"]
    n_state = int(in_state.notna().sum())
    rank = int((in_state < cv).sum()) + 1
    nat = frame["cv"].dropna()
    boxes = [
        _chart_box(
            "The interval behind the CV",
            _interval_chart(est, moe, cv, card.fmt),
            "The bar is the estimate plus and minus its margin of error, drawn from zero. "
            "The CV is the margin’s size relative to the estimate, scaled by 1.645, so a wide "
            "bar next to a small dot means a high CV.",
        ),
        _chart_box(
            f"Same card, other counties in {_esc(state)}",
            _hist_chart(frame.loc[frame["state"] == state, "cv"], cv, state),
            f"This county ranks <strong>{rank} of {n_state}</strong> in {_esc(state)} on this card’s "
            "CV (1 = lowest). Nationally, "
            f"{(nat <= composite.CV_BAND_EDGES[0]).mean() * 100:.0f}% of counties are at or "
            f"under CV 0.12 on this card and {(nat > composite.CV_BAND_EDGES[1]).mean() * 100:.0f}% "
            "are over 0.30.",
        ),
        _chart_box(
            "Why a small number carries a larger CV",
            _scatter_chart(frame, key, card.fmt),
            "Each dot is a U.S. county on this card. Where the estimate is small, the same "
            "sampling noise is a bigger share of it, so CV climbs. Read a high CV in a small "
            "county as “fewer people or households behind this figure”.",
        ),
    ]
    st.html('<div class="how-page">' + "".join(boxes) + "</div>")

    cross: list[tuple[str, float, str]] = []
    skipped = 0
    for k, c in CARDS.items():
        r = _card_frame(k).loc[key]
        if not np.isfinite(r.cv):
            skipped += 1
            continue
        cross.append((c.label, float(r.cv), _fmt_val(float(r.est), c.fmt)))
    st.html(
        '<div class="how-page">'
        + _chart_box(
            f"Every card for {_esc(county)}",
            _cross_chart(cross, card_key),
            "Cards sorted by CV: which figure to trust more in this county, not which problem "
            "is worse. "
            + (f"{skipped} card(s) have no CV here and are left out." if skipped else ""),
        )
        + "</div>"
    )


def _score_builder() -> None:
    st.html(
        '<div class="how-page"><h3 style="color:#205493;font-size:17px;margin:12px 0 4px;">'
        "Try the reliability score</h3>"
        '<p class="chart-cap">Move the CV and the imputation sub-score. The cards use this '
        "same <span class='table-id'>reliability_score</span> function.</p></div>"
    )
    c1, c2 = st.columns(2)
    with c1:
        cv = st.slider("Card CV", 0.0, 0.70, 0.20, 0.01, key="how_cv")
    with c2:
        has_imp = st.checkbox("Card has an imputation input (income or poverty)",
                              value=True, key="how_has_imp")
        imp = st.slider("Imputation sub-score", 0, 100, 90, 1, key="how_imp",
                        disabled=not has_imp)
    rs = composite.reliability_score(cv, float(imp) if has_imp else None)
    if rs is None:
        return
    cap = ("The CV band is stricter than the score band, so the label is capped by the CV."
           if rs.capped_by_cv else
           "The CV band is no stricter than the score band, so the label follows the score.")
    cells = (
        '<div class="worked">'
        + _worked_cell("CV used", f"{cv:.2f}")
        + _worked_cell("Sampling", _fmt_sub(rs.sampling_sub))
        + _worked_cell("Imputation", _fmt_sub(rs.imputation_sub) if rs.imputation_sub is not None else "none")
        + _worked_cell("Score", f"{rs.score:.0f}")
        + "</div>"
    )
    strip = (
        f'<div class="score-strip" style="border-top-color: {_BAND_COLOR[rs.band]};">'
        f'<span class="score-band" style="color: {_BAND_TEXT[rs.band]};">{rs.band}</span>'
        f'<span class="score-num">Reliability score <b>{rs.score:.0f}</b> / 100</span></div>'
    )
    st.html(
        '<div class="how-page">' + cells + strip
        + _chart_box("Sampling sub-score against CV", _score_curve(cv, rs),
                     "The dot is the sampling sub-score for the CV you chose. " + cap)
        + "</div>"
    )


def _compare_section() -> str:
    matrix = (
        "<table class='matrix'><thead><tr><th>Comparison</th><th>Fair?</th>"
        "<th>Why</th><th>Use instead / watch for</th></tr></thead><tbody>"
        "<tr><td><strong>Same card, different counties</strong></td>"
        "<td class='yes'>Yes</td>"
        "<td>Same table, same universe, same definition. The “Nth of N counties” line and the "
        "map color work this way.</td>"
        "<td>Small counties tend to have higher CVs because fewer people or households sit "
        "behind the number. To compare the estimates themselves, use Statistical peers.</td></tr>"
        "<tr><td><strong>Different cards, same county</strong></td>"
        "<td class='care'>With care</td>"
        "<td>The CV is a ratio, so it is on one scale. It says which number is pinned down better. "
        "It does not say which topic is more important or which is worse.</td>"
        "<td>Cards differ in size of universe, in median versus number of people or households, in one cell versus "
        "summed cells, and in whether imputation enters the score. For a like-for-like "
        "summary, use the reliability band.</td></tr>"
        "<tr><td><strong>The card’s CV and its rate</strong></td>"
        "<td class='care'>Different numbers</td>"
        "<td>The card CV is for the number of people or households. The rate uses the proportion formula, which "
        "includes the universe’s margin. Their precisions can differ.</td>"
        "<td>Read the rate’s 90% interval for the percentage. The card explorer above shows "
        "both for a chosen county.</td></tr>"
        "<tr><td><strong>County CV and state CV</strong></td>"
        "<td class='no'>No</td>"
        "<td>A state is estimated from far more sample than one county, so its CV runs "
        "lower by design.</td>"
        "<td>Turn on “Compare to state” on a card. It tests whether the difference is "
        "statistically significant instead.</td></tr>"
        "</tbody></table>"
    )
    faq = (
        "<div class='faq'>"
        "<details><summary>Why does Total population often have no CV?</summary>"
        "<p>Census controls the population total to its own independent estimates. In about "
        "96% of counties it publishes no margin of error, so there is no CV and no score. That "
        "is a controlled figure, not missing data.</p></details>"
        "<details><summary>Can a card be “Lower reliability” with a good CV?</summary>"
        "<p>Yes, on income and poverty cards. A CV of 0.10 gives a sampling sub-score of "
        "about 79. If the county’s imputation rate ranks among the highest in the country, "
        "the imputation sub-score is near 0 and the average is about 40, which is Lower. "
        "The band also cannot be better than the CV band, so the worse of the two always shows.</p></details>"
        "</div>"
    )
    return (
        '<p class="how-lead">Whether two CVs can be set side by side depends on what is '
        "being compared. These are this app’s reading guide, not Census Bureau rules.</p>"
        + matrix
        + '<div class="how-section" style="font-size:19px;">Questions people ask</div>'
        + faq
    )


def main() -> None:
    similarity = _peer_similarity(_EXAMPLE_SELF_EST, _EXAMPLE_PEER_EST)

    st.html(_CSS)
    st.html(
        '<div class="how-page">'
        + _header()
        + "<h1>How this app works</h1>"
        + '<p class="how-lead">From Census tables to the cards on County explorer. '
        "Open a section below.</p></div>"
    )
    with st.expander("From Census files to a card"):
        st.html('<div class="how-page">' + _overview() + "</div>")
    with st.expander("See how one card is calculated", expanded=True):
        _county_explorer()
    with st.expander("What goes into each card’s CV"):
        st.html('<div class="how-page">' + _cv_section() + "</div>")
    with st.expander("How the reliability score is calculated"):
        st.html('<div class="how-page">' + _reliability_section() + "</div>")
        _score_builder()
    with st.expander("Can I compare these CVs?"):
        st.html('<div class="how-page">' + _compare_section() + "</div>")
    with st.expander("How statistical peers are calculated"):
        st.html('<div class="how-page">' + _peers_section(similarity) + "</div>")
    st.html('<div class="how-page">' + _footer() + "</div>")


if __name__ == "__main__":
    main()
