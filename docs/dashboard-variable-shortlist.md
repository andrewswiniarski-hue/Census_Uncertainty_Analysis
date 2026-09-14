# Dashboard Variable Shortlist — Audiences and the Variables That Serve Them

**Status: ADOPTED IN PART (lead decision #18, 2026-09-14).** The dashboard's scope
widens beyond income and poverty to the programs the user research names, across all
US counties.

- **Adopted.** All eight core variables: B19013, B17001, B19001 and B25064 were
  already on the dashboard; C17002 (low income, below 200% of poverty), B23025
  (unemployment), B25070 (cost-burdened renters, 30%+ and 50%+) and B25077 (median
  home value) are now added. From the SVI/ADI stack, B15003 (no high school
  diploma) and B18101 (disability) are added; B01001 age bands were already present.
- **Not adopted.** B03002 minority status is held for a deliberate decision: it is a
  sensitive variable, and its county total is a controlled estimate in 96% of
  counties, so its margin of error reflects only one of its two components. C16001
  duplicates a topic the dashboard already covers through C16002, which is itself
  the dashboard's least reliable card. The unmeasured candidates still need a
  scripted pull before they can be assessed.

## Correction (2026-09-14): table-level CVs are the wrong number for choosing cards

The CV columns below report the **median CV across every cell in a table**. A card
shows one derived figure, usually a sum of several cells, and its CV can differ
sharply from the table median in either direction. The most consequential case:
this page lists B23025 at 0.028, among the most reliable tables, but the
unemployment figure a card would show has a median CV of **0.191**, with 22.3% of
counties over 0.30.

| Table | Card figure | Table median CV (below) | Card median CV | Card CV over 0.30 |
|---|---|---|---|---|
| C17002 | People below 200% of poverty | 0.138 | 0.072 | 0.4% |
| B23025 | Unemployed | 0.028 | 0.191 | 22.3% |
| B25070 | Renters paying 30%+ of income | 0.254 | 0.146 | 10.8% |
| B25070 | Renters paying 50%+ of income | 0.254 | 0.203 | 25.6% |
| B25077 | Median home value | 0.035 | 0.036 | 0.5% |
| B15003 | Adults 25+ without a diploma | 0.213 | 0.100 | 3.2% |
| B18101 | People with a disability | 0.049 | 0.056 | 0.3% |

Method: 3,144 US counties (Puerto Rico excluded), 2024 ACS 5-year, from EDA 14's
county pull. Sums use root-sum-of-squares with the handbook zero-cell rule (HANDOFF
decision #7), controlled margins count as zero, and CV = (MOE / 1.645) / estimate.
These are scoping estimates, **not assert-guarded**; cite them only after they are
moved into a notebook. Any other CV on this page carries the same caveat.

Answers the question "who is this dashboard for, and what goes on it?" by joining
two things the project now has: Garrett's user-segment research
([`user-segments-and-needs.md`](user-segments-and-needs.md)) and the measured
error-bar behavior of the ACS surface (EDA 14, notebook
[`14-acs-wide-error-bar-survey.ipynb`](https://github.com/andrewswiniarski-hue/Census_Uncertainty_Analysis/blob/main/notebooks/14-acs-wide-error-bar-survey.ipynb)).

**This proposal widens the variable set beyond income and poverty.** Decision #18
(2026-09-14) made that call; see the status block above for what was adopted.

## How the numbers on this page were produced

- **Table IDs** were verified against the 2024 `acs/acs5` variable manifest
  (`data/raw/acswide_2024_variable_manifest.parquet`, 28,472 names). All 31
  candidate tables exist.
- **CVs** were computed from EDA 14's county pull
  (`data/raw/acswide_2024_us_county_long.parquet`, 3,222 counties, 2024) using
  **that notebook's own cell-classification precedence** — jam values matched
  numerically, controlled cells and zero estimates excluded from CV — and the
  project's shared `analysis.acs.cv`. Reusing the notebook's logic rather than
  reimplementing it is deliberate: the convention cannot drift.
- **Coverage limit:** EDA 14 sampled 100 tables. Fourteen candidates fall inside
  that sample and carry measured CVs. The rest are verified to exist but
  **unmeasured**, and are marked as such throughout. No unmeasured table should
  appear in a report or deck as though it had a known CV.

## The selection criteria

Five filters, applied in order. The first four come from our own EDA work; the
fifth is what the user research adds.

1. **Is it scoreable at all?** Reject silent publication floors and jam values.
   Show controlled cells as *certain*, not missing, and real zeros as zeros. EDA
   14 found ~28% of the sampled surface is structured absence, so this filter is
   not a formality.
2. **Does the CV actually vary?** A variable that is uniformly reliable makes a
   uniformly green map and teaches the user nothing. The interesting variables
   are the ones where reliability changes across places.
3. **Does it need special scoring treatment?** Counts follow the size law (slope
   −0.54, R² 0.78). Medians escape it (within-table R² ≤ 0.01). Poverty defies it
   (slope −0.18). These cannot share one scoring path without disclosure.
4. **Is there an invisible error source the MOE misses?** Where an allocation
   rate exists and is clean, the variable carries a second uncertainty axis.
5. **Does it feed a decision with documented money or legal consequences?**
   *(New, from the user research.)* This is what turns variable selection from a
   statistical exercise into a defensible one.

## The audiences

Garrett's research ranks eleven segments by documented need. Need alone does not
decide who we design for — that also depends on whether our county data reaches
them.

| Tier | Segments | Why | How they are served |
|---|---|---|---|
| **Primary** | Small and rural county officials; program staff running ACS-funded programs | County-native, threshold-driven decisions, reach ranks 1–2. ~74% of counties are 5-year-only; 1,163 CDBG entitlement communities plus 50 states are funded on ACS inputs | The default view: map, reliability card, cutoff check |
| **Secondary** | State data centers and demographers | Need rank 10 but reach rank 4. They already answer these questions by hand and write the guidance — force multipliers | Same variables; they need the *functions* and a named threshold convention, not more topics |
| **Reachable** | Planners, academics, health-index builders, MPOs, housing/CD, EJ analysts | Need ranks 1–7, but all work below county | Geography-free functions only: bring-your-own-numbers, significance test, propagation, vintage guard |
| **Parked** | Journalists | Reach is documented; need is inferred. No content analysis of newsroom practice exists | Revisit after the proposed content analysis |

**One-sentence framing:** the dashboard is built for the county official and the
program officer, and opened up to everyone below county through
bring-your-own-numbers.

## The core shortlist — primary audience

Eight variables. Every one traces to a named federal program, and their measured
CVs span 0.028 to 0.254, which is wide enough that the reliability display
actually varies across the set.

| Table | What it is | Program it feeds | Median CV | % over 0.30 | Type |
|---|---|---|---|---|---|
| **B19013** | Median household income | HUD income limits, ARC | **0.042** | 0.2% | median |
| **B17001** | Poverty status by sex by age | CDBG, ARC distress | 0.177 | 30.6% | count |
| **C17002** | Ratio of income to poverty | CDBG low/mod income, EJScreen | 0.138 | 11.1% | ratio |
| **B19001** | Household income brackets | HUD income limits | 0.159 | 13.6% | count |
| **B23025** | Employment status | ARC distress | **0.028** | 10.8% | count |
| **B25070** | Gross rent as % of income | CHAS, LIHTC | 0.254 | 39.5% | count |
| **B25064** | Median gross rent | HUD fair market rents | **0.039** | 1.0% | median |
| **B25077** | Median value | CHAS, LIHTC market studies | **0.035** | 0.5% | median |

Verified to exist but **not measured** (outside EDA 14's 100-table sample) —
these need a pull before they can be quoted: **B19301** (per-capita income, ARC),
**B19113** (median family income, HUD), **B25014** (overcrowding, CDBG),
**B25034** (housing age, CDBG), **B25091** and **B25106** (owner cost burden).

## The SVI / ADI stack — health-index builders

These feed CMS payment rules through the Social Vulnerability Index and the Area
Deprivation Index. Both indices are built at block group, so our county values
are **stand-ins for demonstrating method**, not substitutes for their data. Label
them that way on the dashboard.

| Component | Table | Median CV | % over 0.30 |
|---|---|---|---|
| Below poverty | B17001 | 0.177 | 30.6% |
| No high-school diploma | **B15003** | 0.213 | 31.7% |
| Age 65+ / under 17 | **B01001** | 0.113 | 13.2% |
| Disability | **B18101** | **0.049** | 9.8% |
| Minority status | **B03002** | 0.263 | 32.8% |
| Limited English | **C16001** | **0.495** | 42.2% |
| Group quarters | **B26001** | **0.023** | 1.8% |
| Crowding / vehicle access | B25014 / B25044 | not measured | — |
| Single-parent households | B11003 / B11012 | not measured | — |

## VRA Section 203 — one statute, two tables, opposite data quality

| Table | What it is | Scoreable | Median CV |
|---|---|---|---|
| **B29001 / B29003 / B29004** | Citizen voting-age population | high | **0.014** (family median) |
| **C16001** | Language spoken at home | **62.7%** | **0.495** |

The citizen voting-age tables are the most reliable family EDA 14 measured
anywhere in the ACS. Limited-English is among the least. Same statutory purpose,
**35× apart in CV.** This is the clearest warning in the data against treating a
policy area as one quality bucket.

## What the measurements changed about our thinking

### Our anchor variable is one of the most reliable things in the ACS at county scale

B19013 has a median CV of **0.042** across 3,222 counties, and only **0.25%** of
counties exceed the 0.30 caution convention. A county dashboard showing income
reliability will be almost uniformly green.

This is not a failure of the product — it is the honest answer, and it reframes
what the product is about. The uncertainty story is **not** "county income
estimates are shaky." It is three other things:

1. **Reliability collapses as you go down.** Tract MOEs average 75% larger than
   the 2000 long form (Spielman, Folch and Nagle 2014). The pain the user
   research documents is sub-county — which is precisely why the geography-free
   functions matter more than the map does.
2. **Reliability collapses as you go detailed.** Same counties, same geography:
   B19013 at 0.042 against C16001 at 0.495 — a **12× spread** inside our own
   shortlist. County scale protects totals, not detail. This reproduces EDA 14's
   36×-across-families finding on the specific variables an audience would pick.
3. **The MOE is not the whole error.** Household income was allocated at a median
   39% per NJ tract, statistically independent of the MOE. A green county with
   39% imputation is the story only this dashboard tells.

### Structured absence is concrete, not theoretical

**C16001 is 37.1% zero estimates and only 62.7% scoreable at county.** B03002 is
16.0% zero and **12.6% controlled**. B15003 is 15.8% zero. A CV-only tool renders
real zeros and controlled (zero-sampling-error) cells identically to missing
data, which misdescribes both ends of the distribution.

## Recommendation

1. **Ship the eight core variables** for the primary audience.
2. **Add the four measured SVI/ADI tables** (B15003, B03002, B18101, B01001),
   labeled as county-scale stand-ins for block-group work.
3. **Put C16001 on the dashboard as the cautionary case** — not despite its 0.495
   CV but because of it. It is the cleanest single demonstration of why the tool
   exists.
4. **Pull the unmeasured candidates** before any of them reaches a report or
   deck.

## Decisions this needs from the lead

1. **Does decision #14 widen?** *Resolved 2026-09-14 by decision #18: yes, to the programs
   the user research names, across all US counties.* The shortlist reaches into housing, education,
   disability, and language. Each addition traces to a named federal program, but
   this is still a scope change and it is not ours to make.
2. **Which CV threshold convention gets named on the card?** Every "% over 0.30"
   figure on this page moves if the convention changes. Open question in the
   README.
3. **Are county-scale SVI/ADI stand-ins honest enough to ship?** They demonstrate
   method at a geography the index does not use. The alternative is to omit the
   segment.

## Reproducing this page

EDA 14's notebook and pull script live on `main`, not on the dashboard branch, so the links on this page point at `main` on GitHub.

```bash
python -c "import pandas as pd; print(pd.read_parquet('data/raw/acswide_2024_variable_manifest.parquet').shape)"
```

The CV figures come from `data/raw/acswide_2024_us_county_long.parquet` filtered
to the candidate tables, classified by EDA 14's precedence rules, with CV from
`analysis.acs.cv`. Both parquet files are regenerable via
[`ingestion/pull_acs_wide_us_county.py`](https://github.com/andrewswiniarski-hue/Census_Uncertainty_Analysis/blob/main/ingestion/pull_acs_wide_us_county.py).

**Not yet assert-guarded in a notebook.** Per the project standard that every
number in the findings report traces to an assert-guarded notebook, these figures
should be moved into one before they are cited in
[`phase1-findings-report.md`](phase1-findings-report.md).
