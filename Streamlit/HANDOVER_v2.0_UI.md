# Handover: `app_US_v2.0.py` structural UI work

**Written:** 2026-09-17, end of session. **For:** a fresh chat picking this up.
**Purpose of this doc:** enough context to keep making *structural UI changes*
to `Streamlit/app_US_v2.0.py` without re-deriving the last several sessions'
decisions. Paste this whole file as the first message in the new chat.

---

## 1. What this app is

Nationwide (50 states + DC) county-level ACS demographic explorer, built for
a Census Bureau capstone. State-first drill-down: pick/click a state → see
its counties on a map → click/search a county → read its ACS estimates as
cards, each with an explicit margin of error (MOE), coefficient of variation
(CV), and a visible uncertainty interval. Neutral federal-statistical-agency
voice by sponsor direction: no "good/bad" verdict language, no tier chips —
the app shows the number and the uncertainty and lets the user judge it.

## 2. File lineage — READ THIS BEFORE ASSUMING WHICH FILE IS "THE APP"

`Streamlit/` currently has three versions of this app, in effect three
branches of the same idea, **not merged**:

| File | Author | What it uniquely has |
|---|---|---|
| `app_US_v1.1.py` | Justus (you) | The original nationwide explorer: filters-on-top, statistical peer counties, ACS variable-expansion checklist, blue→orange `cv_color()` ramp. Base that v2.0 is built on. |
| `app_US_v1.2.py` | Katie Christiansen | Only difference from v1.1: a redesigned `render_welcome()`. |
| **`app_US_v2.0.py`** | **Andrew Swiniarski's card redesign + scope expansion, layered on v1.1 + v1.2's welcome page** | The interval-bar graphic (`_interval_svg`, zero-anchored SVG axis, replaces a matplotlib figure), state-reference/modelled-rate markers on cards, 7 more measures (low income, unemployment, rent burden ×2, home value, no-diploma, disability), `_unavailable_measures()` guard for stale local data. **This is the file the user wants to keep iterating on.** |

`app_US_v2.0.py` is **currently untracked in git** (`git status` shows `??`).
It was assembled by hand (not a clean merge) — see its module docstring for
the full provenance note. Do not assume `git log` history for this file
reflects its real authorship; check the docstring instead.

Also present, not part of this thread of work: `Streamlit/app.py` (deleted
in the working tree per `git status`, likely superseded), `Streamlit/pages/`
(untracked), `Streamlit/Archived Models/` (untracked).

## 3. Where things stand as of this session's end

Just completed: ACS 1-year precision captions were removed from v2.0
(population and income cards). v1.1/v1.2 and the ACS 1-year parquet pull
are unchanged.

