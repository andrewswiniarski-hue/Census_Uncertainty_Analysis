# HANDOFF.md — Session Handoff Notes

**Written:** 2026-07-09 at project setup; **last updated 2026-07-15**, at the close of the first EDA session.
**For:** the next Claude session (or teammate) picking this work up cold.

---

## Read these first, in order

1. [`CLAUDE.md`](CLAUDE.md) — **how to work on this project.** Check-in-before-acting rules, communication standards, statistical rigor requirements. Non-negotiable; read every session.
2. [`README.md`](README.md) — project brief: research questions Q1–Q4, the three must-have deliverables, milestones, Phase 1 checklist, open mentor questions.
3. [`WORKLOG.md`](WORKLOG.md) — the team work log; live record of what's been done and found. Newest entries first.
4. [`docs/data-dictionary.md`](docs/data-dictionary.md) — before touching any dataset: what it is, what uncertainty ships with it, and its landmines.

## Where the project stands (2026-07-15)

- **The Phase 1 setup runbook (NEXT_ACTIONS.md, Steps 1–6) is complete.** Repo live, environment working, three scripted data pulls committed: ACS estimates+MOEs, matching boundaries, and the DAS demonstration file.
- **First-pass EDA (README Step 5 core) is done and committed:** three notebooks, four mentor-ready charts. Step 5's "done when" is satisfied; EDA #4 (privacy noise) and #5 (allocation rates) remain open — #4 is now unblocked.
- **The project is ACTIVE** — the lead gave the EDA go-ahead on 2026-07-15 (the pause noted in the original handoff is over).
- **First mentor biweekly: July 22, 2026.** Bring a one-slide status; chart candidates are ready (see below).
- Remote: <https://github.com/andrewswiniarski-hue/Census_Uncertainty_Analysis> (branch `main`). **Five commits are local-only, not pushed** (`537a66e` … housekeeping); `docs/team-recap-2026-07-12.pptx` is untracked pending the lead's call on committing binaries.

## What exists

**In the repo (committed):**
- [`ingestion/pull_acs_nj.py`](ingestion/pull_acs_nj.py) — ACS 5-year vintage 2024, NJ, county/tract/block group, estimates + MOEs, sanity-checked.
- [`ingestion/pull_nj_geometry.py`](ingestion/pull_nj_geometry.py) — vintage-matched boundaries (GeoParquet), 1:1 join verified.
- [`ingestion/pull_das_demo_nj.py`](ingestion/pull_das_demo_nj.py) — 2010 Demonstration Data Product–DHC (2022-08-25 release), NJ summary file + parsing docs; no API key needed.
- [`analysis/acs.py`](analysis/acs.py) — shared formulas with citations: CV, top-code flag, aggregate estimate/MOE (handbook zero-cell rule).
- Notebooks (each runs clean top-to-bottom; committed with outputs):
  [`01-cv-by-geography-size`](notebooks/01-cv-by-geography-size.ipynb) · [`02-cv-by-variable-type`](notebooks/02-cv-by-variable-type.ipynb) · [`03-cv-choropleth-nj-tracts`](notebooks/03-cv-choropleth-nj-tracts.ipynb)
- [`docs/glossary.md`](docs/glossary.md) (22 terms) · [`docs/data-dictionary.md`](docs/data-dictionary.md) (ACS, boundaries, DAS demo) · `requirements.txt` (**still not version-pinned** — see TODO).

**Local only (gitignored, regenerable by the scripts/notebooks above):**
- `data/raw/acs5_2024_nj_{county,tract,block_group}.parquet` — 21 / 2,181 / 6,599 rows
- `data/raw/geo_2024_nj_{county,tract,block_group}.parquet` + verification map
- `data/raw/das_demo/` — `nj2010.dhc.zip` (250 MB; 44 table segments + geo header, 2.0 GB uncompressed) + README, technical document, geoheader layout, table matrix
- `data/processed/eda01…eda03 PNG charts` — the four mentor-slide candidates
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

## Data landmines the next session must know

- **censusdis silently converts ACS annotation codes to NaN** — "controlled" (very reliable) and "insufficient sample" (unreliable) become identical blanks. `EA`/`MA` annotation variables can be pulled if the distinction becomes score-relevant.
- **Median income is top-coded at `250,001`**; every top-coded row also has a blank MOE. 41 tracts, 270 block groups in NJ.
- **131 NJ tracts (all 21 counties) have unexplained near-controlled population MOEs** (±14–143 vs. median ±546) — cause unknown, logged as a mentor question; don't guess. (Found in EDA 02.)
- **Poverty reliability is prevalence-capped**: CV-vs-size slope −0.18 (vs. −0.5 sampling law); poverty data is *most* reliable in high-poverty tracts (Spearman −0.58) and worst in affluent ones. (EDA 02/03.)
- **6 invalid geometries at tract and block group** — fine for plotting; `make_valid` before any area/overlay math.
- **The Census demonstration-products archive times out on directory listings (Cloudflare 524)** — deep-link to files directly, as `pull_das_demo_nj.py` does.
- **Demonstration data is for evaluating privacy noise only** — never analyze it as real 2010 populations.

## Next work, in priority order

1. **EDA #4 — privacy noise (now unblocked):** parse `nj2010.dhc.zip` (geo header + a few person segments) against published 2010 SF1 counts via the API; noise = demo − published, by geography size. Hypothesis to test: privacy noise has ~constant absolute scale, so relative error should fall with slope **−1** on the EDA 02 log-log chart (vs. −½ for sampling) — if confirmed, that's a flagship report chart. Label as hypothesis until tested.
2. **EDA #5 — allocation rates:** small new API pull; test whether allocation rates correlate with high-CV geographies (independence ⇒ empirical justification for a multi-component composite score).
3. **July 22 biweekly prep:** one slide — status, chart candidates (EDA 01 boxplot + EDA 03 map pair; EDA 02 mechanism scatter as methods backup), and the mentor questions in the README (product shortlist, DAS vintage confirmation, 131-tract mystery, poverty/BG floor).
4. `docs/uncertainty-sources.md` (README Step 2 writeup).
5. Pin package versions to a lockfile (reproducibility deliverable).
6. Complete `docs/data-dictionary.md` (DHC, Demographic Profile, PPMF entries) once mentors confirm the product shortlist.

## Environment gotchas

- Windows machine. Run scripts from the repo root with `.venv/Scripts/python.exe <script>`; execute notebooks with `.venv/Scripts/python.exe -m jupyter nbconvert --to notebook --execute --inplace <nb>`.
- **The parent folder `C:\Users\andre\Documents` contains a stray zero-commit git repo.** Never run git commands outside this repo without checking `git rev-parse --show-toplevel` first.
- **Git history was rewritten on 2026-07-09** to purge sponsor contact info from the public repo. Pre-rewrite SHAs are invalid; stale clones must not be pushed from. **Never re-add sponsor contact details to any committed file** — the repo is public.
- LF/CRLF warnings on commit are normal on this machine; ignore them.

## Working style (summary — full rules in CLAUDE.md)

Propose before coding; present options + recommendation before methodology choices and let the lead decide; stop and summarize at every checkpoint; flag surprising results immediately (characterize, don't guess at causes); plain English first, define every term, cite every formula; sanity-check every data pull before analyzing it; WORKLOG entry in the same commit as the work; never bluff — log unresolvable questions for the Census mentors in the README.
