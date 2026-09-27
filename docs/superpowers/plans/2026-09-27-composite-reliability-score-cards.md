# Composite Reliability Score on Dashboard Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put an equal-weight reliability score (sampling plus imputation), with a neutral band strip, on every eligible card of the US county dashboard v2, with the sub-score breakdown in "Show me the statistics".

**Architecture:** The scoring rules live as pure functions in `analysis/composite.py` (no Streamlit), unit-tested on synthetic values and on real county data. The app (`Streamlit/app_US_v2.py`) maps each measure to an imputation table, precomputes national imputation sub-scores once in `_load_all()`, and passes a `ReliabilityScore` into `render_card()`, which draws a band strip at the top of the card, a one-line note, and a breakdown in the statistics panel. HTML is built by small pure helper functions so it can be tested without a browser.

**Tech Stack:** Python 3.12, pandas, numpy, Streamlit, pytest/unittest. Run everything from the repo root with `.venv/Scripts/python.exe`.

**Spec:** `docs/superpowers/specs/2026-09-27-composite-reliability-score-cards-design.md`

## Global Constraints

- Branch: `card-error-bar-redesign`. Do not push; do not touch other branches.
- Sampling anchors, exactly: CV 0 → 100; 0.12 → 75; 0.30 → 50; 1/1.645 → 0; linear between, 0 above the last.
- Imputation sub-score, exactly: `min(100, 200 * (1 - p))`, `p` = `rates.rank(pct=True, method="average")` over all 3,144 counties, never over the filtered set.
- Score: plain average of the two sub-scores; sampling sub-score alone when no imputation sub-score.
- Bands, exactly: "Higher reliability" (score ≥ 75), "Moderate reliability" (50 ≤ score < 75), "Lower reliability" (< 50).
- Guard: the band is never better than the CV band (CV ≤ 0.12 Higher, ≤ 0.30 Moderate, above Lower).
- Imputation pairings: `income_alloc` (B99192) for Median household income and the four household income bands; `fam_pov_alloc` (B99172, labeled proxy) for the four poverty age bands and "Low income (below 200% of poverty)". Every other measure is sampling only. Total population gets no score.
- Neutral voice: no "risky", "safe", "cite", "use with care", "too imprecise" or any advice wording on the card or in the score text (sponsor direction 2026-08-12).
- Band colors, exactly: bar `#0072B2` / `#E69F00` / `#D55E00`; label text `#005A8C` / `#8A5A00` / `#A34700` (each ≥ 4.5:1 on white); icons ● ▲ ■ for Higher / Moderate / Lower.
- No em dashes in any doc or on-screen text (CLAUDE.md).
- After changing anything in `analysis/`, restart the Streamlit server; the Rerun button keeps the old module.

## Review Focus

- **CV exactly on a band edge (0.12, 0.30):** 0.12 must be Higher and 0.30 Moderate, matching the existing "at most" convention. Test added in Task 1.
- **MOE larger than the estimate (CV above 0.608, the card's "negative lower bound" case):** sampling sub-score 0, band Lower, strip still drawn. Test added in Task 1.
- **A county missing from the allocation file for a scored measure:** sampling-only score with the note "imputation rate not available for this county", never an exception. Test added in Task 2.
- **Four-across compact cards (about 222px wide):** the strip must wrap, not overflow. Checked in the browser in Task 3, Step 7.
- **A measure hidden by the stale-data guard:** no score is computed and the "re-run the pull" card is unchanged. The generic renderer returns before scoring; checked by reading the code in Task 3, Step 4.

---

### Task 1: Scoring rules in `analysis/composite.py`

**Files:**
- Modify: `analysis/composite.py` (append a new section at the end; one docstring line on `equal_weight_score`)
- Test: `analysis/test_composite.py` (append new test classes)

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Task 2):
  - `CV_SUBSCORE_ANCHORS: tuple[tuple[float, float], ...]`
  - `BAND_HIGHER = "Higher reliability"`, `BAND_MODERATE = "Moderate reliability"`, `BAND_LOWER = "Lower reliability"`, `BAND_ORDER = (BAND_LOWER, BAND_MODERATE, BAND_HIGHER)`
  - `cv_subscore(cv: float) -> float`
  - `imputation_subscores(rates: pd.Series) -> pd.Series`
  - `ReliabilityScore` (frozen dataclass): `score: float`, `sampling_sub: float`, `imputation_sub: float | None`, `band: str`, `capped_by_cv: bool`, `imputation_source: str | None`, `imputation_is_proxy: bool`, `imputation_note: str | None`
  - `reliability_score(cv: float, imputation_sub: float | None = None, *, source: str | None = None, is_proxy: bool = False, note: str | None = None) -> ReliabilityScore | None`

- [ ] **Step 1: Write the failing tests**

Append to `analysis/test_composite.py`. Add these to the existing import block from `analysis.composite`: `BAND_HIGHER, BAND_LOWER, BAND_MODERATE, ReliabilityScore, cv_subscore, imputation_subscores, reliability_score`. Also add `from analysis.dashboard import RAW_DIR, load_alloc_us_county` at the top.

