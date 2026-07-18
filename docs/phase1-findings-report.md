# Phase 1 Findings Report — Census Uncertainty Analytics

**Prepared for:** Andrew Swiniarski, project lead — for briefing the capstone team and Census Bureau mentors
**Date:** July 17, 2026
**Covers:** the complete Phase 1 exploratory analysis (notebooks 01–05), New Jersey testbed
**Companion materials:** biweekly deck (`docs/biweekly-2026-07-22.pptx`), eight charts in `data/processed/`, five notebooks in `notebooks/`

---

## Executive summary

Every number the Census Bureau publishes is an estimate, not an exact truth. Over the past two weeks we measured the three biggest reasons why, using New Jersey as our testbed — and the headline is this:

> **Uncertainty in Census data is not one thing. It is at least three separate things, each following its own rules, and the error bar the Bureau publishes captures only one of them.**

The three sources, in plain terms:

1. **Sampling noise** — surveys like the ACS only reach a fraction of households, so every estimate wobbles. This wobble follows a predictable mathematical law tied to how many people are behind the number. *This is the only source the published margin of error describes.*
2. **Privacy noise** — since 2020, the Bureau deliberately adds random noise to census counts so no individual can be identified. We measured it directly and found it behaves like a **fixed cost per place**: invisible for large areas, overwhelming for tiny ones.
3. **Imputation** — when households skip a question, the Bureau fills in a statistical guess. For income, this touches roughly **4 in 10 households** at the typical NJ tract. Critically, how much of a place's data is guessed has **no relationship** to its published error bar.

Because these three behave independently, two neighborhoods can carry identical margins of error while one has triple the guessed-in data and far more privacy distortion. A data user reading only the published "±" would treat them as equally trustworthy — and they are not. **This is the empirical justification for our main deliverable: a composite reliability score with multiple components.** The data's own structure demands it.

Along the way we made one genuine discovery worth the Bureau's attention (privacy noise depends on *which type* of geography you use, not just its size — see Section 4), and we documented a series of data landmines that any user of these products should know about.

---

## 1. The project and how we worked

**The assignment.** The Census Bureau's estimates influence over $2 trillion in federal funding, yet the uncertainty around those estimates is largely invisible to the people using them — county planners, business analysts, local officials. Our capstone asks: where does the uncertainty come from, can it be summarized into one interpretable score, and can that score be put on a map a non-expert can act on? Deliverables: a written report, a reproducible codebase, and a dashboard.

**The testbed.** All of Phase 1 uses New Jersey: 21 counties, ~2,200 census tracts (neighborhood-sized, ~4,000 people), ~6,600 block groups (~600–3,000 people), and — for the privacy analysis — all 169,588 census blocks (often a single street face). One state keeps the data manageable while spanning the full range from dense cities to rural townships.

**The working method, in one paragraph.** Every dataset we use is downloaded by a script anyone can rerun (no hand-downloaded files), every analysis lives in a notebook that runs top-to-bottom cleanly, and every headline claim in those notebooks is guarded by an automated check that fails loudly if the data ever stops supporting it. Before we analyze anything we run "sanity panels" — row counts against known facts (NJ has exactly 21 counties), checks that tables add up internally, checks that joins between datasets match one-for-one. Several times these checks caught real problems before they could contaminate results. Everything traces back to the project's four research questions, and every surprising result was logged the day we found it.

**The five analyses.**

| Notebook | Question | Noise source |
|---|---|---|
| EDA 01 | How does reliability change as geography shrinks? | Sampling |
| EDA 02 | Why are some variables far less reliable than others? | Sampling |
| EDA 03 | Where does unreliability concentrate on a map? | Sampling |
| EDA 04 | How big is privacy noise, and how does it behave? | Privacy |
| EDA 05 | How much data is imputed, and is that independent of the error bars? | Imputation |

---

## 2. A three-minute vocabulary (everything else builds on this)

