# WORKLOG.md — Team Work Log

A running record of the work done on this project: **who did it, when, and what came of it.** Newest entries go at the top.

**Why we keep this:** with the whole team working in one repo, this file is how we stay aware of each other's progress without reading every commit. It is also part of our defensibility story — when we assemble the final report and present to Census mentors, this is the paper trail of what was done, by whom, and what was found along the way.

---

## How to add an entry

When you finish a piece of work — a script, an analysis, a notebook, a document, a meeting deliverable — copy the template below to the **top of the Log section** (newest first) and fill it in. One entry per completed chunk of work; tiny fixes (typos, formatting) don't need one.

```markdown
### YYYY-MM-DD — Your Name — Short title of the work
- **Area:** ingestion | analysis | notebooks | docs | dashboard | project management
- **What was done:** 2–4 plain-English sentences a teammate on another workstream can follow.
- **Findings / decisions:** anything learned, decided, or surprising — data quirks especially. ("None" is fine.)
- **Files:** paths, notebook names, and/or commit hashes.
```

Ground rules:

- **Plain English first.** Write the summary so a teammate who wasn't there understands it without opening the code.
- **Surprises go here.** A weird distribution, an impossible value, a data quirk — log it even if it feels minor. (Also raise it with the team; see the "Data landmines" list in [HANDOFF.md](HANDOFF.md).)
- **Update the log in the same commit as the work** whenever possible, so the log and the repo never drift apart.
- New statistical terms still get defined in [docs/glossary.md](docs/glossary.md) — the log links to work, the glossary explains terms.

---

## Log

### 2026-07-15 — Andrew Swiniarski — Housekeeping: progress-tracking docs synced to end of first EDA session
- **Area:** docs / project management
- **What was done:** Rewrote [HANDOFF.md](HANDOFF.md) to the current state (runbook complete, EDA 01–03 done, DAS file on disk, decisions 4–9 and new landmines recorded, next-work list refreshed — the stale "project is PAUSED" language is gone). Ticked README's Step 5 "done when" and noted Step 4 as started; refreshed the docs/README status table; extended CLAUDE.md's session reading list to include WORKLOG.md and HANDOFF.md.
- **Findings / decisions:** None — bookkeeping.
- **Files:** HANDOFF.md, README.md, docs/README.md, CLAUDE.md, WORKLOG.md

### 2026-07-15 — Andrew Swiniarski — DAS demonstration data located + downloaded; data dictionary started (runbook Step 6)
- **Area:** ingestion / docs
- **What was done:** Surveyed the Census Bureau's 2010 Demonstration Data Products archive (all five product folders), picked a provisional release, and scripted the download: [ingestion/pull_das_demo_nj.py](ingestion/pull_das_demo_nj.py) pulls the New Jersey summary file from the **2022-08-25 DHC demonstration release** (nj2010.dhc.zip, 250 MB, integrity-verified: 44 table segments + geo header, 2.0 GB uncompressed) plus the four companion docs needed to parse it (README, technical document, state geoheader layout, table matrix) into `data/raw/das_demo/`. Started [docs/data-dictionary.md](docs/data-dictionary.md) (README Step 4) with ACS, boundary, and DAS-demo entries. This closes the NEXT_ACTIONS runbook (Steps 1–6 all done).
- **Findings / decisions:** Provisional vintage choice (mentor question updated in README): **2022-08-25** is the newest *tabulated* demonstration release and nearest to DHC production settings — the 2023-04-03 production suite ships only national microdata (15 GB + 9.4 GB CSVs, impractical) and the 2022-03-16 tabulated release has an April 2022 technical-issues ALERT in its folder, so it was skipped. Gotcha for teammates: the archive's directory-index pages frequently time out (Cloudflare 524) — deep-link to files directly, as the script does. Baseline for the noise comparison (EDA #4) will be published 2010 SF1 tables via the API.
- **Files:** ingestion/pull_das_demo_nj.py, docs/data-dictionary.md, README.md (Step 3 checkboxes, vintage mentor question), NEXT_ACTIONS.md (Step 6 closed); data in data/raw/das_demo/ (local-only, regenerable)

