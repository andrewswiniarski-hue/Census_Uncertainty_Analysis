# Composite reliability score on dashboard cards: design

**Date:** 2026-09-27
**Branch:** `card-error-bar-redesign`
**Files affected:** `analysis/composite.py`, `analysis/test_composite.py`, `Streamlit/app_US_v2.py`, a new test file under `tests/`, and the project docs listed under "Documentation".
**Status:** Design approved by the lead in conversation (2026-09-27); this written spec awaits review.

## Purpose

The project's research question Q2 asks whether several uncertainty components can be combined into one interpretable score. The EDA built that score (notebook 06, the CV by allocation matrix), but the US county dashboard does not show it: cards carry the CV, and only the median household income card mentions imputation, as a separate line. This change puts a combined, equal-weight reliability score on each card, so a county planner sees both sources of uncertainty in one number and a descriptive band, with the parts one click away.

## Decisions already made (lead, 2026-09-27)

1. **Combine the two components with an equal-weight score** (not worst-component, not a matrix-only view).
2. **Cut-offs as recommended** (sections "Sampling sub-score" to "Guard rule" below), including the guard rule and sampling-only scoring for the age bands.
3. **Measures with no imputation data show "not published"** and are scored on sampling alone.
4. **Card layout: a band strip across the top of the card** (option 3 of three mockups), with the sub-score breakdown and bars inside "Show me the statistics".
5. **Neutral band labels.** The v2 module docstring records a sponsor direction (2026-08-12) for a neutral federal-agency voice: no verdict chips, no "too risky" or "safe to cite" wording. The bands are therefore "Higher reliability", "Moderate reliability" and "Lower reliability", which describe the score and give no advice.
6. **Existing colors stay** (the Trenton prototype's Okabe-Ito tier colors). No other visual changes in this pass.

## Scope

**In:** the score calculation, the band strip on every eligible card, the breakdown in "Show me the statistics", tests, and documentation.

**Out, deferred:** the county report-card panel, a score layer on the map, a national "fit for use" view, any color changes, and the pre-existing duplicate "2K" axis tick in `_interval_svg` (found while drafting; a separate one-line fix).

## Score definition (our methodology, not a Census Bureau product)

Every scored card gets two sub-scores from 0 to 100, higher meaning more reliable, and a score that is their plain average.

### Sampling sub-score

Piecewise linear in the card's CV, through these anchors, clamped at 0 above the last:

| CV | Sub-score | Source |
|---|---|---|
| 0 | 100 | |
| 0.12 | 75 | ESRI high-reliability line (already cited in `analysis/viz.py`) |
| 0.30 | 50 | NCHS caution line; HUD's rule that an ACS median's MOE be under half the estimate is CV 0.304, the same line |
| 1/1.645 (about 0.608) | 0 | The MOE equals the estimate, so the 90% interval reaches zero. Our anchor, derived from the CV definition |

The CV is the card's own CV (`cv_from_range` on the card's estimate and interval), so the score and the CV badge describe the same number.

### Imputation sub-score

No published standard exists for how much imputation is too much, and rates are driven mostly by the question (median county: 38% of household incomes imputed, 1% of ages). The sub-score is therefore relative to other US counties on the same allocation table:

- `p` = the county's percentile rank among all 3,144 counties' rates for that table (pandas `rank(pct=True)`, average ties).
- `imputation_sub = min(100, 200 * (1 - p))`: 100 at or below the national median, 50 at the national 75th percentile (the flag line the income card already uses), falling to about 0 for the most-imputed county.
- Ranks are national, never recomputed for the current filter, matching the lead's 2026-08-12 decision that the income flag line is nationwide.

### Which measures carry an imputation component

| Allocation table | Column | Measures | Note |
|---|---|---|---|
| B99192 household income | `income_alloc` | Median household income; the four household income bands | Exact pairing |
| B99172 family poverty status | `fam_pov_alloc` | The four poverty age bands; low income (below 200% of poverty) | Labeled proxy, per decision #11 (no person-level table exists) |

