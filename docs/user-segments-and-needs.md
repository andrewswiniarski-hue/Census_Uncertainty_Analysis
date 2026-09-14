# ACS Uncertainty Dashboard — User Segments, Needs, and Function Ideas

**Status: RESEARCH SUMMARY — for discussion, not committed scope.**
Companion to [`acs-user-needs-and-functions.pptx`](acs-user-needs-and-functions.pptx).

**Author:** Garrett Spangler. **Deck dated:** 2026-08-24.
**Research passes:** 2026-08-19 and 2026-08-24. **Scope of the research:** ACS only.

## Why this document exists

The source deck was circulated on SharePoint rather than committed to the repo,
so its ~30 citations and its segment rankings were not greppable, reviewable, or
traceable from any of our deliverables. This page transcribes the substance into
the repo so that product decisions made from it have a paper trail. The deck
itself is committed alongside it.

This is the project's **first demand-side research** — who the users are and what
they need. It is distinct from the Product Scope Tracker (2026-07-25/26), which
is supply-side: what the Bureau publishes and what uncertainty ships with it.
Both are Garrett's; they answer different questions and should not be cited
interchangeably.

New terms used below (MOE, CV, allocation rate, block group, PUMA) are defined in
[`glossary.md`](glossary.md).

## How to read the evidence labels

The deck labels every claim, and this summary preserves those labels:

- **documented** — traceable to a named published source (survey, methods paper,
  agency methodology document, or a Bureau handbook).
- **proxy** — a measurable stand-in for the thing we actually want to know.
- **inferred** — reasoned from circumstance, with no direct measurement.

Where the deck found no evidence, it says so rather than filling the gap. That
discipline is why the journalist segment below is left deliberately unranked.

## The constraint that shapes everything

> The data stops at county. The functions do not have to.

Our dashboard holds county-level data. Most of the users with the best-documented
uncertainty pain work **below** county — tract, block group, PUMA, TAZ. The deck
resolves this by splitting the tool in two:

| Binding | Features | Why |
|---|---|---|
| **County-bound** | The map, the reliability card, the allocation view | These display our data, so they inherit its geography floor |
| **Geography-free** | Significance test, propagated MOE, vintage warning, cutoff check | These operate on any estimate and MOE the **user brings**, at any geography |

**The constraint limits what the tool displays, not what it computes.**

An earlier framing graded users on fit-with-county *before* grading on need,
which systematically demoted the highest-need segments. This research ranks
**need first, geography second**, then uses the geography-free functions to reach
the sub-county users that ranking surfaces.

## The segments at a glance

Need rank = documented evidence of uncertainty pain, geography ignored.
Reach rank = how well a county-data tool with bring-your-own-numbers serves them.

| Segment | Works at | Decision the number feeds | Need | Reach | Tier |
|---|---|---|---|---|---|
| Planners | Tract, block group, place | Comprehensive plans, needs assessments, grant justifications | 1 | 7 | 2 |
| Academics (published tables) | Tract, block group, PUMA | Indices, small-area models, published research | 2 | 9 | 2 |
| Health-index builders | Block group, tract | SVI and ADI, which feed CMS payment rules | 3 | 10 | 2 |
| Transportation and MPOs | TAZ, tract | Travel-demand models, Title VI | 4 | 8 | 2 |
| Program staff (ACS programs) | County, place, block group | CDBG, VRA 203, HUD income limits, ARC distress | 5 | 1 | **1** |
| Housing and community development | Block group to county | Consolidated Plans, LIHTC studies | 6 | 6 | 2 |
| EJ analysts | Block group | Screening, permitting, targeting | 7 | 12 | 2 |
| Small-county officials | County | Eligibility for rural grants | 8 | 2 | **1** |
| Community organizations | Neighborhood | Grant applications, indicators | 9 | 11 | 2 |
| State data centers | County, state | Guidance and training for local users | 10 | 4 | **1** |
| Journalists | County, place | Is this solid enough to print | 13 | 3 | open |

Omitted from the deck's table for space: business and GIS analysts (need 11,
reach 5 — Esri already ships reliability flags), general public and students
(need 12, *inferred*), tribal data users (need 14 — county geography does not
align with tribal areas).

