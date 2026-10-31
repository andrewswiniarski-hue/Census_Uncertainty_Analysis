# /docs — project documentation

Start with [`../HANDOVER.html`](../HANDOVER.html) at the repo root: it summarizes these documents and links to each one.

| File | Purpose | Status |
|------|---------|--------|
| [`phase1-findings-report.md`](phase1-findings-report.md) | Plain-language deliverable-grade findings report — the report's empirical backbone | Covers EDA 01–05 in full, with bridge sections through EDA 13; updated 2026-08-01. Predates EDA 14, the user-segment research and dashboards v2–v7 |
| [`glossary.md`](glossary.md) | Running glossary — every statistical term, defined on first use | Active — grows as terms first appear |
| [`uncertainty-sources.md`](uncertainty-sources.md) | Plain-English map of uncertainty by product + composite boundary | Updated through the CV-driver model (now Section 7 of notebook 06) |
| [`data-dictionary.md`](data-dictionary.md) | Catalog of each data product: geographies, uncertainty measures, formats, landmines | ACS + allocation, boundaries, DAS demo, SF1, 2020 DHC, 2020 DP1, SAIPE, PUMS, VRTs — full set (DHC/DP1 kept as privacy-noise report evidence per Phase 2 scope) |
| [`acs-data-shape-diagram.md`](acs-data-shape-diagram.md) | Wide ACS rows vs long `variable_group` frame; county / tract / BG examples | Teaching diagram for the CV-driver model |
| [`product-shortlist-proposal.md`](product-shortlist-proposal.md) | The scoped income & poverty product stack — verified uncertainty receipts + the mentor ask | Proposed 2026-08-01 — pending mentor confirmation |
| [`api-surface-verified.md`](api-surface-verified.md) · [`api-surface-b99-income.md`](api-surface-b99-income.md) | Live API receipts for what each product publishes (regenerate with `python verify_api_surfaces.py`) | Garrett Spangler, 2026-08 |
| [`allocation-denominator-sensitivity.md`](allocation-denominator-sensitivity.md) · [`allocation-profile-nj.md`](allocation-profile-nj.md) | Why a bare allocation rate is not well defined; who gets imputed in NJ PUMS (regenerate with `report_alloc_*.py`) | Garrett Spangler, 2026-08 |
| [`dashboard-variable-shortlist.md`](dashboard-variable-shortlist.md) | Which variables the dashboard carries, for which audiences, and why | Adopted in part by decision #18, 2026-09-14; includes a correction to its table-level CVs |
| [`user-segments-and-needs.md`](user-segments-and-needs.md) | Garrett Spangler's user research: who needs ACS uncertainty help and for which decisions | Research summary, 2026-08-24; basis for decision #18 |
| [`imputation-slide-talk-track.md`](imputation-slide-talk-track.md) | 60 to 90 second talk track for the imputation slide: imputation is invisible to the MOE and independent of it | Written 2026-08-10; committed 2026-09-14 |
| [`project-brief.md`](project-brief.md) | The team's original project brief: research questions, deliverables, scope decisions over time, the Phase 1 checklist, milestones, and the full list of open questions for Census mentors | The repo's README until 2026-10-31 |
| [`design-specs/`](design-specs/) | Design specs written before each dashboard build: population data-quality card, Census Bureau branding shell, Statistical peers tab, card reliability score (decision #19), county AI assistant (decision #20) | Design records; file names inside are updated to the current ones |
| [`meeting-decks/`](meeting-decks/) | Slide decks from mentor meetings and team reviews: the July 22 biweekly, team recap, user-needs research, dashboard variable shortlist, two EDA 14 slides | Meeting history; the final presentation will be `presentation.pdf` |
| [`handover/figures/`](handover/figures/) | Research charts used by `HANDOVER.html`, extracted from the committed notebook outputs | 2026-10-25 |

**Final deliverables (to be added):** the final report as `final_report.pdf` and the final presentation as `presentation.pdf`, both in this folder.
