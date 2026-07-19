# Uncertainty sources — plain-English map

Where uncertainty enters Census products we care about, what we can measure
publicly, and how the composite prototype treats each piece. Written for Phase 1
Step 2 and updated through EDA 01–07.

Teaching diagram for ACS wide vs long `variable_group` rows:
[`acs-data-shape-diagram.md`](acs-data-shape-diagram.md).

---

## ACS 5-year estimates (sample product)

| Source | What it is | Public signal we use | EDA status |
|--------|------------|----------------------|------------|
| **Sampling error** | Only a sample of households is surveyed | Margin of error → SE = MOE/1.645 → CV = SE/estimate | EDA 01–03, **07**; helpers in `analysis/acs.py`, `analysis/cv_model.py` |
| **Item nonresponse / imputation** | Missing answers filled in | Item allocation rates (share imputed) | EDA 05; rates in `analysis/alloc.py` |
| **Coverage / nonresponse weighting** | Who is hard to reach | Not separately measured here | Out of scope for prototype |
| **Privacy noise** | ACS is not the 2020 DAS product | — | Do **not** mix into ACS row scores |

**Working composite (EDA 06–07).** For ACS, combine **sampling CV** and **item
allocation** as two visible axes (income headline). Do not collapse them into a
single official weight yet. Privacy stays on the Decennial track. EDA 07 adds
that the sampling axis is driven mainly by **estimate size** (and variable
group), not place population; optional `cv_residual_high` flags CVs worse than
expected given size (stronger for counts than for income medians).

---

## EDA 07 — What drives sampling CV

Nested OLS on a long NJ frame (one row per geography × variable group;
n ≈ 24,947). See [`notebooks/07-cv-driver-model.ipynb`](../notebooks/07-cv-driver-model.ipynb).

| Model | R² (approx.) | Takeaway |
|-------|--------------|----------|
| `log(CV) ~ log(place_pop)` | 0.005 | Place population alone fails (JL Final Takeaway reproduced) |
| `log(CV) ~ log(estimate_size)` | 0.67 | Size of the estimate is the main continuous driver |
| + geography level + variable group | 0.71 | Scale and variable type still add signal |
| + size × variable interactions | 0.73 | Slopes differ by variable (e.g. poverty flatter than counts that follow 1/√N) |

**Definitions used**

- `place_pop` = total population of the geography (`B01003_001E`)
- `estimate_size` = the published count for count variables; for **income** =
  household universe (`B99192_001E`), never the dollar median
- `variable_group` = which estimate the row is about (population / income /
  poverty / black65_agg / black65_cell) — not a Census field; see
  [`acs-data-shape-diagram.md`](acs-data-shape-diagram.md)
- `level` = county / tract / block group (poverty and Black 65+ stop at tract)

**Matched estimate-size panel.** At similar count magnitudes, Black 65+ still
has higher median CV than total population (~0.28 vs ~0.17 in mid-size bins) —
size matters, but variable/table structure still matters.

**Composite V2 note.** `cv_residual_high` flags CVs worse than predicted from
estimate size. Informative for **count** estimates; weak for income medians
(income-only size-model R² ≈ 0.01), so for income it mostly tracks raw high CV.

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

EDA 07 clarifies the sampling half of that score: high CV is usually “this
*estimate* is small / this variable type is hard,” not merely “this *place* has
few people.”

---

## Provisional thresholds (mentor decisions still open)

- **CV 0.30** — Census ACS quality-standard convention (reference, sourced).
- **Allocation 75th percentile** — exploratory NJ sample flag only.
- **Equal-weight vs worst-component** — sensitivity checks; report
  reclassification, do not lock dashboard weights yet.
- **Residual sampling flags** — use alongside raw CV for count variables?
  Prefer raw CV only for income medians given the weak size model?