## Tier 1 — documented need, county-native

### Program staff running on ACS

Federal and state staff administering CDBG, VRA Section 203, HUD income limits
and fair market rents, LIHEAP (via PUMS), EJScreen, and ARC distressed-area
designations. **Money moves and legal determinations get made on a point
estimate.**

**What they need:** the estimate, MOE, and interval as retrievable numbers;
whether the interval crosses an eligibility cutoff; a significance check before
ranking places; the overlapping-vintage rule stated up front.

**Evidence:**

- Nesse and Rahe 2015 — agencies find MOE "adds complexity that does not
  necessarily result in better implementation." *(documented)*
- HUD already applies a written rule: an ACS median is usable only if its **MOE
  is under half the estimate**. *(documented)*
- The ARC distressed-area rule uses the latest 5-year ACS with no mention of
  MOE. *(documented)*
- **1,163** CDBG entitlement communities plus 50 states receive funds on ACS
  poverty, overcrowding, and housing-age inputs (GAO-10-1011).

### Small and rural county officials

County administrators, planners, and grant writers in counties under 65,000
population. **Their geography is the county; their numbers behave like tract
numbers.**

**What they need:** a plain reliability label with the CV one tap below it;
whether the interval crosses a grant threshold; a plain statement of how
reliability falls as population shrinks; the overlapping-vintage rule, since
year-over-year is how they track change.

**Evidence:**

- **~74% of U.S. counties** fall below the 65,000 threshold for 1-year ACS and
  receive 5-year estimates only. The 2015 1-year release covered all states but
  only **26% of counties**. *(documented, Census Bureau)*
- Jurjevich 2019 — rural eligibility decisions are often made with the margin
  disregarded; the workaround is a consultant-run income survey. *(documented)*
- Extension services write their own MOE explainers (University of Kentucky's
  "Grain of Salt" guide) — a demand signal. *(proxy)*
- **Team finding, EDA 07:** CV tracks estimate size, not place size, so
  small-county income and poverty estimates carry tract-scale margins.

### State demographers and data centers

State Data Center lead agencies and state demographic offices that publish ACS
profiles, write reliability guidance, and field questions from local governments.
**The intermediaries who already answer these questions by hand.**

**What they need:** a reference implementation of the significance test and
derived-MOE arithmetic they currently explain in PDFs; a neutral, sourced
reliability convention to point users at; something to link local users to
instead of re-teaching the CV rule.

**Evidence:**

- Washington OFM, Chittenden County RPC, and the Missouri Census Data Center each
  maintain their own MOE guidance. *(documented)*
- **The guides disagree on thresholds** (12/40, 15, 15/30) — which is itself
  evidence that no shared tool exists. *(documented)*
- They serve county and state constituents, so our county data fits natively.

## Tier 2 — strongest documented need, works below county

### Urban and regional planners — the best-documented pain in the literature

Municipal and regional planners producing comprehensive plans, housing needs
assessments, Consolidated Plans, and Title VI analyses at tract, block group, and
place.

**What they need:** CV and MOE as numbers they can footnote; a significance test
before comparing places or years; propagation help on rates and shares; what
combining tracts buys in reliability; ready-made footnote language.

**Evidence:**

- Jurjevich et al. 2018 (JAPA 84(2)) — **n=200 survey plus 7 interviews.** Many
  planners do not understand MOE, find it hard to communicate, and avoid
  reporting it altogether. The paper proposes five guidelines, the first being
  *always test before comparing estimates*. *(documented)*
- **Bosses and clients sometimes instruct planners not to report MOE** because of
  its complexity. *(documented)*
- Spielman, Folch and Nagle 2014 — tract MOEs average **75% larger** than the
  2000 long form. *(documented)*

### Academic researchers using published tables

Researchers building indices, segregation measures, and small-area models from
ACS 5-year tables at tract and block group, plus PUMS users at PUMA.
**Self-sufficient on microdata; not on the tables.**

**What they need:** provenance on every number (table, vintage, formula);
derived-quantity propagation; the overlapping-vintage rule for panel work; the
allocation and imputation view — **this group is best placed to test it.**

**Evidence:**

