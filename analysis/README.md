# /analysis — reusable analysis code

Python modules imported by notebooks and scripts: CV computation, reliability
thresholds, composite score logic, geospatial helpers.

Rule of thumb: **if two notebooks need the same function, it lives here** — not
copy-pasted between notebooks.

| Module | Role |
|--------|------|
| [`acs.py`](acs.py) | Load ACS pulls; CV; top-code flag; handbook zero-cell MOE aggregation |
| [`alloc.py`](alloc.py) | Load allocation pulls; derive item allocation rates (EDA 05 formulas) |
| [`composite.py`](composite.py) | Two-axis reliability matrix + equal-weight / worst-component + residual CV flag |
| [`cv_model.py`](cv_model.py) | Long CV frame; nested OLS; place pop vs estimate size; residual flags |
| [`dhc.py`](dhc.py) | Parse 2010 DHC demonstration files for privacy-noise work |
| `test_*.py` | Focused unit tests for formula-bearing helpers |
