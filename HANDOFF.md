# HANDOFF.md — Session Handoff Notes

**Written:** 2026-07-09 at project setup; **last updated 2026-08-01 (2nd)** — biweekly #1 outcome logged + Phase 2 scope decided: **income & poverty, NJ pilot, EDA endpoint 2026-08-12** (decisions #13–14). Earlier same day: doc-only sync of `main`'s docs to both open branches (`JL_Work_Tree`, `garrett/financial-eda-imputation` — neither merged; dry-runs: Garrett's fast-forwards clean, JL's conflicts on 4 known files). (Prior updates: 2026-07-26 Product Scope Tracker; 2026-07-20 Justus's EDA 06–07.)
**For:** the next Claude session (or teammate) picking this work up cold.

---

## Read these first, in order

1. [`CLAUDE.md`](CLAUDE.md) — **how to work on this project.** Check-in-before-acting rules, communication standards, statistical rigor requirements. Non-negotiable; read every session.
2. [`README.md`](README.md) — project brief: research questions Q1–Q4, the three must-have deliverables, milestones, Phase 1 checklist, open mentor questions.
3. [`WORKLOG.md`](WORKLOG.md) — the team work log; live record of what's been done and found. Newest entries first.
4. [`docs/data-dictionary.md`](docs/data-dictionary.md) — before touching any dataset: what it is, what uncertainty ships with it, and its landmines.

## Where the project stands (2026-08-01)

