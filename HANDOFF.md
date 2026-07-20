# HANDOFF.md — Session Handoff Notes

**Written:** 2026-07-09 at project setup; **last updated 2026-07-20** — Justus's EDA 06–07 (Phase 2 bridge) pulled and accounted for; `JL_Work_Tree` merge pending.
**For:** the next Claude session (or teammate) picking this work up cold.

---

## Read these first, in order

1. [`CLAUDE.md`](CLAUDE.md) — **how to work on this project.** Check-in-before-acting rules, communication standards, statistical rigor requirements. Non-negotiable; read every session.
2. [`README.md`](README.md) — project brief: research questions Q1–Q4, the three must-have deliverables, milestones, Phase 1 checklist, open mentor questions.
3. [`WORKLOG.md`](WORKLOG.md) — the team work log; live record of what's been done and found. Newest entries first.
4. [`docs/data-dictionary.md`](docs/data-dictionary.md) — before touching any dataset: what it is, what uncertainty ships with it, and its landmines.

## Where the project stands (2026-07-20)

- **The Phase 1 setup runbook (NEXT_ACTIONS.md, Steps 1–6) is complete.** Repo live, environment working, five scripted data pulls: ACS estimates+MOEs, matching boundaries, the DAS demonstration file, the published 2010 SF1 baseline, and the ACS allocation tables.
- **README Step 5 is COMPLETE (2026-07-17): EDA 01–05 done** — five notebooks, eight mentor-ready charts, all three uncertainty mechanisms measured empirically: sampling (EDA 01–03), privacy noise (EDA 04: ≈ −1 slope vs. sampling's −½; block-group anomaly), imputation (EDA 05: income imputed for ~39% of households at the median tract; **allocation rates independent of CVs once size is controlled → multi-component composite score empirically justified**).
- **EDA 05 work reviewed by the lead and committed 2026-07-17** (new: `ingestion/pull_acs_alloc_nj.py`, `notebooks/05-allocation-rates-vs-cv.ipynb`, plus README/glossary/data-dictionary/WORKLOG/HANDOFF updates). EDA 04 was committed and pushed 2026-07-16 (`ac4921a`).
- **Both communication deliverables are built and committed:** `docs/phase1-findings-report.md` (the complete Phase 1 analysis in plain language — the briefing document for team and Bureau readers, kept current as later findings land) and `docs/biweekly-2026-07-22.pptx` (9-slide mentor deck with speaker notes, matched to the team-recap design system).
- **Justus Long landed the Phase 2 bridge (2026-07-18/19; pulled + reviewed 2026-07-20):** EDA 06 — composite prototype (income CV × income allocation quadrant matrix; **22.8% of NJ tracts are the low-CV/high-allocation blind spot**; equal-weight vs worst-component scores agree on only 84.6% of the top-risk quartile → weights deliberately not locked) and EDA 07 — CV driver model (place population explains ~nothing, R² ≈ 0.005; **estimate size ≈ 0.67 of pooled CV variance**; level/variable-type add ~+0.06; income medians escape the size law, R² ≈ 0.01). Both honor Phase 1 decisions (top-code exclusion, labeled poverty proxy, no DHC row-join, mentor-gated weights). He also wrote `docs/uncertainty-sources.md` (the Step 2 writeup — done) and `docs/acs-data-shape-diagram.md`.
- **⚠ `main` is currently NOT self-contained:** notebooks 06/07 import `analysis/alloc.py`, `analysis/composite.py`, `analysis/cv_model.py` (+ unit tests), which exist **only on `origin/JL_Work_Tree`** (along with his JL_Analysis sandbox, glossary additions, and a findings-report §8 update). Until that branch merges, 06/07 cannot run from `main`, and their `eda06_*`/`eda07_*` charts do not exist in our local `data/processed/` (his committed outputs were executed on his machine). Merge is next-work #1.
- **First mentor biweekly: July 22, 2026.** The deck is ready to present — status slide with the EDA 04 flagship chart, three priority questions, five chart backups. Open decision: whether EDA 06's 22.8% blind-spot number earns a slide; Justus's four new mentor questions are now in the README list.
- **Binaries decision resolved (lead call, 2026-07-18):** presentation/report files in `/docs` are committed. `docs/team-recap-2026-07-12.pptx` is still untracked from before the decision — fold it into a future commit if wanted.
- Remote: <https://github.com/andrewswiniarski-hue/Census_Uncertainty_Analysis>. Local `main` = `origin/main` (`2c1fd07`) after pulling Justus's work 2026-07-20; his full tree awaits merge from `origin/JL_Work_Tree`.
- **Teammates are active — always fetch (and check branches) before assuming state or pushing.** Katie Christiansen: national ACS + boundaries pulls via web UI (2026-07-14). Justus Long: feature-branch workflow per `Git_Instruct.md`, currently on `JL_Work_Tree`; his web-UI uploads to `main` are what left 06/07 without their modules.

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
- **Notebooks 06/07 on `main` cannot run** until `origin/JL_Work_Tree` merges (their `analysis/` modules live only there), and their committed outputs came from Justus's machine — after the merge, run his `analysis/test_*.py` and re-execute both notebooks locally before citing their numbers anywhere new. General lesson: web-UI uploads can land a notebook without its dependencies — check imports against `main`, not just file presence.

## Next work, in priority order

1. **Merge `origin/JL_Work_Tree` into `main`** (lead-coordinated with Justus — his call or ours, decide together). His branch carries the analysis modules + unit tests notebooks 06/07 need, his JL_Analysis sandbox, glossary additions, and a findings-report §8 update. The `main` README was pre-aligned **verbatim** with his branch's README hunks on 2026-07-20, so that file merges clean; expect a small WORKLOG conflict (both sides added entries — keep both). **After merging:** run `analysis/test_*.py`, re-execute notebooks 06/07 top-to-bottom locally, confirm `eda06_*`/`eda07_*` charts regenerate.
2. **Present the July 22 biweekly** (deck ready: `docs/biweekly-2026-07-22.pptx`; speaker notes on every slide; the README "Open Questions for Mentors" list — now including Justus's four — is the canonical question set). Decide beforehand whether EDA 06's 22.8% blind-spot number gets a slide. Afterward: log mentor answers as decisions in this file and the README.
3. **Composite-score phase proper** (post-biweekly, once tier-philosophy + score-input questions are answered) — EDA 06/07 are the prototype; component list with empirical justification is in `docs/phase1-findings-report.md` §6.
4. Pin package versions to a lockfile (reproducibility deliverable).
5. Complete `docs/data-dictionary.md` (DHC, Demographic Profile, PPMF entries) once mentors confirm the product shortlist.

## Environment gotchas

- Windows machine. Run scripts from the repo root with `.venv/Scripts/python.exe <script>`; execute notebooks with `.venv/Scripts/python.exe -m jupyter nbconvert --to notebook --execute --inplace <nb>`.
- **The parent folder `C:\Users\andre\Documents` contains a stray zero-commit git repo.** Never run git commands outside this repo without checking `git rev-parse --show-toplevel` first.
- **Git history was rewritten on 2026-07-09** to purge sponsor contact info from the public repo. Pre-rewrite SHAs are invalid; stale clones must not be pushed from. **Never re-add sponsor contact details to any committed file** — the repo is public.
- LF/CRLF warnings on commit are normal on this machine; ignore them.

## Working style (summary — full rules in CLAUDE.md)

Propose before coding; present options + recommendation before methodology choices and let the lead decide; stop and summarize at every checkpoint; flag surprising results immediately (characterize, don't guess at causes); plain English first, define every term, cite every formula; sanity-check every data pull before analyzing it; WORKLOG entry in the same commit as the work; never bluff — log unresolvable questions for the Census mentors in the README.
