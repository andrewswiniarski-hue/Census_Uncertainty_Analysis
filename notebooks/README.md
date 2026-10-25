# /notebooks — exploratory analysis (EDA)

One notebook per question, named so the question is obvious from the filename
(e.g., `01-cv-by-geography-size.ipynb`). Ground rules:

- Every notebook runs top-to-bottom cleanly after **Restart & Run All**
- Markdown commentary explains findings in plain English as you go
- Reusable logic graduates to [`/analysis`](../analysis); notebooks stay thin
- Define every statistical term on first use, and add it to
  [`/docs/glossary.md`](../docs/glossary.md)

| Notebook | Question |
|----------|----------|
| `01`–`03` | Sampling CV by size, variable type, and geography |
| `04` | Privacy noise (DAS demo vs SF1) |
| `05` | Allocation rates vs CV (independence) |
| `06` | ACS composite prototype (CV × allocation matrix) + CV driver model (place pop vs estimate size, matched bins) — merged 2026-07-31 from the original separate 06/07 notebooks |
| `08` | Allocation-denominator sensitivity (Garrett) |
| `09` | Who gets inferred: person-level PUMS allocation profile (Garrett) |
| `10`–`12` | Phase B: DHC/DP1 modeled noise by size, variable type, and geography — mirrors `01`–`03`, no composite score. Renumbered 2026-08-01 (was `08`–`10`) to resolve a collision with Garrett's `08`–`09` after the branch merge. |
| `10` (SAIPE) | `10-saipe-vs-acs-county.ipynb`: SAIPE vs. ACS intervals for NJ counties, 2019–2024 — the Bureau's two published uncertainty styles compared (shares the number 10 with the DHC notebook; not renumbered because docs link to both names) |
| `13` | SAIPE vs. ACS for the same variable, Mercer County — model error vs. sampling error, direct comparison (Q3) |
| `14` | ACS-wide error-bar survey: a 100-table sample at every U.S. county — what share can carry an error bar, CV by table family, the size law at national scale |
