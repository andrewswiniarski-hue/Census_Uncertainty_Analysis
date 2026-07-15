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

### 2026-07-14 — Katie Christiansen — US boundary pull & exploration
- **Area:** ingestion
- **What was done:** Wrote and ran [ingestion/pull_acs_us.py](ingestion/pull_acs_us.py) — pulls 2024 ACS 5-year estimates and matching cartographic boundaries for all US states and counties. The script saves separate ACS Parquet and GeoParquet files, verifies a 1:1 join on Census geography IDs, and renders a nationwide county verification map. Added [Explore.py](Explore.py) to join the national county data to its geometry and save a median-household-income map. This is very similar to Andrew's NJ analysis, but at a US level. 
- **Findings / decisions:** National analysis is limited to state and county levels for now because nationwide tract and block-group geometry is substantially larger and slower to manage. Estimates include 90% margin-of-error columns.
- **Files:** ingestion/pull_acs_us.py; Explore.py; outputs `data/raw/acs5_2024_us_*.parquet`, `data/raw/geo_2024_us_*.parquet`, `data/raw/verification_map_us_counties.png`, and `data/raw/us_county_median_household_income.png` (local only, regenerable). I uploaded these files manually for now, so if the above hyperlinks do not work, they are both in the ingestion folder. 

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