Previously completed: reverted `app_US_v2.0.py`'s CV color ramp from
`cv_color_sequential()` (single-hue blue, Andrew's choice) back to
`cv_color()` (diverging blue→orange, v1.1's original), at the user's
request, for consistency across app versions. Four call sites changed
(interval SVG fill, card CV badge, map choropleth fill, map legend
swatches/caption) plus the now-unused `cv_color_sequential` import removed
and the module docstring's provenance note updated. Verified: `py_compile`
clean, `AppTest` smoke run (load + drill into Autauga County AL `01001`)
raises no exception. **Not committed** — file is still untracked.

`analysis/dashboard.py` still defines BOTH `cv_color()` and
`cv_color_sequential()` (plus `CV_SEQ_STOPS`, `CV_COLOR_CONTROLLED`) —
untouched, so nothing was removed from the shared module, just unwired
from this one file. `cv_color()` is what `app_US_v1.1.py`/`v1.2.py` use too.

### Git state to know about (as of 2026-09-17)
```
 M HANDOFF.md, README.md, WORKLOG.md, docs/data-dictionary.md
 D Streamlit/app.py
 D notebooks/10,11,12 (dhc-* notebooks)
M  analysis/dashboard.py, analysis/test_dashboard.py           <- staged
M  ingestion/_common.py, pull_usdash.py, pull_usdash_alloc.py  <- staged
?? Streamlit/app_US_v2.0.py                                    <- THIS FILE, untracked
?? Streamlit/pages/, Streamlit/Archived Models/, notebooks/DHC Archive/
?? ingestion/pull_acs_vrt_nj.py, ingestion/pull_njdash.py
```
The 5 staged files (`analysis/dashboard.py`, `analysis/test_dashboard.py`,
`ingestion/_common.py`, `ingestion/pull_usdash.py`,
`ingestion/pull_usdash_alloc.py`) were cherry-picked from
`origin/card-error-bar-redesign` earlier this session specifically so
`app_US_v2.0.py`'s imports resolve and its 7 new measures have data. **User
said "leave them staged, don't commit/push yet."** Don't commit on their
behalf without asking again — check whether that's changed.

The rest of the modified/deleted files (`HANDOFF.md`, `README.md`,
`WORKLOG.md`, the notebooks) came from a `git pull` bringing in teammates'
changes — not something this session touched or fully audited. Don't assume
they're related to the app work; `git diff` them if they become relevant.

### Data dependency
`data/raw/acs5_2024_usdash_{state,county}.parquet` (gitignored) were
re-pulled this session via `python ingestion/pull_usdash.py` (~230s) to add
the 6 new ACS tables (C17002, B23025, B25070, B25077, B15003, B18101) that
`app_US_v2.0.py`'s new measures need. If a fresh clone/worktree is ever
used, that pull has to be re-run before v2.0 will show all cards — it
degrades gracefully otherwise (`_unavailable_measures()` hides cards whose
columns are missing rather than crashing).

## 4. Code map (`Streamlit/app_US_v2.0.py`, ~2286 lines)

- **`Measure` dataclass + `MEASURES` registry** (`_build_measures()`,
  ~line 190-413): every card/map measure (label, accessor `Callable`,
  universe for rate measures, table_id, unit_suffix, reference_mode
  `"direct"|"rate"|None`, `controlled_when_moe_missing`) goes through this
  registry. `MEASURE_OPTIONS` / `_measure_display()` drive both the map
  dropdown and the card checklist — adding a new measure means adding one
  entry here, not new bespoke UI code, *unless* it needs special wiring
  like population/income do.
- **Peer counties** (`_peer_values`, `PeerResult`, `_compute_peers`,
  `render_peer_panel`, ~line 714-800 + 1776-1892): "statistical peers" —
  counties tied with the selected one on the Census Bureau's two-sample
  difference test, gated by RUCC metro/nonmetro + population bin. Renders
  below the cards in `render_explorer`.
- **`render_card()`** (~1115-1345): the single-measure card. Takes
  `compact=True` from the generic path; population/income cards are
  hand-rolled separately (see below) so they get side-by-side columns +
  extra state/1yr/allocation panels the generic path doesn't have.
- **`render_map()`** (~1357-1503): pydeck GeoJsonLayer choropleth, colored
  by `cv_color()` (just reverted, see §3), with peer-county violet borders
  and controlled-estimate tan fill as special cases layered on top of the
  ramp.
- **`top_filters()`** (~801-882): the top-of-page filter expander (region/
  division filters were already removed pre-v2.0; current filters are
  RUCC metro/nonmetro + population-size bin, cascading with N-shown).
- **`render_welcome()`** (~1591-1776): first tab, Katie's redesign,
  "Start here" 3-column quick links + drill-down sections.
- **`render_explorer()`** (~1893-2266): the main tab. Order: top_filters →
  peer pre-computation (peeks `st.session_state` for widgets not yet drawn,
  see the big comment at line ~1900) → map → geography search → county
  header/ACS-1yr wiring → `st.multiselect` **card checklist** (default:
  just Total population + Median household income, everything else opt-in,
  ~19 measures total) → population/income cards side-by-side → remaining
  selected cards grouped by `TOPIC_ORDER` (line 2244: Population, Poverty,
  Income, Employment, Education, Housing, Health, Disability, Language,
  Transportation), 4-per-row → `render_peer_panel()` behind a divider.
- **`main()`** (~2268-2283): `st.html(_CSS)` → title/caption →
  `st.tabs(["Welcome", "County explorer"])`. **Only two tabs exist.**
- **`_CSS`** constant (search for it near the top of the file): single
  consolidated CSS block, Census Bureau-derived typography/color palette,
  injected once via `st.html()`.

### Session state schema
- `st.session_state["us_geo"]`: `{level: "state"|"county", code, state_scope,
  peer_focus: bool}` — the drill-down position. `_init_geo_state()` seeds it.
- `st.session_state["_us_geo_version"]`: incremented on every map click, used
  to force-reset the geography-search dropdown's widget key so it doesn't
  show a stale selection.
- Widget keys of note: `acs_map_measure`, `card_checklist`, `peer_measure`,
  `peer_same_rucc`, `peer_same_popbin`, `filter_rucc`, `filter_pop`.

## 5. Conventions this project enforces (don't skip these)

- **Read-first, flag-ambiguity, verify-after.** Before editing, report back
  current structure + anything ambiguous. After editing: `py_compile`, grep
  for dead references, run an `AppTest` smoke pass, summarize what changed
  and what was flagged/skipped.
- **No wholesale rewrites.** Edit surgically; don't touch data-loading or
  computation logic unless a change explicitly requires it.
- **Dollar signs in `st.markdown`/`st.info` text must be escaped as `\\$`**
  — Streamlit's markdown treats bare `$` as LaTeX math delimiters, which
  silently breaks the font and drops the currency symbol on income-band
  card titles etc. Already fixed everywhere in v2.0's ancestor files; watch
  for regressions in new copy.
- **`app_US_v2.0.py` has a dot in its "module name"** — `import app_US_v2`
  doesn't work. For any scripted testing, load it with
  `importlib.util.spec_from_file_location` + `module_from_spec`, AND
  register it in `sys.modules[name] = mod` before executing (skipping the
  `sys.modules` step throws a confusing `AttributeError` from `dataclasses`).
- **PowerShell, not bash.** No `&&` chaining (use `;` or separate calls), no
  heredocs (`<<'EOF'` fails) — write multi-line scripts/commit messages to a
  temp file and run/`git commit -F` it instead.
- **`WORKLOG.md`** is the team's running log (newest entries on top, dated,
  attributed). Not required for every micro-edit but worth checking before
  a session to see teammates' latest context, and worth an entry for
  anything structural.
- **Term definitions on first use** — no statistics jargon without a
  one-line plain-English definition, per the project's `CLAUDE.md` (not
  read this session, but referenced repeatedly in `WORKLOG.md`/`HANDOFF.md`
  — worth reading if not already).