- Napierala and Denton 2017 (Demography 54(1)) — MOE "has not been incorporated
  into segregation indexes." Using ACS standard errors is **"not yet standard
  practice."** *(documented)*
- IPUMS — users rarely take the trouble to estimate true standard errors because
  the methods are cumbersome. *(documented)*
- The Bureau discourages 5-year estimates as denominators; the practice is common
  anyway. *(documented)*

### Four more sub-county segments

| Segment | Who / where | Why (evidence) | How we reach them |
|---|---|---|---|
| **Health-index builders** | SVI and ADI at block group and tract; **they feed CMS payment rules** | Health Affairs 2023: block-group home-value MOE averages **$105,418** in the lowest-ownership decile. SVI ships MOEs but does not use them in its ranks; ADI unstable at block group | Propagation and aggregation on numbers they bring |
| **Transportation / MPOs** | CTPP (a special ACS tabulation) at TAZ and tract; **~450 MPOs** nationally | AASHTO: if the MOE is high, consider another source. CTPP custom tables add perturbation noise on top of sampling error | Significance test and propagation on pasted CTPP values |
| **Housing and community development** | CHAS, income limits, LIHTC market studies, block group to county | HUD publishes MOE for income limits and LMISD, but the **CHAS query tool does not surface it**. Rounding breaks additivity | Cutoff check mirroring HUD's own MOE rule |
| **EJ analysts and community groups** | EJScreen at block group; neighborhood indicators for grant writing | EJScreen documentation **concedes MOE grows as population shrinks and then hides it**. NNIP partners write their own MOE guides | Bring-your-own-numbers only; native maps would need block-group data |

## Journalists — tier deliberately left open

County and place are their default geographies, which makes reach high. But the
need is **inferred, not documented.**

| What is documented | What is not | What would settle it |
|---|---|---|
| Census and Brookings both wrote ACS guides for journalists with full MOE chapters | No content analysis of whether newsrooms actually report ACS margins was located in **either** research pass | Sample 150–200 local stories citing ACS county figures over 24 months |
| Census Reporter, built for newsrooms, flags estimates where the margin requires extra care | No measurement of Census Reporter's reach into published stories | Code each for: MOE mentioned, reliability language present, comparison made without a test |
| The Census journalist handbook gives a CV rule of thumb: 10% is fine, 50% probably is not | The need is inferred from the existence of guidance, not from observed practice | Two coders, a double-coded subset, Krippendorff's alpha. **Two weeks of work** |

**Recommendation on record:** build journalist-specific features *second*, after
the content analysis says whether they would be used.

## Four needs cover everyone

The same four surfaced in both research passes:

1. **Is this number solid enough to use?** — the estimate, its margin, its CV, and
   a plain label. Universal, and the only need every existing guide already tries
   to meet.
2. **Is this difference real?** — between two places or two years, with the
   overlapping-window rule stated first. The Census rule is explicit; no consumer
   tool automates it.
3. **What did my own arithmetic do to the error?** — rates, shares, sums,
   differences. Anyone who computes anything from two published cells has created
   error the Bureau never published.
4. **Where does this stop working?** — below county, in small counties, and in
   anything the user aggregated. The honest statement that makes county-only
   defensible.

Two further needs are segment-specific:

- **Does the interval cross my cutoff?** — program staff and small counties.
- **How much of this was imputed?** — academics and health-index builders.
  **This is where the team's income-allocation findings get a user.**

## Function ideas

Ideas, not scope. Grouped by build order, with geography binding noted.

### Wave 1 — build first (all geography-free)

These are what let a county-data tool serve the highest-need users at all.

| Function | What it does | Why people may need it |
|---|---|---|
| **Bring-your-own-numbers** | One input panel: any estimate and its MOE, no geography field. Everything downstream runs on those values | Planners, academics, transportation, and EJ analysts work below county. Pasting a tract estimate gets them the same test, propagation, and warning a county user gets |
| **Comparison and significance check** | Two estimates — two places or two vintages — and a yes/no on whether the difference is distinguishable at 90%. The arithmetic stays visible | Jurjevich's first guideline: test before comparing. The Census tool does this in Excel; nobody does it in a county interface |
| **Derived-quantity MOE calculator** | Propagated margin for sums, ratios, proportions, and differences using the Bureau's formulas. Reuses the repo's `aggregate_moe` | Any rate a user computes carries error the Bureau never published. The independence assumption fails for rates, and the tool can say so |
| **Overlapping-window guard** | Counts shared sample years between two 5-year vintages and warns or blocks. 2023 and 2024 share four of five. Optionally applies the overlap-adjusted SE | The Bureau says do not compare overlapping periods. Users do it constantly. **Strongest documented, least served** |

