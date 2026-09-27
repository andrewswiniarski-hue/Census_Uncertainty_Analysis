"""Tests for the US dashboard v2 reliability score wiring and card HTML.

Run:
    python -m pytest tests/test_us_v2_score.py -v

Spec: docs/superpowers/specs/2026-09-27-composite-reliability-score-cards-design.md
Synthetic values except the one real-data test, which is skipped when
data/raw is absent.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "Streamlit" / "app_US_v2.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis import composite  # noqa: E402
from analysis.dashboard import RAW_DIR  # noqa: E402

ADVICE_WORDS = ("risky", "safe", "cite", "use with care", "too imprecise", "reliable to")


@pytest.fixture(scope="module")
def app():
    spec = importlib.util.spec_from_file_location("app_us_v2_score_under_test", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses needs the module registered
    spec.loader.exec_module(mod)
    return mod


def _contrast_on_white(hex_color: str) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return 1.05 / (lum + 0.05)


def test_exactly_ten_measures_carry_imputation(app):
    scored = {k for k, m in app.MEASURES.items() if m.imputation}
    assert scored == {
        "Median household income",
        "Households earning under \\$25,000",
        "Households earning \\$25,000\u2013\\$50,000",
        "Households earning \\$50,000\u2013\\$100,000",
        "Households earning \\$100,000+",
        "Poverty: Under 5", "Poverty: 5-17", "Poverty: 18-64", "Poverty: 65+",
        "Low income (below 200% of poverty)",
    }
    assert app.MEASURES["Median household income"].imputation == "income"
    assert app.MEASURES["Poverty: Under 5"].imputation == "family_poverty"
    assert app.MEASURES["Under 5"].imputation is None
    assert app.IMPUTATION_SOURCES["family_poverty"].is_proxy is True
    assert app.IMPUTATION_SOURCES["income"].is_proxy is False


def test_score_for_uses_source(app):
    subs = {"income": pd.Series({"04001": 1.72}), "family_poverty": pd.Series(dtype=float)}
    rs = app.score_for("Median household income", "04001", 0.0377, subs)
    assert rs.imputation_sub == pytest.approx(1.72)
    assert rs.imputation_source == app.IMPUTATION_SOURCES["income"].label


def test_score_for_sampling_only_measure(app):
    rs = app.score_for("Unemployed", "04001", 0.078, {"income": pd.Series(dtype=float),
                                                      "family_poverty": pd.Series(dtype=float)})
    assert rs.imputation_sub is None
    assert rs.imputation_note == "not published"


def test_score_for_county_missing_from_allocation(app):
    subs = {"income": pd.Series({"04001": 1.72}), "family_poverty": pd.Series(dtype=float)}
    rs = app.score_for("Median household income", "99999", 0.05, subs)
    assert rs.imputation_sub is None
    assert rs.imputation_note == "not available for this county"


def test_score_for_nan_cv_is_none(app):
    subs = {"income": pd.Series({"04001": 1.72}), "family_poverty": pd.Series(dtype=float)}
    assert app.score_for("Median household income", "04001", float("nan"), subs) is None


def test_strip_shows_band_and_score(app):
    rs = composite.reliability_score(0.0377, 1.72, source="household income, Table B99192")
    html = app._score_strip_html(rs)
    assert composite.BAND_LOWER in html
    assert "47</b> / 100" in html
    assert app.BAND_COLOR[composite.BAND_LOWER] in html
    compact = app._score_strip_html(rs, compact=True)
    assert "Reliability score" not in compact and "47</b> / 100" in compact


@pytest.mark.parametrize("cv,imp", [(0.02, None), (0.2, 90.0), (0.5, 10.0), (0.04, 1.7)])
def test_no_advice_wording(app, cv, imp):
    rs = composite.reliability_score(cv, imp, source="x", note="not published")
    text = (app._score_strip_html(rs) + app._score_note_html(rs)
            + app._score_breakdown_html(rs)).lower()
    for word in ADVICE_WORDS:
        assert word not in text


def test_note_text(app):
    two = composite.reliability_score(0.0377, 1.72, source="x")
    assert "Sampling 92, imputation 2, averaged." in app._score_note_html(two)
    only = composite.reliability_score(0.078, note="not published")
    assert "Sampling only: imputation not published for this figure." in app._score_note_html(only)
    missing = composite.reliability_score(0.078, note="not available for this county")
    assert "imputation rate not available for this county" in app._score_note_html(missing)


def test_breakdown_marks_cap_and_missing_imputation(app):
    capped = composite.reliability_score(0.35, 100.0, source="x")
    assert "capped by the CV" in app._score_breakdown_html(capped)
    only = composite.reliability_score(0.078, note="not published")
    assert "not published" in app._score_breakdown_html(only)


def test_band_text_colors_pass_wcag_aa(app):
    for band in (composite.BAND_HIGHER, composite.BAND_MODERATE, composite.BAND_LOWER):
        assert _contrast_on_white(app.BAND_TEXT[band]) >= 4.5


@pytest.mark.skipif(
    not (RAW_DIR / "acs5_2024_usdash_alloc_county.parquet").exists(),
    reason="US dashboard data not pulled",
)
def test_load_all_imputation_subs_real_data(app):
    data = app._load_all()
    subs = data["imputation_subs"]
    assert set(subs) == {"income", "family_poverty"}
    assert len(subs["income"]) == 3144
    assert subs["income"]["04001"] == pytest.approx(1.72, abs=0.01)
