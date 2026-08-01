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

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from matplotlib.colors import ListedColormap

from analysis.dashboard import (
    BANDS,
    TIER_CARE,
    TIER_RISKY,
    TIER_SOLID,
    acs_poverty,
    acs_range,
    acs_sexage,
    cv_from_range,
    dhc_population_range,
    dhc_sexage,
    dhc_subgroup_range,
    load_acs,
    load_dhc,
    load_trenton_tracts,
    tier,
)
from analysis.acs import Z_90

st.set_page_config(page_title="Trenton Grant Data Prototype", layout="wide")

TIER_COLOR = {TIER_SOLID: "#2ca25f", TIER_CARE: "#f0a336", TIER_RISKY: "#d9534f", "No data": "#cfcfcf"}
TIER_ICON = {TIER_SOLID: "●", TIER_CARE: "▲", TIER_RISKY: "■", "No data": "–"}


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


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------

def render_card(title: str, est: float, low: float, high: float, *, caveat: str | None = None) -> None:
    # CV uses the TRUE (possibly negative) low bound -- a small count's MOE
    # can exceed the estimate, which is real information about how weak the
    # estimate is. Only the DISPLAYED low bound is floored at 0: nobody can
    # cite "-34 children," but the tier must still reflect how bad that MOE
    # really is (a clamped-then-measured CV would UNDERSTATE the risk).
    cv = cv_from_range(est, low, high)
    label, line = tier(cv)
    color = TIER_COLOR[label]
    display_low = max(0.0, low)
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.markdown(
            f"<div style='font-size:1.6rem;font-weight:700;margin:2px 0;'>"
            f"{display_low:,.0f} &ndash; {high:,.0f}</div>"
            f"<div style='color:#888;font-size:0.85rem;'>best estimate: {est:,.0f}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<span style='background:{color};color:white;padding:2px 10px;"
            f"border-radius:12px;font-weight:600;font-size:0.85rem;'>"
            f"{TIER_ICON[label]} {label.upper()}</span>",
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
            st.write(
                {
                    "estimate": round(est, 1),
                    "range half-width": round((high - low) / 2, 1),
                    "true low bound (unclamped)": round(low, 1),
                    "implied CV": round(cv, 4) if cv == cv else None,
                    "tier rule": "CV ≤ 0.12 Solid, ≤ 0.30 Use with care, else Too risky "
                    "(ESRI/NCHS conventions -- our proposed tiers, not adopted Census thresholds)",
                }
            )


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------

def render_tier_map(tracts_gdf, tier_by_tract: dict[str, str], title: str) -> None:
    gdf = tracts_gdf.copy()
    gdf["tier"] = gdf["TRACT"].map(tier_by_tract).fillna("No data")
    order = [TIER_SOLID, TIER_CARE, TIER_RISKY, "No data"]
    gdf["tier"] = pd.Categorical(gdf["tier"], categories=order)
    cmap = ListedColormap([TIER_COLOR[t] for t in order])
    fig, ax = plt.subplots(figsize=(5, 6))
    gdf.plot(column="tier", cmap=cmap, categorical=True, legend=True, ax=ax,
              edgecolor="white", linewidth=0.6, missing_kwds={"color": TIER_COLOR["No data"]})
    ax.set_axis_off()
    ax.set_title(title, fontsize=10)
    st.pyplot(fig)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Geography selection
# ---------------------------------------------------------------------------

def geography_picker(tracts_gdf) -> tuple[str, str | None, str]:
    tract_options = {
        _tract_label(row["NAME"]): row["TRACT"] for _, row in tracts_gdf.iterrows()
    }
    choice = st.sidebar.radio(
        "Geography", ["Trenton (whole city)", "Mercer County"] + sorted(
            tract_options, key=lambda s: tract_options[s]
        ),
    )
    if choice == "Trenton (whole city)":
        return "place", None, "Trenton"
    if choice == "Mercer County":
        return "county", None, "Mercer County"
    return "tract", tract_options[choice], choice


# ---------------------------------------------------------------------------
# App body
# ---------------------------------------------------------------------------

def main() -> None:
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

        st.markdown("##### Age x sex")
        cols = st.columns(4)
        for col, band in zip(cols, BANDS):
            est, moe = acs_sexage(acs_row, band, "both")
            with col:
                render_card(band, float(est.iloc[0]), *acs_range(float(est.iloc[0]), float(moe.iloc[0])))

        st.markdown("##### Living below the poverty line, by age")
        cols = st.columns(4)
        for col, band in zip(cols, BANDS):
            est, moe = acs_poverty(acs_row, band, "both")
            with col:
                render_card(band, float(est.iloc[0]), *acs_range(float(est.iloc[0]), float(moe.iloc[0])))

        st.markdown("##### Where can you actually cite this? (all 25 tracts)")
        map_choice = st.selectbox(
            "Map this figure", ["Total population"] + BANDS, key="acs_map",
        )
        tract_df = data["acs"]["tract"]
        tier_by_tract: dict[str, str] = {}
        for _, row in tract_df.iterrows():
            if map_choice == "Total population":
                e, m = float(row["B01001_001E"]), float(row["B01001_001M"])
            else:
                one = tract_df[tract_df["TRACT"] == row["TRACT"]]
                e_s, m_s = acs_sexage(one, map_choice, "both")
                e, m = float(e_s.iloc[0]), float(m_s.iloc[0])
            lo, hi = acs_range(e, m)
            tier_by_tract[row["TRACT"]] = tier(cv_from_range(e, lo, hi))[0]
        render_tier_map(data["tracts"], tier_by_tract, f"ACS reliability: {map_choice}")

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

        st.markdown("##### Age x sex")
        cols = st.columns(4)
        for col, band in zip(cols, BANDS):
            est = dhc_sexage(dhc_row, band, "both")
            e = float(est.iloc[0])
            rng = dhc_subgroup_range(e, level)
            with col:
                render_card(band, e, *rng, caveat="Modeled, not measured.")

        st.markdown("##### Where can you actually cite this? (all 25 tracts)")
        map_choice_dhc = st.selectbox(
            "Map this figure", ["Total population"] + BANDS, key="dhc_map",
        )
        dhc_tract_df = data["dhc"]["tract"]
        tier_by_tract_dhc: dict[str, str] = {}
        for _, row in dhc_tract_df.iterrows():
            if map_choice_dhc == "Total population":
                e = float(row["P1_001N"])
                lo, hi = dhc_population_range(e, "tract")
            else:
                one = dhc_tract_df[dhc_tract_df["TRACT"] == row["TRACT"]]
                e = float(dhc_sexage(one, map_choice_dhc, "both").iloc[0])
                lo, hi = dhc_subgroup_range(e, "tract")
            tier_by_tract_dhc[row["TRACT"]] = tier(cv_from_range(e, lo, hi))[0]
        render_tier_map(data["tracts"], tier_by_tract_dhc, f"DHC modeled reliability: {map_choice_dhc}")

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
                    fmt="o", color="#3182bd", capsize=4, label="ACS (measured)")
        ax.errorbar([i + width / 2 for i in x], dhc_mid, yerr=[dhc_lo, dhc_hi],
                     fmt="s", color="#e6550d", capsize=4, label="DHC (modeled)")
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
