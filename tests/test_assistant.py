"""Tests for the "Ask about this county" engine and its wording.

Run:
    python -m pytest tests/test_assistant.py -v

No test here calls the network. The fact sheet is hand-written in the shape
Streamlit/app_US_v7.py builds; every test that reaches the model uses a
fake client.

Spec: docs/superpowers/specs/2026-10-10-county-ai-assistant-design.md
Plan: docs/superpowers/plans/2026-10-10-county-ai-assistant.md, Tasks 2 and 3.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import assistant  # noqa: E402
from analysis import assistant_text as text  # noqa: E402
from analysis.assistant import (  # noqa: E402
    Reply,
    UnknownBlank,
    check_answer,
    free_text_enabled,
    is_configured,
    measure_id,
    model_name,
    render_answer,
    sheet_for_model,
    slot_values,
)

SHEET = {
    "county": {"blanks": {
        "name": "Jefferson County, Alabama", "state": "Alabama", "period": "2020-2024, 5-year",
        "metro_class": "metro", "population": "667,755",
    }},
    "measures": {
        "median_household_income": {
            "key": "Median household income", "label": "Median household income",
            "topic": "Income", "table": "B19013", "status": "published",
            "unit": "dollars", "rate_label": None,
            "blanks": {"label": "Median household income", "estimate": "66,388",
                       "ci_low": "64,897", "ci_high": "67,879", "band": "Higher reliability"},
            "values": {"estimate": 66388.0, "ci_low": 64897.0, "ci_high": 67879.0},
        },
        "low_income_below_200_of_poverty": {
            "key": "Low income (below 200% of poverty)",
            "label": "Low income (below 200% of poverty)",
            "topic": "Poverty", "table": "C17002", "status": "published",
            "unit": None, "rate_label": "of the population below 200% of poverty",
            "blanks": {"label": "Low income (below 200% of poverty)", "estimate": "201,442",
                       "rate": "30.8%"},
            "values": {"estimate": 201442.0, "rate": 30.8},
        },
        "median_gross_rent": {
            "key": "Median gross rent", "label": "Median gross rent",
            "topic": "Housing", "table": "B25064", "status": "suppressed",
            "unit": "dollars", "rate_label": None,
            "blanks": {"label": "Median gross rent"},
            "values": {},
        },
    },
}


# -- Task 2: pure functions and wording ---------------------------------------

def test_measure_id_examples():
    assert measure_id("Median household income") == "median_household_income"
    assert measure_id("Poverty: 5-17") == "poverty_5_17"
    assert measure_id("65+") == "65"
    assert measure_id("Households earning \\$25,000\u2013\\$50,000") == "households_earning_25_000_50_000"


def test_render_fills_blanks_and_escapes_dollars():
    out = render_answer("Income in [[county.name]] is [[median_household_income.estimate]].", SHEET)
    assert out == "Income in Jefferson County, Alabama is 66,388."
    assert render_answer("a $ b $", SHEET) == "a \\$ b \\$"


def test_render_unknown_blank_raises():
    with pytest.raises(UnknownBlank):
        render_answer("[[median_household_income.nope]]", SHEET)


@pytest.mark.parametrize("answer, used, expected", [
    ("Income is [[median_household_income.estimate]].", ["median_household_income"], None),
    ("At 90% confidence, [[median_household_income.label]] for 2020-2024 is [[median_household_income.estimate]].", ["median_household_income"], None),
    ("Low income (below 200% of poverty) is on another card.", ["low_income_below_200_of_poverty"], None),
    ("Income is 66,388.", ["median_household_income"], "stray_number"),
    ("Income is about sixty-six thousand.", ["median_household_income"], "stray_number"),
    ("[[median_household_income.nope]]", ["median_household_income"], "unknown_blank"),
    ("Rent is [[median_gross_rent.estimate]].", ["median_gross_rent"], "unknown_blank"),
    ("This figure is safe to use. [[median_household_income.estimate]]", ["median_household_income"], "advice_wording"),
    ("   ", ["median_household_income"], "no_grounding"),
    ("Income is [[median_household_income.estimate]].", ["not_a_measure"], "no_grounding"),
    ("Income is [[median_household_income.estimate]].", [], "no_grounding"),
])
def test_check_answer(answer, used, expected):
    reply = Reply(kind="answer", answer=answer, measures_used=used, terms_explained=[])
    assert check_answer(reply, SHEET) == expected


def test_term_only_answer_is_grounded():
    reply = Reply(kind="answer", answer="A margin of error is the plus or minus around an estimate.",
                  measures_used=[], terms_explained=["margin of error"])
    assert check_answer(reply, SHEET) is None


def test_sheet_for_model_is_deterministic_and_hides_raw_values():
    out = sheet_for_model(SHEET)
    assert out == sheet_for_model(copy.deepcopy(SHEET))
    assert "66388.0" not in out and '"values"' not in out and "66,388" in out


def test_wording():
    assert [p.label for p in text.PRESETS] == [
        "Give me a county brief", "How reliable are these figures?",
        "How does this county compare with similar counties?"]
    assert text.HUD_RULE_VERIFIED is False and "rule.hud" not in slot_values(SHEET)
    assert {"rule.esri", "rule.nchs"} <= set(slot_values(SHEET))
    every = [text.SYSTEM_PROMPT, *[p.prompt for p in text.PRESETS], text.DISCLOSURE, text.CAN_ASK,
             text.REDIRECT_OUT_OF_SCOPE, text.REDIRECT_NOT_IN_DASHBOARD, text.FALLBACK,
             text.UNAVAILABLE, text.OFF, text.TOO_LONG, text.QUESTION_CAP,
             *text.GLOSSARY.values(), *text.RULES.values()]
    assert not any("\u2014" in s for s in every)
    assert not any("the Bureau" in s.replace("Census Bureau", "") for s in every)


def test_configuration(monkeypatch):
    # -- keep the test independent of a real key in the lead's .env
    monkeypatch.setattr(assistant, "load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert is_configured() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert is_configured() is True
    monkeypatch.delenv("ASSISTANT_MODEL", raising=False)
    assert model_name() == "claude-haiku-5-5"
    monkeypatch.setenv("ASSISTANT_FREE_TEXT", "0")
    assert free_text_enabled() is False