### Wave 2 — native county

Where the county data earns its keep.

| Function | Binding | What it does | Why people may need it |
|---|---|---|---|
| **Reliability card** | Partial | Default view for any county estimate: number, MOE, CV, plain-language label. Layered so the label sits on top and the CV is one tap down, **never removed** | Journalists and small counties want the label; planners and data centers need the value for footnotes. Thresholds should be a convention users already know, with the convention named |
| **Cutoff check** | Geography-free | User enters a threshold — a CDBG poverty rate, an ARC distress line — and the tool shows whether the confidence interval crosses it | Program staff act on point estimates near cutoffs. HUD already has a written rule; most programs have none |
| **Allocation view** | County-bound | How much of the estimate was imputed rather than reported: the B98 overall rate (county only) and per-table B99 rates. States plainly that no MOE exists for these | The team found household income allocation at a median 39% per tract, independent of demographic imputation. **No other tool shows it. This is the one thing only this dashboard would do** |

### Wave 3 — extend reach, then later

| Function | Binding | What it does | Caveat |
|---|---|---|---|
| **Reliability-floor model** | Partial | Enter an estimate size, get an expected CV from the EDA 07 relationship. Labeled as a prediction, not a measurement | **See the conflict flagged below — do not ship without a variable-type gate** |
| **Aggregation explainer** | Geography-free | A worked example: two tracts merged, the combined estimate, the combined MOE, the CV before and after. Grounded in Spielman and Folch regionalization | Answers the planner's question of how many tracts to combine before the number is usable |
| **Publishable sentence and citation** | Geography-free | One generated sentence describing the estimate and its uncertainty in plain language, plus table, vintage, and formula in a citation line | Planners need footnote text, reporters need a sentence that survives an editor, community groups need grant language. Cheap once the card and the test exist |

## Where this meets our own findings

### Conflict — the reliability-floor model is stated on superseded numbers

The deck cites the EDA 07 relationship at **R² 0.67 on estimate size**, noting
the income-only fit was R² 0.01. **EDA 14 (2026-08-16) supersedes this:** the
count size law holds at slope −0.54, **R² 0.78 over 6.1M cells**, while medians
escape it entirely (within-table R² ≤ 0.01, reproducing EDA 07).

The consequence is material. A CV-from-size predictor **works for counts and
fails for medians** — and median household income is the anchor variable of the
current scope. If this feature ships without a variable-type gate, it will
produce confident, wrong predictions for the headline number.

**Recommendation:** if it ships at all, gate it to count estimates, label it a
prediction, and re-run EDA 07 on one state's tract MOEs first (which the deck's
own open-questions slide also asks for).

### Conflict — four competing CV threshold conventions

The deck surfaces Esri's 12/40 bands, the Census ACS Compass 15% caution, and the
planner-guide 15/30. Our repo and EDA charts have used **CV > 0.30** for caution
(see [`glossary.md`](glossary.md), which already notes thresholds vary by agency).
The deck's recommendation is to pick one and **name it on the card**. This is a
lead decision and it interacts with the composite tier-label question already
tabled.

### Gap — the deck does not incorporate EDA 14

EDA 14 landed 2026-08-16, eight days before the second research pass, and is not
reflected in the deck. It bears directly on universal need #4 ("where does this
stop working?"): **~72% of the sampled ACS surface is scoreable; the other 28% is
structured absence** — 16% zero estimates, 11% silent publication floors, 0.6%
controlled cells (the *most* reliable in the dataset), ~0.5% jam values. Family
median CVs span **36×** at county scale, and 35.7% of scoreable cells exceed the
0.30 convention.

A CV-only tool misdescribes both ends of that distribution. Our answer to "where
does this stop working" is better-evidenced than the deck currently claims.

