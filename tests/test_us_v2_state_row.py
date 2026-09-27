"""Tests for the US dashboard v2 card graphic's state comparison row.

Run:
    python -m pytest tests/test_us_v2_state_row.py -v

Census Bureau feedback (2026-09) was that drawing the state marker on the
county's own bar was hard to read. The redesign (option B, lead decision
2026-09-27) gives the state its own labelled row under the county bar, on a
shared axis, and shows it only when the card's "Compare to state" toggle is
on. These tests pin the drawing, not the toggle: the toggle only decides
whether `reference` is passed.

No data files needed: every value below is synthetic.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "Streamlit" / "app_US_v2.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="module")
def app():
    spec = importlib.util.spec_from_file_location("app_us_v2_under_test", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses needs the module registered
    spec.loader.exec_module(mod)
    return mod


def _height(svg: str) -> float:
    return float(re.search(r'viewBox="0 0 [\d.]+ ([\d.]+)"', svg).group(1))


def _bars(svg: str) -> list[str]:
    """Every rounded bar (rx="4") in the drawing."""
    return re.findall(r'<rect [^>]*rx="4"[^>]*/>', svg)


def test_no_reference_draws_county_row_only(app):
    svg = app._interval_svg(54210, 49730, 58690, 0.05)
    assert len(_bars(svg)) == 1
    assert "County" not in svg
    assert _height(svg) == 92


def test_direct_reference_adds_labelled_state_row(app):
    ref = app.StateReference(69700, "Michigan", 610, modelled=False)
    svg = app._interval_svg(54210, 49730, 58690, 0.05, reference=ref)
    assert len(_bars(svg)) == 2
    assert "County" in svg
    assert "Michigan 69,700" in svg
    assert _height(svg) > 92
    assert "stroke-dasharray" not in svg  # a published figure is drawn solid


def test_modelled_reference_is_drawn_dashed(app):
    ref = app.StateReference(1200, "at Michigan's rate", 150, modelled=True)
    svg = app._interval_svg(900, 700, 1100, 0.13, reference=ref, compact=True)
    assert len(_bars(svg)) == 2
    assert "stroke-dasharray" in svg
    assert "at Michigan's rate 1,200" in svg


def test_state_without_moe_draws_a_dot_not_a_bar(app):
    ref = app.StateReference(69700, "Michigan", None, modelled=False)
    svg = app._interval_svg(54210, 49730, 58690, 0.05, reference=ref)
    assert len(_bars(svg)) == 1
    assert "Michigan 69,700" in svg


def test_axis_reaches_the_state_interval(app):
    """The state's upper bound must sit inside the drawing, not off the right edge."""
    ref = app.StateReference(69700, "Michigan", 610, modelled=False)
    svg = app._interval_svg(54210, 49730, 58690, 0.05, reference=ref)
    width = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))
    for bar in _bars(svg):
        x = float(re.search(r' x="([\d.]+)"', bar).group(1))
        w = float(re.search(r' width="([\d.]+)"', bar).group(1))
        assert x + w <= width - 12 + 0.5


def test_long_state_label_is_shortened_in_compact_cards(app):
    ref = app.StateReference(12345, "at District of Columbia's rate", 900, modelled=True)
    svg = app._interval_svg(10000, 9000, 11000, 0.06, reference=ref, compact=True)
    assert "District of Columbia" not in svg.split('aria-label="')[1].split('"', 1)[1]
    assert "at state rate 12,345" in svg


def test_labels_stay_inside_the_card(app):
    """Every centred label's estimated extent sits within the viewBox."""
    ref = app.StateReference(3226, "at Michigan's rate", 400, modelled=True)
    svg = app._interval_svg(2291, 1939, 2643, 0.09, reference=ref, compact=True)
    width = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg).group(1))
    for x, text in re.findall(r'<text x="([\d.]+)" y="\d+" font-size="12"[^>]*>([^<]+)</text>', svg):
        half = len(text) * 3.3
        assert float(x) - half >= 0 and float(x) + half <= width, text
