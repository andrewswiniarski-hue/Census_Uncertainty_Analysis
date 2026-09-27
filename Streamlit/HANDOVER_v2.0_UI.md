# Handover: US County Demographic Explorer, structural UI work (v2.0 → v4)

**First written:** 2026-09-17 for `app_US_v2.0.py`. **Updated:** 2026-09-27,
end of session, for `app_US_v4.py`.
**For:** a fresh chat picking this up.
**Purpose of this doc:** enough context to keep making *structural UI changes*
to `Streamlit/app_US_v4.py` without re-deriving the last several sessions'
decisions. Paste this whole file as the first message in the new chat.

---

## 1. What this app is

Nationwide (50 states + DC) county-level ACS demographic explorer, built for
a Census Bureau capstone. State-first drill-down: pick/click a state → see
its counties on a map → click/search a county → read its ACS estimates as
cards, each with an explicit margin of error (MOE), coefficient of variation
(CV), a visible uncertainty interval, and (since v3) a descriptive
reliability score band. Neutral federal-statistical-agency voice by sponsor
direction: no "good/bad" verdict language — the app shows the number and
the uncertainty and lets the user judge it.

## 2. File lineage — READ THIS BEFORE ASSUMING WHICH FILE IS "THE APP"

**`Streamlit/app_US_v4.py` is the file to keep iterating on.** Older
versions are kept unchanged as snapshots:

| File | Where | What it uniquely has |
|---|---|---|
| `app_US_v1.1.py` | worktree | Justus's original nationwide explorer: filters, statistical peers, ACS variable-expansion checklist. |
| `app_US_v1.2.py` | worktree | Katie Christiansen's redesigned `render_welcome()`; otherwise v1.1. |
| `app_US_v2.0.py` | worktree (commit `ee62625`) | Andrew's card redesign (Sep 14) + Justus's Sep 17–18 work: Statistical peers tab, Census Bureau branding, map tooltips, peer-table CV column, performance work, ACS 1-year captions removed. |
| `app_US_v2.py` / `app_US_v3.py` | **`origin/main` only** | Andrew's line. v2 adds "Compare to state" toggles, state row under the county bar, blue-purple-orange CV ramp. v3 adds the card reliability score (lead decision #19). Neither has Justus's v2.0 work. |
| **`app_US_v4.py`** | **worktree** | **main's v3 + everything from v2.0 + this session's changes (§3).** |

v4 was built by a file-level three-way merge (base: `2fadc2f:Streamlit/app_US_v2.py`,
the Sep 14 version both lines started from). **The branches themselves were
never merged**; `JL_Work_Tree` does not contain main's history. Where the two
lines conflicted, v3's card/colour code won:

- CV ramp is `cv_color_blue_orange()` (main), not v2.0's `cv_color()`.
- ACS 1-year precision captions on the population/income cards are **kept**
  in v4 (v2.0 removed them; that removal was scoped to v2.0 only).

`tests/test_us_branding.py::test_cv_color_stays_on_map_and_cards` targets
v2.0 and asserts `cv_color(`; it would fail if pointed at v4, by design.

## 3. What was done in the 2026-09-27 session

1. Pulled main's `app_US_v3.py` plus the two analysis modules it needs
   (`analysis/composite.py`, `analysis/dashboard.py`) into the worktree.
   Data was already local (`data/raw/*usdash*`, `rucc_2023_county`).
2. Restored `proportion_rate_series()` in `analysis/dashboard.py` (main's
   version lacked it; v2.0's vectorized code and `analysis/test_dashboard.py`
   need it). v2.0 runs again.
3. Merged v2.0's work into v3 (now v4): peers tab + shared selection,
   branding shell, tooltips, peer-table formatting, and the performance work
   (tabs render only when open via `st.tabs(on_change="rerun")`, fragments,
   GeoJSON indexed by key, vectorized rates, cached `_unavailable_measures`).
   Also fixed one v3 string ("the Bureau's" → "the Census Bureau's") per
   the naming rule.
