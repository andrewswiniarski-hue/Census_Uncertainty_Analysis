# Data Dictionary — Census Uncertainty Analytics

Catalog of every statistical product this project uses: what it is, which
geographies it covers, **what uncertainty measure ships with it**, how we access
it, and the landmines we've hit. One entry per product; newest additions at the
bottom. (README Phase 1, Step 4 — living document. Scoped income & poverty
set completed 2026-08-01 — SAIPE, PUMS, and Variance Replicate Tables added
per the product-shortlist sprint; DHC and Demographic Profile entries deferred
unless mentors want the wider catalog documented.)

---

## ACS 5-year estimates (2020–2024, vintage 2024)

- **What:** American Community Survey pooled 5-year sample estimates — income,
  poverty, demographics, housing. Our primary Phase 1 product.
- **Geographies used:** county (21) / tract (2,181) / block group (6,599), NJ.
  **Floors vary by table:** B17001 (poverty) and B01001B (race×age) stop at
  tract; B01003/B19013 go to block group.
- **Uncertainty shipped:** **MOE at 90% confidence on every estimate** (`_M`
  columns via API). CV computable as `(MOE/1.645)/estimate`.
- **Update cadence:** annual releases (new 5-year window each year).
- **Access:** Census API via censusdis — [`ingestion/pull_acs_nj.py`](../ingestion/pull_acs_nj.py);
  raw parquet in `data/raw/` (gitignored, regenerable).
- **Landmines:** annotation codes arrive as NaN via censusdis, erasing the
  controlled-vs-insufficient-sample distinction (in raw API responses they are
  jam values — `-666666666` estimate / `-222222222` MOE, seen live at Mercer
  tract 1 BG 1, 2026-08-01); median income top-coded at
  $250,001 with **no MOE published for top-coded rows**; county total population
  is controlled (no MOE, extremely reliable); 131 NJ tracts show unexplained
  near-controlled population MOEs (mentor question); 2 block groups have income
  estimates but no MOE for unknown reasons; **the 2024 `variables.json`
  metadata census lists no `M` variables at all** (0 of 28,475 names match the
  `_NNNM` MOE pattern) even though every MOE variable is individually
  resolvable and queryable (verified 2026-08-01:
  `variables/B19013_001M.json` → HTTP 200 with proper label; block-group data
  query returns MOE values) — any tool inventorying uncertainty from
  `variables.json` alone will wrongly conclude ACS ships no MOEs (the Product
  Scope Tracker's probe currently prints exactly that; flagged for Garrett —
  the probe code is fine, the metadata is incomplete).

### ACS allocation (imputation) tables — sub-entry (added 2026-07-17, EDA 05)

- **What:** The ACS's own measure of imputation: for each subject, how many
  values were **allocated** (statistically filled in) rather than reported.
  Tables used: `B98031`/`B98032` (overall person / housing-unit allocation
  rate, published as a percent), `B99011`/`B99012`/`B99021` (sex/age/race:
  Total / Allocated / Not allocated), `B99192` (household income:
  percent-of-income-allocated bins; any-income-imputed rate =
  `1 − _002/_001`), `B99172` (poverty status for **families** — universe
  does NOT match person-level B17001; used only as a labeled proxy).
- **Uncertainty shipped:** **none — allocation tables publish no MOE
  variables at all (E-only).** An allocation rate is a covariate describing
  data completeness, not a CV-bearing estimate. Requesting a `_M` column
  errors the whole API query — the pull script downloads estimates only.
- **Geographies:** item tables (B99xxx) fully populated at county, tract,
  AND block group (deeper than B17001/B01001B, which stop at tract).
  **Landmine: B98031/B98032 are county-only** — the API returns tract/BG
  rows but every value is null. (Probe lesson: a query returning rows does
  not mean it returns values.)
- **Access:** [`ingestion/pull_acs_alloc_nj.py`](../ingestion/pull_acs_alloc_nj.py)
  → `data/raw/acs5_2024_nj_alloc_{county,tract,block_group}.parquet`
  (gitignored, regenerable). Cell labels verified live at run time.
- **Key EDA 05 facts:** ~39% of households at the median NJ tract had some
  income imputed vs. <1% for age/race and ~0.05% for sex; allocation rates
  are independent of CVs once geography size is controlled (all controlled
  Spearman ρ in [−0.00, +0.19]) — the empirical justification for a
  multi-component composite score.
