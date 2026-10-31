# /notebooks — exploratory analysis (EDA)

One notebook per question, named so the question is obvious from the filename
(e.g., `01-cv-by-geography-size.ipynb`). Ground rules:

- Every notebook runs top-to-bottom cleanly after **Restart & Run All**
- Markdown commentary explains findings in plain English as you go
- Reusable logic graduates to [`/analysis`](../analysis); notebooks stay thin
- Define every statistical term on first use, and add it to
  [`/docs/glossary.md`](../docs/glossary.md)

**Before running a notebook, download its data** with the scripts in the last
column (from the repo root, e.g. `python ingestion/pull_acs_nj.py`; a Census API
key in `.env` is needed for every script except the DAS demonstration download).
The notebooks use New Jersey research data, which is not committed; only the
dashboard's data is. Each notebook is committed with its outputs, so it can be
read without running it.

| Notebook | Question | Data it needs (`ingestion/` scripts) |
|----------|----------|--------------------------------------|
| `01` | Sampling CV by geography size | `pull_acs_nj.py` |
| `02` | Sampling CV by variable type | `pull_acs_nj.py` |
| `03` | Where unreliability concentrates: NJ tract choropleths | `pull_acs_nj.py`, `pull_nj_geometry.py` |
| `04` | Privacy noise (2010 DAS demonstration vs published SF1) | `pull_das_demo_nj.py`, `pull_sf1_2010_nj.py` |
| `05` | Allocation (imputation) rates vs CV: are they independent? | `pull_acs_nj.py`, `pull_acs_alloc_nj.py` |
| `06` | ACS composite prototype (CV × allocation matrix) + CV driver model (place pop vs estimate size, matched bins) — merged 2026-07-31 from the original separate 06/07 notebooks | `pull_acs_nj.py`, `pull_acs_alloc_nj.py`, `pull_nj_geometry.py` |
| `07` | SAIPE vs. ACS intervals for NJ counties, 2019–2024 — the Bureau's two published uncertainty styles compared ("EDA 10" in older documents; renumbered 2026-10-31 because the DHC notebook below also used 10) | `pull_acs_income_county_nj.py`, `pull_saipe_nj.py` |
| `08` | Allocation-denominator sensitivity (Garrett) | `pull_pums_alloc_flags.py` |
| `09` | Who gets inferred: person-level PUMS allocation profile (Garrett) | `pull_pums_alloc_flags.py` |
| `10`–`12` | Phase B: 2020 DHC/DP1 modeled noise by size, variable type, and geography — mirrors `01`–`03`, no composite score | `pull_dhc_nj.py`, `pull_dp_nj.py` (10), `pull_nj_geometry.py` (12) |
| `13` | SAIPE vs. ACS for the same variable, Mercer County — model error vs. sampling error, direct comparison (Q3) | `pull_saipe_counties.py`, `pull_trenton_dashboard.py` |
| `14` | ACS-wide error-bar survey: a 100-table sample at every U.S. county — what share can carry an error bar, CV by table family, the size law at national scale | `pull_acs_wide_us_county.py`, `pull_acs_nj.py`, `pull_acs_income_county_nj.py` |
