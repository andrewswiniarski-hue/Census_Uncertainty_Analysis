# Census Bureau branding shell -- design

**Date:** 2026-09-17
**File affected:** `Streamlit/app_US_v2.0.py`
**Related:** [AEM Branding](https://www.census.gov/aem-user-guide/foundations/branding.html), [Corporate Identity Style Guide (Oct 2019)](https://www2.census.gov/about/policies/cb-style-guide.pdf)
**Status:** Approved in chat 2026-09-17 (census.gov-like shell, CV colors unchanged).

## Problem

`app_US_v2.0.py` already loads Roboto and a screenshot-sampled palette
(`#0D54B0` blue, `#FCBE2D` gold). That is close to census.gov but unofficial,
and gold is used as the generic primary button color. In the Census Bureau
AEM system gold is Subscribe-only, not a default CTA.

The app should look like a Census Bureau data tool when shown to mentors,
without claiming to be an official Census Bureau product, and without
recoloring the colorblind-safe CV map.

## Decisions

| Topic | Decision |
|---|---|
| Depth | census.gov-like shell: navy header, official tokens, button roles, naming. |
| Logo | Typeset wordmark "U.S. Census Bureau". No seal. No DOC lockup. Official SVG only if PIO provides it later. |
| Theme file | App-local CSS in `app_US_v2.0.py`. Do not restyle `app_NJ.py` via `.streamlit/config.toml`. |
| Map / CV | `cv_color()` blue-to-orange ramp stays on maps, badges, and interval bars. |
| Type | Keep Roboto. Do not import 62px AEM heroes. Optional Lora is out of this pass. |

## Naming

First on-page mention of the agency is **U.S. Census Bureau** (the header
wordmark). Later copy uses **Census Bureau**. Do not use **the Bureau**,
**Census**, or **BOC** for the agency or its programs.

Welcome lead-in currently says "county-level Census data". Change that to
Census Bureau data. "Once-a-decade Census" becomes "once-a-decade population
count" so "Census" is not used alone.

## Chrome

### Header

HTML banner above the tabs, rendered from `main()`:

- Navy background `#112E51`
- Left: wordmark **U.S. Census Bureau**, then app title **US County Demographic Explorer**
- Right: **Capstone demonstration**
- Second line: **Measuring America: People, Places, and Economy** (colon, not an em dash)

This replaces the Streamlit `st.title(...)` so the title is not duplicated.

### Footer

HTML footer after the tabs:

- Tagline again
- ACS vintage (`ACS_VINTAGE`)
- Link to https://www.census.gov
- Required line: **This is a student capstone demonstration. It is not an official Census Bureau product.**

### Tokens

| Token | Hex | Use |
|---|---|---|
| navy | `#112E51` | header, footer, H1/H2 |
| azul | `#265FCA` | System Command buttons, tab underline, multiselect chips, widget accent (AEM Azul 700) |
| link | `#008392` | links |
| steel | `#4B636E` / `#78909C` | secondary text |
| ice | `#F6FAFF` | optional quiet surfaces |
| ink | `#131313` | body text |
| white | `#FFFFFF` | page background, primary button text |

Primary Streamlit buttons and leftover Streamlit-red widget chrome (tabs,
chips) use Azul 700 `#265FCA` with white text, matching AEM System Command
buttons. Gold `#FCBE2D` must not remain on buttons. PMS blue `#205493`
(Engage) is not used on this app's command buttons.

**2026-09-17 addendum:** User asked to replace remaining red secondary
chrome with Census Azul and to restyle buttons to that color. App-local
CSS overrides `--primary-color` so Streamlit's default red does not leak
onto tabs or the "Choose what to show" chips. `.streamlit/config.toml`
is still shared with `app_NJ.py` and was left alone.

## Out of scope

- Recoloring maps, CV badges, interval bars, peer violet borders
- Card layout or peer-table logic
- Restyling `app_NJ.py`
- Dark mode
- Official logo file or DOC lockup
- Lora body font

## Tests

- Header HTML names U.S. Census Bureau, the app title, Capstone demonstration, and the tagline.
- Footer HTML contains the not-an-official-product sentence and census.gov.
- `_CSS` uses `#112E51` and Azul `#265FCA`, not gold or Streamlit-red primary buttons.
- `cv_color(` remains in `render_map` and `render_card`.
- Welcome copy no longer says "Census data" or "once-a-decade Census".
- `main()` renders the header and footer helpers.

## Risk

A navy Census header without the capstone/not-official lines would overclaim.
Those two strings are required, not optional polish.
