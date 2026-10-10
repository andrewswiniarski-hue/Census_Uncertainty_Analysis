# "Ask about this county" AI assistant: design

**Date:** 2026-10-10
**Branch:** `county-ai-assistant`
**Files affected:** new `analysis/assistant.py`, `analysis/assistant_eval.py`, `Streamlit/app_US_v7.py`, two new test files under `tests/`; `Streamlit/app_US_v6.py` and one function brought over from `origin/JL_Work_Tree`; `requirements.txt`, `.env.example`, and the project docs listed under "Documentation".
**Status:** Written spec reviewed and approved by the lead (2026-10-10). No code has been written.

## Purpose

The US county dashboard shows up to 26 measures for a county. Each card carries an estimate, a 90% range, a coefficient of variation (CV: the margin of error as a share of the estimate) and a reliability score. A user who is not a statistician sees many numbers and no overall takeaway.

This design adds a panel where that user clicks a ready-made prompt or types a plain question and gets a short written answer. The answer is worded by a large language model (LLM: a text-generating AI system reached over the internet through an API, a programming interface) and built only from figures the dashboard already computes.

It serves research question Q4, how uncertainty should be communicated to non-technical users, and the README's nice-to-have "plain-language interpretive aids". It passes the scope fence (decision #18): no new data and no new measures.

## Decisions already made (lead, 2026-10-10)

1. **Base version.** Bring Justus's `app_US_v6.py` onto `main` as a file, unchanged, then build the assistant into a new `app_US_v7.py`. Older versions stay as snapshots, as with v1.1 through v3.
2. **Model.** Claude Haiku 5.5 (`claude-haiku-5-5`), the lowest-cost current Claude model. The model name is one environment variable, so it can be changed without a code change.
3. **Voice.** "Describe, plus cited outside rules." The assistant states what a figure's reliability band is and what drives it. It may quote named outside rules as theirs. It gives no verdict of its own. This follows the sponsor's 2026-08-12 neutral-voice direction.
4. **Shape.** Three ready-made prompts plus a question box. The question box accepts only questions about the selected county's dashboard figures.
5. **Proceed before mentor confirmation.** The feature is off unless an API key is present, and two questions go on the README's mentor list (see "Open questions for mentors").

## Scope

**In v1:** the County explorer tab, one selected county at a time, all 26 measures.

**Not in v1:**

- Threshold checks ("is our poverty rate above 20%?"). Garrett's user research ranks this a top need for program staff and small-county officials. It needs a comparison done in code, so it is the first follow-on.
- Comparing two counties by name.
- The Statistical peers tab.
- Change over time. The dashboard holds one period, 2020 to 2024.
- A county-versus-state significance test for measures other than income and population. The cards do not run one today, so adding it is a methodology decision for the lead.

## What the user sees

A bordered panel titled "Ask about this county", directly under the county heading and above the card checklist:

- A one-line statement of what can be asked.
- Three buttons: **Give me a county brief**, **How reliable are these figures?**, **How does this county compare with similar counties?**
- A question box (400 characters at most).
- The conversation so far, and a "Clear conversation" button.
- A disclosure line (wording under "Fixed texts").

The conversation restarts when a different county is selected. With no API key configured, the panel is replaced by one line saying the assistant is off, and the rest of the dashboard is unchanged.

**Worked example.** A county clerk selects Jefferson County, Alabama and types "What is the average income here and how does it compare with similar counties?" The answer says the dashboard reports the median household income, which is the middle household and not the average, gives the estimate and its 90% range, and reports how the county sits among counties of the same metro class and population size. Measured on today's data: of 237 similar counties, 196 have a significantly higher median household income than Jefferson County, 23 have a significantly lower one, and 18 cannot be told apart from it.

## Design

### Four pieces

| Piece | Where | Job |
|---|---|---|
| Fact sheet | `Streamlit/app_US_v7.py` | One plain dictionary of every figure for the selected county |
| Engine | `analysis/assistant.py` (no Streamlit imports) | Prompts, the model call, and the checks |
| Panel | `Streamlit/app_US_v7.py` | Buttons, question box, conversation |
| Evaluation | `analysis/assistant_eval.py` | A fixed question set that measures how often replies pass the checks |

### Fact sheet

The card figures are computed today inside the page-drawing code, so no function returns "everything about one county". The fact sheet function fills that gap. It calls the same functions the cards call, so the two cannot disagree:

- `MEASURES` and each `Measure.values` / `Measure.universe` (app file)
- `acs_range`, `cv_from_range`, `proportion_rate`, `expected_at_rate`, `difference_is_significant` (`analysis/dashboard.py`)
- `score_for` and `_compute_peers` (app file), `composite.reliability_score` (`analysis/composite.py`)