Every other measure is **sampling only**, including the four population age bands (age imputation is 1.1% at the median county and 5.4% at the 99th percentile, too small for a relative scale to mean anything; lead decision 2026-09-27).

### Score and bands

- Two components: `score = (sampling_sub + imputation_sub) / 2`. Sampling only: `score = sampling_sub`.
- Bands: **Higher reliability** at 75 and above; **Moderate reliability** from 50 to below 75; **Lower reliability** below 50. Each sub-score's warning line sits at 50 and the CV 0.12 line at 75, so the band edges line up with the published CV lines.

### Guard rule

A figure's band can never be better than its CV alone gives it (CV at most 0.12: Higher; at most 0.30: Moderate; above: Lower). Equal weighting lets a good imputation sub-score offset a poor CV. Without the guard, 6,743 of 43,778 county figures with both components (15.4%) would be banded better than their CV allows. The score number is shown unchanged; only the band is capped, and the statistics panel says so when it happens.

### Figures that get no score

- Total population (a controlled estimate in 96% of counties; no strip, its card is unchanged).
- Top-coded median income (the existing notice is unchanged).
- Any figure with no computable CV (no published MOE, zero or missing estimate).
- A scored measure whose county has no allocation value falls back to sampling only, labeled "imputation rate not available for this county".

### Reference values from the current data (2020-2024 ACS, pulled 2026-09-14)

These are the design's scoping figures, not yet assert-guarded. They become test expectations where noted.

- Median household income, all counties: 67.6% Higher, 25.0% Moderate, 7.4% Lower.
- Poverty, under 5: 7.1% Higher, 46.5% Moderate, 43.9% Lower.
- Apache County, AZ, median household income: CV 3.8%, sampling 92.1; income imputation 58.8% (99.1st percentile), imputation 1.7; score 46.9, Lower reliability.
- Apache County, AZ, unemployed: CV 7.8%, sampling only, score 83.7, Higher reliability.

## Components

### `analysis/composite.py` (pure functions, no Streamlit)

Added beside the existing notebook helpers, which stay unchanged (`equal_weight_score` there is the percentile version used by notebook 06 and is not what the dashboard uses; its docstring gets one line saying so).

- `CV_SUBSCORE_ANCHORS`: the four anchors above, with their sources in a comment.
- `cv_subscore(cv) -> float`: NaN in, NaN out.
- `imputation_subscores(rates: pd.Series) -> pd.Series`: vectorized over all counties, same index; NaN rates stay NaN.
- `BAND_HIGHER`, `BAND_MODERATE`, `BAND_LOWER` label constants and `SCORE_BAND_EDGES = (75, 50)`.
- `ReliabilityScore` frozen dataclass: `score`, `sampling_sub`, `imputation_sub` (None for sampling only), `band`, `capped_by_cv` (bool), `imputation_source` (a short label such as "household income, Table B99192", or None), `imputation_is_proxy` (bool), `imputation_note` (None, "not published", or "not available for this county").
- `reliability_score(cv, imputation_sub=None, *, source=None, is_proxy=False, note=None) -> ReliabilityScore | None`: returns None when the CV is NaN. Applies the average, the bands and the guard.

### `Streamlit/app_US_v2.py`

