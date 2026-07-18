# Uncertainty sources — plain-English map

Where uncertainty enters Census products we care about, what we can measure
publicly, and how the composite prototype treats each piece. Written for Phase 1
Step 2 and updated after EDA 01–06.

---

## ACS 5-year estimates (sample product)

| Source | What it is | Public signal we use | EDA status |
|--------|------------|----------------------|------------|
| **Sampling error** | Only a sample of households is surveyed | Margin of error → SE = MOE/1.645 → CV = SE/estimate | EDA 01–03; helpers in `analysis/acs.py` |
| **Item nonresponse / imputation** | Missing answers filled in | Item allocation rates (share imputed) | EDA 05; rates in `analysis/alloc.py` |
| **Coverage / nonresponse weighting** | Who is hard to reach | Not separately measured here | Out of scope for prototype |
| **Privacy noise** | ACS is not the 2020 DAS product | — | Do **not** mix into ACS row scores |

**Working composite (EDA 06).** For ACS, combine **sampling CV** and **item
allocation** as two visible axes (income headline). Do not collapse them into a
single official weight yet. Privacy stays on the Decennial track.

---

## Decennial / DHC (full-count product)

| Source | What it is | Public signal we use | EDA status |
|--------|------------|----------------------|------------|
| **Disclosure avoidance (DAS)** | Calibrated privacy noise via TopDown | Demonstration − published SF1 | EDA 04; `analysis/dhc.py` |
| **Coverage error** | People missed or counted twice | Not measured in our public files | Mentor/product discussion |
| **Sampling error** | Full count — not the dominant ACS story | — | N/A as primary ACS analog |

**Working composite boundary.** Empirical privacy RMSE belongs in a **separate
DHC reliability view**, not row-joined onto 2024 ACS tracts (different vintage,
universe, and mechanism).

---

## Why two ACS components (not one)

EDA 05 showed allocation rates are largely **independent of CV** once geography
size is controlled. EDA 06 then showed the practical payoff: about **23%** of
classified NJ tracts have acceptable income CV (≤ 0.30) but high income
allocation — a blind spot if users only look at MOEs.

---

## Provisional thresholds (mentor decisions still open)

- **CV 0.30** — Census ACS quality-standard convention (reference, sourced).
- **Allocation 75th percentile** — exploratory NJ sample flag only.
- **Equal-weight vs worst-component** — sensitivity checks; report
  reclassification, do not lock dashboard weights yet.
