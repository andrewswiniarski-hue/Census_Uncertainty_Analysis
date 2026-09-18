# Statistical peers tab -- design

**Date:** 2026-09-17
**File affected:** `Streamlit/app_US_v2.0.py`
**Related copy:** `Streamlit/HANDOVER_v2.0_UI.md` (session context only; not required for the code change)
**Status:** Approved in chat 2026-09-17. Spec written for review before the implementation plan.

## Problem

Statistical peers currently live at the bottom of the County explorer tab
and share that tab's map. Two couplings make the explorer map do two jobs:

1. Violet peer borders on the choropleth whenever a peer measure is chosen.
2. **Show these counties on the map**, which sets `geo["peer_focus"]` and
   replaces the state county map with a national view of the selected
   county plus its tied peers.

The user wants Statistical peers on its own tab, with its own map, and
wants County explorer to go back to a plain state/county drill-down.

## Decisions already made

| Topic | Decision |
|---|---|
| County selection | Shared `st.session_state["us_geo"]` with County explorer. |
| Geography picker on the new tab | Cascading State, then County dropdowns at the top. These can create a selection if none exists yet. |
| Peer map contents | Selected county plus tied peers only, framed nationally. Fill is CV of the peer measure chosen on this tab. Dark border on the selected county, violet border on peers. |
| Map placement | Below the table and the show/hide controls. Hidden until **Show these counties on the map**. |
| Map clicks | Display-only. Clicks do not change the selected county. |
| Explorer map | No `peer_keys`, no `peer_focus` view, no peer legend. |
| Computation | `_compute_peers()` / `statistical_peers()` unchanged. |

## Out of scope

- Stakeholder-specific tabs, card-checklist UX, Welcome-page audience
  guidance beyond the one expander that currently points at Statistical
  peers.
- Changing the peer test, RUCC/population gating, or the peer table.
- `st.navigation` / multipage split.
- Committing or pushing. The app file is still untracked; do not commit
  unless the user asks.

## Architecture

Keep `st.tabs` in `main()`. Three tabs, in this order:

1. Welcome
2. County explorer
3. Statistical peers

`_load_all()` stays in `main()` before the tabs, so both explorer and
peers share one data load.

Streamlit still runs every tab body on every rerun. That is accepted.
The two maps must use **different widget keys** so they cannot collide.
The peer map is not constructed until `peer_map_visible` is true, so the
extra pydeck chart is not paid for until the user reveals it.

Shared geography state (`us_geo`) keeps these fields:

- `level`: `"state"` or `"county"`
- `code`: selected geography key, or `None`
- `state_scope`: selected state's key when drilled into counties

`peer_focus` is removed from `us_geo` and from every writer that currently
clears or sets it.

Map reveal is a tab-local flag:

- `st.session_state["peer_map_visible"]`, default `False`

## Statistical peers tab

New function: `render_peers_tab(data: dict) -> None`.
Called from `main()` inside the third tab. It calls `_init_geo_state()`
so the tab is usable even if the user never opened County explorer.

### 1. State, then County

Two `st.selectbox` controls at the top.

- **State** lists every state in `data["state_df"]`, formatted with
  `data["labels_state"]`.
- **County** lists counties in the chosen state from the **full**
  `data["county_df"]` (not explorer RUCC/population filters). Peers are
  not gated by those filters; the picker should not be either.
- Widget keys: `peer_tab_state` and `peer_tab_county`, including
  `_us_geo_version` in the key the same way `geography_search_control()`
  does, so a map click or search on County explorer re-seeds these
  dropdowns instead of fighting them.
- Changing State or County writes `us_geo` (`level="county"`,
  `state_scope`, `code`) and increments `_us_geo_version`.
- Changing State to a state that does not contain the current county
  clears `code` until a county is chosen. Placeholder: "Select a county".
- If `us_geo` already has a county (user came from County explorer), both
  dropdowns seed to that state and county.

No "go back to County explorer first" dead end. If nothing is selected
yet, the dropdowns are how the user picks a county. Until a county is
chosen, show a short `st.info` and do not render the peer controls.

### 2. Peer controls, headline, table

Reuse the existing `render_peer_panel()` body, minus map coupling:

- Measure selectbox (`key="peer_measure"`), same metro/nonmetro
  (`peer_same_rucc`), same population-size bin (`peer_same_popbin`).
- Existing empty / missing-MOE / zero-tie copy stays, except the caption
  that currently says peers are "not the map filters above". Rewrite to
  say peers are drawn from all U.S. counties, optionally narrowed by the
  two checkboxes, not by County explorer's map filters.
- Table, distance-for-readability caption, higher/lower counts: unchanged.