**County context:** name, state, total population, metro or nonmetro class, population-size group, data period, and the population data quality rates (overall, sex, age and race imputation; imputation means an answer the Census Bureau filled in by statistical methods because the household did not give it).

**Per measure:** label, topic, table, and a status. Status is one of `published`, `suppressed` (the Census Bureau did not publish the estimate), `no margin of error`, `controlled estimate` (pinned to official population estimates, so it has no sampling error), or `not in local data`. Published measures then carry:

- estimate, margin of error, 90% range, CV
- rate and its 90% range, for measures that have one
- reliability score, band, sampling sub-score, imputation sub-score, imputation source, and whether the band was capped by the CV
- share imputed, for income
- CV rank among the state's counties
- the state's published value, or the state-rate benchmark marked as our calculation
- the county-versus-state test result, only where the card already runs it (income and population)
- the ACS 1-year estimate and range, where one exists
- the similar-county comparison: pool size, counties tested, tied, significantly higher, significantly lower, and up to five tied county names
- the three outside-rule results (see "Voice and outside rules")

Every number is stored twice: the raw value, and the exact display string the card shows.

"Similar counties" keeps the dashboard's existing definition: same metro or nonmetro class and same population-size group, compared with the Census Bureau's two-estimate test at 90% confidence. Computing this for all 21 eligible measures takes 0.16 seconds (measured 2026-10-10 on v6). The assistant does not use v6's Similarity score, whose status is still an open lead decision.

The list of cards currently on screen is sent with each question and is not part of the fact sheet. The fact sheet is therefore identical for a county from one question to the next.

### The model never types a number

The model is told to write named blanks in place of numbers:

```
Median household income is [[median_household_income.estimate]], with a 90% range of
[[median_household_income.ci_low]] to [[median_household_income.ci_high]].
```

The engine replaces each blank with the display string from the fact sheet. Each measure's blank name is a fixed, lower-case form of its registry key.

After the blanks are removed, the model's own text may contain no digits. Two exceptions are allowed, both matched as whole phrases: measure labels as they appear in the fact sheet ("below 200% of poverty", "age 25+"), and a short list of fixed phrases ("90%", "5-year", "1-year", "2020-2024").

The result is that the model cannot state a figure the dashboard did not compute. A wrong blank name is caught too, because it will not resolve.

### Checks every reply passes before it is shown

1. **Input limits.** 400 characters per question, 20 questions per session.
2. **Structured reply.** The model must return four fields: `kind` (`answer`, `out_of_scope`, `not_in_dashboard`), `answer`, `measures_used`, `terms_explained`.
3. **Scope.** If `kind` is not `answer`, the user sees our fixed redirect text and the three buttons. The model's own text is not shown.
4. **Grounding.** An answer must name at least one measure or one glossary term. Every blank must resolve, and none may point at a figure whose status is not `published`.
5. **No stray digits** (above).
6. **No advice wording.** A banned-phrase list that extends `ADVICE_WORDS` in `tests/test_us_v3_score.py`: "safe to", "too risky", "use with care", "you should", "we recommend", "trustworthy", "can be trusted", "reliable enough", "good enough".
7. **One retry.** If checks 4 to 6 fail, the engine asks once more, naming the failed check. A second failure shows the fixed fallback text.
8. **Failures.** A refusal by the model, a cut-off reply or an API error shows the fixed "unavailable" text. The page never crashes.

### What can and cannot be asked

**Can:**

- this county's figures across the 26 measures
- what a range, CV, reliability score or band means
- how the county compares with its state and with similar counties
- which figures are imputed, suppressed or controlled
- where to find something on the dashboard

**Cannot:**

- change over time, or forecasts
- why a figure is what it is
- eligibility or policy advice ("do we qualify for CDBG?")
- anything not on the dashboard
- places smaller than a county
- other counties by name

Two near-miss questions get a real answer in place of a redirect, because the honest answer is useful. "Average income" is answered with the median and a sentence saying so. "Is it rising?" is answered with the one period the dashboard holds and a sentence saying it cannot show change.

### The three ready-made prompts (draft wording for review)

Each is sent to the model in place of a typed question. Each asks for about 150 words at most, short paragraphs, and no bullet lists longer than four items.

