# Product Shortlist Proposal — Income & Poverty

**Status: PROPOSED (2026-08-01) — for confirmation at the next mentor touchpoint.**
Follows biweekly #1 guidance (2026-07-22): *narrow the project to a specific
product or metric the EDA found interesting and build the tool around that.*
Scope decisions #13–14 (HANDOFF.md) picked the domain — **income & poverty,
New Jersey pilot**. This page proposes the concrete product stack.

Every "what uncertainty ships" claim below was verified against the live
Census API or the Bureau's file tree on **2026-08-01**; the full receipts
(query URLs, variable lists, directory listings) are in the matching
[`data-dictionary.md`](data-dictionary.md) entries. New terms (SAIPE, PUMS,
replicate weights, VRTs, confidence interval, design factors) are defined in
[`glossary.md`](glossary.md).

## The ask

Confirm this four-product stack as the scope of the uncertainty report,
composite score, and dashboard — one anchor product the tool scores, three
supporting products that each add an uncertainty dimension the anchor lacks.

## The stack

| Product | Role in the tool | Uncertainty it ships (verified) | Geography floor | Cadence |
|---|---|---|---|---|
| **ACS 5-year detailed tables** — B19013 (median HH income), B17001 (poverty), C17002 (income-to-poverty ratio) | **Anchor** — the estimates the tool scores | 90% MOE on every estimate (live query receipts) | B19013, C17002: **block group**; B17001: **tract** (live-probed — block-group rows return silent nulls) | Annual 5-year vintages |
| **ACS allocation tables** — B99192 (income), B99172 (family-poverty proxy); intensity tables B99191–94/B99201 | **Score component** — the imputation axis MOEs can't see | None, by design (E-only) — an allocation rate is a covariate; independent of CV once size is controlled (EDA 05) | County / tract / block group | Annual |
| **SAIPE** — model-based income & poverty | **Comparator / precedent** — the Bureau already ships uncertainty for exactly our variables | Point + 90% CI + MOE on all 10 measures, incl. age detail (0–17, 0–4, 5–17). Live receipt, 2024: Bergen County median HH income **$121,894 ± $2,571**; Mercer **$102,760 ± $4,099**; poverty rates 6.7 ± 0.9% / 10.0 ± 1.5% | County (API); school districts via companion endpoint | Annual, single-year, 2019–2024 in API |
| **PUMS replicate weights + Variance Replicate Tables** | **Exactness upgrade** — exact SEs where the handbook approximation breaks down | PUMS: 80 person + 80 household replicate weights (all 160 verified in the API). VRTs: replicate versions of B17001/C17002/B19001 as bulk files, tract & block group | PUMS: PUMA (~100k people); VRTs: block group | Annual; VRTs 5-year only (1-year confirmed nonexistent) |

## Why this domain — the EDA already voted

- **Poverty is the reliability problem in miniature:** 80% of NJ tracts exceed
  the CV 0.30 caution convention for poverty (Finding 2), poverty defies the
  1/√N sampling law (slope −0.18 vs −0.5, Finding 2), and poverty data is
  *most* reliable in poor urban cores and *least* reliable where poverty is
  suburbanizing (Spearman −0.58, Finding 3) — an equity-relevant blind spot a
  county planner would never see from the map alone.
- **Income carries the invisible error:** ~39% of households at the median NJ
  tract had income imputed (Finding 8), imputation is statistically
  independent of the MOE (Finding 9), and 22.8% of tracts are the low-CV /
  high-allocation blind spot the composite prototype exists to expose
  (EDA 06, Justus — branch, pending local re-execution). Income medians also
  escape the estimate-size law entirely (R² ≈ 0.01, EDA 07), so income needs
  its own scoring treatment.
- **The deepest team workstream is already here:** Garrett's financial EDA
  (branch) found income imputed ~50× more often than demographic items, with
  98.2% of public-assistance allocations imputing a *zero* — and established
  the rule that no bare allocation rate gets quoted without its denominator.

## Division of labor for exact error bars (verified 2026-08-01)

The three uncertainty layers slot together with no overlap:

1. **Published MOEs** (anchor tables) — what the tool scores everywhere.
2. **VRTs** — exact MOEs when we aggregate counts or build custom regions:
   cover B17001 (tract), C17002 + B19001 (down to block group) — and their
   coverage stops exactly where API publication stops, which cross-validates
   both.
3. **PUMS replicate weights** — exact SEs for anything the VRTs can't do,
   **including the median (B19013 has no VRT — medians are nonlinear)** and
   any custom cut; also the person-level imputation profile.

SAIPE sits alongside as the communication benchmark: same variables, published
*with* intervals — the Bureau's own answer to the question our dashboard asks.

## What we are deliberately not doing (scope guidance, decision #14)

- **DHC / privacy noise** becomes report *context*, not a score component —
  income does not exist in decennial products. (Mentor question logged: is
  that the right consequence?)
- **Catalog-wide work is parked** — the Product Scope Tracker stands as the
  record of how this shortlist was chosen.

## Found during verification (new landmine, 2026-08-01)

The 2024 `acs/acs5` `variables.json` metadata census lists **zero** MOE
variables (0 of 28,475 names), yet every MOE variable is individually
resolvable and returns live values. The Bureau's own machine-readable metadata
under-reports its uncertainty surface — directly relevant to Q3/Q4 (how
discoverable is uncertainty?), and a trap for any metadata-driven inventory
(our tracker's probe prints "no MOE variables found" for this reason).

## Open items

1. Mentor confirmation of the stack (README "Open Questions" list).
2. SAIPE age-detail + school-district surfaces verified but unpulled; the
   branch pull script covers median income + all-ages rate only.
3. PUMS replicate-weight computation exists on Garrett's branch
   (`analysis/replicate.py`) — validate against published MOEs after merge.
4. Curated-registry refresh for Garrett: VRT 2024 vintage exists (2023 entry
   superseded); VRT 1-year entry should be marked nonexistent.
5. First scoped EDA once confirmed: SAIPE vs ACS county income/poverty — same
   question, two Bureau products, two published-uncertainty styles.
