# Implementation Report - Granular Error Drivers Notebook

**Date:** 2026-07-13
**Contributor:** Justin Le
**Worktree:** `C:\Users\justu\OneDrive\Desktop\MSBA\Capstone\Census_Uncertainty_Analysis-worktrees\granular-error-drivers-notebook`

## Status

Implemented the requested Census Uncertainty Analytics plan in the isolated
worktree. No commits were created, and the original checkout at
`C:\Users\justu\OneDrive\Desktop\MSBA\Capstone\Census_Uncertainty_Analysis`
was not touched.

## What Changed

- Added `combine_moes_rss` to `analysis/JL_Analysis/helpers.py`.
  - Plain English: when several estimates are added together, their MOEs are
    combined by root-sum-of-squares rather than simple addition.
  - Formula: `combined MOE = sqrt(sum(MOE_i^2))`.
  - Post-review fix: DataFrame estimate/MOE columns are paired by position
    because ACS estimate columns end in `E` and MOE columns end in `M`.
  - Post-review fix: rows with missing, annotation-coded, or invalid component
    estimate/MOE pairs are left blank instead of silently underestimating
    uncertainty.
- Added `analysis/JL_Analysis/test_helpers.py` with standard-library
  `unittest` coverage for RSS, annotation masks, validity guards, and CV math.
- Updated `analysis/JL_Analysis/build_notebooks.py`.
  - Notebook 3 now uses the Census Bureau ACS 0.30 quality-standard benchmark
    as a binary reliability tier: `CV <= 0.30` vs. `CV > 0.30`.
  - Notebook 3 keeps the continuous CV choropleth.
  - Added Notebook 4: `analysis/JL_Analysis/04-granular-error-drivers.ipynb`.
  - Post-review fix: the population-size fit now reports slope standard error
    and clearly caveats that the pooled model does not hold variable type
    constant.
- Regenerated notebooks with `python analysis/JL_Analysis/build_notebooks.py`.
- Executed Notebook 3 and Notebook 4 in place with nbconvert.
- Updated `docs/glossary.md`.
  - Replaced the placeholder CV threshold sentence with the Census 0.30
    benchmark and caveat.
  - Added a plain-English-first RSS MOE combination entry.
- Updated `WORKLOG.md` at the top of the Log section with the actual Notebook 4
  findings.

## Notebook 4 Findings

### Part A - Population Size Driver

Notebook 4 joined each CV row from `build_cv_long` to that row's own
`B01003_001E` total population estimate across county, tract, and block group
levels. The population estimate was used only as a denominator/proxy, so the
analysis did not depend on total-population MOEs being present.

Result:

- Valid CV plus population-proxy rows: **23,330**
- Fitted model: `log(CV) ~ log(population)`
- Slope: **0.041**
- Slope standard error: **0.007**
- R-squared: **0.002**

Interpretation: population size alone does not explain the pooled geography
pattern in this simple model. The near-zero, slightly positive slope means a 1%
increase in population is associated with almost no average change in CV.
Variable type and table availability are also shaping the result, so geography
level remains useful as a communication label, but it should not be treated as
proof that population size by itself drives all ACS reliability differences.

### Part B - RSS Combination of Black 65+ Cells

Notebook 4 combined the six tract-level Black 65+ cells:

- `B01001B_014`
- `B01001B_015`
- `B01001B_016`
- `B01001B_029`
- `B01001B_030`
- `B01001B_031`

Result:

- All tracts had complete valid component estimates and MOEs for RSS
  combination.
- Pooled individual-cell median CV: **0.886**
- RSS-combined Black 65+ tract-total median CV: **0.714**
- Individual-cell median is about **1.2x** the combined median.
- Share at or below the Census ACS 0.30 benchmark:
  - Individual-cell CVs: **1.3%**
  - RSS-combined tract totals: **12.2%**

Interpretation: aggregating the six small cells improves reliability, but the
combined measure is still often above the 0.30 benchmark. The combined Black 65+
tract total is more usable than the six separate age-by-sex cells, but it should
still be communicated as a high-uncertainty subgroup estimate.

## Verification

Commands run in the isolated worktree:

| Command | Result |
|---|---|
| `python -m unittest analysis/JL_Analysis/test_helpers.py` before helper implementation | Failed as expected: `ImportError` because `combine_moes_rss` was missing |
| `python -m unittest analysis/JL_Analysis/test_helpers.py` after implementation | Passed: 2 tests |
| `python -m unittest analysis/JL_Analysis/test_helpers.py` after review fixes | Passed: 12 tests |
| `python -m compileall analysis/JL_Analysis` | Passed |
| `python analysis/JL_Analysis/build_notebooks.py` | Passed; wrote notebooks 00 through 04 |
| `python -m jupyter nbconvert --to notebook --execute --inplace analysis/JL_Analysis/03-tract-cv-choropleth.ipynb` | Passed |
| `python -m jupyter nbconvert --to notebook --execute --inplace analysis/JL_Analysis/04-granular-error-drivers.ipynb` | Passed |
| `ReadLints` on changed Python files | No linter errors |

Environment note: the literal `jupyter` command is not available on PATH in
this PowerShell session, so the equivalent `python -m jupyter nbconvert ...`
invocation was used. Notebook execution completed successfully. The nbconvert
runs emitted non-fatal `MissingIDFieldWarning` and Windows/ZMQ runtime warnings.

## Files Changed

- `WORKLOG.md`
- `docs/glossary.md`
- `analysis/JL_Analysis/helpers.py`
- `analysis/JL_Analysis/test_helpers.py`
- `analysis/JL_Analysis/build_notebooks.py`
- `analysis/JL_Analysis/03-tract-cv-choropleth.ipynb`
- `analysis/JL_Analysis/04-granular-error-drivers.ipynb`
- `implementation-report.md`

Regeneration also wrote the existing generated notebooks:

- `analysis/JL_Analysis/00-data-at-a-glance.ipynb`
- `analysis/JL_Analysis/01-cv-by-geography-size.ipynb`
- `analysis/JL_Analysis/02-cv-by-variable-type.ipynb`

## Concerns

- Notebook execution works via `python -m jupyter nbconvert`, not the literal
  `jupyter` command.
- The pooled population-size model did not support the expected sampling-theory
  story by itself. This is a finding, not a code defect: variable type and table
  availability appear to dominate the simple pooled model.
- Regenerating notebooks from `build_notebooks.py` writes all notebooks in
  `NOTEBOOKS`, so notebooks 00-02 were also written by the generator even though
  the substantive content changes are in Notebooks 3 and 4.