`render_peer_panel()` currently takes `geo` only to set `peer_focus`.
Drop the `geo` argument. It renders the measure/checkbox controls, the
headline, and the table, then returns `PeerResult | None` so the caller
can own show/hide and the map. Do not duplicate `_compute_peers()`.

The early peek of `peer_measure` / checkboxes at the top of
`render_explorer()` is deleted. Those widgets now live only on this tab.
The peek trick existed solely to color the explorer map.

### 3. Show / hide map

Order: table, then buttons, then map. Buttons live in `render_peers_tab()`,
after `render_peer_panel()` returns, so the panel never writes map state.

- **Show these counties on the map** (`key="peer_map_show"`). Disabled when
  the returned result is `None` or the tie set is empty (`n_tied == 0`).
  Sets `peer_map_visible = True` and reruns.
- **Hide peer map** shown only when `peer_map_visible` is true. Sets
  `peer_map_visible = False` and reruns. Replaces **Exit peer view, back
  to state map**, whose wording no longer applies.
- If the user changes county or measure while the map is visible, keep it
  visible and recompute the peer set. If the new tie set is empty, set
  `peer_map_visible = False` (nothing to draw).

### 4. Peer map (only when revealed)

Call the existing `render_map()` with:

- `level="county"`
- `keys_in_scope` = selected county key union tied peer keys
- `cv_by_key` from `_measure_layer()` on that subset, using the **peer
  measure** chosen on this tab (not `acs_map_measure`)
- `selected_key` = current county
- `peer_keys` = tied peer keys
- `view_state` = `_state_view(geo_gdf)` on that subset, else `NATIONAL_VIEW`
- `controlled_keys` as today
- **New args** (see below): unique `map_key="geo_map_peers"`,
  `interactive=False`, no "click a state or county" caption

Legend: keep the CV ramp. Keep the violet "statistical peer" swatch.
Change "measure chosen below" to "measure chosen above", because the
map now sits under the controls. Dark selected-county border still comes
from `selected_key`, not from `peer_keys`.

Clicks are ignored. Do not write `_us_map_last_picked`. Do not update
`us_geo`.

## County explorer

In `render_explorer()`:

- Delete the pre-map `_compute_peers()` peek and `peer_keys`.
- Delete the `peer_focus` branch that subsets the map to selected + peers.
- Call `render_map()` without `peer_keys` (or with `None`).
- Stop calling `render_peer_panel()` at the bottom.
- State-click handler: stop passing `peer_focus=False` (field gone).
- `top_filters()` "Back to national state view": stop passing
  `peer_focus=False`.

`_init_geo_state()` no longer seeds `peer_focus`. Existing sessions that
still have the key in `us_geo` may leave a stale field; ignore it, do not
read it.

## `render_map()` API

Add optional parameters. Keep current explorer behavior as the default.

- `map_key: str | None = None`. If omitted, keep today's
  `f"geo_map_{level}"` so the explorer map is unchanged.
- `interactive: bool = True`. When `False`: `pickable=False` (or
  `on_select` ignored) and return `None` without treating a click as a
  selection.
- `click_caption: str | None`. If `None` and `interactive` is true, keep
  today's "Click a state or county..." caption. If `interactive` is
  false, omit that caption. Allow an explicit override later if needed.

Do not fork a second choropleth helper.

## Welcome copy

In `render_welcome()`, expander **"Which counties are statistically
similar to mine?"**: replace "Use **Statistical peers** below the county
cards" with copy that points at the **Statistical peers** tab. Keep the
definition of statistical indistinguishability at 90% confidence and the
"size of the group is a reliability signal" paragraph.

## Testing

PowerShell. No bash `&&` / heredocs.

1. `python -m py_compile Streamlit/app_US_v2.0.py`
2. Grep `app_US_v2.0.py` for `peer_focus`, explorer `peer_keys=`, and
   `render_peer_panel(` call sites. `peer_focus` should be gone.
   `render_peer_panel` should be called only from `render_peers_tab`.
   Explorer `render_map` should not pass a live peer set.
3. `AppTest` smoke, loaded via `importlib.util.spec_from_file_location`
   with `sys.modules[name] = mod` before execute:
   - App loads with three tabs.
   - Drill to Autauga County, AL (`01001`) on County explorer.
   - Statistical peers seeds State=Alabama, County=Autauga County.
   - Choose a peer measure; table renders; map is absent until Show.
   - After Show, a map is present; explorer map still has no peer subset.
   - No exception.

## Success criteria

- County explorer map never enters a peer-only view and never draws
  violet peer borders.
- Statistical peers is a third top-level tab.
- Shared county selection works in both directions (explorer map/search
  and the new State/County dropdowns).
- Peer map appears only after Show, only as selected + tied peers,
  colored by CV of the peer measure, and does not change selection.
- `_compute_peers()` / `statistical_peers()` are not rewritten.
