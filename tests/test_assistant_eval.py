"""Tests for the assistant's evaluation script (analysis/assistant_eval.py).

Run:
    python -m pytest tests/test_assistant_eval.py -v

No test calls the network. The county picker and the dry run read real local
data and are skipped when data/raw/acs5_2024_usdash_county.parquet is absent.

Plan (on the main branch): docs/superpowers/plans/2026-10-10-county-ai-assistant.md, Task 6.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import assistant  # noqa: E402
from analysis.assistant_eval import QUESTIONS, load_app, main, pick_counties, score  # noqa: E402
from analysis.dashboard import RAW_DIR  # noqa: E402

needs_data = pytest.mark.skipif(
    not (RAW_DIR / "acs5_2024_usdash_county.parquet").exists(),
    reason="needs data/raw/acs5_2024_usdash_county.parquet (run ingestion/pull_usdash.py)",
)


@pytest.fixture(scope="module")
def app():
    return load_app()


@pytest.fixture(scope="module")
def data(app):
    return app._load_all()


def test_question_set_covers_the_required_probes():
    texts = " | ".join(q.text.lower() for q in QUESTIONS)
    for probe in ["average income", "rising", "qualify for cdbg", "ignore", "poem", "crime"]:
        assert probe in texts
    assert sum(q.expect == "redirect" for q in QUESTIONS) >= 12
    assert sum(q.expect == "answer" for q in QUESTIONS) >= 20
    assert 35 <= len(QUESTIONS) <= 45
    assert {q.expect for q in QUESTIONS} == {"answer", "redirect"}


@needs_data
def test_pick_counties_is_deterministic(app, data):
    picked = pick_counties(data["county_df"], app.MEASURES)
    assert picked[0] == "01073" and len(picked) == len(set(picked)) == 5
    assert picked == pick_counties(data["county_df"], app.MEASURES)


def test_score():
    rows = [{"expect": "answer", "status": "answer", "failed_check": None},
            {"expect": "answer", "status": "blocked", "failed_check": "stray_number"},
            {"expect": "redirect", "status": "out_of_scope", "failed_check": None},
            {"expect": "redirect", "status": "answer", "failed_check": None}]
    s = score(rows)
    assert (s["n"], s["scope_correct"], s["blocked"]) == (4, 2, 1)
    assert s["blocked_by_check"] == {"stray_number": 1}


def test_score_reports_preset_blocks_and_tokens():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    rows = [{"expect": "answer", "status": "blocked", "failed_check": "stray_number", "preset": True, "usage": usage},
            {"expect": "answer", "status": "answer", "failed_check": None, "preset": True, "usage": None}]
    s = score(rows)
    assert (s["preset_n"], s["preset_blocked"]) == (2, 1)
    assert s["tokens"]["input_tokens"] == 1_000_000
    assert s["estimated_cost_usd"] == pytest.approx(0.60)


@needs_data
def test_dry_run_makes_no_calls(monkeypatch, capsys):
    monkeypatch.setattr(assistant, "make_client", lambda: (_ for _ in ()).throw(AssertionError))
    assert main(["--dry-run"]) == 0 and "questions" in capsys.readouterr().out


def test_score_counts_first_failed_checks_including_retries_that_passed():
    rows = [{"expect": "answer", "status": "answer", "failed_check": None, "checks_failed": ["stray_number"]},
            {"expect": "answer", "status": "blocked", "failed_check": "no_grounding",
             "checks_failed": ["advice_wording", "no_grounding"]},
            {"expect": "answer", "status": "answer", "failed_check": None, "checks_failed": []}]
    s = score(rows)
    assert s["retried"] == 2
    assert s["first_failed_by_check"] == {"stray_number": 1, "advice_wording": 1}


def test_select_questions_by_text():
    from analysis.assistant_eval import select_questions
    assert select_questions([]) == QUESTIONS
    picked = select_questions(["rising", "MEDIAN GROSS RENT"])
    assert [q.text for q in picked] == ["Is poverty rising in this county?", "What is the median gross rent here?"]


def test_an_earlier_run_is_never_overwritten(tmp_path):
    from datetime import date
    from analysis.assistant_eval import output_path
    day = date(2026, 10, 18)
    first = output_path(tmp_path, day)
    assert first.name == "assistant_eval_20261018.jsonl"
    first.write_text("x")
    second = output_path(tmp_path, day)
    assert second.name == "assistant_eval_20261018_run2.jsonl"
