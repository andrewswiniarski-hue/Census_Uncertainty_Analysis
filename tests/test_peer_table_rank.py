"""Statistical peers table on us_county_explorer.py: rank, similarity, and list size.

Production change that would fail these tests: dropping Rank or Similarity,
ranking by something other than absolute estimate distance, or letting the
list cap return a different row count than requested.
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
APP_PATH = REPO_ROOT / "Streamlit" / "us_county_explorer.py"


def _load_app():
    if "county_explorer_peer_rank" in sys.modules:
        return sys.modules["county_explorer_peer_rank"]
    spec = importlib.util.spec_from_file_location("county_explorer_peer_rank", APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["county_explorer_peer_rank"] = mod
    with patch.object(st, "set_page_config"):
        spec.loader.exec_module(mod)
    return mod


def _sample_peers() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "est": [110_884.0, 50_000.0, 109_000.0],
            "moe": [2_680.0, 1_645.0, 2_000.0],
        },
        index=["49011", "17031", "01001"],
    )


def test_peer_display_table_columns_include_rank_and_similarity():
    app = _load_app()
    display = app._peer_display_table(
        _sample_peers(),
        labels={
            "49011": "Davis County, Utah",
            "17031": "Cook County, Illinois",
            "01001": "Autauga County, Alabama",
        },
        self_est=109_000.0,
    )
    moe_col = f"\u00b1 margin of error ({app.CONFIDENCE_LEVEL_PCT}% CI)"
    assert list(display.columns) == [
        "Rank", "County", "Similarity", "Estimate", moe_col, "CV",
    ]


def test_equal_estimates_share_rank_and_score_100():
    app = _load_app()
    peers = pd.DataFrame(
        {"est": [50_000.0, 50_000.0], "moe": [1_645.0, 800.0]},
        index=["17031", "01001"],
    )
    display = app._peer_display_table(
        peers,
        labels={"17031": "Cook County, Illinois", "01001": "Autauga County, Alabama"},
        self_est=50_000.0,
    )
    assert list(display["Rank"]) == [1, 1]
    assert display["Similarity"].tolist() == pytest.approx([100.0, 100.0])


def test_closer_estimate_ranks_above_a_farther_one():
    app = _load_app()
    display = app._peer_display_table(
        _sample_peers(),
        labels={
            "49011": "Davis County, Utah",
            "17031": "Cook County, Illinois",
            "01001": "Autauga County, Alabama",
        },
        self_est=109_000.0,
    )
    # |109000-109000| = 0, |110884-109000| = 1884, |50000-109000| = 59000
    assert list(display["County"]) == [
        "Autauga County, Alabama",
        "Davis County, Utah",
        "Cook County, Illinois",
    ]
    assert list(display["Rank"]) == [1, 2, 3]
    assert display["Similarity"].iloc[0] == pytest.approx(100.0)
    assert display["Similarity"].iloc[1] == pytest.approx(100.0 * (1 - 1884 / 109_000))
    assert display["Similarity"].iloc[2] == pytest.approx(100.0 * (1 - 59_000 / 109_000))


def test_zero_selected_estimate_does_not_produce_nan_similarity():
    app = _load_app()
    peers = pd.DataFrame(
        {"est": [0.0, 10.0], "moe": [1.0, 1.0]},
        index=["a", "b"],
    )
    display = app._peer_display_table(
        peers, labels={"a": "A County", "b": "B County"}, self_est=0.0,
    )
    assert display["Similarity"].notna().all()
    assert display.loc["a", "Similarity"] == pytest.approx(100.0)
    assert display.loc["b", "Similarity"] == pytest.approx(0.0)


def test_list_limit_of_10_returns_10_closest_rows():
    app = _load_app()
    peers = pd.DataFrame(
        {"est": [float(i) for i in range(15)], "moe": [1.0] * 15},
        index=[f"{i:05d}" for i in range(15)],
    )
    labels = {f"{i:05d}": f"County {i:02d}" for i in range(15)}
    listed = app._listed_peer_table(peers, labels=labels, self_est=0.0, limit=10)
    assert len(listed) == 10
    assert listed["Rank"].iloc[0] == 1
    assert listed["Estimate"].iloc[0] == pytest.approx(0.0)
    assert listed["Estimate"].max() == pytest.approx(9.0)


def test_column_config_formats_rank_and_similarity():
    config = _load_app()._peer_display_column_config()
    assert config["Rank"]["type_config"]["format"] == "%d"
    similarity = config["Similarity"]
    assert similarity["type_config"]["format"] == "%.1f"
    assert "100" in similarity["help"]


def test_panel_and_map_share_the_listed_peer_helper():
    app = _load_app()
    panel = inspect.getsource(app.render_peer_panel)
    tab = inspect.getsource(app.render_peers_tab)
    assert 'st.selectbox(\n            "Listed counties"' in panel or '"Listed counties"' in panel
    assert "peer_list_n" in panel
    assert "_listed_peer_table(" in panel
    assert "_listed_peer_table(" in tab
    assert "set(result.peers.index)" not in tab
