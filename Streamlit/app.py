"""Trenton grant-data dashboard -- a learning prototype, not the MVP.

Scenario: the City of Trenton is assembling community demographic profiles
to support federal Urban Forestry and Safe Streets grant applications. The
grant writer needs age x sex and poverty figures by neighborhood, and is
not a statistician. This app exists to teach the team (not to be shipped)
how to present uncertainty to that person -- range-first, plain-language
tiers, never a bare number.

Run from the repo root:
    streamlit run Streamlit/app.py

Needs data/raw/{acs5_2024_trenton,dhc_2020_trenton,trenton_tracts}*.parquet
-- regenerate with: python ingestion/pull_trenton_dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import json

import matplotlib.pyplot as plt
import pydeck as pdk
import streamlit as st

from analysis.dashboard import (
    BANDS,
    TIER_CARE,
    TIER_RISKY,
    TIER_SOLID,
    acs_poverty,
    acs_poverty_universe,
    acs_range,
    acs_sexage,
    cv_from_range,
    dhc_population_range,
    dhc_sexage,
    dhc_subgroup_range,
    load_acs,
    load_dhc,
    load_trenton_tracts,
    poverty_rate,
    tier,
)
from analysis.acs import Z_90

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


def _hex_to_rgba(hex_color: str, alpha: int = 170) -> list[int]:
    h = hex_color.lstrip("#")
    return [int(h[i : i + 2], 16) for i in (0, 2, 4)] + [alpha]


TIER_RGBA = {label: _hex_to_rgba(color) for label, color in TIER_COLOR.items()}

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
    return {
        "acs": {lvl: load_acs(lvl) for lvl in ("place", "county", "tract")},
        "dhc": {lvl: load_dhc(lvl) for lvl in ("place", "county", "tract")},
        "tracts": load_trenton_tracts(),
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
) -> None:
    """`rate`, if given, is (percent, percent_moe) -- e.g. a poverty rate --
    shown as a second range under the count and added to the stats panel."""
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

    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.markdown(
            f"<div class='card-range'>{display_low:,.0f} &ndash; {high:,.0f}</div>"
            f"<div class='card-sub'>best estimate: {est:,.0f}</div>"
            + rate_line,
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
) -> None:
    """Interactive pydeck choropleth: hover a tract for its number and tier.

    Colors and legend swatches share TIER_COLOR with the cards above, so the
    map and the cards always agree. A compact custom legend replaces
    matplotlib's default (which ran oversized at this figure size). When
    `selected_tract` is set (sidebar geography = one tract), the map shows
    ONLY that tract, zoomed in tight -- otherwise all 25, city-wide.
    `pct_by_tract` (poverty rate maps only) adds a rate line to the tooltip.
    """
    gdf = tracts_gdf.to_crs(epsg=4326).copy()
    if selected_tract is not None:
        gdf = gdf[gdf["TRACT"] == selected_tract]
    gdf["short_name"] = gdf.apply(_tract_full_label, axis=1)
    gdf["tier_label"] = gdf["TRACT"].map(tier_by_tract).fillna("No data")
    gdf["fill_color"] = gdf["tier_label"].map(TIER_RGBA)
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
        f"<span class='legend-swatch' style='background:{TIER_COLOR[label]};'></span>"
        f"<span class='legend-label'>{label}</span>"
        for label in (TIER_SOLID, TIER_CARE, TIER_RISKY, "No data")
    )
    st.markdown(legend, unsafe_allow_html=True)
    st.caption("Hover a tract for its number and tier.")


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
    dhc_row = data["dhc"][level]
    if level == "tract":
        acs_row = acs_row[acs_row["TRACT"] == tract_code]
        dhc_row = dhc_row[dhc_row["TRACT"] == tract_code]

    tab_acs, tab_dhc, tab_compare = st.tabs(
        ["ACS (survey estimates)", "DHC 2020 (full count)", "Compare"]
    )

    # --- Tab 1: ACS -----------------------------------------------------
    with tab_acs:
        st.subheader(f"{geo_label} -- American Community Survey (2020-2024, 5-year)")
        st.info(
            "ACS surveys a *sample* of households, not everyone. Every number below ships "
            "with a real, measured margin of error (MOE) -- the range comes directly from "
            "the Census Bureau, not a model."
        )
        pop_est = float(acs_row["B01001_001E"].iloc[0])
        pop_moe = float(acs_row["B01001_001M"].iloc[0])
        render_card("Total population", pop_est, *acs_range(pop_est, pop_moe))

        st.markdown("##### Population by age")
        cols = st.columns(4, gap="medium")
        for col, band in zip(cols, BANDS):
            est, moe = acs_sexage(acs_row, band, "both")
            with col:
                render_card(band, float(est.iloc[0]), *acs_range(float(est.iloc[0]), float(moe.iloc[0])))

        st.markdown("##### Living below the poverty line, by age")
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
                )

        map_heading = "Where can you actually cite this?"
        map_heading += f" ({geo_label})" if level == "tract" else " (all 25 tracts)"
        st.markdown(f"##### {map_heading}")
        poverty_options = [f"Poverty: {b}" for b in BANDS]
        map_choice = st.selectbox(
            "Map this figure", ["Total population"] + BANDS + poverty_options, key="acs_map",
        )
        is_poverty_map = map_choice in poverty_options
        tract_df = data["acs"]["tract"]
        tier_by_tract: dict[str, str] = {}
        est_by_tract: dict[str, float] = {}
        range_by_tract: dict[str, tuple[float, float]] = {}
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

    # --- Tab 2: DHC -------------------------------------------------------
    with tab_dhc:
        st.subheader(f"{geo_label} -- 2020 Census DHC (full count)")
        st.warning(
            "DHC counts **everyone** -- no sampling error. But the Census Bureau adds "
            "deliberate privacy noise to every cell (differential privacy) and publishes "
            "no margin of error for it. The ranges below are **modeled**, not measured -- "
            "built from a 2010 demonstration study of the noise, not a direct 2020 "
            "measurement. DHC also publishes no poverty table, so there is no poverty "
            "section on this tab -- that gap is itself a finding, not an omission."
        )
        pop_est = float(dhc_row["P1_001N"].iloc[0])
        if level == "place":
            tract_pops = data["dhc"]["tract"].merge(
                data["tracts"][["STATE", "COUNTY", "TRACT"]], on=["STATE", "COUNTY", "TRACT"]
            )["P1_001N"]
            pop_range = dhc_population_range(pop_est, "place", tract_pops=tract_pops)
        else:
            pop_range = dhc_population_range(pop_est, level)
        render_card("Total population", pop_est, *pop_range, caveat="Modeled, not measured.")

        st.markdown("##### Population by age")
        cols = st.columns(4, gap="medium")
        for col, band in zip(cols, BANDS):
            est = dhc_sexage(dhc_row, band, "both")
            e = float(est.iloc[0])
            rng = dhc_subgroup_range(e, level)
            with col:
                render_card(band, e, *rng, caveat="Modeled, not measured.")

        st.markdown(f"##### {map_heading}")
        map_choice_dhc = st.selectbox(
            "Map this figure", ["Total population"] + BANDS, key="dhc_map",
        )
        dhc_tract_df = data["dhc"]["tract"]
        tier_by_tract_dhc: dict[str, str] = {}
        est_by_tract_dhc: dict[str, float] = {}
        range_by_tract_dhc: dict[str, tuple[float, float]] = {}
        for _, row in dhc_tract_df.iterrows():
            if map_choice_dhc == "Total population":
                e = float(row["P1_001N"])
                lo, hi = dhc_population_range(e, "tract")
            else:
                one = dhc_tract_df[dhc_tract_df["TRACT"] == row["TRACT"]]
                e = float(dhc_sexage(one, map_choice_dhc, "both").iloc[0])
                lo, hi = dhc_subgroup_range(e, "tract")
            t_code = row["TRACT"]
            tier_by_tract_dhc[t_code] = tier(cv_from_range(e, lo, hi))[0]
            est_by_tract_dhc[t_code] = e
            range_by_tract_dhc[t_code] = (max(0.0, lo), hi)
        render_tier_map(
            data["tracts"], tier_by_tract_dhc, est_by_tract_dhc, range_by_tract_dhc,
            f"DHC modeled reliability: {map_choice_dhc}",
            selected_tract=tract_code if level == "tract" else None,
        )

    # --- Tab 3: Compare -----------------------------------------------------
    with tab_compare:
        st.subheader(f"{geo_label} -- ACS vs. DHC, side by side")
        st.markdown(
            "**Two things to read correctly before comparing any numbers:**\n\n"
            "1. **They are not the same moment.** ACS 5-year is a 2020-2024 average; "
            "DHC is a snapshot of April 1, 2020. A gap between them is mostly *timing*, "
            "not error -- Trenton's citywide population is 90,338 (ACS) vs. 90,871 (DHC), "
            "a 0.6% difference almost entirely explained by which years are being counted.\n"
            "2. **Their error stories are opposite in shape.** ACS error is measured, "
            "published per cell, and grows fast as geography shrinks. DHC error is "
            "unmeasurable by design (the Census Bureau injects it on purpose), estimated "
            "here from a decade-old demonstration file, and behaves differently by level."
        )

        fig, ax = plt.subplots(figsize=(8, 4.5))
        x = range(len(BANDS))
        width = 0.35
        acs_lo, acs_hi, acs_mid, dhc_lo, dhc_hi, dhc_mid = [], [], [], [], [], []
        for band in BANDS:
            ae, am = acs_sexage(acs_row, band, "both")
            ae, am = float(ae.iloc[0]), float(am.iloc[0])
            alo, ahi = acs_range(ae, am)
            acs_lo.append(ae - alo); acs_hi.append(ahi - ae); acs_mid.append(ae)

            de = float(dhc_sexage(dhc_row, band, "both").iloc[0])
            dlo, dhi = dhc_subgroup_range(de, level)
            dhc_lo.append(de - dlo); dhc_hi.append(dhi - de); dhc_mid.append(de)

        ax.errorbar([i - width / 2 for i in x], acs_mid, yerr=[acs_lo, acs_hi],
                    fmt="o", color=TIER_COLOR[TIER_SOLID], capsize=4, label="ACS (measured)")
        ax.errorbar([i + width / 2 for i in x], dhc_mid, yerr=[dhc_lo, dhc_hi],
                     fmt="s", color=TIER_COLOR[TIER_RISKY], capsize=4, label="DHC (modeled)")
        ax.set_xticks(list(x)); ax.set_xticklabels(BANDS)
        ax.set_ylabel("People")
        ax.set_title(f"{geo_label}: age bands, ACS vs. DHC (bars = 90% range)")
        ax.legend()
        st.pyplot(fig)
        plt.close(fig)

        st.caption(
            "Notice the pattern flip: ACS ranges widen fastest for small subgroups "
            "(65+ is usually the widest ACS bar). DHC's modeled range is comparatively flat "
            "across bands here, because it is built from an aggregate subgroup proxy, not a "
            "band-specific measurement -- a limitation of the model, not a real absence of "
            "risk in the smaller DHC bands."
        )


if __name__ == "__main__":
    main()
