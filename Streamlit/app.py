"""Trenton grant-data dashboard -- a learning prototype, not the MVP.

Scenario: the City of Trenton is assembling community demographic profiles
to support federal Urban Forestry and Safe Streets grant applications. The
grant writer needs age x sex and poverty figures by neighborhood, and is
not a statistician. This app exists to teach the team (not to be shipped)
how to present uncertainty to that person -- range-first, plain-language
tiers, never a bare number.

Run from the repo root:
    streamlit run Streamlit/app.py

Needs data/raw/{acs5_2024_trenton,trenton_tracts}*.parquet
-- regenerate with: python ingestion/pull_trenton_dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import json

import pydeck as pdk
import streamlit as st

from analysis import composite
from analysis.dashboard import (
    BANDS,
    TIER_CARE,
    TIER_RISKY,
    TIER_SOLID,
    acs_poverty,
    acs_poverty_universe,
    acs_range,
    acs_sexage,
    alloc_place_rate,
    cv_from_range,
    load_acs,
    load_alloc_nj_county,
    load_alloc_nj_tract,
    load_saipe_mercer,
    load_trenton_tracts,
    poverty_rate,
    tier,
)
from analysis.acs import flag_topcoded_income, income_cv

st.set_page_config(page_title="Trenton Grant Data Prototype", layout="wide")

# Okabe-Ito colorblind-safe palette (blue/orange/vermillion) -- deliberately
# avoids red-green, the most common confusion (protanopia/deuteranopia).
# Distinct icons (below) give a second, color-independent cue on every card.
TIER_COLOR = {TIER_SOLID: "#0072B2", TIER_CARE: "#E69F00", TIER_RISKY: "#D55E00", "No data": "#999999"}
TIER_ICON = {TIER_SOLID: "●", TIER_CARE: "▲", TIER_RISKY: "■", "No data": "–"}
# Text color per tier -- white fails WCAG AA on the two warm chips
# (2.25:1 and 3.87:1). Backgrounds unchanged: cards and map still agree.
TIER_TEXT = {TIER_SOLID: "#FFFFFF", TIER_CARE: "#1A1A1A",
             TIER_RISKY: "#000000", "No data": "#1A1A1A"}

# Allocation-quadrant colors (analysis.composite.classify_quadrant), a
# separate map view from the CV tier above -- reuses the same Okabe-Ito
# palette so "vermillion = worst" and "blue = best" stay consistent, plus
# reddish-purple for the blind spot (low CV, high allocation): a tract that
# looks fine on sampling error alone but is mostly imputed.
QUADRANT_LABELS_PLAIN = {
    "low_cv_low_alloc": "Low sampling risk, low imputation",
    "low_cv_high_alloc": "Blind spot: low sampling risk, high imputation",
    "high_cv_low_alloc": "High sampling risk, low imputation",
    "high_cv_high_alloc": "High sampling risk, high imputation",
}
QUADRANT_COLOR = {
    QUADRANT_LABELS_PLAIN["low_cv_low_alloc"]: "#0072B2",
    QUADRANT_LABELS_PLAIN["low_cv_high_alloc"]: "#CC79A7",
    QUADRANT_LABELS_PLAIN["high_cv_low_alloc"]: "#E69F00",
    QUADRANT_LABELS_PLAIN["high_cv_high_alloc"]: "#D55E00",
    "No data": "#999999",
}
QUADRANT_ORDER = tuple(QUADRANT_COLOR)


def _hex_to_rgba(hex_color: str, alpha: int = 170) -> list[int]:
    h = hex_color.lstrip("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)] + [alpha]


# One shared style block instead of the inline-style soup this replaces.
# st.html (not st.markdown) -- style-only content is routed to the event
# container so it takes no layout space, and it skips the markdown pipeline
# entirely (a <style> block containing a blank line gets split by markdown's
# HTML-block rule and the remainder reparses as visible text).
_CSS = """
<style>
.card-range  { font-size: clamp(1.15rem, 2.2vw, 1.6rem); font-weight: 700; margin: 2px 0; }
.card-sub    { color: #5A5A5A; font-size: 1.05rem; font-weight: 500; }
.card-rate   { color: #333; font-size: 0.9rem; margin-top: 2px; }
.card-alloc  { color: #333; font-size: 0.85rem; margin-top: 6px; padding-top: 6px;
               border-top: 1px dashed #DDD; }
.stat-row    { display: flex; justify-content: space-between; padding: 5px 2px;
               border-bottom: 1px solid #E6E6E6; font-size: 0.85rem; }
.stat-row .label { color: #5A5A5A; }
.stat-row .value { font-weight: 600; color: #222; font-variant-numeric: tabular-nums; }
.tier-chip   { display: inline-block; padding: 2px 10px; border-radius: 12px;
               font-weight: 600; font-size: 0.85rem; }
.legend-swatch { display: inline-block; width: 11px; height: 11px; border-radius: 2px;
                 margin-right: 4px; vertical-align: middle; }
.legend-label  { font-size: 0.78rem; color: #5A5A5A; }
</style>
"""


# ---------------------------------------------------------------------------
# Cached data loading
# ---------------------------------------------------------------------------

@st.cache_data
def _load_all() -> dict:
    alloc_tract = load_alloc_nj_tract()
    return {
        "acs": {lvl: load_acs(lvl) for lvl in ("place", "county", "tract")},
        "tracts": load_trenton_tracts(),
        "alloc_tract": alloc_tract,
        "alloc_county": load_alloc_nj_county(),
        # Judged against NJ statewide, not Trenton's own tracts -- a threshold
        # computed on Trenton's own 84/25 tracts would flag exactly a quarter
        # of them by construction and carry no information.
        "income_alloc_threshold": composite.allocation_flag_threshold(
            alloc_tract["income_alloc"]
        ),
    }


def _tract_label(name: str) -> str:
    return name.split(";")[0].replace("Census Tract ", "Tract ")


def _tract_full_label(row) -> str:
    """'Tract N -- Neighborhood', falling back to just the tract if unlabeled.

    Neighborhood names come from OpenStreetMap community data (nearest point
    inside Trenton to the tract centroid) -- an approximation for display
    only, not an official City of Trenton boundary. See
    ingestion/pull_trenton_dashboard.py::_attach_neighborhood_names.
    """
    base = _tract_label(row["NAME"])
    hood = row.get("NEIGHBORHOOD")
    return f"{base} — {hood}" if hood else base


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------

def _stats_panel(rows: list[tuple[str, str]], note: str) -> None:
    """A clean label/value block for the 'Show me the statistics' expander --
    replaces st.write(dict), which rendered as a raw JSON tree."""
    body = "".join(
        f"<div class='stat-row'>"
        f"<span class='label'>{label}</span>"
        f"<span class='value'>{value}</span>"
        f"</div>"
        for label, value in rows
    )
    st.markdown(body, unsafe_allow_html=True)
    st.caption(note)


def render_card(
    title: str, est: float, low: float, high: float, *,
    caveat: str | None = None,
    rate: tuple[float, float] | None = None, rate_label: str = "of this group",
    alloc_pct: float | None = None, alloc_label: str = "this figure",
    alloc_threshold_pct: float | None = None, alloc_is_proxy: bool = False,
) -> None:
    """`rate`, if given, is (percent, percent_moe) -- e.g. a poverty rate --
    shown as a second range under the count and added to the stats panel.

    `alloc_pct`, if given, is the share (0-100) of this figure that was
    imputed rather than reported -- a SECOND, separate reliability signal
    from the CV tier above, not folded into it. Only flagged (warning icon)
    when `alloc_threshold_pct` is also given and exceeded -- that threshold
    is only empirically established for income (analysis.composite); the
    other allocation rates are shown as plain context, not a claimed cutoff.
    """
    # CV uses the TRUE (possibly negative) low bound -- a small count's MOE
    # can exceed the estimate, which is real information about how weak the
    # estimate is. Only the DISPLAYED low bound is floored at 0: nobody can
    # cite "-34 children," but the tier must still reflect how bad that MOE
    # really is (a clamped-then-measured CV would UNDERSTATE the risk).
    cv = cv_from_range(est, low, high)
    label, line = tier(cv)
    color = TIER_COLOR[label]
    display_low = max(0.0, low)

    rate_line = ""
    rate_lo = rate_hi = None
    if rate is not None:
        pct, pct_moe = rate
        rate_lo, rate_hi = max(0.0, pct - pct_moe), min(100.0, pct + pct_moe)
        rate_line = (
            f"<div class='card-rate'>≈ <b>{pct:.1f}%</b> {rate_label} "
            f"(range {rate_lo:.1f}%&ndash;{rate_hi:.1f}%)</div>"
        )

    alloc_line = ""
    alloc_flagged = False
    if alloc_pct is not None:
        alloc_flagged = alloc_threshold_pct is not None and alloc_pct > alloc_threshold_pct
        icon = "⚠️" if alloc_flagged else "ℹ️"
        proxy_note = " (a family-income proxy, not measured person by person)" if alloc_is_proxy else ""
        alloc_line = (
            f"<div class='card-alloc'>{icon} About <b>{alloc_pct:.0f}%</b> of {alloc_label} "
            f"were filled in by the Census Bureau, not reported{proxy_note}. The margin of "
            f"error above does not account for this.</div>"
        )

    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.markdown(
            f"<div class='card-range'>{display_low:,.0f} &ndash; {high:,.0f}</div>"
            f"<div class='card-sub'>best estimate: {est:,.0f}</div>"
            + rate_line + alloc_line,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<span class='tier-chip' style='background:{color};color:{TIER_TEXT[label]};'>"
            f"<span aria-hidden='true'>{TIER_ICON[label]}</span> {label.upper()}</span>",
            unsafe_allow_html=True,
        )
        st.caption(line)
        if caveat:
            st.caption(f"⚠️ {caveat}")
        if low < 0:
            st.caption(
                f"⚠️ The true lower bound is {low:,.0f} -- shown here as 0. A range that "
                "dips below zero is itself a signal: the margin of error is larger than the "
                "estimate, which is about as unreliable as a count can get."
            )
        with st.expander("Show me the statistics"):
            rows = [
                ("Best estimate", f"{est:,.0f}"),
                ("Range shown", f"{display_low:,.0f} – {high:,.0f}"),
                ("± margin", f"± {(high - low) / 2:,.0f}"),
                ("Implied CV", f"{cv * 100:.1f}%" if cv == cv else "n/a"),
            ]
            if low < 0:
                rows.append(("True range (unclamped)", f"{low:,.0f} – {high:,.0f}"))
            note = (
                "Tier rule: CV ≤ 12% Solid, ≤ 30% Use with care, else Too risky "
                "(ESRI/NCHS conventions — our proposed tiers, not adopted Census thresholds)."
            )
            if rate is not None:
                pct, pct_moe = rate
                rows += [
                    ("Rate (best estimate)", f"{pct:.1f}%"),
                    ("Rate range shown", f"{rate_lo:.1f}% – {rate_hi:.1f}%"),
                    ("Rate ± margin", f"± {pct_moe:.1f} pts"),
                ]
                note += (
                    " Rate uses the Census ratio-MOE formula (poverty count is a "
                    "SUBSET of the age band, not an independent estimate) against the "
                    "true poverty-universe denominator, not total population -- the two "
                    "differ slightly (B17001 excludes some group quarters residents)."
                )
            if alloc_pct is not None:
                rows.append(("Imputed (allocated)", f"{alloc_pct:.1f}%" + (" [proxy]" if alloc_is_proxy else "")))
                if alloc_threshold_pct is not None:
                    rows.append(("NJ statewide flag line (75th pct.)", f"{alloc_threshold_pct:.1f}%"))
                note += (
                    " Allocation is a separate signal from the CV tier above -- a tract can "
                    "read Solid on sampling error and still have most of this figure imputed. "
                    "Allocation tables carry no margin of error (Census Bureau publishes "
                    "estimates only), so this rate is exact, not itself a range."
                )
            _stats_panel(rows, note)


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

def render_tier_map(
    tracts_gdf,
    tier_by_tract: dict[str, str],
    est_by_tract: dict[str, float],
    range_by_tract: dict[str, tuple[float, float]],
    title: str,
    *,
    selected_tract: str | None = None,
    pct_by_tract: dict[str, float] | None = None,
    color_map: dict[str, str] | None = None,
    legend_order: tuple[str, ...] | None = None,
) -> None:
    """Interactive pydeck choropleth: hover a tract for its number and tier.

    Colors and legend swatches share TIER_COLOR with the cards above, so the
    map and the cards always agree. A compact custom legend replaces
    matplotlib's default (which ran oversized at this figure size). When
    `selected_tract` is set (sidebar geography = one tract), the map shows
    ONLY that tract, zoomed in tight -- otherwise all 25, city-wide.
    `pct_by_tract` (poverty rate maps only) adds a rate line to the tooltip.
    `color_map`/`legend_order` let this same function render a different
    label set (e.g. the four allocation quadrants) -- default is the CV tier.
    """
    hexmap = color_map if color_map is not None else TIER_COLOR
    order = legend_order if legend_order is not None else (TIER_SOLID, TIER_CARE, TIER_RISKY, "No data")
    rgba_map = {label: _hex_to_rgba(hexcolor) for label, hexcolor in hexmap.items()}

    gdf = tracts_gdf.to_crs(epsg=4326).copy()
    if selected_tract is not None:
        gdf = gdf[gdf["TRACT"] == selected_tract]
    gdf["short_name"] = gdf.apply(_tract_full_label, axis=1)
    gdf["tier_label"] = gdf["TRACT"].map(tier_by_tract).fillna("No data")
    gdf["fill_color"] = gdf["tier_label"].map(rgba_map)
    gdf["estimate_text"] = gdf["TRACT"].map(
        lambda t: f"{est_by_tract[t]:,.0f}" if t in est_by_tract else "n/a"
    )
    gdf["range_text"] = gdf["TRACT"].map(
        lambda t: f"{range_by_tract[t][0]:,.0f} – {range_by_tract[t][1]:,.0f}"
        if t in range_by_tract else "n/a"
    )
    cols = ["short_name", "tier_label", "fill_color", "estimate_text", "range_text"]
    tooltip_html = (
        "<b>{short_name}</b><br/>{tier_label}<br/>"
        "Range: {range_text}<br/>Best estimate: {estimate_text}"
    )
    if pct_by_tract is not None:
        gdf["pct_text"] = gdf["TRACT"].map(
            lambda t: f"{pct_by_tract[t]:.1f}%" if t in pct_by_tract else "n/a"
        )
        cols.append("pct_text")
        tooltip_html += "<br/>Poverty rate: {pct_text}"
    geojson = json.loads(gdf[cols + ["geometry"]].to_json())

    layer = pdk.Layer(
        "GeoJsonLayer",
        geojson,
        opacity=0.75,
        stroked=True,
        filled=True,
        get_fill_color="properties.fill_color",
        get_line_color=[255, 255, 255, 200],
        line_width_min_pixels=1,
        pickable=True,
        auto_highlight=True,
        highlight_color=[0, 0, 0, 80],
    )
    centroid = gdf.geometry.union_all().centroid
    zoom = 14.6 if selected_tract is not None else 12.2
    view_state = pdk.ViewState(latitude=centroid.y, longitude=centroid.x, zoom=zoom, pitch=0)
    tooltip = {
        "html": tooltip_html,
        "style": {"backgroundColor": "white", "color": "#222", "fontSize": "12px"},
    }
    st.caption(title)
    st.pydeck_chart(
        pdk.Deck(
            layers=[layer], initial_view_state=view_state, tooltip=tooltip,
            map_provider="carto", map_style="light",
        ),
        height=420,
        use_container_width=True,
    )
    legend = " &nbsp;&nbsp; ".join(
        f"<span class='legend-swatch' style='background:{hexmap[label]};'></span>"
        f"<span class='legend-label'>{label}</span>"
        for label in order
    )
    st.markdown(legend, unsafe_allow_html=True)
    st.caption("Hover a tract for its number and tier.")


# ---------------------------------------------------------------------------
# Allocation (imputation) lookups for the current geography selection
# ---------------------------------------------------------------------------

def _alloc_rate(
    data: dict, level: str, tract_code: str | None, *,
    rate_col: str, numerator_cols: str | list[str], denominator_col: str,
    complement: bool = False,
) -> float:
    """Allocation rate for whatever geography is currently selected.

    Tract and county are published allocation-table rows (analysis.alloc).
    Trenton citywide ("place") has no published row -- allocation tables
    stop at county/tract/block group -- so it's derived by summing raw
    counts over the 25 constituent tracts (dashboard.alloc_place_rate),
    never by averaging the 25 tracts' own rates.
    """
    if level == "tract":
        row = data["alloc_tract"][data["alloc_tract"]["TRACT"] == tract_code]
        return float(row[rate_col].iloc[0])
    if level == "county":
        county_code = data["tracts"]["COUNTY"].iloc[0]
        row = data["alloc_county"][data["alloc_county"]["COUNTY"] == county_code]
        return float(row[rate_col].iloc[0])
    return alloc_place_rate(
        data["alloc_tract"], data["tracts"]["TRACT"], numerator_cols, denominator_col,
        complement=complement,
    )


def _income_alloc(data: dict, level: str, tract_code: str | None) -> float:
    return _alloc_rate(
        data, level, tract_code, rate_col="income_alloc",
        numerator_cols="B99192_002E", denominator_col="B99192_001E", complement=True,
    )


def _age_alloc(data: dict, level: str, tract_code: str | None) -> float:
    return _alloc_rate(
        data, level, tract_code, rate_col="age_alloc",
        numerator_cols="B99012_002E", denominator_col="B99012_001E",
    )


def _fam_pov_alloc(data: dict, level: str, tract_code: str | None) -> float:
    return _alloc_rate(
        data, level, tract_code, rate_col="fam_pov_alloc",
        numerator_cols=["B99172_002E", "B99172_009E"], denominator_col="B99172_001E",
        complement=True,
    )


def _render_saipe_comparison(acs_est: float, acs_moe: float) -> None:
    """County-only comparator: ACS vs. SAIPE for the same variable (Phase 3, HANDOFF #17).

    SAIPE stops at the county level, so this never appears on the tract or
    citywide views. It is one element, not a tab -- the methodological point
    (a SAIPE interval is model error, an ACS MOE is sampling error, the
    widths are not comparable at face value) is made in full in
    notebooks/13-saipe-vs-acs-county.ipynb; this only surfaces the numbers.
    """
    saipe = load_saipe_mercer()
    st.markdown("###### Bureau comparison: SAIPE for the same variable")
    st.markdown(
        f"<div class='card-alloc'>SAIPE (a separate Census Bureau program that models "
        f"income rather than surveying it) puts Mercer County's {saipe['year']} median "
        f"household income at <b>{saipe['SAEMHI_PT']:,.0f}</b>, 90% interval "
        f"<b>{saipe['SAEMHI_LB90']:,.0f}&ndash;{saipe['SAEMHI_UB90']:,.0f}</b> "
        f"(ACS above: {acs_est:,.0f} range {acs_est - acs_moe:,.0f}&ndash;{acs_est + acs_moe:,.0f}). "
        "The two ranges are not measuring the same kind of error: ACS's is sampling error "
        "only, SAIPE's blends sampling error with model uncertainty. A wider SAIPE range "
        "does not mean SAIPE is less reliable. See notebooks/13-saipe-vs-acs-county.ipynb "
        "for the full comparison.</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Geography selection
# ---------------------------------------------------------------------------

def geography_picker(tracts_gdf) -> tuple[str, str | None, str]:
    tract_options = {
        _tract_full_label(row): row["TRACT"] for _, row in tracts_gdf.iterrows()
    }
    labels = sorted(tract_options, key=lambda s: tract_options[s])
    scope = st.sidebar.radio(
        "Geography", ["Trenton (whole city)", "Mercer County", "Single tract"]
    )
    result: tuple[str, str | None, str] = ("place", None, "Trenton")
    if scope == "Mercer County":
        result = ("county", None, "Mercer County")
    elif scope == "Single tract":
        # Streamlit drops a widget's state on any rerun where the widget is not
        # rendered (session_state.py::_is_stale_widget) -- key= does NOT prevent
        # this. Mirror the pick under a plain, non-widget key, which survives.
        remembered = st.session_state.get("geo_tract_label", labels[0])
        choice = st.sidebar.selectbox(
            "Which tract?",
            labels,
            index=labels.index(remembered) if remembered in labels else 0,
        )
        st.session_state["geo_tract_label"] = choice
        result = ("tract", tract_options[choice], choice)
    st.sidebar.caption(
        "Neighborhood names: nearest OpenStreetMap community point to each "
        "tract's center — approximate, not an official City of Trenton boundary."
    )
    return result


# ---------------------------------------------------------------------------
# App body
# ---------------------------------------------------------------------------

def main() -> None:
    st.html(_CSS)
    st.title("Trenton Community Demographic Profile")
    st.caption(
        "A learning prototype -- NOT the MVP. Built to help the team understand how a "
        "non-technical grant writer would read (and misread) this data, and where the "
        "EDA needs to draw a clearer line. Scenario: the City of Trenton needs age x sex "
        "and poverty figures to support Urban Forestry and Safe Streets grant applications."
    )

    data = _load_all()
    level, tract_code, geo_label = geography_picker(data["tracts"])

    acs_row = data["acs"][level]
    if level == "tract":
        acs_row = acs_row[acs_row["TRACT"] == tract_code]

    st.subheader(f"{geo_label} -- American Community Survey (2020-2024, 5-year)")
    st.info(
        "ACS surveys a *sample* of households, not everyone. Every number below ships "
        "with a real, measured margin of error (MOE) -- the range comes directly from "
        "the Census Bureau, not a model."
    )
    pop_est = float(acs_row["B01001_001E"].iloc[0])
    pop_moe = float(acs_row["B01001_001M"].iloc[0])
    render_card("Total population", pop_est, *acs_range(pop_est, pop_moe))

    st.markdown("##### Median household income")
    if bool(flag_topcoded_income(acs_row).iloc[0]):
        st.info(
            f"{geo_label}'s median household income is top-coded at $250,001 -- the Census "
            "Bureau censors values at this cap, and top-coded rows publish no margin of "
            "error. Not shown as a range; the true median is at least $250,001."
        )
    else:
        income_est = float(acs_row["B19013_001E"].iloc[0])
        income_moe = float(acs_row["B19013_001M"].iloc[0])
        render_card(
            "Median household income", income_est, *acs_range(income_est, income_moe),
            alloc_pct=_income_alloc(data, level, tract_code) * 100,
            alloc_label="household incomes",
            alloc_threshold_pct=data["income_alloc_threshold"] * 100,
        )
        if level == "county":
            _render_saipe_comparison(income_est, income_moe)

    st.markdown("##### Population by age")
    age_alloc_pct = _age_alloc(data, level, tract_code) * 100
    cols = st.columns(4, gap="medium")
    for col, band in zip(cols, BANDS):
        est, moe = acs_sexage(acs_row, band, "both")
        with col:
            render_card(
                band, float(est.iloc[0]), *acs_range(float(est.iloc[0]), float(moe.iloc[0])),
                alloc_pct=age_alloc_pct, alloc_label="age records",
            )

    st.markdown("##### Living below the poverty line, by age")
    fam_pov_alloc_pct = _fam_pov_alloc(data, level, tract_code) * 100
    cols = st.columns(4, gap="medium")
    for col, band in zip(cols, BANDS):
        est, moe = acs_poverty(acs_row, band, "both")
        univ_est, univ_moe = acs_poverty_universe(acs_row, band, "both")
        rate = poverty_rate(
            float(est.iloc[0]), float(moe.iloc[0]), float(univ_est.iloc[0]), float(univ_moe.iloc[0])
        )
        with col:
            render_card(
                band, float(est.iloc[0]), *acs_range(float(est.iloc[0]), float(moe.iloc[0])),
                rate=rate, rate_label=f"of {band} residents in poverty",
                alloc_pct=fam_pov_alloc_pct, alloc_label="family poverty determinations",
                alloc_is_proxy=True,
            )

    map_heading = "Where can you actually cite this?"
    map_heading += f" ({geo_label})" if level == "tract" else " (all 25 tracts)"
    st.markdown(f"##### {map_heading}")
    poverty_options = [f"Poverty: {b}" for b in BANDS]
    IMPUTATION_INCOME = "Imputation: household income"
    map_choice = st.selectbox(
        "Map this figure",
        ["Total population"] + BANDS + poverty_options + [IMPUTATION_INCOME],
        key="acs_map",
    )
    is_poverty_map = map_choice in poverty_options
    tract_df = data["acs"]["tract"]

    if map_choice == IMPUTATION_INCOME:
        # A different map view from the CV tier above: sampling risk crossed
        # with imputation risk (analysis.composite), colored by quadrant --
        # not folded into the CV tier itself. The blind-spot quadrant (low
        # CV, high allocation) is exactly the case a CV-only map would miss.
        income_df = tract_df[["TRACT", "B19013_001E", "B19013_001M"]].merge(
            data["alloc_tract"][["TRACT", "income_alloc"]], on="TRACT", how="left"
        ).set_index("TRACT")
        cv_series = income_cv(income_df)
        quadrant = composite.classify_quadrant(
            cv_series, income_df["income_alloc"],
            alloc_threshold=data["income_alloc_threshold"],
        )
        plain = quadrant.map(QUADRANT_LABELS_PLAIN)
        quadrant_by_tract = {t: (v if isinstance(v, str) else "No data") for t, v in plain.items()}
        est_by_tract = income_df["B19013_001E"].to_dict()
        range_by_tract = {
            t: (max(0.0, e - m), e + m)
            for t, e, m in zip(income_df.index, income_df["B19013_001E"], income_df["B19013_001M"])
        }
        render_tier_map(
            data["tracts"], quadrant_by_tract, est_by_tract, range_by_tract,
            "Income reliability: sampling risk x imputation",
            selected_tract=tract_code if level == "tract" else None,
            color_map=QUADRANT_COLOR, legend_order=QUADRANT_ORDER,
        )
    else:
        tier_by_tract: dict[str, str] = {}
        est_by_tract = {}
        range_by_tract = {}
        pct_by_tract: dict[str, float] | None = {} if is_poverty_map else None
        for _, row in tract_df.iterrows():
            t_code = row["TRACT"]
            if map_choice == "Total population":
                e, m = float(row["B01001_001E"]), float(row["B01001_001M"])
            else:
                one = tract_df[tract_df["TRACT"] == t_code]
                if is_poverty_map:
                    band = map_choice.removeprefix("Poverty: ")
                    e_s, m_s = acs_poverty(one, band, "both")
                    e, m = float(e_s.iloc[0]), float(m_s.iloc[0])
                    u_s, u_m = acs_poverty_universe(one, band, "both")
                    pct, _ = poverty_rate(e, m, float(u_s.iloc[0]), float(u_m.iloc[0]))
                    pct_by_tract[t_code] = pct
                else:
                    e_s, m_s = acs_sexage(one, map_choice, "both")
                    e, m = float(e_s.iloc[0]), float(m_s.iloc[0])
            lo, hi = acs_range(e, m)
            tier_by_tract[t_code] = tier(cv_from_range(e, lo, hi))[0]
            est_by_tract[t_code] = e
            range_by_tract[t_code] = (max(0.0, lo), hi)  # same display-floor as the cards
        render_tier_map(
            data["tracts"], tier_by_tract, est_by_tract, range_by_tract,
            f"ACS reliability: {map_choice}",
            selected_tract=tract_code if level == "tract" else None,
            pct_by_tract=pct_by_tract,
        )


if __name__ == "__main__":
    main()