1. **Give me a county brief.** "Write a short brief on this county for someone who is not a statistician. Start with one sentence on its size and whether it is metro or nonmetro. Then cover each card on screen: the figure in plain words, its 90% range, and its reliability band. Say how the county compares with its state and with similar counties where the fact sheet has that comparison. End by naming any card on screen that is not published. Do not recommend anything."
2. **How reliable are these figures?** "For each card on screen, state its reliability band and whether sampling, imputation or both drive it. Name any figure in the Lower reliability band and any figure that is suppressed, controlled or has no margin of error. Add one sentence on what the bands mean. Where an outside rule in the fact sheet applies to a figure, you may include that rule's sentence. Do not say whether a figure should be used."
3. **How does this county compare with similar counties?** "Define similar counties in one sentence, using the fact sheet's definition. For median household income and for each other card on screen that has a similar-county comparison, give how many counties are significantly higher, significantly lower, and cannot be told apart from this one. Do not rank the tied counties."

The second button was requested as "how trustworthy is the data". It is renamed because "trustworthy" is verdict wording under the neutral-voice direction.

### Voice and outside rules

The system prompt (the standing instructions sent with every question) tells the model to describe and never recommend, to use the band names "Higher reliability", "Moderate reliability" and "Lower reliability" exactly, to say "U.S. Census Bureau" on first mention and "Census Bureau" after, and to use plain words with every statistical term explained on first use.

Three outside rules are available. Each is a fixed sentence written by us, and the comparison is done in code:

| Rule | What the code checks | Source in this repo |
|---|---|---|
| ESRI: CV under 0.12 is high reliability, 0.12 to 0.40 medium, over 0.40 low | CV against 0.12 and 0.40 | `docs/glossary.md`, "Reliability threshold conventions" |
| National Center for Health Statistics: CV over 0.30 is flagged | CV against 0.30 | Same glossary entry |
| HUD: a median is usable when its margin of error is under half the estimate | Margin of error against half the estimate, medians only | `docs/user-segments-and-needs.md`, marked "documented" |

The HUD rule has not been checked against a HUD document by this project. It is verified before shipping or dropped.

### Fixed texts (draft wording for review)

- **Disclosure, always shown:** "The wording of these answers is generated by an AI model. Every figure is filled in from this dashboard's data. This is not a statement of the U.S. Census Bureau. Your question is sent to an outside AI service, so do not enter personal information."
- **Redirect, out of scope:** "I can only answer questions about this county's figures on this dashboard. Try one of the buttons above, or ask about a figure, its range, or how the county compares with its state or with similar counties."
- **Redirect, not in dashboard:** "This dashboard does not hold that. It covers population, income, poverty, employment, education, housing, health insurance, disability, language and transportation for 2020 to 2024, by county."
- **Fallback:** "I could not produce an answer that I can check against this dashboard's figures. The figures are on the cards below."
- **Unavailable:** "The AI assistant is not available right now. The dashboard's figures are unaffected."
- **Off:** "The AI assistant is off because no API key is configured. See Streamlit/README.md."

### Model call

- Anthropic Python SDK (`anthropic`), model `claude-haiku-5-5`, read from `ASSISTANT_MODEL`.
- Structured output through `client.messages.parse()` with a Pydantic schema for the four reply fields.
- Effort `low`. Thinking is left at the model's default.
- `max_tokens` 4000. Replies are short, and the model's own reasoning counts against the limit.
- No streaming. A reply must pass the checks before any of it is shown.
- The system prompt and the fact sheet carry cache markers, so follow-up questions about the same county reuse them at a tenth of the input price. The fact sheet is written with sorted keys and no timestamps so it is byte-identical between questions.
- Conversation memory: the last six exchanges, stored as the model's raw text with blanks.
- Current Claude models reject a temperature setting, so the wording cannot be pinned. Reproducibility comes from fixed prompts in the repo, a tested fact sheet, and checks in code.

**Cost estimate.** A question sends about 8,000 input tokens (pieces of words) and returns about 1,000. At Haiku 5.5's listed $0.10 and $0.50 per million tokens, that is about a tenth of a cent per question. This is an estimate from list prices dated 2026-10-06, not a measurement.

**What leaves the machine.** The typed question, the fact sheet (public statistics) and the instructions. No file from `data/raw/` is sent, and nothing is logged to disk in v1.

### Configuration

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Credential, in `.env`, never committed | none; assistant is off |
| `ASSISTANT_MODEL` | Model name | `claude-haiku-5-5` |
| `ASSISTANT_FREE_TEXT` | `0` hides the question box and leaves the three buttons | `1` |

## Components

### `analysis/assistant.py` (pure functions, no Streamlit)

