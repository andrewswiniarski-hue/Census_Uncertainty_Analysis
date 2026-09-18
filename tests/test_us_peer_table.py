"""Statistical peers table: thousands separators and a CV column.

Production change that would fail this test: dropping the CV column,
putting it left of margin of error, or rendering Estimate/MOE without
a thousands-separator format.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
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


def _sample_peers() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "est": [110_884.0, 50_000.0],
            "moe": [2_680.0, 1_645.0],
        },
        index=["49011", "17031"],
    )


def test_peer_display_table_columns_are_county_estimate_moe_then_cv():
    app = _load_app()
    display = app._peer_display_table(
        _sample_peers(),
        labels={"49011": "Davis County, Utah", "17031": "Cook County, Illinois"},
        self_est=109_000.0,
    )
    moe_col = f"\u00b1 margin of error ({app.CONFIDENCE_LEVEL_PCT}% CI)"
    assert list(display.columns) == ["County", "Estimate", moe_col, "CV"]


def test_peer_display_table_cv_matches_acs_convention():
    """MOE of 1645 on an estimate of 50000 -> SE 1000 -> CV 0.02."""
    app = _load_app()
    peers = pd.DataFrame({"est": [50_000.0], "moe": [1_645.0]}, index=["17031"])
    display = app._peer_display_table(
        peers, labels={"17031": "Cook County, Illinois"}, self_est=50_000.0
    )
    assert display["CV"].iloc[0] == pytest.approx(0.02)


def test_peer_display_column_config_adds_thousands_separators():
    config = _load_app()._peer_display_column_config()
    estimate = config["Estimate"]
    moe = next(v for k, v in config.items() if "margin of error" in k)
    estimate_fmt = estimate["type_config"]["format"]
    moe_fmt = moe["type_config"]["format"]
    for fmt in (estimate_fmt, moe_fmt):
        assert fmt == "localized" or "," in str(fmt), fmt


def test_peer_display_column_config_formats_cv_as_percent():
    config = _load_app()._peer_display_column_config()
    cv_fmt = config["CV"]["type_config"]["format"]
    assert "percent" in str(cv_fmt) or "%" in str(cv_fmt)


def test_peer_panel_wires_display_helper_and_column_config():
    src = inspect.getsource(_load_app().render_peer_panel)
    assert "_peer_display_table(" in src
    assert "column_config=_peer_display_column_config()" in src