- **Scope addendum (2026-08-01):** five further income-**intensity** tables
  exist — B99191/B99192/B99193/B99194/B99201, 8 cells each
  (percent-of-income-allocated bins, split by **universe rather than income
  source**) — discovered by concept filter and geography-probed at
  county/tract/BG on `origin/garrett/financial-eda-imputation`
  (`docs/api-surface-verified.md`, pending merge). Same E-only rule applies.
  Companion decision from that branch's EDA 08: **never quote a bare
  allocation rate** — across eight defensible denominators, income sources
  rank anywhere from 1st to 6th.

## Cartographic boundary files (vintage 2024)

- **What:** Generalized TIGER/Line-derived boundaries for mapping.
- **Geographies used:** NJ county / tract / block group; 1:1 join to ACS data
  verified on STATE/COUNTY/TRACT(/BLOCK_GROUP).
- **Uncertainty shipped:** none (boundaries, not estimates).
- **Access:** censusdis `with_geometry=True` — [`ingestion/pull_nj_geometry.py`](../ingestion/pull_nj_geometry.py);
  GeoParquet in `data/raw/`.
- **Landmines:** 6 invalid geometries at tract and 6 at block group
  (self-intersections) — harmless for plotting, run `make_valid` before any
  area/overlay math.

## 2010 Demonstration Data Product — DHC (release 2022-08-25) — *privacy-noise data*

