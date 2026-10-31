# /Streamlit: dashboard apps

| File | What it is | Status |
|---|---|---|
| [`us_county_explorer.py`](us_county_explorer.py) | The US County Demographic Explorer, version 7: v6 plus the "Ask about this county" AI assistant, which is off unless an API key is set (2026-10-18). Named `app_US_v7.py` until 2026-10-31 | **Current.** The only app on the handoff branch |

Its data files are committed in `data/raw/`, so `streamlit run Streamlit/us_county_explorer.py` works straight after cloning; the four pulls below refresh them.

**How v7 came to be.** v1.1 (Justus Long, the nationwide county explorer) → v1.2 (Katie Christiansen's redesigned welcome page) → v2 (Andrew Swiniarski: every US county, 26 measures, error-bar cards) → v3 (the card reliability score, 2026-09-27) → v6 (Justus Long: Statistical peers tab, ranked peers, Census Bureau branding shell, with Katie Christiansen's v5 welcome page) → v7 (Andrew Swiniarski: the assistant). The earlier files (v1.1–v3, and the Trenton grant data prototype `app.py`, NJ tracts, a learning instrument) remain on `main`; v6 is on the `county-ai-assistant` and `JL_Work_Tree` branches. [`HANDOVER.html`](../HANDOVER.html) at the repo root explains how v7 works.

## US county dashboard (v7): the "Ask about this county" assistant

Version 7 is version 6 plus one panel on the County explorer tab, directly under the county heading (2026-10-18; spec `docs/design-specs/2026-10-10-county-ai-assistant-design.md`). Without an API key the panel is one line saying the assistant is off, and the page is otherwise identical to v6.

**What the panel does.** Three buttons ("Give me a county brief", "How reliable are these figures?", "How does this county compare with similar counties?") and a question box (400 characters at most, 20 questions per session). A large language model, Claude Haiku 5.5, writes a short plain-language answer. It does not type figures: it writes named blanks such as `[[median_household_income.estimate]]`, and our code fills each one with the exact figure the card shows, taken from a fact sheet built by the same functions the cards call (`_county_fact_sheet`). A reply is shown only if every blank resolves, no other digits, spelled-out numbers or fraction signs remain (a number that defines a measure, such as "aged 5 to 17" or "below 200% of the poverty line", is allowed only in that wording), and it contains no advice wording; otherwise the model gets one retry, then a fixed fallback text. Off-topic questions get a fixed redirect. Selecting a different county starts a new conversation. All wording is in `analysis/assistant_text.py`; the engine and its checks are in `analysis/assistant.py`.

**What leaves the machine.** The question, the county's fact sheet (public statistics) and the standing instructions go to Anthropic's API. Nothing is written to disk. The panel's disclosure line says so.

**Switching it on.** Copy `.env.example` to `.env` if you have not already, then set:

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Your Claude API key. Never commit it; `.env` is git-ignored | none: the assistant is off |
| `ASSISTANT_MODEL` | Model name | `claude-haiku-5-5` |
| `ASSISTANT_FREE_TEXT` | `0` hides the question box and keeps the three buttons | `1` |

Install the client with `pip install -r requirements.txt` (it adds `anthropic`), then run `streamlit run Streamlit/us_county_explorer.py`. Restart Streamlit after changing `.env` or anything in `analysis/`. Measured cost is about four hundredths of a cent per question (205 questions for about \$0.09 at list prices, 2026-10-18).

**Evaluation (2026-10-18).** `analysis/assistant_eval.py` asks 41 fixed questions about each of five counties chosen by fixed rules (Jefferson County, Alabama; Loving County, Texas; Alpine County, California; Bristol Bay Borough, Alaska; Wyoming County, Pennsylvania). First full run, 205 replies: the scope decision (answer or redirect) was right in 183 (89%); 11 (5%) were blocked by the checks, 6 for an unknown blank and 5 for a stray number; 1 of 15 ready-made prompt replies was blocked (under the one-in-ten line for moving to a larger model); none were unavailable; estimated cost about \$0.09. Fixes for the miss patterns followed: the eight questions that had missed went from 25 to 38 of 40 right on rerun, and the similar-county comparison now reads the right way round in all live checks. Details and open items: WORKLOG 2026-10-18.

**Rerun it** from the repo root (live runs need the key and spend money):

```bash
python analysis/assistant_eval.py --dry-run
```

```bash
python analysis/assistant_eval.py --county 01073 --limit 2
```

```bash
python analysis/assistant_eval.py --match rising --match "median gross rent"
```

```bash
python analysis/assistant_eval.py
```

Each live run writes `data/processed/assistant_eval_<date>.jsonl` (git-ignored; later runs the same day add `_run2`, `_run3`), one line per reply with the question, the shown text, the model's text with blanks, every failed check and the failed attempts' text, and token counts. Read a sample of answers against the cards after any change to the wording or the fact sheet: the checks are built so that figures come only from the dashboard's data, but they do not check that every sentence about a figure is right.

## What v6 added (carried into v7)

Version 6 (Justus Long, copied unchanged onto the v7 line from `JL_Work_Tree`, commit 46850e8) is version 3 below plus a Statistical peers tab with its own map and ranked peer table, the Census Bureau branding shell, map tooltips, a left-hand filter panel, "Nth of N counties in the state" CV ranks, and Katie Christiansen's goal-oriented welcome page (v5). Still open lead decisions: the peer table's "Similarity" score (our invention, not yet in the glossary), the blue and gold palette, and the em dashes in its user-facing text.

## Cards, measures and data (from v3, unchanged in v7)

**Run it** from the repo root:

```bash
streamlit run Streamlit/us_county_explorer.py
```

