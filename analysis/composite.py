"""Composite reliability helpers for ACS sampling CV + allocation rates.

What it does
------------
Builds a two-axis reliability matrix (CV vs allocation) and optional
sensitivity scores (equal-weight, worst-component). This is an exploratory
prototype for mentor review — not an official Census product.

What it needs
-------------
Joined rows with:
- a CV column (from analysis.acs.cv)
- an allocation-rate column in [0, 1] (from analysis.alloc.derive_rates)

Default thresholds
------------------
- CV flag: 0.30 (Census ACS quality standard for "unreliable for most uses")
- Allocation flag: exploratory NJ 75th percentile of the chosen rate
  (not an official Census cutoff; document in notebook findings)

Plain-English matrix
--------------------
Four quadrants from CV_ok x alloc_ok:
1. low CV / low allocation  — relatively trustworthy on both axes
2. low CV / high allocation — CV looks fine but imputation is high (blind spot)
3. high CV / low allocation — sampling noise dominates
4. high CV / high allocation — both axes elevated
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from analysis.cv_model import (
    RESIDUAL_PERCENTILE_DEFAULT,
    flag_high_cv_residual,
)

CV_THRESHOLD_DEFAULT = 0.30
ALLOC_PERCENTILE_DEFAULT = 0.75

QuadrantLabel = Literal[
    "low_cv_low_alloc",
    "low_cv_high_alloc",
    "high_cv_low_alloc",
    "high_cv_high_alloc",
]

QUADRANT_ORDER: tuple[QuadrantLabel, ...] = (
    "low_cv_low_alloc",
    "low_cv_high_alloc",
    "high_cv_low_alloc",
    "high_cv_high_alloc",
)

QUADRANT_LABELS_PLAIN: dict[QuadrantLabel, str] = {
    "low_cv_low_alloc": "Low CV / low allocation",
    "low_cv_high_alloc": "Low CV / high allocation (blind spot)",
    "high_cv_low_alloc": "High CV / low allocation",
    "high_cv_high_alloc": "High CV / high allocation",
}


def allocation_flag_threshold(
    rates: pd.Series,
    percentile: float = ALLOC_PERCENTILE_DEFAULT,
) -> float:
    """Return the exploratory allocation flag at a sample percentile.

    NaNs are ignored. Raises if no finite values remain.
    """
    if not 0 < percentile < 1:
        raise ValueError(f"percentile must be in (0, 1), got {percentile}")
    clean = rates.dropna()
    if clean.empty:
        raise ValueError("rates has no non-null values for threshold")
    return float(clean.quantile(percentile))


def classify_quadrant(
    cv: pd.Series,
    alloc_rate: pd.Series,
    *,
    cv_threshold: float = CV_THRESHOLD_DEFAULT,
    alloc_threshold: float,
) -> pd.Series:
    """Classify each row into one of four reliability quadrants.

    Rows with missing CV or allocation rate receive NaN (not a quadrant).
    """
    if cv_threshold <= 0:
        raise ValueError(f"cv_threshold must be > 0, got {cv_threshold}")

    aligned = pd.concat(
        [cv.rename("cv"), alloc_rate.rename("alloc")],
        axis=1,
        join="outer",
    )
    cv_ok = aligned["cv"] <= cv_threshold
    alloc_ok = aligned["alloc"] <= alloc_threshold
    both_present = aligned["cv"].notna() & aligned["alloc"].notna()

    labels = pd.Series(pd.NA, index=aligned.index, dtype="object")
    labels.loc[both_present & cv_ok & alloc_ok] = "low_cv_low_alloc"
    labels.loc[both_present & cv_ok & ~alloc_ok] = "low_cv_high_alloc"
    labels.loc[both_present & ~cv_ok & alloc_ok] = "high_cv_low_alloc"
    labels.loc[both_present & ~cv_ok & ~alloc_ok] = "high_cv_high_alloc"
    return labels


def percentile_risk(series: pd.Series) -> pd.Series:
    """Map values to empirical percentile ranks in [0, 1] (higher = riskier).

    NaNs stay NaN. Ties use the average rank (pandas default).
    """
    return series.rank(pct=True, method="average")


def equal_weight_score(cv: pd.Series, alloc_rate: pd.Series) -> pd.Series:
    """Mean of CV and allocation percentile ranks (sensitivity check).

    Percentile version for the notebooks; the dashboard card score is
    reliability_score() below.
    """
    return (percentile_risk(cv) + percentile_risk(alloc_rate)) / 2


def worst_component_score(cv: pd.Series, alloc_rate: pd.Series) -> pd.Series:
    """Max of CV and allocation percentile ranks (sensitivity check)."""
    return pd.concat(
        [percentile_risk(cv), percentile_risk(alloc_rate)],
        axis=1,
    ).max(axis=1)


def quadrant_counts(labels: pd.Series) -> pd.Series:
    """Count rows per quadrant in a fixed display order (missing excluded)."""
    counts = labels.value_counts(dropna=True)
    return pd.Series(
        {q: int(counts.get(q, 0)) for q in QUADRANT_ORDER},
        dtype="int64",
    )


def build_reliability_frame(
    df: pd.DataFrame,
    *,
    cv_col: str,
    alloc_col: str,
    cv_threshold: float = CV_THRESHOLD_DEFAULT,
    alloc_percentile: float = ALLOC_PERCENTILE_DEFAULT,
    alloc_threshold: float | None = None,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Attach quadrant labels and sensitivity scores; return (frame, thresholds).

    Does not mutate the input. Threshold dict always includes cv_threshold and
    alloc_threshold used for classification.
    """
    if cv_col not in df.columns:
        raise KeyError(f"cv_col {cv_col!r} not in dataframe")
    if alloc_col not in df.columns:
        raise KeyError(f"alloc_col {alloc_col!r} not in dataframe")

    out = df.copy()
    if alloc_threshold is None:
        alloc_threshold = allocation_flag_threshold(
            out[alloc_col], percentile=alloc_percentile
        )

    out["quadrant"] = classify_quadrant(
        out[cv_col],
        out[alloc_col],
        cv_threshold=cv_threshold,
        alloc_threshold=alloc_threshold,
    )
    out["equal_weight_score"] = equal_weight_score(out[cv_col], out[alloc_col])
    out["worst_component_score"] = worst_component_score(out[cv_col], out[alloc_col])

    thresholds = {
        "cv_threshold": float(cv_threshold),
        "alloc_threshold": float(alloc_threshold),
        "alloc_percentile": float(alloc_percentile),
    }
    return out, thresholds


def attach_cv_residual_flag(
    df: pd.DataFrame,
    *,
    cv_col: str,
    estimate_size_col: str,
    residual_percentile: float = RESIDUAL_PERCENTILE_DEFAULT,
    flag_col: str = "cv_residual_high",
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Attach a sampling-axis residual flag (composite V2 tooltip seed).

    Fits log(CV) ~ log(estimate_size) and flags rows whose residual is at/above
    the sample percentile — i.e. CV worse than expected given size. Does not
    change quadrant labels or allocation logic.
    """
    if cv_col not in df.columns:
        raise KeyError(f"cv_col {cv_col!r} not in dataframe")
    if estimate_size_col not in df.columns:
        raise KeyError(f"estimate_size_col {estimate_size_col!r} not in dataframe")

    out = df.copy()
    flag, meta = flag_high_cv_residual(
        out[cv_col],
        out[estimate_size_col],
        residual_percentile=residual_percentile,
    )
    out[flag_col] = flag
    return out, meta


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
