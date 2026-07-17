# HANDOFF.md — Session Handoff Notes

**Written:** 2026-07-09 at project setup; **last updated 2026-07-16**, after EDA 04 (privacy noise).
**For:** the next Claude session (or teammate) picking this work up cold.

---

## Read these first, in order

1. [`CLAUDE.md`](CLAUDE.md) — **how to work on this project.** Check-in-before-acting rules, communication standards, statistical rigor requirements. Non-negotiable; read every session.
2. [`README.md`](README.md) — project brief: research questions Q1–Q4, the three must-have deliverables, milestones, Phase 1 checklist, open mentor questions.
3. [`WORKLOG.md`](WORKLOG.md) — the team work log; live record of what's been done and found. Newest entries first.
4. [`docs/data-dictionary.md`](docs/data-dictionary.md) — before touching any dataset: what it is, what uncertainty ships with it, and its landmines.

## Where the project stands (2026-07-15)

- **The Phase 1 setup runbook (NEXT_ACTIONS.md, Steps 1–6) is complete.** Repo live, environment working, four scripted data pulls: ACS estimates+MOEs, matching boundaries, the DAS demonstration file, and the published 2010 SF1 baseline.
- **EDA 01–04 are done:** four notebooks, seven mentor-ready charts. **EDA 04 (privacy noise) completed 2026-07-16** — headline: the two dominant noise mechanisms follow measurably different laws (privacy ≈ −1 slope vs. sampling −½), plus a genuine surprise (the block-group anomaly, see landmines). Only EDA #5 (allocation rates) remains from the Step 5 list.
- **EDA 04 work reviewed by the lead and committed 2026-07-16** (new: `ingestion/pull_sf1_2010_nj.py`, `analysis/dhc.py`, `notebooks/04-privacy-noise-das-demo.ipynb`, plus README/glossary/data-dictionary/WORKLOG/HANDOFF updates).
- **First mentor biweekly: July 22, 2026.** Bring a one-slide status; chart candidates are ready (see below) — EDA 04's flagship chart is the strongest new candidate.
- Remote: <https://github.com/andrewswiniarski-hue/Census_Uncertainty_Analysis> (branch `main`). Everything through 2026-07-15 is pushed; `docs/team-recap-2026-07-12.pptx` remains untracked, pending the lead's call on committing binaries.
- **Teammates are contributing via the GitHub web UI** — fetch before you push. Katie Christiansen added a national-level ACS + boundaries pull ([`ingestion/pull_acs_us.py`](ingestion/pull_acs_us.py), state/county only) and [`ingestion/Explore.py`](ingestion/Explore.py) on 2026-07-14; see her WORKLOG entry.

## What exists

**In the repo (committed):**
- [`ingestion/pull_acs_nj.py`](ingestion/pull_acs_nj.py) — ACS 5-year vintage 2024, NJ, county/tract/block group, estimates + MOEs, sanity-checked.
- [`ingestion/pull_nj_geometry.py`](ingestion/pull_nj_geometry.py) — vintage-matched boundaries (GeoParquet), 1:1 join verified.
- [`ingestion/pull_das_demo_nj.py`](ingestion/pull_das_demo_nj.py) — 2010 Demonstration Data Product–DHC (2022-08-25 release), NJ summary file + parsing docs; no API key needed.
- [`ingestion/pull_sf1_2010_nj.py`](ingestion/pull_sf1_2010_nj.py) — published 2010 SF1 baseline (P1 + twelve P12B Black 65+ cells) at state/county/tract/BG/block; block queries per-county; 10 sanity checks incl. full-count additivity.
- [`analysis/acs.py`](analysis/acs.py) — shared formulas with citations: CV, top-code flag, aggregate estimate/MOE (handbook zero-cell rule).
- [`analysis/dhc.py`](analysis/dhc.py) — DHC demonstration-file parser: reads geo header + segments straight from the zip (never extracts), LOGRECNO join, quality panel that proves the parse (state invariant, P1↔POP100, P12B additivity). Run standalone: `python -m analysis.dhc`.
- Notebooks (each runs clean top-to-bottom; committed with outputs):
  [`01-cv-by-geography-size`](notebooks/01-cv-by-geography-size.ipynb) · [`02-cv-by-variable-type`](notebooks/02-cv-by-variable-type.ipynb) · [`03-cv-choropleth-nj-tracts`](notebooks/03-cv-choropleth-nj-tracts.ipynb) · [`04-privacy-noise-das-demo`](notebooks/04-privacy-noise-das-demo.ipynb)
- [`docs/glossary.md`](docs/glossary.md) (22 terms) · [`docs/data-dictionary.md`](docs/data-dictionary.md) (ACS, boundaries, DAS demo) · `requirements.txt` (**still not version-pinned** — see TODO).

**Local only (gitignored, regenerable by the scripts/notebooks above):**
- `data/raw/acs5_2024_nj_{county,tract,block_group}.parquet` — 21 / 2,181 / 6,599 rows
- `data/raw/geo_2024_nj_{county,tract,block_group}.parquet` + verification map
- `data/raw/das_demo/` — `nj2010.dhc.zip` (250 MB; 44 table segments + geo header, 2.0 GB uncompressed) + README, technical document, geoheader layout, table matrix
- `data/raw/sf1_2010_nj_{state,county,tract,block_group,block}.parquet` — 1 / 21 / 2,010 / 6,320 / 169,588 rows (published 2010 baseline)
- `data/processed/eda01…eda04 PNG charts` — seven mentor-slide candidates (flagship: `eda04_noise_rmse_by_size.png`)
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

## Next work, in priority order

1. **July 22 biweekly prep:** one slide — status, chart candidates (EDA 04 flagship `eda04_noise_rmse_by_size.png` + EDA 01 boxplot + EDA 03 map pair), and the mentor questions in the README (product shortlist, DAS vintage confirmation, 131-tract mystery, poverty/BG floor, **block-group anomaly**, **ε-vs-empirical for the score**).
2. **EDA #5 — allocation rates:** small new API pull; test whether allocation rates correlate with high-CV geographies (independence ⇒ empirical justification for a multi-component composite score). Completes the README Step 5 list.
3. `docs/uncertainty-sources.md` (README Step 2 writeup) — EDA 01–04 now provide the empirical content for all the major sources except imputation.
4. Pin package versions to a lockfile (reproducibility deliverable).
5. Complete `docs/data-dictionary.md` (DHC, Demographic Profile, PPMF entries) once mentors confirm the product shortlist.

## Environment gotchas

- Windows machine. Run scripts from the repo root with `.venv/Scripts/python.exe <script>`; execute notebooks with `.venv/Scripts/python.exe -m jupyter nbconvert --to notebook --execute --inplace <nb>`.
- **The parent folder `C:\Users\andre\Documents` contains a stray zero-commit git repo.** Never run git commands outside this repo without checking `git rev-parse --show-toplevel` first.
- **Git history was rewritten on 2026-07-09** to purge sponsor contact info from the public repo. Pre-rewrite SHAs are invalid; stale clones must not be pushed from. **Never re-add sponsor contact details to any committed file** — the repo is public.
- LF/CRLF warnings on commit are normal on this machine; ignore them.

## Working style (summary — full rules in CLAUDE.md)

Propose before coding; present options + recommendation before methodology choices and let the lead decide; stop and summarize at every checkpoint; flag surprising results immediately (characterize, don't guess at causes); plain English first, define every term, cite every formula; sanity-check every data pull before analyzing it; WORKLOG entry in the same commit as the work; never bluff — log unresolvable questions for the Census mentors in the README.
