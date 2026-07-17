# Data Dictionary — Census Uncertainty Analytics

Catalog of every statistical product this project uses: what it is, which
geographies it covers, **what uncertainty measure ships with it**, how we access
it, and the landmines we've hit. One entry per product; newest additions at the
bottom. (README Phase 1, Step 4 — living document; DHC and Demographic Profile
entries pending the mentor shortlist confirmation.)

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
  controlled-vs-insufficient-sample distinction; median income top-coded at
  $250,001 with **no MOE published for top-coded rows**; county total population
  is controlled (no MOE, extremely reliable); 131 NJ tracts show unexplained
  near-controlled population MOEs (mentor question); 2 block groups have income
  estimates but no MOE for unknown reasons.

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