### 2026-07-15 — Andrew Swiniarski — EDA 03: tract-level reliability choropleth, dashboard prototype (Phase 1, Step 5)
- **Area:** notebooks
- **What was done:** Third EDA notebook, [notebooks/03-cv-choropleth-nj-tracts.ipynb](notebooks/03-cv-choropleth-nj-tracts.ipynb): joins tract CVs to the vintage-matched boundaries (1:1 join re-asserted in-notebook), bins them into reference reliability tiers (ESRI/NCHS conventions, shown descriptively), and renders a side-by-side choropleth of median household income vs. poverty — a crude prototype of the executive-dashboard map (deliverable #3). Gray "no usable estimate" rendered as its own first-class category. Verified top-to-bottom with `jupyter nbconvert --execute`.
- **Findings / decisions:** (1) **Not one of NJ's 2,181 tracts reaches the high-reliability tier for poverty** (income: 44% do; 92% of tracts are below CV 0.30 for income vs. 21% for poverty); (2) **poverty-data reliability maps as the inverse of poverty itself** — Spearman −0.58 between poverty rate and poverty CV; median CV 0.31 in the poorest quartile of tracts vs. 0.49 in the least-poor quartile. Urban cores (Newark, Camden, Trenton, Atlantic City) are the *most* reliable places for poverty data; affluent/suburban tracts the least — an equity-relevant blind spot for anyone tracking suburbanizing poverty. (3) Classed tiers + explicit gray class communicate at a glance; carried forward as dashboard design seeds. Phase 1 Step 5's "done when" (notebooks committed, 2–3 mentor-ready charts) is now satisfied.
- **Files:** notebooks/03-cv-choropleth-nj-tracts.ipynb, docs/glossary.md (choropleth entry), README.md (Step 5 checkbox); map at data/processed/eda03_cv_choropleth_income_poverty.png (local-only, regenerable)

### 2026-07-15 — Andrew Swiniarski — EDA 02: CV by variable type + first derived estimate (Phase 1, Step 5)
- **Area:** notebooks / analysis
- **What was done:** Second EDA notebook, [notebooks/02-cv-by-variable-type.ipynb](notebooks/02-cv-by-variable-type.ipynb): at tract level, compares CV distributions across variable types, builds the project's first **derived estimate** (Black 65+ = six sex×age cells summed, MOE via the Census handbook's root-sum-of-squares formula with the zero-cell rule, sensitivity vs. plain RSS shown), and tests the mechanism with a CV-vs-estimate-size log-log scatter against the theoretical −½ sampling-noise slope. Extended [analysis/acs.py](analysis/acs.py) with `aggregate_estimate` and a zero-rule `aggregate_moe`. Verified top-to-bottom with `jupyter nbconvert --execute`.
- **Findings / decisions:** (1) **The sampling-noise law holds for size-driven counts** — fitted log-log slopes: population −0.47, Black 65+ aggregate −0.51, vs. theoretical −0.50; (2) **poverty defies it (slope −0.18)** — bigger poverty counts mean poorer tracts, not bigger samples, so its reliability is capped by prevalence (explains EDA 01's "80% of tracts unreliable" shocker); (3) **aggregation helps but doesn't rescue subgroups**: median CV 0.886 → 0.631 (1.4×) and coverage 11–50% → 73% of tracts, yet 87% of nonzero tracts stay above CV 0.30; (4) the handbook zero-cell rule trims a median 10% (max 55%) off plain-RSS MOEs — adopted as default, documented in glossary; (5) **surprise, unexplained: 131 tracts (all 21 counties) publish population MOEs of ±14–143 vs. median ±546** — near-controlled precision with a published MOE; cause unknown, logged as a mentor question rather than guessed at. Composite-score implications: estimate magnitude is a strong free predictor for counts, but variable type must be its own component.
- **Files:** analysis/acs.py, notebooks/02-cv-by-variable-type.ipynb, docs/glossary.md (derived estimate, MOE aggregation entries), README.md (Step 5 checkbox, new mentor question); charts at data/processed/eda02_*.png (local-only, regenerable)

### 2026-07-15 — Andrew Swiniarski — EDA 01: CV by geography size (Phase 1, Step 5)
- **Area:** notebooks / analysis
- **What was done:** First EDA notebook, [notebooks/01-cv-by-geography-size.ipynb](notebooks/01-cv-by-geography-size.ipynb): runs a data-quality panel on the NJ pull, computes coefficients of variation for every variable at county / tract / block group, and produces the headline mentor chart (income CV by geography level, log scale, with ESRI/NCHS reference lines shown descriptively). Shared formulas graduated to a new reusable module, [analysis/acs.py](analysis/acs.py) (CV, top-code flag, root-sum-of-squares MOE aggregation — each with its Census citation), so every later notebook computes them identically. Verified top-to-bottom with `jupyter nbconvert --execute`.
- **Findings / decisions:** Central empirical fact confirmed: median income CV **0.014 (county) → 0.128 (tract) → 0.204 (block group)**; worst-case income MOE ±$3,982 → ±$247,531. Surprises worth flagging: (1) **tract-level poverty exceeds CV 0.30 in 80% of NJ tracts** — a policy-critical variable is low-reliability almost everywhere planners would use it; (2) Black 65+ single cells are effectively noise at tract level (median CV ≈ 0.9) and are zero in 50–89% of tracts — supports aggregating the six cells in EDA 02; (3) every top-coded income (41 tracts, 270 block groups) ships with **no MOE at all**, and 2 non-top-coded block groups also lack income MOEs (unexplained annotation — logged for the data dictionary); (4) county population MOEs are all blank because the estimates are *controlled* (very reliable) — the "two opposite meanings of a missing MOE" landmine seen live. Decisions per the approved EDA plan: zero estimates → CV undefined; top-coded incomes excluded from CV distributions; thresholds 0.12/0.30/0.40 cited descriptively only (our tiers = later mentor decision).
- **Files:** analysis/acs.py, notebooks/01-cv-by-geography-size.ipynb, docs/glossary.md (reliability-threshold conventions entry), README.md (Step 5 checkbox); chart at data/processed/eda01_income_cv_by_geography.png (local-only, regenerable)

### 2026-07-12 — Andrew Swiniarski — Team sync recap deck; work log started
- **Area:** project management / docs
- **What was done:** Built the recap deck for the July 12 team sync ([docs/team-recap-2026-07-12.pptx](docs/team-recap-2026-07-12.pptx)) covering setup status, the NJ pilot dataset, the headline finding (uncertainty explodes at small geographies), documented data landmines, and the 10-minute teammate onboarding path. Created this work log; teammates begin working in the repo from this point.
- **Findings / decisions:** First mentor meeting set for **July 22, 2026** — we bring a one-slide status and the CV-by-geography chart. Open items from the sync: workstream assignments (analysis / dashboard / methodology write-up / data hunting), repo-review feedback, confirming the recurring biweekly slot.
- **Files:** docs/team-recap-2026-07-12.pptx, WORKLOG.md

### 2026-07-09 — Andrew Swiniarski — NJ boundary pull + 1:1 join verification (Phase 1, Step 5)
- **Area:** ingestion
- **What was done:** Wrote and ran [ingestion/pull_nj_geometry.py](ingestion/pull_nj_geometry.py) — pulls NJ county/tract/block group cartographic boundaries (vintage-matched to the 2024 ACS data), saves GeoParquet to `data/raw/`, verifies every data row joins to exactly one shape at all three levels, and renders a verification map of all 2,181 tracts.
- **Findings / decisions:** Join checks passed 1:1 at every level. **6 invalid geometries at tract level and 6 at block group** (self-intersection quirks) — harmless for choropleths, but `make_valid` must run in the future processing layer before any area/overlay math.
- **Files:** ingestion/pull_nj_geometry.py (commit e7895a5); outputs `data/raw/geo_2024_nj_*.parquet` + `verification_map_nj_tracts.png` (local only, regenerable)

### 2026-07-09 — Andrew Swiniarski — ACS 5-year NJ data pull with MOEs (Phase 1, Step 4)
- **Area:** ingestion
- **What was done:** Wrote and ran [ingestion/pull_acs_nj.py](ingestion/pull_acs_nj.py) — ACS 5-year vintage 2024, New Jersey, at county / tract / block group: total population, median household income, poverty count, and six Black 65+ subgroup cells, each with its margin of error. Verifies official variable labels at runtime, hard-checks the 21-county count, and prints a per-column sanity report. Row counts: 21 counties / 2,181 tracts / 6,599 block groups.
- **Findings / decisions:** Three data landmines found and documented: (1) poverty (B17001) and race×age (B01001B) tables are **not published below tract level** — tract confirmed as the floor, mentor question logged; (2) **censusdis converts ACS annotation codes to NaN**, collapsing "controlled/very reliable" and "insufficient sample/unreliable" into identical blanks; (3) **median income is top-coded at $250,001**. Decision: `data/raw/` stays exactly as the API returned it; all cleaning belongs in a future processing layer.
- **Files:** ingestion/pull_acs_nj.py (commit 3e0cb91); outputs `data/raw/acs5_2024_nj_*.parquet` (local only, regenerable); landmines detailed in [HANDOFF.md](HANDOFF.md)

### 2026-07-09 — Andrew Swiniarski — Repo, environment, and secrets setup (Phase 1, Steps 1–3)
- **Area:** infrastructure
- **What was done:** Initialized the repo and pushed to GitHub; scaffolded the folder structure (`/ingestion`, `/notebooks`, `/analysis`, `/docs`, `/data`) with per-folder READMEs; set up `.gitignore` (raw data + secrets excluded), the `.env` API-key pattern with a committed `.env.example`, `requirements.txt`, and a Python 3.12 virtual environment. Census API key verified with a live call. Added the "Getting Started" quickstart to the README and seeded [docs/glossary.md](docs/glossary.md) (18 terms).
- **Findings / decisions:** Git history was **rewritten on 2026-07-09** to purge sponsor contact details (the repo is public) — commit SHAs from before that date are invalid, and stale clones must not be pushed from. Never re-add sponsor contact info to committed files. Session handoff notes written to [HANDOFF.md](HANDOFF.md).
- **Files:** commits 9d11afb → bcc1c5c; requirements.txt, .env.example, .gitignore, HANDOFF.md, docs/glossary.md