```python
class CvSubscoreTest(unittest.TestCase):
    def test_anchors_map_exactly(self) -> None:
        self.assertAlmostEqual(cv_subscore(0.0), 100.0)
        self.assertAlmostEqual(cv_subscore(0.12), 75.0)
        self.assertAlmostEqual(cv_subscore(0.30), 50.0)
        self.assertAlmostEqual(cv_subscore(1 / 1.645), 0.0)

    def test_linear_between_anchors(self) -> None:
        self.assertAlmostEqual(cv_subscore(0.06), 87.5)
        self.assertAlmostEqual(cv_subscore(0.21), 62.5)

    def test_zero_beyond_last_anchor(self) -> None:
        self.assertEqual(cv_subscore(0.9), 0.0)
        self.assertEqual(cv_subscore(12.5), 0.0)

    def test_falls_steadily(self) -> None:
        values = [cv_subscore(c) for c in np.linspace(0, 0.6, 61)]
        self.assertTrue(all(a > b for a, b in zip(values, values[1:])))

    def test_nan_in_nan_out(self) -> None:
        self.assertTrue(np.isnan(cv_subscore(float("nan"))))


class ImputationSubscoresTest(unittest.TestCase):
    def test_median_75th_and_max(self) -> None:
        rates = pd.Series(np.arange(1, 101, dtype=float))  # p = value / 100
        subs = imputation_subscores(rates)
        self.assertEqual(subs.iloc[0], 100.0)            # well below the median
        self.assertAlmostEqual(subs.iloc[49], 100.0)     # p = 0.50
        self.assertAlmostEqual(subs.iloc[74], 50.0)      # p = 0.75
        self.assertAlmostEqual(subs.iloc[99], 0.0)       # p = 1.00, the most imputed

    def test_nan_rates_stay_nan_and_keep_index(self) -> None:
        rates = pd.Series([0.3, np.nan, 0.5], index=["a", "b", "c"])
        subs = imputation_subscores(rates)
        self.assertEqual(list(subs.index), ["a", "b", "c"])
        self.assertTrue(np.isnan(subs["b"]))


class ReliabilityScoreTest(unittest.TestCase):
    def test_averages_two_components(self) -> None:
        rs = reliability_score(0.12, 25.0, source="household income, Table B99192")
        self.assertAlmostEqual(rs.score, 50.0)
        self.assertEqual(rs.sampling_sub, 75.0)
        self.assertEqual(rs.imputation_sub, 25.0)
        self.assertEqual(rs.band, BAND_MODERATE)
        self.assertEqual(rs.imputation_source, "household income, Table B99192")

    def test_sampling_only(self) -> None:
        rs = reliability_score(0.06, note="not published")
        self.assertAlmostEqual(rs.score, 87.5)
        self.assertIsNone(rs.imputation_sub)
        self.assertIsNone(rs.imputation_source)
        self.assertEqual(rs.imputation_note, "not published")
        self.assertEqual(rs.band, BAND_HIGHER)
        self.assertFalse(rs.capped_by_cv)

    def test_band_edges(self) -> None:
        # Score edges: 75 is Higher, 50 is Moderate.
        self.assertEqual(reliability_score(0.12).band, BAND_HIGHER)    # score 75
        self.assertEqual(reliability_score(0.30).band, BAND_MODERATE)  # score 50
        self.assertEqual(reliability_score(0.31).band, BAND_LOWER)

    def test_guard_caps_band_at_cv_band(self) -> None:
        # CV 0.35 alone is Lower; a perfect imputation sub-score lifts the
        # SCORE to about 71 (Moderate range) but must not lift the BAND.
        rs = reliability_score(0.35, 100.0, source="x")
        self.assertAlmostEqual(rs.score, 70.94, places=2)
        self.assertEqual(rs.band, BAND_LOWER)
        self.assertTrue(rs.capped_by_cv)

    def test_imputation_can_lower_band(self) -> None:
        rs = reliability_score(0.04, 1.7, source="x")  # Apache-like
        self.assertEqual(rs.band, BAND_LOWER)
        self.assertFalse(rs.capped_by_cv)

    def test_moe_larger_than_estimate(self) -> None:
        rs = reliability_score(1.5)
        self.assertEqual(rs.sampling_sub, 0.0)
        self.assertEqual(rs.band, BAND_LOWER)

    def test_nan_cv_gives_none(self) -> None:
        self.assertIsNone(reliability_score(float("nan"), 80.0, source="x"))

    def test_nan_imputation_falls_back_to_sampling_only(self) -> None:
        rs = reliability_score(0.06, float("nan"), source="x",
                               note="not available for this county")
        self.assertIsNone(rs.imputation_sub)
        self.assertIsNone(rs.imputation_source)
        self.assertAlmostEqual(rs.score, 87.5)

    def test_is_frozen(self) -> None:
        rs = reliability_score(0.1)
        self.assertIsInstance(rs, ReliabilityScore)
        with self.assertRaises(Exception):
            rs.score = 1.0  # type: ignore[misc]


_USDASH = RAW_DIR / "acs5_2024_usdash_county.parquet"
_USALLOC = RAW_DIR / "acs5_2024_usdash_alloc_county.parquet"


@unittest.skipUnless(_USDASH.exists() and _USALLOC.exists(), "US dashboard data not pulled")
class ReliabilityScoreRealDataTest(unittest.TestCase):
    """Reference values from the spec, computed from the 2026-09-14 pull."""

    @classmethod
    def setUpClass(cls) -> None:
        df = pd.read_parquet(_USDASH)
        alloc = load_alloc_us_county()

        def key(d: pd.DataFrame) -> pd.Series:
            return d["STATE"].astype(str).str.zfill(2) + d["COUNTY"].astype(str).str.zfill(3)

        df.index = key(df)
        alloc.index = key(alloc)
        est = pd.to_numeric(df["B19013_001E"], errors="coerce")
        moe = pd.to_numeric(df["B19013_001M"], errors="coerce")
        cls.cv = (moe / 1.645) / est.where(est > 0)
        cls.imp = imputation_subscores(alloc["income_alloc"]).reindex(df.index)

    def test_apache_county_median_income(self) -> None:
        rs = reliability_score(float(self.cv["04001"]), float(self.imp["04001"]), source="x")
        self.assertAlmostEqual(rs.sampling_sub, 92.11, places=2)
        self.assertAlmostEqual(rs.imputation_sub, 1.72, places=2)
        self.assertAlmostEqual(rs.score, 46.91, places=2)
        self.assertEqual(rs.band, BAND_LOWER)

    def test_national_band_shares_median_income(self) -> None:
        bands = [
            rs.band for rs in (
                reliability_score(float(c), float(i), source="x")
                for c, i in zip(self.cv, self.imp)
            ) if rs is not None
        ]
        self.assertEqual(len(bands), 3143)
        share = pd.Series(bands).value_counts(normalize=True) * 100
        self.assertAlmostEqual(share[BAND_HIGHER], 67.58, places=2)
        self.assertAlmostEqual(share[BAND_MODERATE], 24.98, places=2)
        self.assertAlmostEqual(share[BAND_LOWER], 7.45, places=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest analysis/test_composite.py -q`