- **What:** Confidential 2010 Census data re-tabulated after passing through the
  2020 Disclosure Avoidance System (TopDown Algorithm) at near-production DHC
  settings. Comparing these tables against the *published* 2010 counts is the
  only public way to observe DAS privacy noise empirically (EDA #4).
- **Why this release (provisional, mentor question logged):** newest *tabulated*
  demonstration product; the later 2023-04-03 production-settings suite ships
  only national person/unit microdata (15 GB + 9.4 GB CSVs) and noisy
  measurement files. The earlier 2022-03-16 tabulated release carries an April
  2022 technical-issues ALERT, so we skip it.
- **Geographies:** SF1-style summary levels down to block (state file); see
  `Table_Matrix.xlsx` and the summary-level hierarchy charts for what exists
  per table.
- **Uncertainty shipped:** none per cell — the noise is *in* the numbers; its
  distribution is described in the release documentation (privacy-loss budget
  allocations PDF).
- **Format:** zipped segmented flat files in the 2010 SF1/DHC summary-file
  layout — verified contents: 44 table segments (`nj00001…nj00044 2010.dhc`)
  plus a geo-header file (`njgeo2010.dhc`), 2.0 GB uncompressed; parse with the
  geoheader + technical document layouts.
- **Access:** plain HTTPS from the Census FTP archive —
  [`ingestion/pull_das_demo_nj.py`](../ingestion/pull_das_demo_nj.py) downloads
  `nj2010.dhc.zip` (250 MB, integrity-checked) plus README, technical document,
  state geoheader layout, and table matrix into `data/raw/das_demo/`
  (gitignored, regenerable).
  Source directory:
  `www2.census.gov/programs-surveys/decennial/2020/program-management/data-product-planning/2010-demonstration-data-products/02-Demographic_and_Housing_Characteristics/2022-08-25_Summary_File/`
- **Baseline for comparison:** published 2010 Census SF1 tables via
  [`ingestion/pull_sf1_2010_nj.py`](../ingestion/pull_sf1_2010_nj.py) (entry
  below) — the demo minus published difference *is* the privacy noise (plus
  residual swapping in the baseline; see that entry).
- **Parsing:** [`analysis/dhc.py`](../analysis/dhc.py) reads the geo header and
  table segments straight from the zip (never extracted) and proves the parse
  at runtime: state-invariant check (demo NJ total must equal 8,791,894
  exactly), P1 vs. geo-header POP100 on every record, and P12B internal
  additivity on all 219,847 records. Used by
  [`notebooks/04-privacy-noise-das-demo.ipynb`](../notebooks/04-privacy-noise-das-demo.ipynb).
- **Landmines:** demonstration data are for evaluation only, **never for actual
  analysis of 2010 populations**; noise levels reflect the 2022-08-25 settings,
  not necessarily the final 2020 production settings (close, but confirm with
  mentors); the numeric privacy-loss-budget allocations live in a **separate
  allocations file we have not downloaded** (extend the pull script if it
  becomes score-relevant); noise scale is **level-dependent, not just
  size-dependent** — NJ block groups carry ~9× the absolute total-population
  noise of tracts (EDA 04 finding, mentor question logged); the Bureau's own
  index pages for this directory time out (Cloudflare 524) — deep-link
  directly to files, as the pull script does.

## 2010 Census Summary File 1 (SF1) — published baseline for privacy-noise work

- **What:** The actually-published 2010 Decennial counts — a full count of every
  resident (no sampling). Used in this project **only** as the baseline the
  demonstration data is differenced against (EDA #4); the same twelve P12B
  sex×age cells as the ACS pull give the Black 65+ subgroup parallel.
- **Geographies used:** NJ state (1) / county (21) / tract (2,010) / block
  group (6,320) / block (169,588) — 2010 geography vintage, which matches the
  demonstration file 1:1 but must **never be row-joined to 2024 ACS
  geographies** (tract/BG boundaries changed).
- **Uncertainty shipped:** none — no MOEs (full count, no sampling error). Its
  uncertainty is *coverage error* plus the 2010-era disclosure avoidance:
  **record swapping is baked into the published values**, which is exactly why
  demo − published = DAS noise + residual swapping, never pure DAS noise.
- **Update cadence:** none — 2010 is final.
- **Access:** Census API dataset `dec/sf1`, vintage 2010, via censusdis —
  [`ingestion/pull_sf1_2010_nj.py`](../ingestion/pull_sf1_2010_nj.py) (block
  and block-group queries run county-by-county; the API wants a containing
  county for small-area requests). Raw parquet in `data/raw/sf1_2010_nj_*.parquet`
  (gitignored, regenerable). All 10 sanity checks pass, including full-count
  additivity: every level sums to exactly 8,791,894.
- **Landmines:** per the raw-stays-raw convention the parquets keep the API's
  string values — coerce numerics in the analysis layer (notebook 04's
  `load_sf1` does); variable codes use the `P001001`/`P012B020` convention
  (verified live against the API, 2026-07-16 — note `PCT012B020` also exists
  and is a *different* table); 30% of NJ blocks have zero published population,
  so relative-error metrics must exclude/report them separately.

## SAIPE — Small Area Income & Poverty Estimates (API years 2019–2024) — *scoped-stack comparator* (added 2026-08-01)

- **What:** The Bureau's **model-based** annual estimates of median household
  income and poverty (counts and rates, for all ages / 0–17 / 0–4 / related
  children 5–17) at state, county, and school-district level — ACS data
  combined with administrative records and population estimates in a
  small-area model. In this project: the **comparator/precedent product** —
  the Bureau already ships uncertainty with these income/poverty numbers,
  which is what our tool wants to do for ACS estimates.
- **Geographies:** us / state / county via API `timeseries/poverty/saipe`
  (51 variables, probe 2026-08-01); school districts (elementary / secondary /
  unified) via `timeseries/poverty/saipe/schdist` (12 variables).
- **Uncertainty shipped:** **point estimate + 90% CI bounds + MOE on every
  measure** — 40 `SAEMHI*`/`SAEPOV*` variables (each measure ×
  `_PT/_LB90/_UB90/_MOE`), verified live 2026-08-01. Receipt (`time=2024`):
  Bergen County NJ median HH income **$121,894 ± $2,571** (90% CI
  $119,323–$124,465), poverty rate 6.7 ± 0.9%; Mercer **$102,760 ± $4,099**,
  10.0 ± 1.5%. Published MOE equals `(UB90−LB90)/2` exactly in the receipt.
- **Update cadence:** annual single-year estimates; the API `time=` parameter
  serves 2019–2024; older years in bulk files.
- **Access:** API, key optional for light use. No pull script on `main` yet —
  `ingestion/pull_saipe_counties.py` exists on
  `origin/garrett/financial-eda-imputation` (all US counties × 2019–2024,
  pending merge). Bulk: `www2.census.gov/programs-surveys/saipe/datasets/`.
- **Landmines:** SAIPE 2024 is a **single-year model estimate**; ACS 5-year
  vintage 2024 is a 2020–2024 average centered ~2022 — the same-named years
  describe different windows, so compare uncertainty *styles*, never join as
  the same quantity. Its intervals reflect **model error**, not ACS sampling
  error. County FIPS churn (CT planning regions from 2022) breaks naive
  year-over-year joins.
- **Key EDA 10 facts (2026-08-06):** at NJ county scale SAIPE's published
  interval is **~2× the ACS 5-year's relative width, essentially always**
  (wider in 99–100% of 2019–2024 county-years; median relative half-widths
  4.3% vs 2.2% for income, 14.8% vs 7.3% for the poverty rate), while
  same-label points agree within ~2% — SAIPE's width buys single-year
  currency, the ACS's narrowness buys a five-year average. All NJ counties
  are large; SAIPE's small-area advantage is invisible here (national test
  queued post-merge). See `notebooks/10-saipe-vs-acs-county.ipynb`.

## ACS 5-year PUMS — Public Use Microdata Sample (vintage 2024) — *exact SEs + person-level imputation* (added 2026-08-01)

- **What:** Anonymized ACS person and household records — supports **any
  custom estimate** instead of pre-published tables. In this project: the
  **exactness upgrade** (exact standard errors for medians and custom cuts)
  and the person-level view of imputation (who gets inferred — Garrett's
  EDA 09, branch).
- **Geographies:** region / division / state / **PUMA only** (~100k people
  each) — no county, tract, or block group (probe 2026-08-01). NJ ≈ 445k
  person records.
- **Uncertainty shipped:** no per-estimate MOEs. Instead **80 person replicate
  weights (`PWGTP1–80`) and 80 household replicate weights (`WGTP1–80`) — all
  160 verified present in `variables.json` 2026-08-01** (521 variables
  total). SE by successive difference replication:
  `Var = (4/80)·Σ(θ_r − θ)²`, `MOE = 1.645·SE` (the 4/80 constant is
  ACS-design-specific). Implementation: `analysis/replicate.py` on Garrett's
  branch (pending merge).
- **Update cadence:** annual 1-year and 5-year releases.
- **Access:** API `acs/acs5/pums` (≤50 variables per query — the 80 replicate
  weights need chunked pulls, as the branch script's `--replicates` mode
  does); bulk CSVs at `www2.census.gov/programs-surveys/acs/data/pums/`.
  Method + design-factor PDFs verified at
  `www2.census.gov/programs-surveys/acs/tech_docs/pums/accuracy/`
  (per-vintage `AccuracyPUMS.pdf`, checked 2026-08-01).
- **Landmines:** income N/A sentinels are **not uniform** — `WAGP/SSP/RETP/PAP`
  use −1 but `SEMP/INTP` use −10001, so a blanket `<0` filter corrupts the
  two most interesting sources; `FHINCP` is a household flag delivered on
  person rows — dedupe on `SERIALNO` or NJ reads 9.07M households instead of
  ~3.4M; the PUMA floor means PUMS facts can never be row-joined to
  tract-level scores (ecological-inference limits). (First two found by
  Garrett, EDA 09.)

## ACS Variance Replicate Estimate Tables (5-year; vintages 2014–2024) — *exact MOEs for aggregates* (added 2026-08-01)

- **What:** Pre-computed 80-replicate versions of selected ACS detailed
  tables, distributed as **bulk CSVs outside the API**. They yield **exact**
  MOEs for sums/aggregations of estimates — replacing the handbook
  root-sum-of-squares approximation (which EDA 02 showed needs the zero-cell
  rule and tends to overstate for same-table cells). Role: the exact-SE path
  if the tool scores aggregated estimates or custom regions.
- **Geographies:** per-summary-level directories verified 2026-08-01: US(010),
  state(040), county(050), county subdivision(060), **tract(140), block
  group(150)**, place(160), and others; files are per table × state (suffix =
  state FIPS).
- **Uncertainty shipped:** replicate estimates → exact variance for any linear
  combination of cells.
- **Coverage (verified live 2026-08-01):** at tract (6,552 files) NJ has
  **`B17001_34`, `C17002_34`, `B19001_34`**; at block group (3,796 files)
  `C17002_34` and `B19001_34` — **B17001 absent at BG, exactly mirroring its
  API publication floor**. **`B19013` (median income) is not covered at any
  level** — medians are nonlinear, so exact SEs for medians come from PUMS
  replicate weights instead. Division of labor: **counts + the income
  distribution → VRTs; the median → PUMS.**
- **Update cadence:** annual 5-year vintages, 2014–2024 all present in the
  tree. **5-year only — the 1-year path returns 404** (curated-registry
  suspicion confirmed 2026-08-01).
- **Access:** `www2.census.gov/programs-surveys/acs/replicate_estimates/2024/data/5-year/<summary-level>/`;
  landing page + Table & Geography List:
  `census.gov/programs-surveys/acs/data/variance-tables.html`. **No API
  product ID** — invisible to catalog-based tooling; carried by the Product
  Scope Tracker's curated registry (whose 2023 entry is now superseded by
  2024, and whose 1-year entry should be marked nonexistent — noted for
  Garrett).
- **Landmines:** bulk-only; nothing downloaded yet — no pull script exists,
  and scoring-layer use would need one (scripted, per reproducibility rules);
  per-state × per-table file layout means a custom-region workflow touches
  many files.