- `is_configured()`: whether a credential is present.
- `PRESETS`: the three ready-made prompts and their button labels.
- `build_system_prompt()`: instructions, scope rules, compact glossary, outside-rule sentences.
- `render_answer(template, fact_sheet)`: fills the blanks.
- `check_answer(reply, fact_sheet)`: checks 4 to 6; returns the first failure or none.
- `ask(client, fact_sheet, on_screen, history, question)`: one question in, one checked reply out, including the retry.

### `Streamlit/app_US_v7.py`

- A copy of `app_US_v6.py` with two additions.
- `_county_fact_sheet(...)`: builds the fact sheet; cached per county.
- `_assistant_fragment(...)`: the panel, in its own fragment so asking a question does not redraw the map.

### `analysis/assistant_eval.py`

About 40 questions across 5 counties: in scope, out of scope, "average income", "is poverty rising?", "do we qualify for CDBG?", an attempt to override the instructions, and a suppressed figure. It reports the share of replies blocked by each check and how often the scope decision was right. It spends money, so it runs only with the lead's approval. Estimated cost on Haiku 5.5 is under $1.

## Error handling

- No credential: the panel shows the "off" text. Nothing else on the page changes.
- Authentication, rate limit, server and network errors are caught by type and show the "unavailable" text.
- A measure missing from local data is marked `not in local data` in the fact sheet, using the existing `_unavailable_measures` guard.
- A county with no similar-county result for a measure simply has no comparison for it.

## Testing

- **Engine, no network (`tests/test_assistant.py`):** blanks fill correctly; an unknown blank, a stray digit and a banned phrase each block the reply; label digits are allowed; out-of-scope replies show only the fixed text; one retry then fallback; refusal, cut-off and error paths; no credential means off.
- **Fact sheet, real data, skipped when data is absent (`tests/test_us_v7_assistant.py`):** Jefferson County, Alabama (`01073`) must match what the v6 cards showed on 2026-10-10: income 66,388, range 64,897 to 67,879, CV 1.4%, score 95 with sampling 97 and imputation 92, Higher reliability band, CV rank 3 of 67, and 18 tied of 237 tested with 196 higher and 23 lower. A county with a suppressed median rent (seven exist) reports `suppressed` and offers no blanks. Two builds for one county are byte-identical. The 26 blank names are unique.
- **App smoke tests:** all three tabs load with and without a credential.
- **Full suite:** `python -m pytest analysis tests -q` stays green (248 passed, 8 skipped on `main` today).
- **Live check:** run v7, select Jefferson County, use the three buttons and the county clerk question, and read every figure against the cards. Confirm the second question reads from the cache.
- **Evaluation:** as above, with results in the WORKLOG. The lead reads 20 answers against the cards.

## Build order

Each phase ends at a checkpoint, and `main` stays shippable after each.

1. **v6 onto `main` as files.** Copy `app_US_v6.py` unchanged, plus `proportion_rate_series` and its test. No branch merge, because `JL_Work_Tree` never took in `main`'s history and a merge would delete 18 files. Justus is told first.
2. **Engine and its tests.** No screen changes, no credential needed.
3. **Fact sheet and panel in v7.**
4. **Live check, evaluation, documentation.**

**Cut line:** if delivery is close, stop after step 3 with the three buttons only and the question box switched off.

## Documentation

- `HANDOFF.md`: decision #20 (base version, model, voice, the no-typed-numbers rule), and landmines found during the build.
- `README.md`: the two mentor questions; Current Scope note.
- `WORKLOG.md`: an entry per phase.
- `docs/glossary.md`: LLM, API key, prompt, system prompt, fact sheet, token.
- `Streamlit/README.md`: a v7 section and how to switch the assistant on.
- `requirements.txt` and `.env.example`: the new package and variables.

## Open questions for mentors

1. Is a panel whose wording is generated by an AI model acceptable in a tool that carries the Census Bureau's name, given that every figure is inserted by code and the panel is labeled as not a Census Bureau statement?
2. Under the neutral-voice direction, is it acceptable for the tool to quote ESRI, NCHS and HUD reliability rules as theirs?

## Risks

- **Timing.** The README milestone table puts weeks 13 to 14 at "Launch Tool". This is a nice-to-have arriving at that stage.
- **Blocked replies.** A small model slips on strict rules more often than a large one, so more replies will be blocked. The evaluation measures the rate. If more than about one in ten button replies is blocked, the recommendation will be to move up a model.
- **Right number, wrong sentence.** The checks stop invented numbers. They do not prove that the surrounding sentence describes a figure correctly. Self-describing blank names reduce this, and the evaluation's human read is the check.
- **v6 wording.** v6 carries 14 em dashes and one "Census" naming slip in user-facing text. v7 inherits them. Fixing them is a small separate task.
