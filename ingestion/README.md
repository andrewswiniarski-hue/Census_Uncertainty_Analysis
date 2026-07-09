# /ingestion — scripted data pulls

One script per data source. Every script must have a docstring stating:

1. **What it pulls** (product, variables, geographies, vintage)
2. **What it needs** (e.g., `CENSUS_API_KEY` in `.env`)
3. **What it produces** (files written to `/data/raw`)

Scripts print sanity checks on completion (row counts vs. known totals, null rates,
value ranges) — review those before analyzing the data.

**No manual downloads where avoidable:** if it can be pulled by script, it is.