## 6. Prior brainstorming relevant to "structural UI changes"

The user has NOT yet specified exactly what structural change they want
next — this handover was requested right after the color-ramp revert, before
a new ask was made. Context from earlier sessions that's likely relevant
background for whatever comes next:

- We discussed **scope expansion to more stakeholders** (local government/
  urban planning, business/econ dev, community/social services, real
  estate/housing, education/healthcare) and debated **one dashboard vs.
  stakeholder-specific tabs**. No decision was made — the resolution taken
  so far is the opt-in **card checklist** (§4) rather than separate tabs,
  keeping "County explorer" as a single surface. If the next structural
  change revisits multi-tab-by-audience, that's a bigger architectural
  shift (would touch `main()`'s `st.tabs()`, `render_welcome()`'s guidance
  copy, and possibly split `render_explorer()`).
- The **Welcome page** was flagged as the natural place to instruct
  different user types on how to use the app for their use case — not yet
  implemented beyond Katie's general-purpose redesign.
- **Statistical peers** (§4) was the last major structural feature added
  (2026-08-30) — grant-writing/"find similar counties" use case. If further
  peer-related UI work is wanted (e.g., promoting it out of "below the
  cards, behind a divider" into a more prominent structural position),
  `render_peer_panel()` and its call site at the end of `render_explorer()`
  are the places to look.
- Card redesign (interval SVG, CV badge, removed redundant range line) is
  considered DONE per the user's last explicit sign-off — don't re-open
  without a new ask.

## 7. Suggested first step in the new chat

Ask the user what specific structural UI change they want (e.g.: multi-tab
by stakeholder, reorganizing the card-checklist UX, promoting peer counties,
something else entirely) before making changes — this doc gives the "where
things are," not a plan for "what's next."
