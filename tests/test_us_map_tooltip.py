"""Hover names on the County explorer and Statistical peers maps.

Production change that would fail this test: dropping `tooltip_name` from
the cached GeoJSON, or removing `{tooltip_name}` from `_map_tooltip` HTML.
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
    """Import the Streamlit script as a module so helpers can be unit-tested.

    set_page_config only works inside `streamlit run`; stub it so import
    does not raise.
    """
    if "app_us_v20" in sys.modules:
        return sys.modules["app_us_v20"]
    spec = importlib.util.spec_from_file_location("app_us_v20", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app_us_v20"] = mod
    with patch.object(st, "set_page_config"):
        spec.loader.exec_module(mod)
    return mod


def test_map_tooltip_reads_tooltip_name_property():
    tooltip = _load_app()._map_tooltip()
    assert "{tooltip_name}" in tooltip["html"]


def test_state_geojson_features_carry_a_readable_name():
    features = _load_app()._base_geojson("state")
    names = {f["properties"]["tooltip_name"] for f in features}
    keys = {f["properties"]["state_key"] for f in features}
    assert "Alabama" in names
    assert "Alabama" not in keys


def test_county_geojson_features_carry_county_and_state():
    features = _load_app()._base_geojson("county")
    autauga = next(
        f["properties"]["tooltip_name"]
        for f in features
        if f["properties"]["county_key"] == "01001"
    )
    assert autauga == "Autauga County, Alabama"


def test_geojson_tooltip_names_are_not_raw_fips():
    app = _load_app()
    for level, key_col in (("state", "state_key"), ("county", "county_key")):
        for feat in app._base_geojson(level):
            name = feat["properties"]["tooltip_name"]
            key = feat["properties"][key_col]
            assert name and not name.isdigit(), (level, key, name)
            assert name != key


def test_tooltip_is_wired_before_the_interactive_branch():
    """Both maps share one Deck construction; click-to-select is gated later.

    A refactor that puts tooltip= only inside `if interactive:` would keep
    the helper tests green and silently drop names on Statistical peers.
    """
    src = inspect.getsource(_load_app().render_map)
    assert "tooltip=_map_tooltip()" in src
    assert src.index("tooltip=_map_tooltip()") < src.index("if interactive:")