**Data it needs.** Run these four pulls first. Each prints its own sanity checks; outputs land in `data/raw/`. The three Census pulls need `CENSUS_API_KEY` in `.env`; `pull_rucc.py` does not. Run `pull_usdash.py` first: `pull_rucc.py` cross-checks its county join against that file.

```bash
python ingestion/pull_usdash.py
python ingestion/pull_usdash_alloc.py
python ingestion/pull_us_geometry.py
python ingestion/pull_rucc.py
```

`pull_usdash.py` requests 399 variables. The Census API sometimes drops one of the metadata lookups that run before a download; the dashboard pulls retry automatically (`ingestion/_common.py::download_with_retry`), so a transient failure costs seconds rather than the whole pull. If your local data is older than the code, the app does not crash: measures it cannot draw are hidden from the map and peers lists, and their cards say to re-run the pull.

### What is on it

- **Map.** Click a state, then a county. The map colors each county by the coefficient of variation (CV, the standard error, which is the margin of error divided by 1.645, as a share of the estimate) of the measure you choose, on a continuous scale from blue (lower CV) through purple to orange (higher CV, a larger margin of error). The blue and orange ends are the Okabe-Ito colorblind-safe pair; the purple midpoint replaced the original near-white midpoint, which made card bars near CV 25% invisible (2026-09-16). It opens on median household income. Total population is a controlled estimate in most counties, with no sampling error, and gets its own color and legend entry.
- **Cards.** Every card shows the estimate, its CV, and its 90% interval on a zero-anchored axis, so a wide margin of error visibly takes up more of the bar. Cards in the four-across grid use a narrower drawing so their text stays readable.
- **State comparison (per-card toggle).** 25 of 26 cards have a "Compare to state" switch, off by default, so each card opens showing the county alone with its axis fitted to the county (2026-09-27, after Census Bureau feedback that county and state on one bar was hard to read). Switched on, the state appears as its own grey row under the county bar, on the same axis. Medians and percentages show the state's own published value as a solid bar over its published margin of error. Counts show what the county's number would be at the state's rate, because a state count is not on a county's scale; that row is our calculation, drawn lighter with a dashed outline, and the card says so. The switch also governs the income card's county-vs-state significance line. Each card remembers its setting as you move between counties. Total population has no state comparison.
- **Reliability score (v3, 2026-09-27).** A strip across the top of each card gives a band (Higher, Moderate or Lower reliability) and a 0 to 100 score: the average of a sampling sub-score from the CV and, for income and poverty figures, an imputation sub-score comparing the county with all US counties. The band is never better than the CV alone gives. "Show me the statistics" shows both sub-scores. Total population has no score. Our methodology, pending mentor review (HANDOFF decision #19).
- **Statistical peers.** Counties whose estimate is statistically indistinguishable from the selected one at 90% confidence.

### The 26 measures

| Topic | Measures |
|---|---|
| Population | Total population; Under 5, 5-17, 18-64, 65+ |
| Poverty | Below poverty by the same four age bands; low income (below 200% of poverty) |
| Income | Median household income; households earning under $25k, $25k-$50k, $50k-$100k, $100k+ |
| Employment | Unemployed |
| Education | No high school diploma (age 25+) |
| Housing | Median gross rent; rent burden (median); cost-burdened renters (30%+); severely cost-burdened renters (50%+); median home value |
| Health | Uninsured |
| Disability | With a disability |
| Language | Limited English speaking households |
| Transportation | Households with no vehicle available |

The last seven additions follow scope decision #18 (2026-09-14); `docs/dashboard-variable-shortlist.md` records why each was chosen and which were held back.

### Adding a measure

Three lists in the code fail silently if you miss them: nothing errors, the measure just does not work.

1. Add its cells to the pull in `ingestion/pull_usdash.py`, with a sanity check.
2. Add its table prefix to `VALUE_COL_PREFIXES` in `analysis/dashboard.py`, or its columns are never converted to numbers.
3. Add accessor functions in `analysis/dashboard.py` and tests in `tests/test_dashboard.py`, checking cell numbers against the published labels.
4. Add a `Measure` to `_build_measures()` in `us_county_explorer.py`.
5. If its topic is new, add it to `TOPIC_ORDER`, or its card never appears.
6. If it is a median, add it to `_PEER_MEDIANS`, or the peers panel treats it as a count.
7. If the Census Bureau publishes an allocation table for the measure's item, add it to `IMPUTATION_SOURCES` (and to the allocation pull) and set `Measure.imputation`; otherwise the card is scored on sampling only and says so.
8. Re-run the pull, then **restart** the server. Streamlit's Rerun button does not reload changed `analysis/` modules.
9. Set `controlled_when_moe_missing=True` only after confirming against the API that every missing margin of error for that measure carries the controlled-estimate annotation (`*****`).

### Known limits

- Comments carried over from v1.1 still name `app_NJ.py` and `app_US.py`; the module docstring explains they mean `app.py` and `app_US_v1.1.py` (both on `main`, not on the handoff branch).
- Only total population is treated as a controlled estimate, because that convention has only been verified for it. Any other measure with no published margin of error is shown as "no margin of error published".
- The state-rate benchmark on count cards treats the state rate and the county's universe as independent. That slightly overstates its margin of error, since the county is part of the state.

## Trenton grant data prototype

`Streamlit/app.py` (NJ tracts, 2026-07-31) was the team's learning instrument: it started from a City of Trenton grant writer's decision and worked backwards to how uncertainty should be shown. It is not part of the handoff branch; its full write-up is in this file on `main` and in WORKLOG 2026-07-31 to 2026-08-01.
