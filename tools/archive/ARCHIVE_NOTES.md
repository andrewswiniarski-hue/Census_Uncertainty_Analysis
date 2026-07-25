# tools/archive/ — Product Scope Tracker, v1 snapshot

Preserved copy of the simpler Product Scope Tracker taken **before the Phase 1/2
redesign** landed on `main`. Kept as a fallback in case a teammate prefers the
plainer version for a specific use case (mentor demo, quick triage, working
around a redesign bug).

## What this is

A byte-for-byte snapshot of the three tool files from commit
[`2db1799`](../../..) — *"product_scope: add --export csv/xlsx for per-product
review"* — the last commit before the eight Phase 1/2 redesign features shipped.

| File in this folder | Extracted from |
|---|---|
| `product_scope_v1.py` | `git show 2db1799:tools/product_scope.py` |
| `scope_evidence_v1.py` | `git show 2db1799:tools/scope_evidence.py` |
| `README_v1.md` | `git show 2db1799:tools/README.md` |

## Date range this version covers

Roughly **2026-07-24 → 2026-07-25**, pre-redesign:

- **Born:** during Garrett's PRODUCT_MATCH-coverage + `--export csv/xlsx` work
  (commits `f93f6db` and `2db1799`, 2026-07-25). Everything from `2db1799`
  backward is what this snapshot preserves.
- **Superseded:** 2026-07-25 by the eight-commit Phase 1/2 redesign
  (`25c5450` → `91be821`). Once that shipped, this became the fallback.

## What v1 has

- Self-contained HTML report with **tabs** (Home / Aggregate tables / Microdata /
  Time series / Unflagged).
- **`--export csv/xlsx`** — writes `product_review.csv` or `product_review.xlsx`,
  one row per product family.
- **`--probe PATH`** and **`--probe-queue FILE`** — API probe support against
  `variables.json` / `geography.json`.
- **`PRODUCT_MATCH` fix** — expanded matchers for DHC, Composite prototype,
  Allocation analysis, CV driver model.
- **Hand-edited `product_review.json`** — same file the current version uses
  (v1 wrote it first, current version adds fields but never overwrites existing
  entries, so state is compatible in both directions).

## What v1 LACKS relative to the current version

The Phase 1/2 redesign added eight features that v1 does not have:

1. **Freshness pill** on every page (age since last regen, color-graded).
2. **Faceted browsing sidebar** on the Products tabs (7 facets with live counts).
3. **Clickable receipts** — evidence `file (line N)` receipts are plain text in
   v1; the current version links them to GitHub blobs or `file://` URLs.
4. **State-driven contextual affordances** — v1 leaves blank sections blank; the
   current version fills them with copyable action commands ("no evidence → run
   this probe", "candidate without probe → run this probe", etc.).
5. **Diff view** — the "Since last regeneration" banner on the Home tab is
   redesign-only; v1 has no `.product_scope_last_run.json` snapshot.
6. **Composite code references** — AST-derived hits from
   `analysis/composite.py`, `cv_model.py`, `alloc.py` on `origin/JL_Work_Tree`
   are redesign-only.
7. **`composite_role` / `composite_role_note` fields** on product reviews —
   v1's `product_review.json` schema has `stage`, `uncertainty_metrics`, and
   `note` only. New fields default to empty in the current tool, so v1 is
   forward-compatible: it will just ignore the extra keys.
8. **Divergence flag** (composite code vs. declared role) — redesign-only.

v1 also lacks Phase 3's **sample/EDA mode** (added later; not part of v1's
scope by definition).

## How to run v1 if you fall back

```powershell
python tools/archive/product_scope_v1.py --repo .
```

Reads the same state files the current tool does — **fully compatible with the
team's committed state**:

- `product_review.json` (v1 will ignore the redesign's new `composite_role` and
  `composite_role_note` keys; existing entries stay untouched).
- `scope_field_cache.json` (same API-catalog cache format).
- `product_probes.json` (same probe result format).

Same flags as the current tool's core: `--repo`, `--online`, `--probe`,
`--probe-queue`, `--export csv|xlsx`, `--out`.

**One caveat about deep forensics:** the archived engine file is named
`scope_evidence_v1.py` (per archive naming convention), but `product_scope_v1.py`
does `from scope_evidence import deep_scan, locate` — so run from the archive
folder, Python won't find the module and the tool silently drops to the shallow
regex-fallback scan. Work-depth will be less reliable. If you want deep
forensics on the fallback, copy the engine alongside the tool without the `_v1`
suffix:

```powershell
copy tools\archive\scope_evidence_v1.py tools\archive\scope_evidence.py
```

Then re-run. (Leave the file if you want it; it doesn't collide with anything.)

## When to consider falling back

- If the current version's UI (faceted sidebar, freshness bar, diff banner,
  divergence blocks) is overwhelming for a specific mentor demo and you want a
  cleaner surface.
- If a redesign feature has a bug that's blocking a team workflow and you need
  a quick, known-working fallback while it gets fixed.
- To reproduce a report as it would have looked on 2026-07-25 pre-redesign
  (e.g., for a "before/after" comparison in the final write-up).

In all other cases, use the current tool at `tools/product_scope.py`. This
archive is a safety net, not a recommended path.