Expected: collection error, `ImportError: cannot import name 'BAND_HIGHER' from 'analysis.composite'`.

- [ ] **Step 3: Implement**

Add `from dataclasses import dataclass` and `import numpy as np` to the imports at the top of `analysis/composite.py`. In `equal_weight_score`'s docstring add a second line: `Percentile version for the notebooks; the dashboard card score is reliability_score() below.` Then append:

```python
# ---------------------------------------------------------------------------
# Dashboard reliability score (lead decision #19, 2026-09-27)
#
# OUR methodology, not a Census Bureau product, pending mentor review (README
# "Composite tier philosophy"). Spec:
# docs/superpowers/specs/2026-09-27-composite-reliability-score-cards-design.md
# ---------------------------------------------------------------------------

Z_90 = 1.645

# Sampling sub-score anchors (CV, sub-score), linear between, 0 above the last.
CV_SUBSCORE_ANCHORS: tuple[tuple[float, float], ...] = (
    (0.0, 100.0),
    (0.12, 75.0),      # ESRI high-reliability line (analysis/viz.py CV_REFERENCE_LINES)
    (0.30, 50.0),      # NCHS caution line; HUD's "MOE under half the estimate" rule is CV 0.304
    (1 / Z_90, 0.0),   # MOE equals the estimate: the 90% interval reaches zero (our anchor)
)

BAND_HIGHER = "Higher reliability"
BAND_MODERATE = "Moderate reliability"
BAND_LOWER = "Lower reliability"
BAND_ORDER: tuple[str, ...] = (BAND_LOWER, BAND_MODERATE, BAND_HIGHER)  # worst first

SCORE_BAND_EDGES = (75.0, 50.0)  # Higher at or above the first, Moderate at or above the second
CV_BAND_EDGES = (0.12, 0.30)     # the same lines expressed as CV, "at most" convention


def cv_subscore(cv: float) -> float:
    """Sampling sub-score, 0-100 (higher = more reliable). NaN in, NaN out."""
    if cv is None or not np.isfinite(cv):
        return float("nan")
    xs, ys = zip(*CV_SUBSCORE_ANCHORS)
    return float(np.interp(min(float(cv), xs[-1]), xs, ys))


def imputation_subscores(rates: pd.Series) -> pd.Series:
    """Imputation sub-score for every geography, relative to all of them.

    100 at or below the median rate, 50 at the 75th percentile, 0 for the
    most-imputed. Pass the full national series: ranks are never recomputed
    for a filtered subset. NaN rates stay NaN; the index is preserved.
    """
    p = rates.rank(pct=True, method="average")
    return (200.0 * (1.0 - p)).clip(upper=100.0)


def _band_from_score(score: float) -> str:
    if score >= SCORE_BAND_EDGES[0]:
        return BAND_HIGHER
    if score >= SCORE_BAND_EDGES[1]:
        return BAND_MODERATE
    return BAND_LOWER


def _band_from_cv(cv: float) -> str:
    if cv <= CV_BAND_EDGES[0]:
        return BAND_HIGHER
    if cv <= CV_BAND_EDGES[1]:
        return BAND_MODERATE
    return BAND_LOWER


@dataclass(frozen=True)
class ReliabilityScore:
    """One card's score. `imputation_sub` is None when scored on sampling only."""
    score: float
    sampling_sub: float
    imputation_sub: float | None
    band: str
    capped_by_cv: bool
    imputation_source: str | None = None
    imputation_is_proxy: bool = False
    imputation_note: str | None = None


def reliability_score(
    cv: float,
    imputation_sub: float | None = None,
    *,
    source: str | None = None,
    is_proxy: bool = False,
    note: str | None = None,
) -> ReliabilityScore | None:
    """Equal-weight score with the CV guard on the band. None when CV is NaN.

    A NaN `imputation_sub` is treated as absent (sampling only); pass `note`
    to say why ("not published" or "not available for this county").
    """
    sampling = cv_subscore(cv)
    if np.isnan(sampling):
        return None
    imp = None
    if imputation_sub is not None and np.isfinite(imputation_sub):
        imp = float(imputation_sub)
    score = sampling if imp is None else (sampling + imp) / 2
    by_score = _band_from_score(score)
    by_cv = _band_from_cv(cv)
    band = min(by_score, by_cv, key=BAND_ORDER.index)
    return ReliabilityScore(
        score=score,
        sampling_sub=sampling,
        imputation_sub=imp,
        band=band,
        capped_by_cv=BAND_ORDER.index(by_cv) < BAND_ORDER.index(by_score),
        imputation_source=source if imp is not None else None,
        imputation_is_proxy=is_proxy if imp is not None else False,
        imputation_note=None if imp is not None else note,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest analysis/test_composite.py -q`