4. **Toggle/checkbox CSS fix.** The branding rule
   `[data-testid="stCheckbox"] [data-selected] div:has(svg)` also matched
   the *label* of `st.toggle` (its help "?" icon is an SVG) and painted the
   "Compare to state" text azul, while the toggle track was never targeted
   and fell back to Streamlit red whenever the repo's
   `.streamlit/config.toml` isn't picked up (e.g. launching from inside
   `Streamlit/`). Now: `label[data-selected] > div:has(> svg)` (checkbox box
   only) plus an explicit rule for the switch track. Verified in a browser
   with and without the repo config.
5. **Card CV rank.** "This county's CV is in the Nth percentile of the M
   counties in the current filter selection" → "This county's CV ranks Nth
   of the M counties in <State> (1st is the lowest CV)". Pool = every county
   in the selected county's state, independent of the explorer filters.
   Still ranks the **CV**, not the estimate (user may later want the
   estimate ranked instead — one-line change in `_rank_and_n`).
6. **County explorer layout.** Filters, geography search, and "Color the map
   by" now sit in a fixed-height bordered panel on the left
   (`EXPLORER_PANEL_HEIGHT = 560`, matched to title caption + 520px map),
   level with a ~2.6× wider map on the right. The filter expander and its
   four-across row are gone.

Verification each step: `py_compile`; `pytest analysis/test_dashboard.py
tests/test_us_branding.py tests/test_us_peer_table.py tests/test_us_map_tooltip.py`
(76 passed, 6 skipped); main's `tests/test_us_v3_score.py` run against the
merged file (15 passed); AppTest smoke on all three tabs using Jefferson
County, AL `01073` (Autauga `01001` is under the 65k ACS 1-year threshold,
so it has no 1-year caption).

### Git state (2026-09-27)
Committed and pushed to `origin/JL_Work_Tree`: `Streamlit/app_US_v4.py`,
this handover, `analysis/composite.py`, `analysis/dashboard.py`,
`analysis/test_dashboard.py`. `Streamlit/app_US_v3.py` was unstaged and is
not in the worktree (it lives on main). Everything else in `git status`
(teammates' `HANDOFF.md`/`README.md`/`WORKLOG.md`/notebook changes from an
earlier pull, `ingestion/*` edits, untracked `pages/`, `Archived Models/`)
was **not** touched or committed — ask before including any of it.

### Data dependency
Needs `data/raw/{acs5_2024_usdash,acs1_2024_usdash,geo_2024_usdash,
acs5_2024_usdash_alloc,rucc_2023}_*` (gitignored). Regenerate with the
ingestion scripts listed in v4's module docstring. `_unavailable_measures()`
hides cards whose columns are missing rather than crashing.

## 4. Code map (`Streamlit/app_US_v4.py`, ~2,940 lines)

- **`Measure` + `MEASURES` registry** (`_build_measures()`, ~354–473): every
  card/map measure goes through this. `MEASURE_OPTIONS` / `_measure_display()`
  drive the map dropdown, card checklist, and peer measure picker.
- **Reliability score** (`ImputationSource`, ~224; `score_for`,
  `_score_strip_html`, `_score_note_html`, `_score_breakdown_html`,
  ~1401–1460): band strip on each card; rules in `analysis/composite.py`.
- **`_CSS`** (~570) + `_brand_header_html()` / `_brand_footer_html()`
  (~701–730): Census Bureau shell (navy `#112E51`, Azul `#265FCA`, teal links),
  including the tab/checkbox/toggle overrides from §3.4.
- **`_load_all()`** (~745) and `_load_acs1_county()` (~799): cached data;
  geo frames carry `_key`.
- **Map plumbing:** `_map_tooltip`, `_base_geojson`, `_base_geojson_by_key`
  (~807–866), `_measure_layer` (~870, vectorized), `render_map` (~1745,
  optional `map_key`, `interactive`, `click_caption`).