- `Measure` gains `imputation: str | None = None`, a key into a new `IMPUTATION_SOURCES` dict: `"income"` and `"family_poverty"`, each giving the allocation column, a display label, the table ID and the proxy flag. Set on the ten measures in the table above; median household income is wired through the same dict even though its card is rendered by hand.
- `_load_all()` adds `data["imputation_subs"]`: for each source, `imputation_subscores()` over all counties, indexed by `_key`. Computed once per process.
- `render_card()` gains `reliability: ReliabilityScore | None = None`. When given, the first element inside the card container is the band strip (a 4px bar in the band color, then a row with the icon and band label on the left and "Reliability score 47 / 100" on the right), and one line under a dashed divider: "Sampling 92, imputation 2, averaged." or "Sampling only: imputation not published for this figure." In the four-across grid the right side shortens to "47 / 100".
- "Show me the statistics" gains: reliability score, band, and whether it was capped by the CV; sampling and imputation sub-scores as small horizontal bars in the existing panel style (or "not published"); the imputation source and proxy flag; and a note giving the method in one paragraph, labeled as our methodology pending mentor review.
- The existing income imputation line on the median income card and its statistics rows stay as they are.
- Band colors reuse `Streamlit/app.py`'s values: `#0072B2` Higher, `#E69F00` Moderate, `#D55E00` Lower, with icons ● ▲ ■. Band label text uses a darker shade of each color chosen to reach at least 4.5:1 contrast on white (WCAG AA), asserted by a test.
- Module docstring points 3 and 6 are updated: point 3 records that the score uses neutral band labels under the sponsor direction; point 6 records that the equal-weight card score now exists, as lead decision #19, with the tier-philosophy question still open for mentors.

## Error handling

The score never raises in the page: a missing CV gives no strip, and a missing allocation value gives a sampling-only score with its note. The stale-data guard is unaffected, since scoring only reads columns a card already needs plus the allocation file `_load_all()` already loads.

## Testing

- **`analysis/test_composite.py`:** the four anchors map exactly; the sub-score falls steadily as CV rises and is 0 beyond 0.608; NaN handling; the imputation sub-score is 100 at or below the median, 50 at the 75th percentile, and about 0 at the maximum on a synthetic series; band edges at 75 and 50; the guard (CV 0.35 with imputation 100 gives a score of about 71 but the Lower band, with `capped_by_cv` true); sampling-only scoring; None for NaN CV.
- **Real-data tests** (skipped when `data/raw` is absent, like the existing ones): Apache County median income scores 46.9 and Lower; the national median income band shares match the reference values above to one decimal.
- **App tests (new file under `tests/`):** the strip HTML carries the band label and score and no "risky", "safe" or "reliable to cite" wording; sampling-only cards show the "not published" line; each band's text color passes 4.5:1 on white.
- **Headless run of the real app** on Apache County and Washtenaw County, MI: the strip appears on every selected card except total population, the statistics panel shows both sub-scores, and there are no exceptions. Screenshot shared with the lead.
- The full suite (`analysis/` and `tests/`) must still pass.

## Documentation

- `HANDOFF.md`: decision #19 (the score definition, neutral labels, guard, sampling-only rule), and the dashboard status line.
- `README.md` Open Questions: the composite tier philosophy entry gains a note that an equal-weight score is now on the dashboard as a lead decision, pending mentor review of the anchors, the relative imputation scale and the guard.
- `WORKLOG.md`: an entry with the findings above.
- `docs/glossary.md`: reliability score, sampling sub-score, imputation sub-score.
- `Streamlit/README.md`: what the strip means and how a new measure gets an imputation source.
- Before any of the reference values go into the findings report or a deck, they need an assert-guarded notebook (CLAUDE.md). Not part of this change.

## Amendments after the final code review (2026-09-27)

- **Rounding.** The score is rounded half up to a whole number and the band is assigned from that rounded score, so the number on the card is the number that was classified. Before this, 783 county figures showed a score that contradicted their band (for example Los Angeles County median income, raw 74.502, shown as 75 beside Moderate). Median household income bands become 68.09% Higher, 24.79% Moderate, 7.13% Lower.
- **Wording for sampling-only cards.** Decision 3's "not published" is replaced on screen by "imputation is not part of this figure's score". The Census Bureau does publish age imputation (B99012); the age bands are sampling only by lead decision, so "not published" was untrue for them, and may be for other measures whose allocation tables were never checked.