Expected: all pass (the real-data class runs, because `data/raw` is present locally).

- [ ] **Step 5: Commit**

```bash
git add analysis/composite.py analysis/test_composite.py
git commit -m "Composite score: equal-weight card reliability score with CV guard"
```
(End the message body with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line.)

---

### Task 2: Measure-to-imputation wiring and card HTML helpers in the app

**Files:**
- Modify: `Streamlit/app_US_v2.py` (imports; `Measure`; `_build_measures()`; `_load_all()`; `_CSS`; new helpers placed just above `render_card`)
- Test: `tests/test_us_v2_score.py` (create)

**Interfaces:**
- Consumes (Task 1): `ReliabilityScore`, `reliability_score`, `imputation_subscores`, `BAND_HIGHER`, `BAND_MODERATE`, `BAND_LOWER` from `analysis.composite` (the app already imports the module as `composite`; use `composite.X`).
- Produces (used by Task 3):
  - `ImputationSource(NamedTuple)`: `column: str`, `label: str`, `is_proxy: bool`
  - `IMPUTATION_SOURCES: dict[str, ImputationSource]` with keys `"income"`, `"family_poverty"`
  - `Measure.imputation: str | None = None`
  - `data["imputation_subs"]: dict[str, pd.Series]` (keyed like `IMPUTATION_SOURCES`, each indexed by county `_key`)
  - `score_for(measure_key: str, code: str, cv: float, imputation_subs: dict[str, pd.Series]) -> ReliabilityScore | None`
  - `BAND_COLOR`, `BAND_TEXT`, `BAND_ICON: dict[str, str]`
  - `_score_strip_html(rs: ReliabilityScore, compact: bool = False) -> str`
  - `_score_note_html(rs: ReliabilityScore) -> str`
  - `_score_breakdown_html(rs: ReliabilityScore) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_us_v2_score.py`:

```python
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
        "Households earning \\$25,000–\\$50,000",
        "Households earning \\$50,000–\\$100,000",
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
```

Note: the income-band keys contain an en dash (–) and escaped dollar signs, exactly as `_INCOME_BAND_TITLES` builds them. If the set assertion fails only on those keys, print `sorted(app.MEASURES)` and copy the exact keys; do not change the app's titles.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_us_v2_score.py -q`
Expected: FAIL, `AttributeError: 'Measure' object has no attribute 'imputation'` (or similar missing-name errors).

- [ ] **Step 3: Implement**

In `Streamlit/app_US_v2.py`:

(a) Just above `@dataclass(frozen=True) class Measure`, add:

