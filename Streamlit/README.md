# /Streamlit: dashboard apps

| File | What it is | Status |
|---|---|---|
| [`app_US_v2.py`](app_US_v2.py) | US county dashboard, version 2: every US county, 26 measures across 10 topics | **Current.** Use this one |
| [`app_US_v1.2.py`](app_US_v1.2.py) | Katie Christiansen's redesigned welcome page on top of v1.1 | Superseded by v2, which includes its welcome page verbatim |
| [`app_US_v1.1.py`](app_US_v1.1.py) | Justus Long's nationwide county explorer | Superseded by v2 |
| [`app.py`](app.py) | Trenton grant data prototype, NJ tracts | A learning instrument, not the deliverable (below) |

## US county dashboard (v2)

**Run it** from the repo root:

```bash
streamlit run Streamlit/app_US_v2.py
```

**Data it needs.** Run these four pulls first, in any order. Each prints its own sanity checks; outputs land in `data/raw/`.

```bash
python ingestion/pull_usdash.py
python ingestion/pull_us_geometry.py
python ingestion/pull_usdash_alloc.py
python ingestion/pull_rucc.py
```

`pull_usdash.py` requests 399 variables and can fail partway with "Unable to get metadata on the variable ...". That is an intermittent API failure, not a bad variable (see HANDOFF data landmines); run it again. If your local data is older than the code, the app does not crash: measures it cannot draw are hidden from the map and peers lists, and their cards say to re-run the pull.

### What is on it

- **Map.** Click a state, then a county. The map colors each county by the coefficient of variation (CV, the margin of error as a share of the estimate) of the measure you choose.
- **Cards.** Every card shows the estimate, its CV, and its 90% interval on a zero-anchored axis, so a wide margin of error visibly takes up more of the bar. Cards in the four-across grid use a narrower drawing so their text stays readable.
- **State reference markers.** 25 of 26 measures carry one. Medians and percentages show the state's own published value. Counts show what the county's number would be at the state's rate, because a state count is not on a county's scale; that marker is our calculation, carries a shaded margin of error, and is labelled on the card. Total population has no marker.
- **Statistical peers.** Counties whose estimate is statistically indistinguishable from the selected one at 90% confidence.

### The 26 measures

| Topic | Measures |
|---|---|
| Population | Total population; Under 5, 5-17, 18-64, 65+ |
| Poverty | Below poverty by the same four age bands; low income (below 200% of poverty) |
| Income | Median household income; households earning under $25k, $25k-$50k, $50k-$100k, $100k+ |
| Employment | Unemployed |
| Education | No high school diploma (age 25+) |
| Housing | Median gross rent; rent burden (median); cost-burdened renters (30%+); severely cost-burdened renters (50%+); median home value |
| Health | Uninsured |
| Disability | With a disability |
| Language | Limited English speaking households |
| Transportation | Households with no vehicle available |

The last seven additions follow scope decision #18 (2026-09-14); `docs/dashboard-variable-shortlist.md` records why each was chosen and which were held back.

### Adding a measure

Three lists in the code fail silently if you miss them: nothing errors, the measure just does not work.

1. Add its cells to the pull in `ingestion/pull_usdash.py`, with a sanity check.
2. Add its table prefix to `VALUE_COL_PREFIXES` in `analysis/dashboard.py`, or its columns are never converted to numbers.
3. Add accessor functions in `analysis/dashboard.py` and tests in `analysis/test_dashboard.py`, checking cell numbers against the published labels.
4. Add a `Measure` to `_build_measures()` in `app_US_v2.py`.
5. If its topic is new, add it to `TOPIC_ORDER`, or its card never appears.
6. If it is a median, add it to `_PEER_MEDIANS`, or the peers panel treats it as a count.
7. Re-run the pull, then **restart** the server. Streamlit's Rerun button does not reload changed `analysis/` modules.

### Known issues

- The welcome page is out of date in places: it says other cards do not compare to the state, and cites about 20 figures and seven topics. Its CV example drops two dollar signs, because Streamlit reads a pair of `$` as math.
- The default map (total population) is mostly grey. Total population is a controlled estimate with no published margin of error in most counties, and the map colors that the same as missing data.
- The bar fill is nearly white around CV 25%.
- A card can read "CV percentile rank: 39th of 23 counties", which joins a percentile to a county count.

## Trenton Grant Data Prototype — a learning instrument, not the MVP

**Run it:**
```bash
streamlit run Streamlit/app.py
```
Needs `data/raw/{acs5_2024_trenton,dhc_2020_trenton,trenton_tracts}*.parquet` —
regenerate with `python ingestion/pull_trenton_dashboard.py`.

### What this is

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

### How it's organized

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

### Two methodology choices baked into `analysis/dashboard.py`

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

### A real bug the stakeholder test caught

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

### The map

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

### Neighborhood names

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

### What's deliberately not here

DP1 (adds a third caveat with no new capability at tract level — it stops at tract
and duplicates DHC's population), block-group drilldown, any composite score
(excluded from Phase B by design), authentication, caching beyond `st.cache_data`,
and deployment. All MVP concerns, not prototype ones.
