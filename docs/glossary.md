# Glossary — Census Uncertainty Analytics

Running glossary of every statistical term used in this project. House rule (from
`CLAUDE.md`): define every term the first time it appears in any document or
notebook, then add it here. Plain English first, math second.

> *Seeded from terms already used in `README.md` and `NEXT_ACTIONS.md`. Definitions
> will be refined against the official Census methodology docs during Phase 1,
> Step 2 (methodology grounding) — treat these as working definitions until then.*

---

**ACS (American Community Survey)** — The Census Bureau's ongoing survey covering
income, poverty, education, housing, and more. Because it surveys a *sample* of
households rather than everyone, every ACS estimate has sampling error — which is
why ACS estimates ship with margins of error. The **5-year estimates** pool five
years of responses so that even small areas (tracts, block groups) have enough
sample to publish.

**Decennial Census** — The full count of every U.S. resident, every 10 years. It is
not a sample, so it has no sampling error; its main uncertainty sources are
*coverage error* (missed or double-counted people) and, since 2020, deliberately
injected *privacy noise* (see DAS).

**Estimate** — The published number (a count, a median, a rate). It is never exactly
the truth; the uncertainty measures below describe how far off it might be.

**Derived estimate** — A number we compute from published estimates (e.g., summing
the six Black 65+ sex×age cells into one 65+ count) rather than one the Bureau
publishes directly. A derived estimate needs its own uncertainty measure, combined
from the components' MOEs (see *MOE aggregation*), and is always labeled as our
computation. First used in `notebooks/02-cv-by-variable-type.ipynb`.

**MOE (Margin of Error)** — The "±" published alongside every ACS estimate, at 90%
confidence. "Median income $67,000 ± $3,000" means: if the survey were run many
times, about 90% of intervals built this way would contain the true value.
*Source: ACS "Accuracy of the Data" documentation.*

**MOE aggregation (root-sum-of-squares, RSS)** — The Census-documented way to give
a *derived estimate* an MOE: square each component's MOE, sum, take the square
root (`MOE_agg = sqrt(Σ MOE_i²)`). One refinement matters when components are
zero: include only the **largest** zero-cell MOE, once — zero-estimate MOEs are
near-identical placeholders, and root-sum-squaring several of them overstates the
combined uncertainty. The formula assumes independent components, which tends to
overstate MOEs for cells from the same table. *Source: "Understanding and Using
American Community Survey Data: What All Data Users Need to Know," Ch. 8.*
Implemented in `analysis/acs.py::aggregate_moe`.

**SE (Standard Error)** — The typical size of the random wobble in an estimate.
For ACS estimates: `SE = MOE / 1.645`, because 1.645 is the multiplier for 90%
confidence. *Source: ACS "Accuracy of the Data" documentation.*

**CV (Coefficient of Variation)** — The noise expressed as a fraction of the thing
being measured: `CV = SE / estimate`. A CV of 0.30 means the noise is 30% the size
of the estimate itself. Because it's unitless, it lets us compare reliability
across variables of totally different scales (income vs. population counts).
Reliability thresholds (e.g., "CV > 0.30 = low reliability") vary by agency — we
will cite the source when we adopt ours.

**Reliability threshold conventions** — Common CV cutoffs other organizations use
to label estimate reliability: ESRI's ACS documentation calls CV < 0.12 *high
reliability*, 0.12–0.40 *medium*, and > 0.40 *low*; the National Center for
Health Statistics (NCHS Data Presentation Standards) flags estimates with
CV > 0.30 as unreliable. Our EDA charts show these lines for orientation only —
this project's own tiers are a deliberate, mentor-reviewed decision scheduled
for the composite-score phase (weeks 4–6). First used in
`notebooks/01-cv-by-geography-size.ipynb`.

**Sampling error** — Uncertainty that exists because a sample was measured instead
of everyone. Shrinks as sample size grows; explodes for small geographies and
small subgroups. The dominant uncertainty source in the ACS.

**Nonresponse** — People who don't answer: a whole household skipping the survey is
*unit nonresponse*; skipping one question is *item nonresponse*. Both are handled
by statistical fixes (weighting, imputation) that add their own uncertainty.

**Imputation / allocation** — Filling in a missing answer with a statistically
plausible value. The **item allocation rate** is the share of a variable's
published values that were filled in rather than reported — a rough proxy for how
much of that variable is "real" data.

**Disclosure avoidance / DAS** — Methods that prevent identifying individual people
from published tables. The 2020 **Disclosure Avoidance System (DAS)** deliberately
adds calibrated random noise ("privacy noise") to Decennial counts using the
TopDown Algorithm.

**Differential privacy** — The mathematical framework behind the 2020 DAS. It sets a
"privacy-loss budget" (epsilon, ε) that makes the tradeoff between privacy
protection and data accuracy explicit and tunable.

**PPMF (Privacy-Protected Microdata File)** — Demonstration files the Bureau
releases showing what the data looks like after DAS noise is applied. Comparing a
PPMF against the corresponding baseline is how we can observe privacy noise
empirically.

