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

- **ACS (survey estimates).** Age × sex and poverty-by-age cards, each range-first:
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

## A real bug the stakeholder test caught

Early testing showed the poverty/Under-5 card at Mercer Tract 1 rendering a range of
**"-34 to 402"** — a negative count of children, because the true MOE exceeds the
estimate for that small a subgroup. `render_card()` now floors the *displayed* low
bound at 0 while keeping the *true* (possibly negative) bound in the CV calculation —
clamping the number a stakeholder never touches the number that decides the tier. A
range that dips below zero is now called out explicitly as its own warning: it's a
signal of how unreliable the estimate is, not a bug to hide.

## What's deliberately not here

DP1 (adds a third caveat with no new capability at tract level — it stops at tract
and duplicates DHC's population), interactive hover tooltips, block-group drilldown,
any composite score (excluded from Phase B by design), authentication, caching beyond
`st.cache_data`, and deployment. All MVP concerns, not prototype ones.
