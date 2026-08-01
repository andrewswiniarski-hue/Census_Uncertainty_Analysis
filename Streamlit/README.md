# Trenton Grant Data Prototype — a learning instrument, not the MVP

**Run it:**
```bash
streamlit run Streamlit/app.py
```
Needs `data/raw/{acs5_2024_trenton,dhc_2020_trenton,trenton_tracts}*.parquet` —
regenerate with `python ingestion/pull_trenton_dashboard.py`.

## What this is

The EDA suite (`notebooks/01–10`) has produced metrics and charts, but nobody on the
team had yet sat in the seat of the person who actually *uses* this data. This app
reverses the direction of the work: instead of measuring uncertainty and then
wondering how to present it, it starts from a real decision a real stakeholder has to
make and works backwards.

**The scenario:** the City of Trenton, NJ is assembling community demographic
profiles — age × sex counts and poverty figures, by neighborhood — to support federal
**Urban Forestry** and **Safe Streets** grant applications. The grant writer is not a
statistician. If they cite a tract-level number with a ±66% error, the application is
built on sand and nobody in the room knows it.

This is **not** the Executive Dashboard deliverable. It exists to teach the team (and
give the mentors something concrete to react to for the Weeks 4–6 "dashboard
wireframe" exit criterion) — not to be shipped, hardened, or deployed.

## How it's organized

Three tabs, one geography picker in the sidebar (Trenton citywide, Mercer County, or
any of the 25 Mercer tracts that make up Trenton — Trenton is exactly
tract-coextensive, confirmed live against the API):

- **ACS (survey estimates).** Population-by-age and poverty-by-age cards, each range-first:
  the range is the headline, the point estimate is secondary, with a plain-language
  tier chip (**Solid / Use with care / Too risky**) and a collapsed "Show me the
  statistics" panel for CV/MOE detail. Ranges come directly from the Census Bureau's
  published margin of error — measured, not modeled.
- **DHC 2020 (full count).** Same card pattern, but DHC ships no uncertainty measure
  at all. Every range here is **modeled**, built from the 2010 DAS demonstration study
  in `analysis/noise_model.py` (EDA 04), scaled into a comparable interval — and
  labeled that way on every card. No poverty section: DHC publishes no poverty table,
  which is itself a finding, not an omission.
- **Compare.** The same age bands from both products side by side, with the two
  things a stakeholder must not misread: the vintage gap (ACS 5-year average vs. a
  DHC April-2020 snapshot) and the shape gap (ACS error grows with shrinking
  geography; DHC's modeled error is comparatively flat because it's built from an
  aggregate proxy, not a band-specific measurement).

## Two methodology choices baked into `analysis/dashboard.py`

1. **Tiers** (Solid ≤ 0.12 CV, Use with care ≤ 0.30, Too risky above) reuse the
   ESRI/NCHS conventions already cited in `analysis/viz.py`. They are **our proposed
   tiers**, not adopted Census thresholds (see HANDOFF.md decision #8) — every card
   says so in its stats panel.
2. **DHC ranges at the "place" (whole-city) level** are not looked up from a curve —
   Trenton isn't a DAS spine geography (state/county/tract/block group/block only).
   Instead they're built by root-sum-of-squares over the 25 constituent tracts'
   modeled errors, the same independence-assumption combination
   `analysis.acs.aggregate_moe` already uses for ACS. This is an extension of the
   noise model, not something notebook 04 measured directly.
3. **Poverty rates use the true poverty-universe denominator, not total population.**
   Every poverty card now also shows a rate (e.g. "≈ 27.8% of Under 5 residents in
   poverty, range 22.2%–33.5%"), computed with the Census ratio-MOE formula
   (`analysis.dashboard.poverty_rate`) — poverty count is a *subset* of the poverty
   universe, so combining their MOEs in quadrature (like `aggregate_moe` does for
   independent estimates) would be the wrong formula. The denominator is B17001's
   own poverty-universe total (below + at-or-above poverty, both pulled), not
   B01001's total population — the two differ by a few percent because B17001
   excludes some group quarters residents from poverty-status determination. The
   same rate, with a tooltip line, is available on the map for any "Poverty: *band*"
   selection.

## A real bug the stakeholder test caught

Early testing showed the poverty/Under-5 card at Mercer Tract 1 rendering a range of
**"-34 to 402"** — a negative count of children, because the true MOE exceeds the
estimate for that small a subgroup. `render_card()` now floors the *displayed* low
bound at 0 while keeping the *true* (possibly negative) bound in the CV calculation —
clamping the number a stakeholder never touches the number that decides the tier. A
range that dips below zero is now called out explicitly as its own warning: it's a
signal of how unreliable the estimate is, not a bug to hide.

A second gap, this one in labeling rather than data: the age cards were titled
"Age × sex" on both product tabs, but every card calls `acs_sexage`/`dhc_sexage`
with `sex="both"` — sex is never actually broken out on screen, just total
population per age band. The section is titled **"Population by age"** now,
which is what it has shown all along. The underlying tables (B01001, P12) do
carry the male/female split if a future pass wants to surface it (a bigger UI
decision, deliberately not made here — see WORKLOG).

## The map

Each product tab ends in an interactive tract choropleth (pydeck `GeoJsonLayer` over
a CARTO basemap, `st.pydeck_chart`) — hover any of the 25 tracts for its tier, range,
and best estimate. Colors are the **Okabe-Ito colorblind-safe palette** (blue / orange
/ vermillion), chosen specifically to avoid red-green — the most common form of color
blindness — and every tier also carries a distinct icon (● ▲ ■) on the cards as a
second, color-independent cue. The legend is a small inline HTML strip under the map,
not matplotlib's default legend (which rendered oversized at this figure size — the
original static-map version of this app used `geopandas.plot` + matplotlib; it's been
fully replaced). When the sidebar geography is a single tract, the map shows **only**
that tract, zoomed in tight — the all-25 view is reserved for the citywide/county
selections, where cross-tract comparison is the point.

## Neighborhood names

The sidebar and map tooltips show `Tract N — Neighborhood` (e.g. "Tract 3 —
Chambersburg"). **No official Census or City of Trenton neighborhood-boundary file
exists** — this project checked. The names come from OpenStreetMap's community-tagged
`place=neighbourhood/suburb/quarter` points (15 fall inside Trenton's boundary), each
tract labeled with its *nearest* such point to the tract centroid
(`ingestion/pull_trenton_dashboard.py::_attach_neighborhood_names`). Verified in
planning: all 25 tracts land within 0.70 miles of their assigned point. This is a
**display-only approximation** — it affects no statistic, only what the sidebar and
map tooltip are labeled — and is called out as such in the sidebar caption. Logged as
an open question for mentors (README.md): is showing an approximate, crowdsourced
neighborhood name an acceptable stakeholder-facing convenience, or does an unofficial
label risk undermining trust in the (correct) statistics next to it?

## What's deliberately not here

DP1 (adds a third caveat with no new capability at tract level — it stops at tract
and duplicates DHC's population), block-group drilldown, any composite score
(excluded from Phase B by design), authentication, caching beyond `st.cache_data`,
and deployment. All MVP concerns, not prototype ones.