```python
class ImputationSource(NamedTuple):
    """An ACS allocation (imputation) table a card's score can draw on."""
    column: str      # column in data["alloc_county"]
    label: str       # shown in the statistics panel
    is_proxy: bool   # True when the table does not measure the card's own item


# Card reliability score (lead decision #19, 2026-09-27). Only these two
# tables pair with dashboard measures; every other measure is scored on
# sampling alone and says "imputation not published". Age bands are
# deliberately sampling only: age imputation is 1.1% at the median county,
# too small for a relative scale to mean anything.
IMPUTATION_SOURCES: dict[str, ImputationSource] = {
    "income": ImputationSource("income_alloc", "household income, Table B99192", False),
    "family_poverty": ImputationSource(
        "fam_pov_alloc", "family poverty status, Table B99172", True,
    ),
}
```

`NamedTuple` is already imported (used by `StateReference`); confirm with `grep -n "NamedTuple" Streamlit/app_US_v2.py`.

(b) Add a field to `Measure`, after `controlled_when_moe_missing`:

```python
    # Key into IMPUTATION_SOURCES, or None for a sampling-only score.
    imputation: str | None = None
```

(c) In `_build_measures()`: add `imputation="income",` to the "Median household income" `Measure(...)`; add `imputation="family_poverty",` to "Low income (below 200% of poverty)"; add `imputation="family_poverty",` inside the poverty-band loop's `Measure(...)`; add `imputation="income",` inside the `INCOME_BANDS` loop's `Measure(...)`.

(d) In `_load_all()`, before the `return`, add:

```python
    alloc_by_key = alloc_county.set_index("_key")
    imputation_subs = {
        name: composite.imputation_subscores(alloc_by_key[src.column])
        for name, src in IMPUTATION_SOURCES.items()
    }
```

and add `"imputation_subs": imputation_subs,` to the returned dict.

(e) Add to `_CSS`, just before `</style>`:

```css
.score-strip { display: flex; justify-content: space-between; align-items: baseline;
               flex-wrap: wrap; gap: 2px 8px; padding-top: 6px; margin-bottom: 4px;
               font-size: 0.8rem; }
.score-band  { font-weight: 700; }
.score-num   { color: #5A5A5A; white-space: nowrap; }
.score-num b { color: #131313; }
.score-bar-row { display: grid; grid-template-columns: 8.5rem 1fr 2.5rem; gap: 8px;
                 align-items: center; padding: 5px 2px; font-size: 0.85rem;
                 border-bottom: 1px solid #E6E6E6; }
.score-bar-row .label { color: #5A5A5A; }
.score-bar-row .value { text-align: right; font-weight: 600; color: #222;
                        font-variant-numeric: tabular-nums; }
.score-bar { display: block; position: relative; height: 6px; background: #EEEEEE;
             border-radius: 3px; }
.score-bar > span { position: absolute; left: 0; top: 0; height: 6px;
                    background: #5A6672; border-radius: 3px; }
```

(f) Just above `def render_card(`, add:

```python
# Band colors reuse the Trenton prototype's tier colors (Streamlit/app.py
# TIER_COLOR), per the lead (2026-09-27). Label text uses a darker shade of
# each so it passes WCAG AA (4.5:1) on white; the bar keeps the brand color.
BAND_COLOR = {composite.BAND_HIGHER: "#0072B2", composite.BAND_MODERATE: "#E69F00",
              composite.BAND_LOWER: "#D55E00"}
BAND_TEXT = {composite.BAND_HIGHER: "#005A8C", composite.BAND_MODERATE: "#8A5A00",
             composite.BAND_LOWER: "#A34700"}
BAND_ICON = {composite.BAND_HIGHER: "●", composite.BAND_MODERATE: "▲",
             composite.BAND_LOWER: "■"}


def score_for(measure_key: str, code: str, cv: float,
              imputation_subs: dict[str, pd.Series]) -> composite.ReliabilityScore | None:
    """The card score for one measure in one county (None when CV is NaN)."""
    measure = MEASURES[measure_key]
    if measure.imputation is None:
        return composite.reliability_score(cv, note="not published")
    src = IMPUTATION_SOURCES[measure.imputation]
    sub = imputation_subs[measure.imputation].get(code, float("nan"))
    if pd.isna(sub):
        return composite.reliability_score(cv, note="not available for this county")
    return composite.reliability_score(cv, float(sub), source=src.label, is_proxy=src.is_proxy)


def _score_strip_html(rs: composite.ReliabilityScore, compact: bool = False) -> str:
    """Band strip for the top of a card: colored bar, band label, score."""
    number = f"<b>{rs.score:.0f}</b> / 100"
    right = number if compact else f"Reliability score {number}"
    return (
        f"<div class='score-strip' style='border-top: 4px solid {BAND_COLOR[rs.band]};'>"
        f"<span class='score-band' style='color: {BAND_TEXT[rs.band]};'>"
        f"<span aria-hidden='true'>{BAND_ICON[rs.band]}</span> {rs.band}</span>"
        f"<span class='score-num'>{right}</span></div>"
    )


def _score_note_html(rs: composite.ReliabilityScore) -> str:
    """One neutral line under the card's dashed divider."""
    if rs.imputation_sub is not None:
        text = f"Sampling {rs.sampling_sub:.0f}, imputation {rs.imputation_sub:.0f}, averaged."
    elif rs.imputation_note == "not available for this county":
        text = "Sampling only: imputation rate not available for this county."
    else:
        text = "Sampling only: imputation not published for this figure."
    return f"<div class='card-alloc'>{text}</div>"


def _score_breakdown_html(rs: composite.ReliabilityScore) -> str:
    """Sub-score bars and facts for 'Show me the statistics'."""
    def bar(label: str, value: float | None, missing: str) -> str:
        if value is None:
            return (f"<div class='score-bar-row'><span class='label'>{label}</span>"
                    f"<span></span><span class='value'>{missing}</span></div>")
        return (f"<div class='score-bar-row'><span class='label'>{label}</span>"
                f"<span class='score-bar'><span style='width: {value:.0f}%;'></span></span>"
                f"<span class='value'>{value:.0f}</span></div>")

    missing = rs.imputation_note or "not published"
    band = rs.band + (" (capped by the CV)" if rs.capped_by_cv else "")
    source = "not published" if rs.imputation_source is None else (
        rs.imputation_source + (" [proxy]" if rs.imputation_is_proxy else ""))
    return (
        f"<div class='stat-row'><span class='label'>Reliability score</span>"
        f"<span class='value'>{rs.score:.1f} / 100</span></div>"
        f"<div class='stat-row'><span class='label'>Band</span>"
        f"<span class='value'>{band}</span></div>"
        + bar("Sampling sub-score", rs.sampling_sub, "")
        + bar("Imputation sub-score", rs.imputation_sub, missing)
        + f"<div class='stat-row'><span class='label'>Imputation source</span>"
        f"<span class='value'>{source}</span></div>"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_us_v2_score.py -q`