**Geography hierarchy** — Census geographies nest inside each other. Relevant to us,
big → small: **state → county → tract (~4,000 people on average) → block group
(~600–3,000 people) → block**. The central empirical fact of this project:
smaller geography = noisier estimates.

**TIGER/Line shapefiles** — The Census Bureau's published boundary files for every
geography level. They're what let us join estimates to maps.

**Vintage** — The release year/edition of a dataset (e.g., the 2019–2023 ACS 5-year
estimates). Always record the vintage: numbers differ across vintages for the
same geography and variable.

**Annotation codes (sentinel values)** — Giant negative numbers (e.g., `-555555555`,
`-666666666`) the Census API returns *in place of* a real value, each encoding a
reason: estimate controlled, insufficient sample, etc. They must be treated as
missing, never as data (a naive CV calculation on one produces nonsense). Note:
our client library (censusdis) converts them to blanks automatically — convenient,
but it erases *which* reason applied. *Source: "Notes on ACS Estimate and
Annotation Values," census.gov.*

**Choropleth** — A map in which each area (here: census tract) is shaded by a data
value — in our case, by reliability tier. Classed bins (a handful of labeled
color steps) communicate to non-technical readers better than continuous color
ramps, which is why the dashboard deliverable specifies color-coded tiers.
First used in `notebooks/03-cv-choropleth-nj-tracts.ipynb`.

**Controlled estimate** — An estimate pinned to an official benchmark (the
Population Estimates Program) rather than measured by the survey — e.g., state
and county total population. No sampling MOE is published (annotation
`-555555555`). Important: a controlled estimate's missing MOE means *extremely
reliable*, the opposite of an estimate suppressed for insufficient sample —
two blank MOEs with opposite meanings.

**Top-coding** — Capping a published value at a threshold to avoid revealing
extremes: ACS median household income above $250,000 is published as `250,001`,
meaning "somewhere above $250k." A form of deliberate censoring — uncertainty
that isn't sampling noise. First seen in our NJ tract pull (several tracts at
exactly 250,001).

**Demonstration data** — Files the Bureau produces by running the 2020 DAS over
the *confidential* 2010 Census data, so the public can evaluate privacy noise by
comparing them against what was actually published in 2010. They exist **only**
for that evaluation — demonstration counts must never be analyzed as real 2010
populations. First used in `notebooks/04-privacy-noise-das-demo.ipynb`.

**Swapping** — The pre-2020 disclosure-avoidance method: exchanging the records
of similar households between nearby geographies so no table cell can be traced
to a real household. The published 2010 SF1 was protected this way — which is
why our noise measurement (demonstration − published) is DAS noise **plus
residual swapping effects**, never pure DAS noise. *Source: 2022-08-25
demonstration-data Technical Document ("the comparison is imperfect…").*

**TopDown Algorithm (TDA)** — How the 2020 DAS injects privacy noise: it starts
from the national total and allocates noisy counts *down* the geography
hierarchy (nation → state → county → tract → … → block), forcing every level to
stay consistent with the level above. Two consequences we observed directly
(EDA 04): errors at any level sum to exactly zero across the state, and how much
noise a level gets depends on where the privacy-loss budget is spent — not just
on unit size (see the block-group anomaly, EDA 04 findings).

**Invariant** — A count the DAS publishes exactly as enumerated, with no noise:
state total population, block-level housing-unit counts, and block-level
occupied group-quarters counts. Everything else gets noise — including statewide
totals of characteristic tables (the NJ Black 65+ total is off by +16 in the
demonstration data). Invariants double as parser checks: our demo NJ total had
to equal 8,791,894 exactly, and did. *Source: 2022-08-25 Technical Document.*

**Privacy-loss budget (PLB, ε)** — Differential privacy's global "spend" that
trades privacy for accuracy (see *Differential privacy*), which the DAS then
**allocates** across geography levels and tables. More budget at a level/table →
less noise there. The allocation is why the same variable carries different
noise at different levels (EDA 04's block-group anomaly). The numeric
allocations for the 2022-08-25 release live in a separate allocations file we
have not pulled (noted in the data dictionary).

**Relative RMSE (binned)** — Our methodology (documented in EDA 04) for putting
mean-zero privacy noise on the same scale as a CV: bin geographies by published
size, then compute `RMSE(demo − published) / mean(published)` per bin. RMSE is
the empirical standard deviation of the noise, so this is the direct analog of
`CV = SE/estimate` — the two noise mechanisms can be compared on one axis. A
per-unit log-log fit would have to drop the many exactly-zero errors, biasing
the slope; binned RMSE keeps them.

**Ghost / vanished places** — A categorical artifact of mean-zero noise on tiny
counts: a *ghost* is a geography published as zero that the noisy file shows as
populated; a *vanished* place is the reverse. EDA 04 found 807 ghost blocks
(4,695 phantom residents) and 427 vanished blocks (1,154 real residents erased)
in NJ. For block-level uses this flips places between "inhabited" and "empty" —
it is not adequately described as ±noise, so we report it as its own class.