- **Estimate** — the published number. Never exactly the truth.
- **Margin of error (MOE)** — the published "±". "Median income $67,000 ± $3,000" means: if the survey were run many times, about 90% of ranges built this way would contain the true value.
- **Coefficient of variation (CV)** — our workhorse measure: the noise expressed *as a fraction of the thing being measured*. A CV of 0.30 means the noise is 30% the size of the estimate itself. Why we use it: a ±$3,000 error means something completely different on a $200,000 estimate versus a $10,000 one; the CV puts every estimate — income, population, poverty — on one comparable scale. (Common conventions from other agencies: CV under 0.12 is "high reliability," over 0.30 gets flagged, over 0.40 is "low." We show these lines for orientation; our own tiers will be a mentor-reviewed decision.)
- **The Decennial Census vs. the ACS** — the Decennial Census counts *everyone* every ten years (no sampling noise, but privacy noise since 2020). The American Community Survey (ACS) runs continuously on a *sample* (sampling noise dominates; MOEs published with every number).

---

## 3. Sampling noise: the law of shrinking places (EDA 01–03)

### What we did

We pulled four variables spanning the difficulty range — total population, median household income, people below the poverty line, and one deliberately small subgroup (Black residents 65+) — at county, tract, and block-group level, together with the Bureau's official margins of error. From these we computed CVs and studied how they change across geography levels and variable types, then put the results on maps.

### What we found, in plain terms

**Finding 1 — Zoom in and reliability collapses, predictably.** The same survey, in the same state, gives wildly different reliability depending on zoom level. Median household income: at county level the typical error is about **1.4%** of the estimate. At tract level, **13%**. At block-group level, **20%**, with worst cases where the error bar is *bigger than the incomes being measured* (we found a county-level ±$3,982 versus a block-group ±$247,531 — a 62× difference in the same data product). The important part is not that small places are noisier — it's that the collapse is *lawful*: noise grows in near-perfect proportion to one over the square root of the number of people behind the estimate. On the right kind of chart, that law is a straight line, and our data sits on it. A predictable problem is a scoreable problem.

