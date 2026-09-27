# Population data-quality card -- design

**Date:** 2026-08-18
**File affected:** `Streamlit/app_US.py`
**Status:** Approved by user, pending implementation plan.

## Problem

The county-detail page renders "Total population" and "Median household
income" side by side in two columns (`pop_col`, `income_col`). For roughly
96% of counties, the Census Bureau publishes no sampling margin of error
for total population -- it's calibrated to independent population controls
(the Population Estimates Program) rather than measured purely from the
ACS sample, so a MOE would be misleading. In that (common) branch, the
population card is only three lines (title, big number, one caption)
while the income card next to it renders the full `render_card()` treatment
(CV, distribution plot, percentile rank, state comparison, ACS 1-year
comparison, "Show me the statistics" expander) -- producing a large,
visually unbalanced gap under the population card.

## Scope decision

Confirmed with the user before designing: **use only ACS/allocation data
already pulled and loaded** by this app (`data["alloc_county"]`, populated
in `_load_all()` via `load_alloc_us_county()`). No new Census API
ingestion. Race/ethnicity, education, housing, insurance, and employment
topics were identified as available future directions but require a new
ingestion script each and are explicitly out of scope here.

## Design

### What renders

A new bordered card, **"Population data quality,"** rendered directly
below the Total population card, inside `pop_col`, for **every** county
-- regardless of whether that county's population MOE exists (i.e.
identical in both the `pd.isna(pop_moe)` and `else` branches of the
existing code). This was a deliberate choice over only rendering it in
the no-MOE branch: showing it everywhere keeps the two branches
consistent (a well-measured county doesn't show strictly less context
than a poorly-measured one), even though it slightly grows the ~4% of
counties that already have a full population card.

Content, built with the app's existing `_stats_panel(rows, note)` helper
(the same `.stat-row` label/value HTML already used inside `render_card`'s
"Show me the statistics" expander -- no new CSS, no new visual language):

| Row | Source column | Table |
|---|---|---|
| Overall person-level imputation (Bureau-published) | `overall_alloc` | B98031 |
| Sex imputed | `sex_alloc` | B99011 |
| Age imputed | `age_alloc` | B99012 |
| Race imputed | `race_alloc` | B99021 |

All four columns already exist in `data["alloc_county"]` (produced by
`analysis/alloc.derive_rates()`), keyed by the same `_key` the income
card already uses to look up `income_alloc`. Missing values render
`"n/a"`, matching this file's existing `_ordinal()` NaN convention --
this panel always displays, so silently hiding a missing value (the
pattern `render_card`'s threshold-gated `alloc_line` uses) is wrong here.

One caption note beneath the four rows:

> "Imputed: filled in by the Census Bureau's statistical methods when a
> household didn't answer that question, rather than reported directly.
> These rates come from the Bureau's own person-level allocation tables
> and are separate from the margin of error above -- a county can have a
> very precise population count and still have some characteristics
> imputed, or vice versa."

This both defines "imputed" on first use (per the app's existing
plain-language convention, e.g. the Welcome tab and
`Streamlit/pages/1_Whose_data_is_this.py`'s `_term()` helper) and heads
off the likely misreading that this panel is another way of stating the
population CV.

### Where in the code

One new small helper function:

```python
def _population_quality_panel(alloc_county: pd.DataFrame, code: str) -> None:
    ...
```

Called once, in `pop_col`, immediately after the existing
`if pd.isna(pop_moe): ... else: ...` block -- so it renders once per
county regardless of which branch ran, and neither `render_card()` nor
the no-MOE `st.container(border=True)` block needs to change at all.

### Explicitly excluded (YAGNI)

- **No new ACS ingestion** (race/ethnicity detail, education, housing,
  insurance, employment) -- out of scope per the scope decision above.
- **No threshold/flagging logic** (unlike income's `alloc_threshold_pct` /
  `alloc_flagged` pattern) -- this panel is descriptive context, not a
  "this crossed a notable line" flag.
- **No SAIPE revival.** SAIPE's income comparison was deliberately removed
  from the Median household income card earlier in this same working
  session (explicit prior instruction). Reviving it here, even attached to
  a different card, would contradict that recent, explicit direction, so
  it's left out unless the user asks for it separately.
- **No proportional bar/meter visualization.** This project's own EDA 05
  finding: sex/age/race allocation is typically well under 1% nationwide
  (contrast income allocation, which can run ~39% in some counties). A
  bar rendered at sub-1% width would look like an empty/broken bar, not
  informative content -- plain stat-rows communicate the actual number
  without a misleading visual.

## Alternatives considered

1. **Only render in the no-MOE branch.** More minimal/literal fix for the
   exact visual gap in the reported screenshot, and touches less code.
   Rejected because it produces an inconsistent user experience: a
   county with a *better-measured* population (one that has a published
   MOE) would show *less* context than one with a worse-measured
   population, which reads backwards when a user compares two counties.
2. **Population by sex (Male/Female split).** Reuses `acs_sexage()` with
   `sex="male"/"female"`, already pulled. Considered but not chosen --
   the user's selected direction was the imputation/data-quality framing,
   not a demographic breakdown.
3. **Surface the already-computed ACS 1-year population estimate in the
   no-MOE branch too** (currently only shown in the has-MOE branch via
   `render_card`'s `acs1_compare` parameter). Considered as a "combo"
   option; not chosen since the user picked the data-quality direction
   specifically. Worth a future follow-up.

## Verification plan (for the implementation)

- `python -m py_compile Streamlit/app_US.py`
- `streamlit.testing.v1.AppTest`: render a real county in both the
  no-MOE branch (~96% of counties, e.g. `01001`) and, if one exists in
  the current pull, a county with a published population MOE, confirming
  the new card renders with no exception in both cases and shows `"n/a"`
  gracefully if any allocation column is NaN for that county.
