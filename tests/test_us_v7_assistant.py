"""Tests for the US county dashboard v7's assistant: the county fact sheet
(built from the cards' own functions) and the "Ask about this county" panel.

Run:
    python -m pytest tests/test_us_v7_assistant.py -v

Every test here reads real local data and is skipped when
data/raw/acs5_2024_usdash_county.parquet is absent. No test calls the
network: the panel tests replace analysis.assistant.make_client with a fake.

Expected Jefferson County, Alabama (01073) figures are the ones the v6 cards
showed on 2026-10-10 (spec, "Testing").

Spec: docs/superpowers/specs/2026-10-10-county-ai-assistant-design.md
Plan: docs/superpowers/plans/2026-10-10-county-ai-assistant.md, Tasks 4 and 5.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "Streamlit" / "app_US_v7.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import assistant  # noqa: E402
from analysis.dashboard import RAW_DIR, proportion_rate  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (RAW_DIR / "acs5_2024_usdash_county.parquet").exists(),
    reason="needs data/raw/acs5_2024_usdash_county.parquet (run ingestion/pull_usdash.py)",
)


@pytest.fixture(scope="module")
def app():
    spec = importlib.util.spec_from_file_location("app_us_v7_under_test", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses needs the module registered
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def data(app):
    return app._load_all()


@pytest.fixture(scope="module")
def sheet(app, data):
    return app._county_fact_sheet(data, "01073", set())


# -- Task 4: the fact sheet ---------------------------------------------------

def test_ids_are_unique(app):
    ids = [assistant.measure_id(k) for k in app.MEASURES]
    assert len(set(ids)) == 26 and all(re.fullmatch(r"[a-z0-9_]+", i) for i in ids)


def test_cv_rank_helper(app, data):
    assert app._cv_rank_in_state(data, "01", app.IMPUTATION_INCOME, "01073") == (3, 67)


def test_jefferson_matches_the_cards(sheet):
    c, m = sheet["county"]["blanks"], sheet["measures"]["median_household_income"]
    assert (c["name"], c["population"], c["metro_class"]) == ("Jefferson County, Alabama", "667,755", "metro")
    assert (c["overall_imputed"], c["sex_imputed"], c["age_imputed"], c["race_imputed"]) == ("13.5%", "0.1%", "1.2%", "1.1%")
    b = m["blanks"]
    assert m["status"] == "published" and m["unit"] == "dollars"
    assert (b["estimate"], b["ci_low"], b["ci_high"], b["cv"]) == ("66,388", "64,897", "67,879", "1.4%")
    assert (b["score"], b["sampling_score"], b["imputation_score"], b["band"]) == ("95", "97", "92", "Higher reliability")
    assert (b["cv_rank"], b["cv_rank_n"]) == ("3rd", "67")
    assert (b["similar_tested"], b["similar_tied"], b["similar_higher"], b["similar_lower"]) == ("237", "18", "196", "23")
    assert (b["acs1_estimate"], b["acs1_ci_low"], b["acs1_ci_high"]) == ("69,363", "66,685", "72,041")
    assert b["esri_class"] == "high reliability" and "hud_median_rule" not in b
    assert m["values"]["estimate"] == 66388.0


def test_income_state_comparison(sheet):
    b = sheet["measures"]["median_household_income"]["blanks"]
    assert (b["state_value"], b["state_moe"], b["vs_state"]) == ("63,999", "399", "differs from")
    assert len(b["similar_tied_examples"].split("; ")) == 5


def test_controlled_population(sheet):
    m = sheet["measures"]["total_population"]
    assert m["status"] == "controlled" and set(m["blanks"]) == {"label", "estimate"}


def test_suppressed_rent_offers_only_a_label(app, data):
    est, _ = app.MEASURES["Median gross rent"].values(data["county_df"])
    code = data["county_df"].loc[est.isna().to_numpy(), "_key"].iloc[0]
    m = app._county_fact_sheet(data, code, set())["measures"]["median_gross_rent"]
    assert m["status"] == "suppressed" and set(m["blanks"]) == {"label"}


def test_rate_measure_matches_its_card_formula(app, data, sheet):
    measure = app.MEASURES["Uninsured (all ages)"]
    row = data["county_df"][data["county_df"]["_key"] == "01073"]
    (e,), (m,) = (s.to_numpy(dtype=float) for s in measure.values(row))
    (ue,), (um,) = (s.to_numpy(dtype=float) for s in measure.universe(row))
    b = sheet["measures"]["uninsured_all_ages"]["blanks"]
    assert b["rate"] == f"{proportion_rate(e, m, ue, um)[0]:.1f}%"
    assert {"state_rate", "state_rate_benchmark"} <= set(b) and "state_value" not in b


def test_two_builds_are_identical(app, data, sheet):
    again = app._county_fact_sheet(data, "01073", set())
    assert assistant.sheet_for_model(again) == assistant.sheet_for_model(sheet)
    assert len(assistant.sheet_for_model(sheet)) < 40_000


def test_builds_for_a_spread_of_counties(app, data):
    for code in data["county_df"]["_key"].iloc[::75]:  # 42 counties; one build is about 0.4 s
        s = app._county_fact_sheet(data, code, set())
        blanks = [v for m in s["measures"].values() for v in m["blanks"].values()]
        blanks += list(s["county"]["blanks"].values())
        # -- word boundary: "Buchanan County" is a name, not a missing value
        assert all(isinstance(v, str) and not re.search(r"\bnan\b", v.lower()) for v in blanks)


def test_missing_measure_is_marked(app, data):
    m = app._county_fact_sheet(data, "01073", {"Unemployed"})["measures"]["unemployed"]
    assert m["status"] == "not_in_local_data" and set(m["blanks"]) == {"label"}
