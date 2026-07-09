# HANDOFF.md — Session Handoff Notes

**Written:** 2026-07-09, at the close of the project setup session.
**For:** the next Claude session (or teammate) picking this work up cold.

---

## Read these first, in order

1. [`CLAUDE.md`](CLAUDE.md) — **how to work on this project.** Check-in-before-acting rules, communication standards, statistical rigor requirements. Non-negotiable; read every session.
2. [`README.md`](README.md) — project brief: research questions Q1–Q4, the three must-have deliverables, milestones, Phase 1 checklist, open mentor questions.
3. [`NEXT_ACTIONS.md`](NEXT_ACTIONS.md) — the Phase 1 setup runbook. Steps 1–5 are checked off, with findings noted inline.

## Where the project stands

- **Steps 1–5 of the runbook are complete:** GitHub repo live, API key verified, Python environment working, repo scaffolded, ACS data pull scripted + sanity-checked, matching geometries scripted + join-verified.
- **The project is PAUSED at the lead's request:** teammates are reviewing the repo before EDA begins. **Do not start EDA (or any new work) without the lead's explicit go-ahead** — that's also the standing rule in CLAUDE.md.
- Remote: <https://github.com/andrewswiniarski-hue/Census_Uncertainty_Analysis> (branch `main`). Everything is committed and pushed; working tree clean at handoff.

## What exists

**In the repo (committed):**
- [`ingestion/pull_acs_nj.py`](ingestion/pull_acs_nj.py) — ACS 5-year vintage 2024, NJ, county/tract/block group, estimates + MOEs. Verifies official variable labels at runtime, hard-checks 21 NJ counties, detects annotation codes, prints per-column sanity report.
- [`ingestion/pull_nj_geometry.py`](ingestion/pull_nj_geometry.py) — matching boundaries (GeoParquet, vintage-matched), verifies a 1:1 join against the data files, renders a verification map.
- [`docs/glossary.md`](docs/glossary.md) — 18 terms, plain-English first. Every new statistical term gets added here on first use.
- `requirements.txt` (top-level deps, **not yet version-pinned** — see TODO), `.env.example`, folder READMEs throughout.

**Local only (gitignored, regenerable by the scripts above):**
- `data/raw/acs5_2024_nj_{county,tract,block_group}.parquet` — 21 / 2,181 / 6,599 rows
- `data/raw/geo_2024_nj_{county,tract,block_group}.parquet` + `verification_map_nj_tracts.png`
- `.env` with a working `CENSUS_API_KEY`
- `.venv` — Python 3.12.10; pandas 2.3.3, geopandas 1.0.1, censusdis 1.4.2, pyarrow 18.1.0, matplotlib 3.11.0

## Decisions already made (by the project lead — don't relitigate)

1. **Vintage 2024** (2020–2024 ACS 5-year, newest available).
2. **Tract is the floor for poverty/subgroup analysis.** B17001 (poverty) and B01001B (race×age) are not published below tract — verified empirically (API returns HTTP 204). The C17002 block-group alternative is logged as a mentor question in the README.
3. **Small subgroup = six raw B01001B 65+ cells** (male/female × 65–74, 75–84, 85+), pulled raw in the same call. Analyze single cells first; combining the six MOEs into one 65+ MOE (root-sum-of-squares) is deferred to a documented analysis step.
4. **`data/raw/` stays exactly as the API returned it.** All cleaning (annotation handling, geometry fixes, renames) belongs in a processing layer, which does not exist yet.

## Data landmines the next session must know

- **censusdis silently converts ACS annotation codes to NaN.** The raw API returns codes like `-555555555` (controlled estimate — *very reliable*) and `-666666666` (insufficient sample — *unreliable*); by the time censusdis hands over the dataframe, both are blank. Opposite meanings, identical NaN. If the distinction matters for the composite score, the API offers annotation variables (`EA`/`MA` suffixes) that can be added to the pull.
- **Median income is top-coded at `250,001`** (= "above $250k"). Several NJ tracts sit at the cap; their MOEs may also be blank.
- **6 invalid geometries at tract level and 6 at block group** (self-intersection quirks). Harmless for choropleths; run `make_valid` in the processing layer before any area/overlay math.
- **CV formula in use:** `CV = (MOE / 1.645) / estimate` — ACS MOEs are published at 90% confidence, 1.645 converts MOE to standard error. Cite ACS "Accuracy of the Data" documentation.

## Next work, in priority order

1. **(Blocked on lead's go-ahead after team review)** EDA notebook #1: **CV by geography size** — CV distributions at county vs. tract vs. block group. This is the project's central empirical chart and the first biweekly deliverable. All data it needs is on disk. Preview of the punchline: worst county income MOE ±$3,982 vs. worst block group ±$247,531.
2. EDA #2 (CV by variable type) and EDA #3 (tract-level CV choropleth — geometries are ready and join-verified).
3. Runbook Step 6: locate + download a DAS demonstration file (privacy noise data). Only blocks EDA #4; the "which vintage?" mentor question is already logged in the README.
4. Draft `docs/uncertainty-sources.md` (README Phase 1, Step 2 writeup).
5. Pin package versions to a lockfile once the pipeline stabilizes (reproducibility deliverable).
6. Build `docs/data-dictionary.md` (README Step 4) — the landmines above are its first entries.

## Environment gotchas

- Windows machine. Run scripts from the repo root with `.venv/Scripts/python.exe <script>`.
- **The parent folder `C:\Users\andre\Documents` contains a stray zero-commit git repo.** Never run git commands outside this repo without checking `git rev-parse --show-toplevel` first.
- **Git history was rewritten on 2026-07-09** to purge sponsor contact info from the public repo. Any commit SHAs recorded before that date are invalid, and stale clones from before the rewrite must not be pushed from. **Do not re-add sponsor contact details to any committed file** — the repo is public.
- LF/CRLF warnings on commit are normal on this machine; ignore them.

## Working style (summary — full rules in CLAUDE.md)

Propose before coding; present options + recommendation before methodology choices and let the lead decide; stop and summarize at every checkpoint; flag surprising results immediately; plain English first, define every term, cite every formula; sanity-check every data pull before analyzing it; never bluff — log unresolvable questions for the Census mentors in the README.