Expected: all pass.

- [ ] **Step 5: Run the full suite (nothing else broke)**

Run: `.venv/Scripts/python.exe -m pytest analysis/ tests/ -q`
Expected: all pass (the 165 existing plus this task's and Task 1's new tests), 7 or more skipped.

- [ ] **Step 6: Commit**

```bash
git add Streamlit/app_US_v2.py tests/test_us_v2_score.py
git commit -m "Dashboard v2: map measures to imputation tables; score strip HTML helpers"
```
(End the message body with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line.)

---

### Task 3: Draw the score on the cards and in the statistics panel

**Files:**
- Modify: `Streamlit/app_US_v2.py` (`render_card`; the generic `_render_measure_card` call; the median-income `render_card` call; module docstring points 3 and 6)

**Interfaces:**
- Consumes (Task 2): `score_for`, `_score_strip_html`, `_score_note_html`, `_score_breakdown_html`, `data["imputation_subs"]`; existing `cv_from_range`, `acs_range`.
- Produces: `render_card(..., reliability: composite.ReliabilityScore | None = None)`.

- [ ] **Step 1: Add the parameter and the strip**

In `render_card`'s signature, after `compact: bool = False,` add `reliability: composite.ReliabilityScore | None = None,`. Add to its docstring: `` `reliability`: the card's score (lead decision #19); when given, a band strip opens the card, a one-line note follows the interval graphic, and the breakdown joins "Show me the statistics". ``

Inside `with st.container(border=True):`, make the strip the first element, before `st.markdown(f"**{title}**")`:

```python
        if reliability is not None:
            st.markdown(_score_strip_html(reliability, compact=compact), unsafe_allow_html=True)
```

- [ ] **Step 2: Add the note under the interval graphic**

Directly after the block that draws `_interval_svg(...)` and its `reference_note` caption (the `if not np.isnan(cv):` block), add:

```python
        if reliability is not None:
            st.markdown(_score_note_html(reliability), unsafe_allow_html=True)
```

- [ ] **Step 3: Add the breakdown to "Show me the statistics"**

Inside the expander, immediately before `_stats_panel(rows, note)`, add:

```python
            if reliability is not None:
                note += (
                    " Reliability score (our methodology, pending mentor review): the average "
                    "of a sampling sub-score set from the CV (100 at 0, 75 at 0.12, the ESRI "
                    "high-reliability line, 50 at 0.30, the NCHS caution line, and 0 where the "
                    "margin of error equals the estimate) and, where the Census Bureau publishes "
                    "an imputation table for this figure, an imputation sub-score comparing this "
                    "county with all US counties (100 at or below the national median, 50 at "
                    "the 75th percentile). The band is never higher than the CV alone gives."
                )
```

and immediately after `_stats_panel(rows, note)`:

```python
            if reliability is not None:
                st.markdown(_score_breakdown_html(reliability), unsafe_allow_html=True)
```

- [ ] **Step 4: Pass the score from the two call sites**

In `_render_measure_card` (inside `render_explorer`), confirm the stale-data branch (`if measure_label in unavailable:`) and the NaN-estimate and NaN-MOE branches all `return` before the final `render_card(...)`, so no score is computed for them. Then change the final call to add:

```python
            reliability=score_for(measure_label, code, cv_from_range(e, *acs_range(e, m)),
                                  data["imputation_subs"]),
```

In the median household income call (the `render_card("Median household income", ...)` inside `if income_selected:`), add:

```python
                        reliability=score_for(
                            "Median household income", code,
                            cv_from_range(income_est, *acs_range(income_est, income_moe)),
                            data["imputation_subs"],
                        ),
```

Leave the Total population call unchanged (no score, per the spec). Confirm `cv_from_range` and `acs_range` are already imported: `grep -n "cv_from_range\|acs_range" Streamlit/app_US_v2.py | head -3`.

- [ ] **Step 5: Update the module docstring**

Replace point 3's first sentence block so it reads:

```
3. Neutral federal-statistical-agency voice (sponsor direction,
   2026-08-12, see README's "Composite tier philosophy" open question):
   no "safe to cite" / "too risky" language. The card reliability score
   (point 6) therefore uses descriptive bands, "Higher / Moderate / Lower
   reliability", which describe the score and give no advice.
```

keeping the rest of point 3 (map colors, CV number, `analysis.dashboard.tier()` unchanged) as it is. Replace point 6 with:

```
6. Card reliability score (lead decision #19, 2026-09-27): an equal-weight
   average of a sampling sub-score (from the CV, anchored to the ESRI 0.12
   and NCHS 0.30 lines) and, for income and poverty figures, an imputation
   sub-score relative to all US counties, with the band capped at the CV's
   own band. Built by analysis.composite.reliability_score(); spec in
   docs/superpowers/specs/2026-09-27-composite-reliability-score-cards-design.md.
   The composite tier question stays open for mentors; this is our
   methodology, not a Census Bureau product.
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest analysis/ tests/ -q`
Expected: all pass.

- [ ] **Step 7: Verify in the real app**

Restart the server (analysis/ changed): `preview_stop` the `us-dashboard-v2-8503` server, then `preview_start` it again. In the County explorer, choose Arizona, then Apache County. In "Choose what to show", add Unemployed, Poverty: Under 5, Under 5 and Median gross rent. Check:
- Median household income: strip "■ Lower reliability", "Reliability score 47 / 100", note "Sampling 92, imputation 2, averaged."
- Unemployed: "● Higher reliability", 84 / 100, "Sampling only: imputation not published for this figure."
- Poverty: Under 5: a strip with a two-part note; statistics panel shows "[proxy]".
- Under 5: sampling-only note.
- Total population: no strip.
- The four-across cards: strip wraps inside the card with no overflow.
- "Show me the statistics" on the income card: score, band, two bars, source.
- `preview_logs` shows no errors; `read_console_messages` shows nothing new beyond the known `height="auto"` SVG warning.
Then Washtenaw County, MI: median income shows Higher reliability. Take a screenshot of the Apache cards for the lead.

- [ ] **Step 8: Commit**

```bash
git add Streamlit/app_US_v2.py
git commit -m "Dashboard v2: reliability score strip on cards, breakdown in statistics panel"
```
(End the message body with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line.)

---

### Task 4: Project documentation

**Files:**
- Modify: `HANDOFF.md`, `README.md`, `WORKLOG.md`, `docs/glossary.md`, `Streamlit/README.md`

**Interfaces:** none (docs only). No em dashes in any added text.

- [ ] **Step 1: HANDOFF.md**

After decision 18 in "Decisions already made", add:

```markdown
19. **Card reliability score (lead decision, 2026-09-27):** the US dashboard v2 shows an equal-weight score on each card: the average of a sampling sub-score (CV 0 → 100, 0.12 → 75, 0.30 → 50, 1/1.645 → 0; ESRI and NCHS lines, the last anchor is where the 90% interval reaches zero) and, for income (B99192) and poverty (B99172, labeled proxy) figures only, an imputation sub-score relative to all US counties (100 at or below the national median, 50 at the 75th percentile). Bands: Higher (75+), Moderate (50 to below 75), Lower (below 50), never better than the CV's own band (the guard; without it 15.4% of scored county figures would be banded above their CV). Neutral band labels because of the sponsor's 2026-08-12 voice direction. Age bands and all other measures are sampling only; total population is unscored. Our methodology, pending mentor review (README Open Questions). Spec: `docs/superpowers/specs/2026-09-27-composite-reliability-score-cards-design.md`; code: `analysis.composite.reliability_score`.
```

In the "US county dashboard v2" bullet of "Where the project stands", add one sentence: `Cards now carry a reliability score and band strip (decision #19, 2026-09-27).`

- [ ] **Step 2: README.md**

At the end of the "Composite tier philosophy" open question, append: ` **Update 2026-09-27 (lead decision #19):** the US dashboard now shows an equal-weight card score with a CV guard on the band and neutral band labels. For mentors: are the sampling anchors (ESRI 0.12, NCHS 0.30, interval reaching zero), the relative imputation scale (national percentile within each allocation table) and the guard the right choices?`

- [ ] **Step 3: docs/glossary.md**

Add, in the file's existing format and alphabetical position:
- **Reliability score (dashboard card):** our 0 to 100 score for one figure in one county, the average of its sampling sub-score and, where published, its imputation sub-score. Higher means more reliable. Not a Census Bureau product.
- **Sampling sub-score:** the CV mapped to 0 to 100 through fixed anchors: 100 at CV 0, 75 at 0.12, 50 at 0.30, 0 where the margin of error equals the estimate.
- **Imputation sub-score:** how a county's imputation (allocation) rate compares with every US county on the same allocation table: 100 at or below the national median, 50 at the 75th percentile, 0 for the most imputed.

- [ ] **Step 4: Streamlit/README.md**

In "What is on it", add a bullet after "State comparison":

```markdown
- **Reliability score (2026-09-27).** A strip across the top of each card gives a band (Higher, Moderate or Lower reliability) and a 0 to 100 score: the average of a sampling sub-score from the CV and, for income and poverty figures, an imputation sub-score comparing the county with all US counties. The band is never better than the CV alone gives. "Show me the statistics" shows both sub-scores. Total population has no score. Our methodology, pending mentor review (HANDOFF decision #19).
```

In "Adding a measure", add a step before the re-pull step: `If the Census Bureau publishes an allocation table for the measure's item, add it to IMPUTATION_SOURCES (and to the allocation pull) and set Measure.imputation; otherwise the card is scored on sampling only and says so.`

- [ ] **Step 5: WORKLOG.md**

Add at the top of the Log section, filling the two counts from the Task 3 Step 6 pytest output:

```markdown
### 2026-09-27 — Andrew Swiniarski — US county dashboard v2: reliability score on cards (decision #19)
- **Area:** dashboard / analysis
- **What was done:** Put the composite reliability score on the dashboard cards. Each card gets a band strip (Higher, Moderate or Lower reliability) and a 0 to 100 score: the equal-weight average of a sampling sub-score from the CV and, for the ten income and poverty cards, an imputation sub-score comparing the county with every US county on the same allocation table. "Show me the statistics" shows the two sub-scores as bars. The lead chose equal weighting, the cut-offs, the band-strip layout and neutral labels after comparing mockups.
- **Findings / decisions:** (1) **County CVs rarely cross 0.30 for medians** (0.3% of counties for median income) but often do for small counts (55% for limited-English households, 36% for poverty under 5), so the score is per figure, not per county; a single county-wide score would largely re-map population size (Spearman 0.85). (2) **Imputation is scored relative, not absolute:** rates are driven by the question (median county 38% for income, 1% for age), no published standard exists, and an absolute scale would mark every income figure down. Age bands are sampling only for that reason. (3) **The guard matters:** without it, 6,743 of 43,778 scored county figures (15.4%) would be banded better than their CV allows. (4) **Neutral labels** because the v2 docstring records a sponsor direction (2026-08-12) against verdict wording; the original sponsor wording was not found elsewhere in the repo. (5) Median household income: 67.58% Higher, 24.98% Moderate, 7.45% Lower of 3,143 scored counties; Apache County, AZ scores 46.91 (Lower): CV 3.8% but 58.8% of household incomes imputed, more than 99% of counties. These figures are asserted in `analysis/test_composite.py`, not yet in a notebook. (6) Pre-existing, not fixed: `_interval_svg` labels two ticks "2K" on some axes (1,500 rounds to 2K). Verified: N pass and M skip (`analysis/` + `tests/`); Apache and Washtenaw checked in the running app.
- **Files:** analysis/composite.py, analysis/test_composite.py, Streamlit/app_US_v2.py, tests/test_us_v2_score.py (new), docs/superpowers/specs/2026-09-27-composite-reliability-score-cards-design.md, docs/superpowers/plans/2026-09-27-composite-reliability-score-cards.md, HANDOFF.md, README.md, docs/glossary.md, Streamlit/README.md, .claude/launch.json, WORKLOG.md.
- **Next:** mentor review of the anchors, relative imputation scale and guard; an assert-guarded notebook before these figures enter the findings report or a deck; the county report card and map layer remain deferred.
```

Replace `N` and `M` with the real counts.

- [ ] **Step 6: Check for em dashes in added text and commit**

Run: `git diff HANDOFF.md README.md docs/glossary.md Streamlit/README.md | grep "^+" | grep -c "—"`
Expected: `0` (the WORKLOG heading separator follows the file's existing template and is exempt; it is not in this diff check).

```bash
git add HANDOFF.md README.md WORKLOG.md docs/glossary.md Streamlit/README.md .claude/launch.json docs/superpowers/plans/2026-09-27-composite-reliability-score-cards.md
git commit -m "Docs: decision #19, card reliability score (HANDOFF, README, WORKLOG, glossary)"
```
(End the message body with the `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` line.)