- **Phase 1 is complete and documented.** Setup runbook done; five scripted, sanity-checked data pulls (ACS estimates+MOEs, boundaries, DAS demo file, 2010 SF1 baseline, ACS allocation tables); README Step 5 EDA 01–05 done 2026-07-17 — all three uncertainty mechanisms measured empirically: sampling (income CV 0.014 county → 0.204 block group; poverty prevalence-capped), privacy noise (level-dependent; block-group anomaly), imputation (~39% of median-tract households had income imputed; allocation independent of CV once size is controlled → **multi-component composite score empirically justified**). Plain-language record: `docs/phase1-findings-report.md` (EDA 01–05 only — branch numbers stay out until validated, see flags below).
- **Milestone clock: weeks 4–6 (Concept Pitch & Wireframe)** — exit criteria: composite-score approach + dashboard wireframe presented to mentors. EDA 06/07 give the composite a head start; the wireframe has only EDA 03's choropleth as a seed. **Scope is now fixed: income & poverty, NJ pilot (decisions #13–14); EDA phase endpoint 2026-08-12.**
- **Justus Long (`origin/JL_Work_Tree`, final commits 2026-07-20 — unmerged):** EDA 06 composite prototype (**22.8% of NJ tracts are the low-CV/high-allocation blind spot**; equal-weight vs worst-component agree on only 84.6% of the top-risk quartile → weights not locked) and EDA 07 CV driver model (estimate size ≈ **0.67** of pooled CV variance; place population ≈ 0.005; income medians escape the size law, R² ≈ 0.01). The branch also carries the `analysis/alloc.py`/`composite.py`/`cv_model.py` modules + unit tests that notebooks 06/07 import, NEWER re-runs of both notebooks, **a twice-revised `docs/biweekly-2026-07-22.pptx`** (incl. a lead-feedback round — `main`'s deck copy is two revisions stale), glossary additions, a findings-report §8, and his JL_Analysis sandbox.
- **Garrett Spangler, on `main` (2026-07-24…26):** the Product Scope Tracker — `tools/product_scope.py` generates `product_report.html`, a self-contained browser of ~573 Data API product families + a curated 35-entry file-only registry, with `--probe`/`--sample`/`--review` deep dives and the team-shared `product_review.json`. Reportable finding: **no machine-readable index of the Bureau's file-only datasets exists**; the Datasets-page count is unreconciled (**710 vs ~6,158 — cite neither**). His planned CMS scrape (dated 07-27) has not started; 11 registry URLs are flagged `unverified` pending a Windows spot-check.
- **Garrett Spangler (`origin/garrett/financial-eda-imputation`, 2026-07-28 — unmerged):** financial EDA end-to-end — notebooks 08 (allocation-denominator sensitivity) + 09 (person-level PUMS allocation profile, 376,037 NJ records), six pull scripts, `verify_api_surfaces.py`, four analysis modules with **98 passing tests**, replicate-weight MOEs, four `/docs` method pages. Headlines: income imputed ~50× more than any demographic item and independently of them; 98.2% of public-assistance allocations impute a zero; 44.3% of flagged records are whole-person substitutions; his working decision: **never quote a bare allocation rate** (across eight defensible denominators, wages rank 1st–6th). We have not re-executed his notebooks yet.
- **⚠ `main` is still NOT self-contained (since 2026-07-18):** notebooks 06/07 import modules that exist only on `JL_Work_Tree`, and their `eda06_*`/`eda07_*` charts do not exist in our local `data/processed/`. **Lead decision 2026-08-01: doc-only sync now; both branch merges stay open coordination items with Justus and Garrett.** Merge dry-runs (2026-08-01): Garrett's branch **fast-forwards cleanly**; the JL merge conflicts on exactly README.md (now pre-restored — should resolve trivially), WORKLOG.md (both sides added entries; `main` now holds the superset), and notebooks 06+07 (add/add — take his newer versions). After any merge: run that branch's `test_*.py` and re-execute its notebooks top-to-bottom before citing numbers anywhere new.
- **Biweekly #1 (2026-07-22) outcome — logged 2026-08-01 from the lead's debrief:** mentors endorsed the EDA breadth and directed a narrowing — build the tool around a specific product/metric our EDA surfaced, not an all-products reporter. Decisions #13–14 implement it. The four composite questions + the new scoped-stack question go to the next mentor touchpoint (EDA endpoint 2026-08-12; exact meeting date TBC).
- **Binaries decision (lead call, 2026-07-18) stands:** presentation/report files in `/docs` are committed. `docs/team-recap-2026-07-12.pptx` is *still* untracked — fold it into a future commit.
- Remote: <https://github.com/andrewswiniarski-hue/Census_Uncertainty_Analysis>. Local `main` = `origin/main` (`5d859fc`) + this doc-sync. Teammates active: Katie Christiansen (web-UI national pulls, 2026-07-14), Justus Long (`JL_Work_Tree`), Garrett Spangler (tools on `main`; financial-EDA branch). **Always fetch — and check for new branches — before assuming state or pushing.**

## What exists

**In the repo (committed):**
- [`ingestion/pull_acs_nj.py`](ingestion/pull_acs_nj.py) — ACS 5-year vintage 2024, NJ, county/tract/block group, estimates + MOEs, sanity-checked.
- [`ingestion/pull_nj_geometry.py`](ingestion/pull_nj_geometry.py) — vintage-matched boundaries (GeoParquet), 1:1 join verified.
- [`ingestion/pull_das_demo_nj.py`](ingestion/pull_das_demo_nj.py) — 2010 Demonstration Data Product–DHC (2022-08-25 release), NJ summary file + parsing docs; no API key needed.
- [`ingestion/pull_sf1_2010_nj.py`](ingestion/pull_sf1_2010_nj.py) — published 2010 SF1 baseline (P1 + twelve P12B Black 65+ cells) at state/county/tract/BG/block; block queries per-county; 10 sanity checks incl. full-count additivity.
- [`ingestion/pull_acs_alloc_nj.py`](ingestion/pull_acs_alloc_nj.py) — ACS allocation (imputation) tables at county/tract/BG, **estimates only** (allocation tables publish no MOEs); cell labels verified live.
- [`analysis/acs.py`](analysis/acs.py) — shared formulas with citations: CV, top-code flag, aggregate estimate/MOE (handbook zero-cell rule).
- [`analysis/dhc.py`](analysis/dhc.py) — DHC demonstration-file parser: reads geo header + segments straight from the zip (never extracts), LOGRECNO join, quality panel that proves the parse (state invariant, P1↔POP100, P12B additivity). Run standalone: `python -m analysis.dhc`.
- Notebooks 01–05 (each runs clean top-to-bottom; committed with outputs):
  [`01-cv-by-geography-size`](notebooks/01-cv-by-geography-size.ipynb) · [`02-cv-by-variable-type`](notebooks/02-cv-by-variable-type.ipynb) · [`03-cv-choropleth-nj-tracts`](notebooks/03-cv-choropleth-nj-tracts.ipynb) · [`04-privacy-noise-das-demo`](notebooks/04-privacy-noise-das-demo.ipynb) · [`05-allocation-rates-vs-cv`](notebooks/05-allocation-rates-vs-cv.ipynb)
- Notebooks 06–07 (Justus; committed with *his* outputs — **cannot currently run from `main`**, modules on `JL_Work_Tree`):
  [`06-composite-reliability-prototype`](notebooks/06-composite-reliability-prototype.ipynb) · [`07-cv-driver-model`](notebooks/07-cv-driver-model.ipynb)
- [`docs/glossary.md`](docs/glossary.md) · [`docs/data-dictionary.md`](docs/data-dictionary.md) (ACS + allocation, boundaries, DAS demo, SF1) · [`docs/uncertainty-sources.md`](docs/uncertainty-sources.md) + [`docs/acs-data-shape-diagram.md`](docs/acs-data-shape-diagram.md) (Justus) · `Git_Instruct.md` (team branch workflow) · `requirements.txt` (**still not version-pinned** — see TODO).
- [`tools/product_scope.py`](tools/product_scope.py) + [`tools/scope_evidence.py`](tools/scope_evidence.py) (Garrett) — Product Scope Tracker; regenerates `product_report.html` (committed) from the Census API catalog + repo evidence; team notes in `product_review.json` (committed, team-shared); v1 archived under `tools/archive/`. Reference: `tools/README.md`.

**On branches only (not on `main` — see "Where the project stands"):**
- `origin/JL_Work_Tree` (Justus): `analysis/alloc.py` · `analysis/composite.py` · `analysis/cv_model.py` + `analysis/test_*.py`; newer runs of notebooks 06/07; twice-revised `docs/biweekly-2026-07-22.pptx`; findings-report §8; glossary additions; `analysis/JL_Analysis/` sandbox.
- `origin/garrett/financial-eda-imputation` (Garrett): notebooks 08–09; `analysis/{common,alloc_denominator,alloc_profile,replicate}.py`; `tests/` (98 tests); six `ingestion/pull_*.py`; `verify_api_surfaces.py`; `report_alloc_*.py`; `requirements-dev.txt`; docs `api-surface-verified` / `api-surface-b99-income` / `allocation-denominator-sensitivity` / `allocation-profile-nj`.

**Local only (gitignored, regenerable by the scripts/notebooks above):**
- `data/raw/acs5_2024_nj_{county,tract,block_group}.parquet` — 21 / 2,181 / 6,599 rows
- `data/raw/geo_2024_nj_{county,tract,block_group}.parquet` + verification map
- `data/raw/das_demo/` — `nj2010.dhc.zip` (250 MB; 44 table segments + geo header, 2.0 GB uncompressed) + README, technical document, geoheader layout, table matrix
- `data/raw/sf1_2010_nj_{state,county,tract,block_group,block}.parquet` — 1 / 21 / 2,010 / 6,320 / 169,588 rows (published 2010 baseline)
- `data/raw/acs5_2024_nj_alloc_{county,tract,block_group}.parquet` — 21 / 2,181 / 6,599 rows (allocation tables)
- `data/processed/eda01…eda05 PNG charts` — eight mentor-slide candidates (flagship: `eda04_noise_rmse_by_size.png`; independence backup: `eda05_allocation_vs_cv.png`)
- `.env` with a working `CENSUS_API_KEY`; `.venv` — Python 3.12.10 (pandas 2.3.3, geopandas 1.0.1, censusdis 1.4.2, pyarrow 18.1.0, matplotlib 3.11.0)

## Decisions already made (by the project lead — don't relitigate)

1. **Vintage 2024** (2020–2024 ACS 5-year, newest available).
2. **Tract is the floor for poverty/subgroup analysis** (B17001/B01001B not published below tract; C17002 alternative logged as mentor question).
3. **`data/raw/` stays exactly as the API returned it** — all cleaning in a processing layer (still doesn't exist).
4. **CV formula:** `CV = (MOE / 1.645) / estimate` (ACS "Accuracy of the Data").
5. **Zero or missing estimates → CV undefined (NaN)**, reported separately — never treated as "infinitely unreliable."
6. **Top-coded income ($250,001) is flagged and excluded from CV distributions**, count reported.
7. **Derived-estimate MOEs: root-sum-of-squares with the handbook zero-cell rule as default** (only the largest zero-cell MOE enters, once) — ACS handbook Ch. 8; plain RSS kept available for sensitivity.
8. **Reliability thresholds CV 0.12 / 0.30 / 0.40 (ESRI, NCHS) are cited descriptively only.** Our own tiers are a weeks-4–6 decision with mentors.
9. **DAS demonstration vintage, provisional: 2022-08-25 tabulated DHC release** (2023-04-03 suite is 15 GB national microdata only; 2022-03-16 has a technical-issues alert). Mentor confirmation pending.
10. **EDA 04 scope and metric (approved 2026-07-16):** variables = total population + Black 65+ (parallels EDA 02); geography = down to block; headline metric = **binned relative RMSE** (quarter-decade log bins, ≥30 units/bin, RMSE(demo−published)/mean(published) — the CV analog for mean-zero noise), with the per-unit scatter as supporting view only. Zero-baseline units are their own reported class (extends decision #5 to a second mechanism).
11. **EDA 05 scope and method (approved 2026-07-17):** poverty allocation uses the family-universe table B99172 as a **labeled proxy** (no person-level table exists); independence testing uses **raw + size-controlled Spearman** — residualize log10(CV) on log10(universe COUNT) first (households for income, never dollar values) — and the composite-score claim rests on the controlled number. B98031 (county-only) serves as prevalence context, item-matched pairings as the tract-level headline. Any future correlation-with-CV analysis defaults to the size-controlled version.
12. **Composite prototype working boundaries (Justus, EDA 06/07 — PROVISIONAL, pending mentor review):** the two-axis CV × allocation matrix is the headline view; combination weights are **not locked** (equal-weight vs worst-component top-quartile agreement only 84.6%); DHC privacy noise stays a **separate product-level score** (never row-joined into ACS rows); thresholds (CV 0.30, allocation = NJ 75th percentile) are exploratory conventions; income residual flags are a V2 seed for count variables only (income size-model R² ≈ 0.01). All four are on the mentor question list — treat as working assumptions, not settled decisions.
13. **Mentor guidance, biweekly #1 (2026-07-22; logged 2026-08-01):** EDA breadth endorsed; **narrow the project** — build the tool around a specific product/metric surfaced by our EDA rather than an uncertainty reporter for the whole product catalog.
14. **Phase 2 scope (lead, 2026-08-01):** domain = **income & poverty** (one domain, together); **composite score unchanged** as a deliverable — the reporting tool's *form* follows the anchor product; **NJ pilot**; **product-first** — shortlist proposal + published-uncertainty verification before further EDA (headline: ACS 5-year B19013/B17001/C17002 + allocation tables B99192/B99172; supporting: SAIPE, PUMS replicate weights / Variance Replicate Tables; mentor confirmation pending); whole-catalog work **parked** (CMS scrape); **EDA phase endpoint 2026-08-12**. Consequence: the DAS/privacy-noise thread demotes to report context (income is absent from decennial products) — confirmation question logged in the README, not silently dropped.

## Data landmines the next session must know

- **censusdis silently converts ACS annotation codes to NaN** — "controlled" (very reliable) and "insufficient sample" (unreliable) become identical blanks. `EA`/`MA` annotation variables can be pulled if the distinction becomes score-relevant.
- **Median income is top-coded at `250,001`**; every top-coded row also has a blank MOE. 41 tracts, 270 block groups in NJ.
- **131 NJ tracts (all 21 counties) have unexplained near-controlled population MOEs** (±14–143 vs. median ±546) — cause unknown, logged as a mentor question; don't guess. (Found in EDA 02.)
- **Poverty reliability is prevalence-capped**: CV-vs-size slope −0.18 (vs. −0.5 sampling law); poverty data is *most* reliable in high-poverty tracts (Spearman −0.58) and worst in affluent ones. (EDA 02/03.)
- **6 invalid geometries at tract and block group** — fine for plotting; `make_valid` before any area/overlay math.
- **The Census demonstration-products archive times out on directory listings (Cloudflare 524)** — deep-link to files directly, as `pull_das_demo_nj.py` does.
- **Demonstration data is for evaluating privacy noise only** — never analyze it as real 2010 populations.
- **The block-group anomaly (EDA 04, unexplained — don't guess):** absolute privacy noise is level-dependent, not size-dependent. NJ block groups carry ~9× tract-level total-population noise (RMSE 23.2 vs. 2.5); for the P12B subgroup table, *county* is the noisiest level (34.6). Mentor question logged; spine/off-spine allocation is our labeled hypothesis only.
- **Ghost/vanished blocks exist in the demo data** (807 gain phantom people, 427 lose everyone) — treat zero/near-zero baselines as their own class in any noise metric.
- **2010 SF1 API variable naming:** it's `P001001`/`P012B020` (not `P0010001`), and `PCT012B020` is a *different* table that also resolves — verify labels at runtime, as the pull script does.
- **SF1 parquets store API strings** (raw-stays-raw convention) — coerce numerics in the analysis layer before math.
- **2010 vs. 2024 geography vintages must never be row-joined** — EDA 04 vs. EDA 01–03 comparisons are of mechanisms/slopes only.
- **B98031/B98032 (overall allocation rates) are county-only** — the API returns tract/BG rows with every value null. General probe lesson: *a query returning rows does not mean it returns values* — check nullness, not just row counts.
- **Allocation tables (B98/B99) publish no MOE variables** — requesting a `_M` errors the whole query; pull them E-only. An allocation rate has no CV; treat it as a covariate.
- **Notebooks 06/07 on `main` cannot run** until `origin/JL_Work_Tree` merges (their `analysis/` modules live only there), and their committed outputs came from Justus's machine — after the merge, run his `analysis/test_*.py` and re-execute both notebooks locally before citing their numbers anywhere new. His branch also carries NEWER runs of both notebooks, so `main`'s copies are stale as well as non-runnable. General lesson: web-UI uploads can land a notebook without its dependencies — check imports against `main`, not just file presence.
- **`ingestion/pull_acs_alloc_nj.py`'s B98031 range check passes vacuously at tract/BG** — the column is 100% null there, and `.all()` over the surviving (empty) values returns `True` (found by Garrett, 2026-07-28; unfixed as of 2026-08-01). General lesson: assert on the count of non-null values too, not just `.all()`.
- **PUMS income N/A codes are not uniform** — `WAGP`/`SSP`/`RETP`/`PAP` use −1 but `SEMP`/`INTP` use −10001; a blanket `< 0` filter corrupts the two sources of most interest (Garrett, EDA 09).
- **`FHINCP` is a household flag arriving on person rows** — dedupe on `SERIALNO` first, or NJ reads as 9.07M households instead of ~3.4M (Garrett, EDA 09).
- **The Datasets-page universe count is unreconciled** — census.gov's page reports 710 where we'd been quoting ~6,158 from the same page; almost certainly different units. Cite neither until the `getfacets` payload is captured (Garrett, 2026-07-26).

## Next work, in priority order

1. **Product shortlist sprint (product-first, decision #14):** verify the scoped candidates — ACS 5-year income/poverty (B19013/B17001/C17002), allocation tables, SAIPE, PUMS replicate weights / Variance Replicate Tables — for what uncertainty each publishes, geography floor, cadence, and access path; write their `docs/data-dictionary.md` entries (closes README Step 4 for the scoped set) and a one-page mentor-ready shortlist proposal. Use the Product Scope Tracker's `--probe`/`--sample` for receipts.
2. **Coordinate the two branch merges with Justus and Garrett** (their branches; merging is a joint call with the lead — both read as final per their WORKLOG entries; **Garrett's branch is now core to the scoped domain**). Dry-runs (2026-08-01): `garrett/financial-eda-imputation` **fast-forwards cleanly** onto `main`; `JL_Work_Tree` conflicts on exactly README.md (pre-restored 2026-08-01 — should now resolve trivially), WORKLOG.md (`main` holds the superset — keep it), and notebooks 06+07 (add/add — take his newer versions). **After each merge:** run that branch's tests (`analysis/test_*.py` / `tests/`), re-execute its notebooks top-to-bottom locally, confirm charts regenerate — only then may its numbers enter `docs/phase1-findings-report.md`.
3. **Targeted income/poverty EDA until 2026-08-12** (gated on #1's shortlist): first candidates — SAIPE vs ACS county income/poverty (same question, two Bureau products, two published-uncertainty styles) and denominator-aware allocation reporting (Garrett's "never quote a bare allocation rate").
4. **Concept pitch + dashboard wireframe ready by 2026-08-12** (weeks 4–6 exit criteria): composite approach (EDA 06/07 prototype, weights still mentor-gated) + income/poverty reliability dashboard mock (seeds: EDA 03 choropleth, EDA 06 quadrant matrix).
5. **Fix `ingestion/pull_acs_alloc_nj.py`'s vacuous B98031 range check** (see landmines).
6. Pin package versions to a lockfile (reproducibility deliverable; Garrett's `requirements-dev.txt` on his branch is a seed).
7. Complete `docs/data-dictionary.md` beyond the scoped set (DHC, Demographic Profile, PPMF entries) if mentors want the wider catalog documented.

**Parked (scope decision #14):** Garrett's CMS-scrape plan — `getfacets` capture, catalog scraper, count reconciliation (710 vs ~6,158 vs ~4,400), the 11 `URL unverified` spot-checks. Revisit only if it serves the income/poverty story.

## Environment gotchas

- Windows machine. Run scripts from the repo root with `.venv/Scripts/python.exe <script>`; execute notebooks with `.venv/Scripts/python.exe -m jupyter nbconvert --to notebook --execute --inplace <nb>`.
- **The parent folder `C:\Users\andre\Documents` contains a stray zero-commit git repo.** Never run git commands outside this repo without checking `git rev-parse --show-toplevel` first.
- **Git history was rewritten on 2026-07-09** to purge sponsor contact info from the public repo. Pre-rewrite SHAs are invalid; stale clones must not be pushed from. **Never re-add sponsor contact details to any committed file** — the repo is public.
- LF/CRLF warnings on commit are normal on this machine; ignore them.

## Working style (summary — full rules in CLAUDE.md)

Propose before coding; present options + recommendation before methodology choices and let the lead decide; stop and summarize at every checkpoint; flag surprising results immediately (characterize, don't guess at causes); plain English first, define every term, cite every formula; sanity-check every data pull before analyzing it; WORKLOG entry in the same commit as the work; never bluff — log unresolvable questions for the Census mentors in the README.
