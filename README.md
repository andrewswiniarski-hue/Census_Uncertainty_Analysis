# Census Uncertainty Analytics: From Collection to Decision Making

## 📌 Project Overview & Metadata

**Author(s):** Andrew Swiniarski, Justus Long, Katie Christiansen, Garrett Spangler, Theodore Ruth
**Completion Date:** TBD
**Partner Organization:** U.S. Census Bureau
**Program:** Georgetown University, MS in Business Analytics (MSBA) Capstone
**License:** [CC0 1.0 Universal](LICENSE) (public domain dedication) for the team's code and documents; the committed Census Bureau and USDA data are U.S. government works

> **Visual guide:** after cloning, open [`HANDOVER.html`](HANDOVER.html) in a web browser. It walks through how the dashboard works (with diagrams, a worked example and an interactive reliability-score calculator), the data pipeline, the research findings and the tech stack. GitHub shows that file as code, so it has to be opened locally.

### Core Goals & Problem Statement

* **The Problem:** Every number the Census Bureau publishes from a survey carries uncertainty, but that uncertainty is not one thing. At least three separate sources affect a published estimate: **sampling error** (the American Community Survey asks a sample, not everyone), **privacy noise** (the 2020 Census adds deliberate statistical noise to protect respondents), and **imputation** (when someone skips a question, the Bureau fills in a plausible answer). The published margin of error measures only the first. A planner, grant writer or county official looking at a single number has no easy way to tell whether it is solid enough for their decision. In short: *a tight margin of error is not the same thing as a trustworthy number.*
* **Project Goals:**
  1. Decompose where uncertainty enters Census data products, and measure each source empirically.
  2. Test whether those sources can be combined into one interpretable reliability score.
  3. Judge which existing public uncertainty measures are fit for which uses.
  4. Show uncertainty to non-technical users in a way they can act on: the **US County Demographic Explorer**, a dashboard that puts the Bureau's own published uncertainty, and a reliability score that also reflects imputation, next to 26 American Community Survey measures for every U.S. county.

  This matters because funding formulas and local decisions rest on estimates whose reliability varies enormously: the same median household income is about 14 times less precise at block group level than at county level, and income is imputed for roughly 39% of households in a typical New Jersey tract, which no published margin of error shows.

---

## 📂 Detailed File & Folder Map

```text
├── Streamlit/
│   ├── us_county_explorer.py   # The dashboard: US County Demographic Explorer (version 7)
│   └── README.md               # Its 26 measures, how to add one, the AI assistant, known limits
├── .streamlit/config.toml      # Dashboard theme (Census Bureau palette and font)
├── analysis/                   # Reusable code: CV and margin-of-error formulas, the reliability
│                               #   score, dashboard data loaders, the optional AI assistant
├── ingestion/                  # One script per data download from the Census Data API / USDA,
│                               #   each with its own sanity checks (shared helpers in _common.py)
├── data/
│   ├── raw/                    # Source data exactly as downloaded. The 7 files the dashboard
│   │                           #   reads are committed; research data is downloaded by scripts
│   └── processed/              # Notebook outputs (charts); created locally, not committed
├── notebooks/                  # Research notebooks 01–14 (EDA), committed with their outputs
├── tests/                      # Automated tests (pytest) for the formulas, loaders and dashboard
├── docs/
│   ├── final_report.pdf        # Final report (to be added)
│   ├── presentation.pdf        # Final presentation (to be added)
│   ├── phase1-findings-report.md   # Plain-language research findings, EDA 01–13
│   ├── glossary.md             # Every statistical term, in plain English
│   ├── data-dictionary.md      # Each data product: geographies, uncertainty published, caveats
│   ├── project-brief.md        # Research questions, scope history, open questions for mentors
│   ├── design-specs/           # Design records for each dashboard feature
│   ├── meeting-decks/          # Slides from mentor meetings and team reviews
│   ├── handover/figures/       # Research charts used by HANDOVER.html
│   └── *.md                    # Methodology notes, user research, allocation studies, API receipts
├── tools/                      # Product Scope Tracker: catalog of ~573 Census data products
├── product_report.html         # The tracker's generated report (open in a browser)
├── product_review.json         # The team's review notes on catalog products (tracker input)
├── product_probes.json         # Metadata probes for selected products (tracker input)
├── notes/                      # Drop-in notes the tracker ingests
├── verify_api_surfaces.py      # Re-checks what each product publishes; writes docs/api-surface-verified.md
├── report_alloc_denominators.py, report_alloc_profile.py   # Regenerate the two allocation studies in docs/
├── HANDOVER.html               # Visual guide to the project (open locally in a browser)
├── HANDOFF.md                  # Technical appendix: the 20 methodology decisions, data caveats
├── WORKLOG.md                  # Dated record of who did what and what was found
├── .env.example                # Template for the local .env file holding API keys (never committed)
├── .gitignore                  # Keeps keys, local environments and downloaded research data out of git
├── LICENSE                     # CC0 1.0 Universal
├── README.md                   # This file
├── requirements.txt            # Exact package versions needed to run the code
└── requirements-dev.txt        # Test-only dependency (pytest)
```