- **Peers:** `_peer_values`, `PeerResult`, `_compute_peers` (~952–1030);
  `render_peer_panel` (~2241), `_peer_geo_controls` (~2338, cascading
  State → County writing shared `us_geo`), `render_peers_tab` (~2429, peer map
  hidden until "Show these counties on the map", display-only).
- **`top_filters()`** (~1033): now a vertical stack (back button, search slot,
  RUCC, population size, count, RUCC note) for the left panel.
- **`render_card()`** (~1463): `cv_rank`/`rank_n`/`rank_scope`,
  `reference` + "Compare to state" toggle, `acs1_compare`, `reliability`.
- **County explorer:** `_explorer_top_fragment` (~2511: left panel + map in
  `st.columns([1, 2.6])`; filter/colour changes rerun only this fragment,
  geography changes call `st.rerun()`), `_explorer_map` (~2571),
  `_explorer_cards_fragment` (~2605: checklist + cards; CV rank pool is the
  county's whole state), `render_explorer` (~2870).
- **`main()`** (~2908): header → `st.tabs(["Welcome", "County explorer",
  "Statistical peers"], on_change="rerun", key="main_tabs")`, each body
  gated on `tab.open` → footer.

### Session state schema
- `st.session_state["us_geo"]`: `{level: "state"|"county", code, state_scope}`
  — shared by County explorer and Statistical peers. (`peer_focus` is gone.)
- `_us_geo_version`: bumped on every map click/search/peer-dropdown change;
  part of dropdown widget keys so they re-seed instead of fighting.
- `peer_map_visible`: peer-tab map reveal flag.
- Widget keys of note: `main_tabs`, `acs_map_measure`, `card_checklist`,
  `filter_rucc`, `filter_pop`, `cmp_state::<measure>`, `peer_measure`,
  `peer_same_rucc`, `peer_same_popbin`, `peer_tab_state_<v>`,
  `peer_tab_county_<v>_<state>`, `peer_map_show`, `peer_map_hide`.

## 5. Conventions this project enforces (don't skip these)

- **Read-first, flag-ambiguity, verify-after.** Before editing, report back
  current structure + anything ambiguous. After editing: `py_compile`, grep
  for dead references, run an `AppTest` smoke pass, summarize what changed
  and what was flagged/skipped.
- **No wholesale rewrites.** Edit surgically; don't touch data-loading or
  computation logic unless a change explicitly requires it.
- **Dollar signs in `st.markdown`/`st.info` text must be escaped as `\\$`**
  (bare `$` is a LaTeX delimiter in Streamlit markdown).
- **Naming:** first mention "U.S. Census Bureau", later "Census Bureau".
  Never "the Bureau", "Census" alone, or "BOC".
- **AppTest tips:** load dotted file names with
  `importlib.util.spec_from_file_location` and register in `sys.modules`
  before executing. Open a tab by setting `session_state["main_tabs"]` in a
  **fresh** AppTest session — switching it mid-session snaps back on the next
  widget interaction (harness quirk; real browser clicks are fine).
  Selectboxes with `format_func` need `select_index()`, not `set_value()`.
- **PowerShell, not bash.** No `&&`, no heredocs; `>` writes UTF-16 (use
  Python or `Out-File -Encoding utf8` for files git will read).
- **`WORKLOG.md`** is the team's running log (newest on top). Worth an entry
  for anything structural.
- **Term definitions on first use**, per the project's `CLAUDE.md`.

## 6. Open threads / ideas not yet decided

- CV rank ranks the CV; ranking the estimate itself was not chosen yet.
- Stakeholder-specific tabs vs one dashboard: still resolved via the opt-in
  card checklist; Welcome page could carry audience-specific guidance.
- The "Viewing: national (all states)" status button is styled as an Azul
  command button; could become plain text.
- Main's `tests/test_us_v3_score.py` is not in the worktree; a v4 copy of it
  (and v4 versions of the branding/peer/tooltip tests) would be worth adding.

## 7. Suggested first step in the new chat

Ask the user what specific change they want next before editing — this doc
gives the "where things are," not a plan for "what's next."
