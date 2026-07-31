# HANDOFF.md — Session Handoff Notes

**Written:** 2026-07-09 at project setup; **last updated 2026-07-31** — Phase 1 (EDA 01–05) complete; composite-score + CV-driver work (EDA 06/07) complete and merged into one notebook; codebase audited and trimmed (shadow codebase removed, duplication consolidated) ahead of extending the analysis to DHC + Demographic Profile.
**For:** the next Claude session (or teammate) picking this work up cold.

---

## Read these first, in order

1. [`CLAUDE.md`](CLAUDE.md) — **how to work on this project.** Check-in-before-acting rules, communication standards, statistical rigor requirements. Non-negotiable; read every session.
2. [`README.md`](README.md) — project brief: research questions Q1–Q4, the three must-have deliverables, milestones, Phase 1 checklist, open mentor questions.
3. [`WORKLOG.md`](WORKLOG.md) — the team work log; live record of what's been done and found. Newest entries first.
4. [`docs/data-dictionary.md`](docs/data-dictionary.md) — before touching any dataset: what it is, what uncertainty ships with it, and its landmines.

## Where the project stands (2026-07-31)

- **Phase 1 (README Step 5) is COMPLETE:** EDA 01–05 measured all three uncertainty mechanisms empirically — sampling (EDA 01–03), privacy noise (EDA 04: ≈ −1 slope vs. sampling's −½; block-group anomaly), imputation (EDA 05: income imputed for ~39% of households at the median tract; allocation rates independent of CVs once size is controlled → multi-component composite score empirically justified).
- **The composite score + CV driver model (formerly EDA 06 and EDA 07) are COMPLETE and merged into one notebook**, [`notebooks/06-composite-reliability-and-cv-drivers.ipynb`](notebooks/06-composite-reliability-and-cv-drivers.ipynb): the two-axis CV × allocation matrix (22.8% blind-spot share), the nested OLS driver model (place population fails, R² ≈ 0.005; estimate size dominates, R² ≈ 0.67–0.73), and the composite V2 residual flag. An absolute 0–100 scoring API (`cv_subscore`/`reliability_index`/`assign_tier`) was prototyped and then deliberately removed — the score/tier philosophy is still an open mentor question (see Open Questions in README).
- **Codebase audit and trim (2026-07-31):** removed the `analysis/JL_Analysis/` shadow codebase (duplicate notebooks + helpers, superseded by `notebooks/01–03` and `analysis/acs.py`), consolidated ingestion boilerplate into `ingestion/_common.py`, consolidated chart/formula duplication into `analysis/viz.py` and `analysis/cv_model.py` (`loglog_slope`, `spearman_corr`), and merged notebooks 06+07. All headline published numbers were verified unchanged (re-executed, spot-checked against WORKLOG). See the WORKLOG entry for the full list.
- **Both communication deliverables are built and committed:** `docs/phase1-findings-report.md` (the complete Phase 1 analysis in plain language — the briefing document for team and Bureau readers, kept current as later findings land) and `docs/biweekly-2026-07-22.pptx` (9-slide mentor deck with speaker notes, matched to the team-recap design system).
- **First mentor biweekly (July 22, 2026) happened; product shortlist confirmed** (decision #12 below).
- **Binaries decision resolved (lead call, 2026-07-18):** presentation/report files in `/docs` are committed. `docs/team-recap-2026-07-12.pptx` is still untracked from before the decision — fold it into a future commit if wanted.
- Remote: <https://github.com/andrewswiniarski-hue/Census_Uncertainty_Analysis> (branch `main`). This worktree (`JL_Work_Tree`) has diverged from `main` — see the Risks note in the audit-and-trim WORKLOG entry before merging.
- **Teammates are contributing via the GitHub web UI** — fetch before you push. Katie Christiansen added a national-level ACS + boundaries pull ([`ingestion/pull_acs_us.py`](ingestion/pull_acs_us.py), state/county only) on 2026-07-14; see her WORKLOG entry. (`ingestion/Explore.py`, her scratch script from the same date, was removed in the 2026-07-31 audit — superseded, no functions, hard-coded paths.)

## What exists

**In the repo (committed):**
- [`ingestion/_common.py`](ingestion/_common.py) — shared pull-script mechanics: API key loading, official-label fetching, the ACS annotation sanity report.
- [`ingestion/pull_acs_nj.py`](ingestion/pull_acs_nj.py) — ACS 5-year vintage 2024, NJ, county/tract/block group, estimates + MOEs, sanity-checked.
- [`ingestion/pull_nj_geometry.py`](ingestion/pull_nj_geometry.py) — vintage-matched boundaries (GeoParquet), 1:1 join verified.
- [`ingestion/pull_das_demo_nj.py`](ingestion/pull_das_demo_nj.py) — 2010 Demonstration Data Product–DHC (2022-08-25 release), NJ summary file + parsing docs; no API key needed.
- [`ingestion/pull_sf1_2010_nj.py`](ingestion/pull_sf1_2010_nj.py) — published 2010 SF1 baseline (P1 + twelve P12B Black 65+ cells) at state/county/tract/BG/block; block queries per-county; 10 sanity checks incl. full-count additivity.
- [`ingestion/pull_acs_alloc_nj.py`](ingestion/pull_acs_alloc_nj.py) — ACS allocation (imputation) tables at county/tract/BG, **estimates only** (allocation tables publish no MOEs); cell labels verified live.
- [`analysis/acs.py`](analysis/acs.py) — shared formulas with citations: CV, top-code flag, aggregate estimate/MOE (handbook zero-cell rule), geometry loading (`load_geo`, NJ State Plane reprojection).
- [`analysis/alloc.py`](analysis/alloc.py) — allocation-rate derivation (EDA 05 formulas).
- [`analysis/composite.py`](analysis/composite.py) — two-axis CV × allocation quadrant matrix, sensitivity scores, residual-flag attachment.
- [`analysis/cv_model.py`](analysis/cv_model.py) — long CV driver frame, nested OLS, `loglog_slope`, `spearman_corr`.
- [`analysis/viz.py`](analysis/viz.py) — shared chart furniture (boxplot style, CV reference lines, brand palette, `save_chart`).
- [`analysis/dhc.py`](analysis/dhc.py) — DHC demonstration-file parser: reads geo header + segments straight from the zip (never extracts), LOGRECNO join, quality panel that proves the parse (state invariant, P1↔POP100, P12B additivity). Run standalone: `python -m analysis.dhc`.
- Notebooks (each runs clean top-to-bottom; committed with outputs):
  [`01-cv-by-geography-size`](notebooks/01-cv-by-geography-size.ipynb) · [`02-cv-by-variable-type`](notebooks/02-cv-by-variable-type.ipynb) · [`03-cv-choropleth-nj-tracts`](notebooks/03-cv-choropleth-nj-tracts.ipynb) · [`04-privacy-noise-das-demo`](notebooks/04-privacy-noise-das-demo.ipynb) · [`05-allocation-rates-vs-cv`](notebooks/05-allocation-rates-vs-cv.ipynb) · [`06-composite-reliability-and-cv-drivers`](notebooks/06-composite-reliability-and-cv-drivers.ipynb)
- [`docs/glossary.md`](docs/glossary.md) · [`docs/data-dictionary.md`](docs/data-dictionary.md) (ACS, boundaries, DAS demo, 2010 SF1) · `requirements.txt` (**still not version-pinned** — see TODO).

**Local only (gitignored, regenerable by the scripts/notebooks above):**
- `data/raw/acs5_2024_nj_{county,tract,block_group}.parquet` — 21 / 2,181 / 6,599 rows
- `data/raw/geo_2024_nj_{county,tract,block_group}.parquet` + verification map
- `data/raw/das_demo/` — `nj2010.dhc.zip` (250 MB; 44 table segments + geo header, 2.0 GB uncompressed) + README, technical document, geoheader layout, table matrix (**not present in this worktree** — regenerate with `pull_das_demo_nj.py` before re-running notebook 04)
- `data/raw/sf1_2010_nj_{state,county,tract,block_group,block}.parquet` — 1 / 21 / 2,010 / 6,320 / 169,588 rows (published 2010 baseline; **not present in this worktree**, same caveat)
- `data/raw/acs5_2024_nj_alloc_{county,tract,block_group}.parquet` — 21 / 2,181 / 6,599 rows (allocation tables)
- `data/processed/eda01…eda06 PNG charts` — mentor-slide candidates (flagship: `eda04_noise_rmse_by_size.png`; independence backup: `eda05_allocation_vs_cv.png`; composite matrix: `eda06_income_reliability_matrix.png`; driver model: `eda07_r2_waterfall.png`, filenames kept from the pre-merge notebooks)
- `.env` with a working `CENSUS_API_KEY`; `.venv` (not present in this worktree — see Environment gotchas)

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
12. **Product shortlist confirmed by mentors (2026-07-22 biweekly):** ACS 5-year + DHC + Demographic Profile are the 3 core products for the report/dashboard.
13. **DHC uncertainty methodology (lead decision, 2026-07-31, pending mentor confirmation):** score real 2020 DHC production data (NJ) using the EDA 04 demo-derived noise model (RMSE by geography level/size bin, from the 2010 demonstration-vs-SF1 comparison) as an **estimated/modeled** uncertainty input — clearly labeled as modeled, not measured. No ground truth exists for production disclosure-avoidance noise by design (the demo/SF1 pairing is the only place a comparison is possible), so this is the only way to score DHC rows at all, not a shortcut.
14. **Demographic Profile uncertainty methodology (lead decision, 2026-07-31):** score real 2020 DP1 data (NJ) using the **same** DAS noise model as DHC — same disclosure-avoidance mechanism, same protected microdata source. No separate empirical noise study for DP; DP1 is a new table/geography-availability run through the existing scoring pipeline, not a new measurement workstream.

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

## Next work, in priority order

*(Revised 2026-07-31 — product shortlist confirmed, composite-score + CV-driver work for ACS done, codebase audited and trimmed. Now in Weeks 4–6, "Concept Pitch & Wireframe" phase; exit criteria: composite score approach + dashboard wireframe presented to mentors.)*

1. **Pull real 2020 DHC production data + real 2020 Demographic Profile (DP1) data for NJ** — two new ingestion scripts on `ingestion/_common.py`, sanity-checked per convention (row counts, null rates, geography-count checks). These are the actual products (not the 2010 demo/SF1 files already on disk), per decisions #13–14 above. Note: DP1 only publishes state/county/tract (no block group, no block) — see README Open Questions.
2. **Extend `analysis/composite.py` (or a new module) to score DHC/DP rows** using the demo-derived noise model as the modeled uncertainty input — reuses EDA 04's RMSE-by-size/level curve; no new empirical measurement.
3. **Q4: dashboard wireframe** — the actual mentor exit criterion for this phase. Can start from ACS's already-working composite matrix (notebook 06) without waiting on steps 1–2; DHC/DP slots in as those scores land.
4. **Q3: existing-metrics review** — assess which current Census-published uncertainty metrics (MOE, CV conventions, quality flags) are fit for which real user decisions; a documentation/synthesis doc, not a notebook. Untouched since kickoff.
5. Pin package versions to a lockfile (reproducibility deliverable).
6. Complete `docs/data-dictionary.md` (DHC production, Demographic Profile, PPMF entries) now that the product shortlist and scoring methodology are confirmed.

## Environment gotchas

- Windows machine. Run scripts from the repo root with `.venv/Scripts/python.exe <script>` if `.venv` exists; this worktree currently has no `.venv` and runs on system Python 3.13 instead (all packages except `censusdis` present — ingestion scripts needing the Census API cannot run here without it). Execute notebooks with `python -m jupyter nbconvert --to notebook --execute --inplace <nb>`.
- **The parent folder `C:\Users\andre\Documents` contains a stray zero-commit git repo.** Never run git commands outside this repo without checking `git rev-parse --show-toplevel` first.
- **Git history was rewritten on 2026-07-09** to purge sponsor contact info from the public repo. Pre-rewrite SHAs are invalid; stale clones must not be pushed from. **Never re-add sponsor contact details to any committed file** — the repo is public.
- LF/CRLF warnings on commit are normal on this machine; ignore them.

## Working style (summary — full rules in CLAUDE.md)

Propose before coding; present options + recommendation before methodology choices and let the lead decide; stop and summarize at every checkpoint; flag surprising results immediately (characterize, don't guess at causes); plain English first, define every term, cite every formula; sanity-check every data pull before analyzing it; WORKLOG entry in the same commit as the work; never bluff — log unresolvable questions for the Census mentors in the README.