### Key Deliverables Quick-Links

* 📄 **Final Report:** `docs/final_report.pdf` *(to be added)*
* 📊 **Presentation Deck:** `docs/presentation.pdf` *(to be added)*
* 🗺️ **Dashboard:** [`Streamlit/us_county_explorer.py`](Streamlit/us_county_explorer.py), the US County Demographic Explorer
* 🧭 **Visual guide:** [`HANDOVER.html`](HANDOVER.html), open locally in a browser
* 🔬 **Research findings:** [`docs/phase1-findings-report.md`](docs/phase1-findings-report.md) and [`notebooks/`](notebooks/)
* 🗂️ **Product Scope Tracker:** [`tools/`](tools/) and its report [`product_report.html`](product_report.html)

---

## 🛠️ Step-by-Step Setup & Execution

Follow these plain-English steps to open, set up and run the project from start to finish. Every command is run from the repository's top folder.

### Prerequisites

* **Software:** [Git](https://git-scm.com/) and **Python 3.13** (the package versions in `requirements.txt` were verified together on Python 3.13.5).
* **Licenses:** none. Everything used is free and open source.
* **API keys:**
  * A **Census API key** (free, arrives by email within minutes: <https://api.census.gov/data/key_signup.html>). Needed only to refresh the dashboard's data or to download the research notebooks' data. The dashboard itself runs without one.
  * An **Anthropic API key** is optional, only for the dashboard's "Ask about this county" AI assistant. Without it the assistant is switched off and everything else works.

### Step 1: Clone the Repository

```bash
git clone https://github.com/andrewswiniarski-hue/Census_Uncertainty_Analysis.git
cd Census_Uncertainty_Analysis
```

### Step 2: Set Up Environment & Install Dependencies

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate

# Install exact requirements (pytest is only for the tests)
pip install -r requirements.txt -r requirements-dev.txt
```

If you will refresh data or use the assistant, copy `.env.example` to a new file named `.env` and paste your key(s) in. `.env` is git-ignored, so keys never leave your machine.

### Step 3: Run the Dashboard

The dashboard's data is already in `data/raw/`, so it runs immediately:

```bash
streamlit run Streamlit/us_county_explorer.py
```

It opens at <http://localhost:8501>. Pick a state, then a county, on the map or in the search box. See [`Streamlit/README.md`](Streamlit/README.md) for what each card shows.

### Step 4 (optional): Refresh the Dashboard's Data from the Census Bureau

These four scripts re-download the seven data files the dashboard reads. Run them in this order (the last one checks its county list against the first one's output). They take about six minutes in total and need the Census API key in `.env`, except `pull_rucc.py`.

```bash
python ingestion/pull_usdash.py        # ACS 2020–2024 5-year and 2024 1-year estimates, state and county
python ingestion/pull_usdash_alloc.py  # ACS imputation (allocation) tables, county
python ingestion/pull_us_geometry.py   # State and county boundaries for the maps
python ingestion/pull_rucc.py          # USDA Rural-Urban Continuum Codes 2023
```

Each script prints its own sanity checks. To move to a newer ACS release, change the year in these scripts and in the file names that `analysis/dashboard.py` reads, re-run them, then run the tests.

### Step 5: Run the Tests

```bash
python -m pytest tests -q
```

On this repository: 351 passed and 14 skipped. The skipped tests need New Jersey research data that the dashboard does not use. No test calls the Census or Anthropic APIs.

### Step 6 (optional): Re-run the Research Notebooks

The notebooks are committed with their outputs, so they can be read on GitHub without running anything. To re-run one, first download its data with the scripts listed for it in [`notebooks/README.md`](notebooks/README.md) (for example `python ingestion/pull_acs_nj.py` for notebooks 01 and 02), then open it with `jupyter lab`. The research data is New Jersey's, plus a national sample for notebook 14.

### Step 7 (optional): The Product Scope Tracker

```bash
python tools/product_scope.py            # rebuild product_report.html from the cached catalog
python tools/product_scope.py --online   # re-crawl the Census Data API catalog first
```

Or simply open the committed [`product_report.html`](product_report.html) in a browser. See [`tools/README.md`](tools/README.md).

---

## 💡 Plain-English Analytical Methods & Transparency

### Analytical Steps & Methodology Overview

* **Data Ingestion & Preparation:** Every dataset is downloaded by a script in `ingestion/` from an official public source (mainly the Census Data API), never by hand. Each script checks what it downloaded against the Bureau's published labels and against simple rules (for example, that parts add up to their total) and stops if something is off. Files are saved in `data/raw/` exactly as the source returned them; all cleaning happens in code in `analysis/`, so every step can be reviewed and rerun.
* **Analytical Approach:**
  * **Sampling error:** for each estimate we use the margin of error the Bureau publishes and compute the **coefficient of variation (CV)**: the standard error (the margin divided by 1.645) as a share of the estimate. A CV of 0.10 means the typical sampling error is about 10% of the number.
  * **Combined figures:** when the dashboard adds published cells together (for example, several age groups), it combines their margins with the Census Bureau's own handbook formula (root-sum-of-squares). Rates use the Bureau's proportion formula.
  * **Privacy noise:** measured by comparing the Bureau's 2010 demonstration data, which has privacy noise added, with the published 2010 counts (notebook 04).
  * **Imputation:** measured from the Bureau's allocation tables, which report how many answers were filled in (notebooks 05, 08, 09).
  * **The reliability score (dashboard cards):** a 0–100 score that averages a sampling sub-score (from the CV) and, for income and poverty figures, an imputation sub-score (how the county's imputation rate ranks against every U.S. county). The label (Higher, Moderate or Lower reliability) is never better than the CV alone would give.
  * **Statistical peers:** counties whose estimate cannot be told apart from the selected county's at 90% confidence.
* **Decision Logic:** the project lead's 20 numbered decisions are listed in full in [`HANDOFF.md`](HANDOFF.md) and summarized in `HANDOVER.html`. The ones that most shape the results:
  * The newest release is used: ACS 2020–2024 5-year estimates (vintage 2024), the only ACS product published for every county.
  * A zero or missing estimate has no CV and is reported separately, never treated as "infinitely unreliable".
  * Median household income published as the top-code $250,001 has its margin set aside, because a censored value would look falsely precise.
  * The CV lines 0.12, 0.30 and 0.40 are other organizations' conventions (Esri and the National Center for Health Statistics) and are always named as theirs; the Bureau has no adopted threshold.
  * Imputation is shown beside the CV, not hidden inside it, because the research found the two are independent.
  * Following the Census Bureau sponsor's direction, the dashboard uses a neutral voice: it shows the estimate, its margin and its CV, and does not tell the user what to conclude.

### Assumptions, Limitations & Potential Biases

* **Key Analytical Assumptions:**
  * *Published margins are taken as given.* The dashboard does not re-estimate sampling error, so an implausibly narrow published margin (for example, median household income in Loving County, Texas, from about 27 households) scores as highly reliable.
  * *Imputation proxy:* no person-level poverty imputation table exists, so poverty cards use the family-poverty allocation table (B99172) as a labeled proxy. Imputation enters the score only for income and poverty figures.
  * *Controlled estimates:* total population has no margin of error in most counties because the Bureau fixes it to its own population estimates. It is shown as "controlled", not as missing or unreliable.
  * *The reliability score is this team's method,* pending Census Bureau review, not an official Census Bureau measure.
* **Data Gaps & Coverage Limits:**
  * The dashboard is **county level only** (all 3,144 counties and county equivalents; Puerto Rico is excluded). It holds no tract or block-group data.
  * Estimates are 2020–2024 averages; the dashboard shows no change over time.
  * The research notebooks use **New Jersey** as the test state (counties, tracts and block groups). Patterns were checked nationally only where noted (notebook 14).
  * The privacy-noise analysis uses the Bureau's 2010 *demonstration* data, because the noise in the 2020 Census itself cannot be measured directly.
* **Potential Biases & Caveats:**
  * Small counties and small groups have larger CVs because fewer people sit behind the number, not because the place is unusual. Comparing CVs across counties of very different size needs care.
  * Imputation is uneven: income is imputed far more often than age or sex, and more often for some groups (see `docs/allocation-profile-nj.md`).
  * The optional AI assistant's checks guarantee that every figure it shows comes from the dashboard's data, but not that every sentence about a figure is right; its evaluation found errors that wording changes reduced but cannot rule out. It is labeled as AI-generated and is not a statement of the Census Bureau.
  * Questions the team raised for the Census Bureau, such as which CV threshold convention to name and whether an AI-worded panel is appropriate, are listed in [`docs/project-brief.md`](docs/project-brief.md) under "Open Questions for Mentors".

---

## 🛡️ Citations

For guidance on how to cite Census Bureau data, tools, technical documents and research, see [https://www.census.gov/about/policies/citation.html](https://www.census.gov/about/policies/citation.html).

### External Data Sources

Accessed: 2026-10-25 for the dashboard data; July–August 2026 for the New Jersey research data.

1. **American Community Survey 5-Year Estimates, 2020–2024** (detailed tables, including the B98/B99 allocation tables) – Published by *U.S. Census Bureau* (2025). Available at: `https://api.census.gov/data/2024/acs/acs5` (dataset page: https://www.census.gov/data/developers/data-sets/acs-5year.html).
2. **American Community Survey 1-Year Estimates, 2024** – Published by *U.S. Census Bureau* (2025). Available at: `https://api.census.gov/data/2024/acs/acs1` (dataset page: https://www.census.gov/data/developers/data-sets/acs-1year.2024.html).
3. **American Community Survey Public Use Microdata Sample (PUMS), 2020–2024 5-Year** – Published by *U.S. Census Bureau*. Available at: `https://api.census.gov/data/2024/acs/acs5/pums` (program page: https://www.census.gov/programs-surveys/acs/microdata.html).
4. **Cartographic Boundary Files, 2024** – Published by *U.S. Census Bureau*. Available at: `https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html` (downloaded through the censusdis package).
5. **Rural-Urban Continuum Codes, 2023** – Published by *USDA Economic Research Service* (2024). Available at: `https://www.ers.usda.gov/data-products/rural-urban-continuum-codes`.
6. **Small Area Income and Poverty Estimates (SAIPE), 2019–2024** – Published by *U.S. Census Bureau*. Available at: `https://api.census.gov/data/timeseries/poverty/saipe` (program page: https://www.census.gov/programs-surveys/saipe.html).
7. **2020 Census Demographic and Housing Characteristics File (DHC) and Demographic Profile (DP)** – Published by *U.S. Census Bureau* (2023). Available at: `https://api.census.gov/data/2020/dec/dhc` and `https://api.census.gov/data/2020/dec/dp` (dataset page: https://www.census.gov/data/developers/data-sets/decennial-census.html).
8. **2010 Census Summary File 1** – Published by *U.S. Census Bureau* (2011). Available at: `https://api.census.gov/data/2010/dec/sf1`.
9. **2010 Demonstration Data Products – Demographic and Housing Characteristics, 2022-08-25 release** – Published by *U.S. Census Bureau* (2022). Available at: `https://www2.census.gov/programs-surveys/decennial/2020/program-management/data-product-planning/2010-demonstration-data-products/02-Demographic_and_Housing_Characteristics/`.
10. **Census Regions and Divisions of the United States** – Published by *U.S. Census Bureau*. Available at: `https://www2.census.gov/geo/docs/maps-data/maps/reg_div.txt`.
11. **OpenStreetMap** (neighborhood names for the Trenton research data, via the Overpass API) – © OpenStreetMap contributors, available under the Open Database License. Available at: `https://www.openstreetmap.org/copyright`.

### Background Literature & References

* U.S. Census Bureau. (2020). *Understanding and Using American Community Survey Data: What All Data Users Need to Know.* U.S. Government Publishing Office. https://www.census.gov/programs-surveys/acs/library/handbooks/general.html
* U.S. Census Bureau. *American Community Survey Accuracy of the Data, 2020–2024 5-year* and *2024 1-year*. https://www.census.gov/programs-surveys/acs/technical-documentation/code-lists.html
* U.S. Census Bureau. *2020–2024 ACS 5-year PUMS Accuracy of the Data.* https://www2.census.gov/programs-surveys/acs/tech_docs/pums/accuracy/2020_2024AccuracyPUMS.pdf
* Abowd, J. M., Ashmead, R., Cumings-Menon, R., Garfinkel, S., Heineck, M., Heiss, C., Johns, R., Kifer, D., Leclerc, P., Machanavajjhala, A., Moran, B., Sexton, W., Spence, M., & Zhuravlev, P. (2022). The 2020 Census Disclosure Avoidance System TopDown Algorithm. *Harvard Data Science Review*. https://doi.org/10.1162/99608f92.529e3cb9
* Spielman, S. E., Folch, D., & Nagle, N. (2014). Patterns and causes of uncertainty in the American Community Survey. *Applied Geography, 46*, 147–157. https://doi.org/10.1016/j.apgeog.2013.11.002
* Spielman, S. E., & Folch, D. C. (2015). Reducing uncertainty in the American Community Survey through data-driven regionalization. *PLOS ONE, 10*(2), e0115626. https://doi.org/10.1371/journal.pone.0115626
* Parker, J. D., et al. (2023). *National Center for Health Statistics Data Presentation Standards for Rates and Counts.* National Center for Health Statistics. https://doi.org/10.15620/cdc:124368 (NCHS's reliability standards; the dashboard's CV 0.30 caution line follows NCHS practice as described in `docs/glossary.md`.)
* Esri. *U.S. Census Bureau's American Community Survey — Esri Demographics documentation* (the reliability measure Esri publishes with ACS estimates). https://doc.arcgis.com/en/esri-demographics/latest/esri-demographics/american-community-survey.htm (The 12% and 40% CV lines are as cited from Esri's 2025 methodology statement in `docs/user-segments-and-needs.md`.)
* Okabe, M., & Ito, K. (2002, revised 2008). *Color Universal Design (CUD): How to make figures and presentations that are friendly to colorblind people.* https://jfly.uni-koeln.de/color/ (the colorblind-safe palette used for the dashboard's maps and bands)
* censusdis contributors. *censusdis: a Python package for discovering, loading and analyzing U.S. Census data.* https://github.com/censusdis/censusdis
* Further sources behind the user research (planner surveys, program documentation such as HUD CHAS, CDC/ATSDR SVI and EPA EJScreen, and state data center guidance) are listed in [`docs/user-segments-and-needs.md`](docs/user-segments-and-needs.md#sources).
