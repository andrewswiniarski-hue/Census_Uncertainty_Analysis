"""Census Bureau branding shell on app_US_v2.0.py.

Production change that would fail these tests: dropping the navy header
wordmark, removing the not-an-official-product footer, restoring gold or
Streamlit-red widget chrome, dropping Azul system-command buttons, or
unwiring cv_color() from the map/cards.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "Streamlit" / "app_US_v2.0.py"


def _load_app():
    if "app_us_v20" in sys.modules:
        return sys.modules["app_us_v20"]
    spec = importlib.util.spec_from_file_location("app_us_v20", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app_us_v20"] = mod
    with patch.object(st, "set_page_config"):
        spec.loader.exec_module(mod)
    return mod


def test_brand_header_names_us_census_bureau_and_the_app():
    html = _load_app()._brand_header_html()
    assert "U.S. Census Bureau" in html
    assert "US County Demographic Explorer" in html


def test_brand_header_marks_the_app_as_a_capstone_demonstration():
    html = _load_app()._brand_header_html()
    assert "Capstone demonstration" in html
    assert "Measuring America: People, Places, and Economy" in html


def test_brand_footer_says_not_an_official_product_and_links_census_gov():
    html = _load_app()._brand_footer_html()
    assert (
        "This is a student capstone demonstration. "
        "It is not an official Census Bureau product."
    ) in html
    assert "https://www.census.gov" in html
    assert "Measuring America: People, Places, and Economy" in html


def test_brand_footer_cites_the_acs_vintage():
    app = _load_app()
    html = app._brand_footer_html()
    assert app.ACS_VINTAGE in html


def test_css_uses_official_navy_and_azul():
    app = _load_app()
    css = app._CSS
    assert "#112E51" in css
    assert app._CENSUS_AZUL == "#265FCA"
    assert app._CENSUS_AZUL in css


def test_css_overrides_streamlit_red_primary_with_azul():
    """Tabs, chips, sliders, and checkboxes follow --primary-color.

    Streamlit's default primary is #FF4B4B, which is what still showed on
    the County explorer tab underline and the 'Choose what to show' chips.
    """
    app = _load_app()
    css = app._CSS
    assert "--primary-color" in css
    assert "--st-primary-color" in css
    assert f"--primary-color: {app._CENSUS_AZUL}" in css
    assert f"--st-primary-color: {app._CENSUS_AZUL}" in css


def test_css_tabs_and_multiselect_chips_use_azul():
    app = _load_app()
    css = app._CSS
    azul = app._CENSUS_AZUL
    assert 'data-testid="stTab"' in css
    assert "react-aria-SelectionIndicator" in css
    assert 'data-baseweb="tag"' in css
    tab_at = css.index('data-testid="stTab"')
    tag_at = css.index('data-baseweb="tag"')
    assert azul in css[tab_at : tab_at + 400]
    assert azul in css[tag_at : tag_at + 250]


def test_css_checkboxes_use_azul_when_selected():
    """Streamlit 1.60 checkboxes are React Aria labels with data-selected.

    The red fill the user still saw was theme.colors.primary on the box
    div that wraps the check SVG, not a BaseWeb checkbox.
    """
    app = _load_app()
    css = app._CSS
    assert 'data-testid="stCheckbox"' in css
    box_at = css.index('data-testid="stCheckbox"')
    assert app._CENSUS_AZUL in css[box_at : box_at + 400]
    assert "data-selected" in css[box_at : box_at + 400]


def test_css_buttons_are_azul_not_gold_or_pms_blue():
    css = _load_app()._CSS
    assert "#FCBE2D" not in css
    start = css.index('button[kind="primary"]')
    block = css[start : start + 400]
    assert "#265FCA" in block
    assert "#FFFFFF" in block
    # Default (secondary) Streamlit buttons must also be Azul, not steel-only.
    default_at = css.index(".stButton > button")
    default_block = css[default_at : default_at + 320]
    assert "#265FCA" in default_block


def test_css_headings_use_census_navy():
    css = _load_app()._CSS
    assert "color: #112E51" in css or "color:#112E51" in css


def test_welcome_lead_in_names_the_census_bureau_not_census_alone():
    src = inspect.getsource(_load_app().render_welcome)
    assert "U.S. Census Bureau" in src or "Census Bureau data" in src
    assert "county-level Census data" not in src
    assert "once-a-decade Census" not in src


def test_main_renders_brand_header_and_footer():
    src = inspect.getsource(_load_app().main)
    assert "_brand_header_html()" in src
    assert "_brand_footer_html()" in src
    assert "st.title(" not in src


def test_css_does_not_use_streamlit_red_as_a_brand_accent():
    css = _load_app()._CSS
    assert "#FF4B4B" not in css
    assert "#ff4b4b" not in css


def test_cv_color_stays_on_map_and_cards():
    app = _load_app()
    assert "cv_color(" in inspect.getsource(app.render_map)
    assert "cv_color(" in inspect.getsource(app.render_card)
    assert "cv_color(" in inspect.getsource(app._interval_svg)
