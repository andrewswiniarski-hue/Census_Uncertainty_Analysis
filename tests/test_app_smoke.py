"""Smoke tests for the US county dashboard v7.

Run:
    python -m pytest tests/test_app_smoke.py -v

Checks that the app file loads, carries the expected measure registries,
reproduces known peer counts for Jefferson County, Alabama (01073), and that
each main tab renders without an exception. Real-data tests are skipped when
data/raw/acs5_2024_usdash_county.parquet is absent.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from analysis.dashboard import RAW_DIR  # noqa: E402

APP_FILES = ["us_county_explorer.py"]

needs_data = pytest.mark.skipif(
    not (RAW_DIR / "acs5_2024_usdash_county.parquet").exists(),
    reason="needs data/raw/acs5_2024_usdash_county.parquet (run ingestion/pull_usdash.py)",
)


@pytest.fixture(scope="module", params=APP_FILES)
def app_path(request):
    return REPO_ROOT / "Streamlit" / request.param


@pytest.fixture(scope="module")
def app(app_path):
    name = "smoke_" + app_path.stem.replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, app_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses needs the module registered
    spec.loader.exec_module(mod)
    return mod


def test_registry_sizes(app):
    assert len(app.MEASURES) == 26
    assert len(app.PEER_MEASURES) == 21


@needs_data
def test_jefferson_income_peers(app):
    data = app._load_all()
    r = app._compute_peers(data["county_df"], "01073", "Median household income", True, True)
    assert (r.pool_n, r.tested_n, len(r.peers), r.n_higher, r.n_lower) == (238, 237, 18, 196, 23)


@needs_data
@pytest.mark.parametrize("tab", ["Welcome", "County explorer", "Statistical peers"])
def test_tabs_load(app_path, tab):
    at = AppTest.from_file(str(app_path), default_timeout=180)
    at.session_state["main_tabs"] = tab
    at.session_state["us_geo"] = {"level": "county", "code": "01073", "state_scope": "01"}
    at.run()
    assert not at.exception