**Finding 2 — What you count matters as much as where.** At the *same* tract level: total population is fine (typical CV ~0.08), poverty is shaky (~0.38), and the Black 65+ count is close to unusable (~0.89 — the noise is nearly as large as the number itself). The mechanism is the same law again: the fewer people behind a number, the noisier it is, and subgroup counts have few people behind them by definition. One practical technique came out of this: adding the six published sex-and-age cells for Black 65+ into a single number (with the Bureau's own formula for combining error margins) meaningfully improves its reliability — aggregation is the user's best defense against sampling noise.

**Finding 3 — Unreliability has a geography.** On the map, low-reliability tracts are not scattered randomly; they cluster — and income holds up much better than poverty everywhere. The pair of maps (one variable reliable, one not, same tracts) is the clearest preview of what the final dashboard should let a county planner see.

### Landmines documented along the way

These matter because a naive analysis silently gets them wrong: incomes above $250,000 are published as exactly "$250,001" (a cap, not a measurement — we exclude them and say so); the API returns giant negative code numbers in place of some values, which must be treated as "no data," never as data; county population totals are pinned to official benchmarks and carry *no* error margin — which means a missing error bar can signal either "extremely reliable" or "too little data to publish," two opposite meanings; and 131 NJ tracts publish population error margins suspiciously close to zero for no documented reason (logged as a mentor question).

---

## 4. Privacy noise: a fixed cost that small places pay (EDA 04)

### The setup, in plain terms

Since 2020, the Bureau protects privacy by adding deliberate random noise to census counts before publishing them (the "Disclosure Avoidance System"). To let the public evaluate that system, the Bureau took the *confidential* 2010 census data and re-published it with the 2020 noise applied — the "demonstration data." Because the real 2010 counts were also published back in 2010, subtracting one file from the other reveals the noise itself. That's what we did, for every geography in New Jersey from the state down to all 169,588 blocks.

Two honesty notes we carry everywhere: the demonstration data exists *only* for this kind of evaluation (it must never be read as real 2010 populations), and the 2010 published baseline was itself lightly protected by an older method called swapping — so what we measure is the new noise plus a residue of the old, a caveat the Bureau's own documentation states.

### How we measured it (and why we trust the numbers)

Before analyzing anything, we proved our file-reading was correct using the system's own promises. The Bureau guarantees state totals get *no* noise — and our parsed demonstration total for New Jersey came out at exactly **8,791,894**, matching the published count to the person. We also verified internal arithmetic (males + females = total, on all 219,847 records) that would shatter if we had misread even one column. Only then did we compute noise.

For the headline analysis we grouped places into size buckets and asked, per bucket: *how big is the typical miss, relative to the size of the place?* (Technically: the root-mean-square error divided by the average count — the direct analog of the CV, so privacy noise and sampling noise can be read on the same scale.) We did it this way because privacy noise averages out to zero and many places are hit by exactly zero — a naive place-by-place approach would silently drop the zeros and overstate the noise.

### What we found, in plain terms

**Finding 4 — Privacy noise is a nearly fixed absolute cost, which means small places pay the biggest relative price.** A county of 500,000 people gets misstated by ±2–5 people — nothing. A tract's worst miss statewide was 11 people. But the noise doesn't shrink much as places get smaller, so *relatively* it explodes: for total population it crosses the standard "interpret with caution" line for blocks under ~21 people and the "high reliability" line at ~62. On the chart, privacy noise falls along a visibly steeper line than sampling noise — **the two mechanisms follow different laws**, which is the flagship chart of the whole phase. Practical reading: aggregate up even slightly and privacy noise vanishes; work at block level and it dominates — and at block level, it's the *only* game in town, because surveys don't publish there at all.

**Finding 5 — the discovery: noise depends on the *type* of geography, not just its size.** We expected noise to grow steadily as geography shrinks. It doesn't. Block groups — sitting *between* tracts and blocks in the hierarchy — carry about **9× more absolute noise than tracts** and 3× more than blocks. A block group and a tract of the *same population* differ by roughly **12×** in noise. The likely mechanism (offered as a hypothesis, not a conclusion): the privacy system spends its "noise budget" down a specific spine of geographies, and published block groups appear to sit off that spine, inheriting accumulated noise from the blocks beneath them. We've queued this for the mentors. The implication for our score is immediate: **which geography type you use must be a scoring component in its own right** — size alone cannot capture this.

**Finding 6 — ghost and vanished places.** Mean-zero noise on tiny counts does something categorical, not just numerical: **807 blocks** published as empty show phantom residents in the noisy file (4,695 phantom people), and **427 inhabited blocks** show as empty (1,154 real people erased). For anyone consuming block-level counts directly — redistricting, emergency planning — that's not "a little noise," it's a flipped answer to "does anyone live here?"

**Finding 7 — small subgroups take the worst of it, again.** For the Black 65+ count, privacy noise at the typical tract (which holds just 18 such residents) runs 30–40% relative — right at the caution thresholds. Context that surprised us: that's still 2–3× *smaller* than the sampling noise the ACS carries for the same subgroup at the same level. For small groups in small places, *both* mechanisms bite, and the discipline of the census hierarchy showed up beautifully in our checks: total-population errors cancel to exactly zero at every level, and the subgroup's statewide error of +16 propagates identically through every level of the hierarchy.

---

## 5. Imputation: the uncertainty the error bar can't see (EDA 05)

### The setup, in plain terms

When a household skips a question, the Bureau fills the blank with a statistically plausible value — "imputation" (the ACS calls it "allocation"). The Bureau publishes, for each subject, how much of the data was filled in this way. Two facts shape everything: these allocation tables carry **no error margins of their own**, and an estimate's published MOE **does not widen** when the data behind it was guessed. So imputation is a genuinely separate dimension of trustworthiness — *if* it doesn't simply track the error bars anyway. Testing that was the point of EDA 05.

### What we found, in plain terms

**Finding 8 — Imputation is common, and wildly uneven across subjects.** Overall, about **1 in 7 person-characteristics** in New Jersey is imputed (county rates 11.5–16.4%). But the average hides the story: sex is almost never imputed (~0.05%), age and race under 1% — while **income is imputed for ~39% of households at the typical tract**, and similar for the poverty-status calculation built on it. People will tell the Census who they are; they resist saying what they earn. Imputation, like sampling noise, is a *variable-type* story.

**Finding 9 — Imputation is statistically independent of the published error bars.** Across 2,200 tracts we asked: do heavily-imputed places also have wide error bars? Answer: essentially no relationship — knowing one tells you nothing about the other. One methods point worth understanding, because it's the kind of thing the mentors will probe: both reliability and (potentially) imputation vary with the *size* of a place, so a naive correlation can be pure coincidence-by-size. We removed the known size effect first, then correlated what remained. The poverty pairing proved the point perfectly: the naive calculation shows an apparent relationship (−0.18) that vanishes to zero (+0.02) once size is accounted for. Every properly-controlled correlation landed between 0.00 and 0.19 — noise level. (The single 0.19, income-on-income, is queued as a mentor question.)

**Why this finding carries the whole project:** if imputation *had* tracked the error bars, one number could summarize both and a simple score would do. It doesn't. **The multi-component composite score is not our design preference — it's what the data requires.**

---

## 6. The synthesis: what the composite score must be

Phase 1's purpose was to find out what a credible reliability score needs to contain. The evidence now says:

| Component | Why (which finding) |
|---|---|
| **Size of the count** behind the estimate | The sampling law — the single strongest driver (Findings 1–2) |
| **Geography level** as its own factor | The block-group anomaly — same size, 12× the privacy noise (Finding 5) |
| **Variable type** (total vs. characteristic vs. income-like) | Reliability and imputation both vary by orders of magnitude across variables (Findings 2, 8) |
| **Product mechanism** (survey vs. full count) | Sampling and privacy noise follow different laws — different advice to users (Findings 1, 4) |
| **Data completeness** (imputation rate) | Independent of everything the MOE captures (Finding 9) |
| **A "no usable estimate" class** | Zero counts, top-coded values, ghost/vanished places — never averaged in, always labeled (Findings 6 + landmines) |

And one sentence for the Bureau audience, which I'd stand behind in any room:

> *A tight margin of error is not the same thing as a trustworthy number. We can now show, with the Bureau's own published data, that two places with identical error bars can differ enormously in how much of their data was imputed and how much privacy noise they carry — and a reliability score that reflects all three dimensions is buildable, because all three turned out to be measurable and lawful.*

---

## 7. What we don't know yet (queued for the mentors)

1. **Product shortlist** — confirm the 3–5 Census products the report and dashboard should cover.
2. **Privacy-noise vintage** — is the 2022-08-25 demonstration release the right basis, or should we move to the 2023 production-settings files?
3. **The block-group anomaly** — is our budget-allocation reading correct, and does the pattern persist in the production 2020 data?
4. **Score input for privacy** — the Bureau's published noise-budget numbers, or the noise we measured empirically?
5. **The 131-tract mystery** — why do 6% of NJ tracts publish near-zero population error margins?
6. **The tract floor** — poverty and detailed demographic tables stop at tract level; is that an acceptable floor for the dashboard?
7. **The income-allocation signal** — is the one weak correlation we found (0.19) a known mechanism or ignorable?

---

## 8. What happens next

- **July 22 biweekly:** present the status slide and the three priority questions (deck is built: `docs/biweekly-2026-07-22.pptx`).
- **Composite-score phase:** design the score from the component list above, with the tier thresholds as an explicit mentor-reviewed decision.
- **Dashboard:** grow the EDA 03 map prototype into the linked-map deliverable a county planner can act on.
- **Report:** this document's findings become the report's empirical backbone; the methodology write-up (`docs/uncertainty-sources.md`) is the next writing task.

---

## Appendix: where everything lives

| Item | Location |
|---|---|
| Analyses (run top-to-bottom, checks included) | `notebooks/01…05-*.ipynb` |
| Shared formulas, with citations | `analysis/acs.py`, `analysis/dhc.py` |
| Data pull scripts (rerunnable by anyone) | `ingestion/pull_*.py` |
| All eight charts | `data/processed/eda0*.png` |
| Term definitions | `docs/glossary.md` |
| Dataset catalog + landmines | `docs/data-dictionary.md` |
| Running log of who did what and what was found | `WORKLOG.md` |
| Open questions, decisions, current state | `README.md`, `HANDOFF.md` |

*Every number in this report is reproducible: each one is computed and assert-guarded in a committed notebook, from data that regenerates via a single script run.*