### Confirmation — the allocation view's geography limit is stated correctly

The deck says the B98 overall allocation rate "exists only at county," which
matches Garrett's own financial EDA: `B98031`/`B98032` return 21/21 at county and
**0 of 2,181 at tract**. Show the axis where it is clean; suppress it where it is
not.

### Consequence for variable selection

The research adds a selection criterion our EDA-driven filters did not have:
**does this variable feed a decision with documented money or legal
consequences?** Working backward from the programs the deck names:

| Program / index | Variables it runs on |
|---|---|
| CDBG | poverty, overcrowding, housing age |
| HUD income limits / FMR / CHAS | median household income, family income, rent burden |
| ARC distress | poverty rate, per-capita income, unemployment |
| VRA Section 203 | limited-English proficiency, voting-age citizens |
| SVI / ADI (feeding CMS payment rules) | poverty, income, education, housing, vehicle access, crowding, single-parent, disability, age |
| EJScreen | low-income, minority, linguistic isolation, education |

This supports a **modest, documented widening** beyond income and poverty — each
addition traceable to a named federal program — rather than a catalog-wide sweep.
It does not by itself authorize a scope change; decision #14 still governs.

## What the evidence does not settle

Scoping calls for the group, with the deck's proposed cheapest resolution.
**None of these is a team decision yet.**

| Open question | Cheapest way to settle it | Why it matters |
|---|---|---|
| Will Tier 2 users paste their own numbers, or stay in tidycensus and Esri? | Usability test with 5–8 sub-county users | Decides whether bring-your-own-numbers is the bridge or a dead end |
| Do journalists report ACS margins at all? | Two-week content analysis, 150–200 stories | Decides whether journalist features get built |
| Does anyone want one combined reliability label rather than two numbers side by side? | Structured interviews with 8–12 county and health users | Sponsor Q2 has no user evidence anywhere; this is the only tie-breaker |
| Does the reliability-floor model hold below county? | Re-run EDA 07 on one state's tract MOEs | Decides whether the model ships as a feature or stays an analysis note |
| Which CV thresholds: Esri 12/40, Census 15, or planner 15/30? | Pick one and name it on the card | Interacts with the tier-label decision already tabled |
| Is public health a first-class segment? | Track County Health Rankings' 2026 release status | CHR paused its annual release in 2026; the segment's stability is uncertain |

**Caveat carried from the deck:** function lists come from documented pain, **not
from user testing.** No user of this dashboard has been interviewed or observed.

## Sources

As cited in the deck. Not independently re-verified by the team.

- Jurjevich et al., *Journal of the American Planning Association* 84(2), 2018 (n=200 planner survey)
- Jurjevich, *Confronting Statistical Uncertainty in Rural America*, Springer, 2019
- Spielman, Folch and Nagle, *Applied Geography* 46, 2014
- Spielman and Folch, *PLOS ONE*, 2015 (regionalization)
- Napierala and Denton, *Demography* 54(1), 2017
- Folch, Spielman and Graber, *Population Research and Policy Review*, 2023
- Nesse and Rahe, *Population Research and Policy Review* 34(4), 2015
- Petterson et al., *Health Affairs*, 2023
- GAO-10-1011 (CDBG formula inputs)
- HUD income limits methodology, FY2018–FY2026; HUD CHAS documentation
- ARC Distressed Areas Classification System
- CDC/ATSDR SVI 2022 documentation
- AASHTO CTPP Key Considerations, 2017–2021
- EPA EJScreen technical documentation
- Census ACS General Handbook 2018, ch. 7 (overlap-adjusted SE); ACS Compass guidance; Census Statistical Testing Tool; Census blog, March 2022 (overlapping periods)
- Washington OFM ACS User Guide; Chittenden County RPC, 2018; Missouri Census Data Center documentation
- Esri 2025 methodology statement (12% and 40% CV bands)
- IPUMS USA sampling error documentation; Bayesian areal-data methods paper, PMC8297362
- NNIP; Zimmerman and McAlister, University of Kentucky ("Grain of Salt")
- Team: EDA 07, EDA 14, Financial EDA (New Jersey, 2024)
