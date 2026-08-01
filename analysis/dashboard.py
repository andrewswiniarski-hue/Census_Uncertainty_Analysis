"""Formulas and thresholds behind the Trenton dashboard prototype (Streamlit/app.py).

What it does
------------
Everything the app needs that isn't presentation: the four grant-relevant
age bands (mapped onto ACS's B01001/B17001 cells and DHC's P12 cells, which
share an identical sex-x-age layout), range-first uncertainty for both
products, and the plain-language reliability tier. Keeping this here means
the Streamlit file only renders -- every number it shows traces to a tested
function.

Reuses rather than reinvents: analysis.acs (aggregate_estimate,
aggregate_moe, Z_90 -- the same handbook zero-cell MOE rule every ACS
notebook uses) and analysis.noise_model (the DAS noise model, EDA 04).

What it needs
-------------
data/raw/acs5_2024_trenton_{place,county,tract}.parquet and
data/raw/dhc_2020_trenton_{place,county,tract}.parquet
(regenerate with: python ingestion/pull_trenton_dashboard.py)

Two methodology choices made here, both approved before building:
--------------------------------------------------------------
1. Tiers (Solid / Use with care / Too risky) use the ESRI 0.12 and NCHS
   0.30 CV conventions already cited in analysis/viz.py -- labeled in the
   app as OUR proposed tiers, not adopted Census thresholds (HANDOFF.md
   decision #8: our tiers are a Weeks 4-6 call with mentors, not decided).
2. DHC ships no MOE. To render a DHC number in the same range-first card
   as ACS, its modeled relative noise is scaled by Z_90 into a
   comparable interval -- flagged everywhere as MODELED, not measured.
   "Place" (Trenton) is not a DAS spine geography (state/county/tract/
   block group/block only), so its DHC range is NOT looked up directly --
   it's built by root-sum-of-squares over the 25 constituent tracts'
   modeled errors, the same independence-assumption aggregation the ACS
   MOE handbook rule already uses (analysis.acs.aggregate_moe). This is
   an extension of the noise model, not something notebook 04 measured;
   call it out if reviewing this file.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from analysis.acs import Z_90, aggregate_estimate, aggregate_moe
from analysis.noise_model import BLACK_65PLUS_RMSE_BY_LEVEL, estimate_relative_noise

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"

LEVELS = ["place", "county", "tract"]
GEO_LABELS = {"place": "Trenton (whole city)", "county": "Mercer County", "tract": "Tract"}
N_TRENTON_TRACTS = 25

BANDS = ["Under 5", "5-17", "18-64", "65+"]
SEXES = ["male", "female", "both"]

# Cell numbers (no table prefix, no E/M/N suffix) -- verified live against
# both APIs during planning. B01001 and P12 share this exact layout;
# B17001 uses different age brackets, mapped onto the same four bands.
_SEXAGE_CELLS = {
    "Under 5": {"male": ["003"], "female": ["027"]},
    "5-17": {"male": ["004", "005", "006"], "female": ["028", "029", "030"]},
    "18-64": {
        "male": [f"{i:03d}" for i in range(7, 20)],
        "female": [f"{i:03d}" for i in range(31, 44)],
    },
    "65+": {
        "male": ["020", "021", "022", "023", "024", "025"],
        "female": ["044", "045", "046", "047", "048", "049"],
    },
}
_POVERTY_CELLS = {
    "Under 5": {"male": ["004"], "female": ["018"]},
    "5-17": {"male": ["005", "006", "007", "008", "009"], "female": ["019", "020", "021", "022", "023"]},
    "18-64": {"male": ["010", "011", "012", "013", "014"], "female": ["024", "025", "026", "027", "028"]},
    "65+": {"male": ["015", "016"], "female": ["029", "030"]},
}
# The mirror "at or above poverty level" branch -- same age cells, offset
# +29 from _POVERTY_CELLS. Below + at-or-above = the true poverty-universe
# total per band (verified live in planning). This is NOT the same universe
# as B01001's total population -- B17001 excludes some group quarters
# populations from poverty-status determination -- so it must be pulled
# and summed, not approximated from the population bands.
_POVERTY_ABOVE_CELLS = {
    "Under 5": {"male": ["033"], "female": ["047"]},
    "5-17": {"male": ["034", "035", "036", "037", "038"], "female": ["048", "049", "050", "051", "052"]},
    "18-64": {"male": ["039", "040", "041", "042", "043"], "female": ["053", "054", "055", "056", "057"]},
    "65+": {"male": ["044", "045"], "female": ["058", "059"]},
}


def _sexes(sex: str) -> list[str]:
    if sex not in SEXES:
        raise ValueError(f"sex must be one of {SEXES}, got {sex!r}")
    return ["male", "female"] if sex == "both" else [sex]


def _codes(prefix: str, cells: dict, band: str, sex: str) -> list[str]:
    if band not in BANDS:
        raise ValueError(f"band must be one of {BANDS}, got {band!r}")
    return [f"{prefix}_{n}" for s in _sexes(sex) for n in cells[band][s]]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_acs(level: str) -> pd.DataFrame:
    """ACS 5-year B01001 (sex x age) + B17001 (poverty) for Trenton/Mercer."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    path = RAW_DIR / f"acs5_2024_trenton_{level}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_trenton_dashboard.py"
        )
    df = pd.read_parquet(path)
    value_cols = [c for c in df.columns if c[:-1].startswith(("B01001_", "B17001_"))]
    df[value_cols] = df[value_cols].apply(pd.to_numeric, errors="coerce")
    return df


def load_dhc(level: str) -> pd.DataFrame:
    """2020 DHC P12 (sex x age, full count) for Trenton/Mercer."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    path = RAW_DIR / f"dhc_2020_trenton_{level}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_trenton_dashboard.py"
        )
    df = pd.read_parquet(path)
    value_cols = [c for c in df.columns if c.startswith("P1")]
    df[value_cols] = df[value_cols].apply(pd.to_numeric, errors="coerce")
    return df


def load_trenton_tracts() -> pd.DataFrame:
    """25 Mercer tracts inside the Trenton place polygon (with geometry)."""
    import geopandas as gpd

    path = RAW_DIR / "trenton_tracts.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- regenerate with: python ingestion/pull_trenton_dashboard.py"
        )
    return gpd.read_parquet(path)


# ---------------------------------------------------------------------------
# ACS estimate + measured range
# ---------------------------------------------------------------------------

def acs_sexage(df: pd.DataFrame, band: str, sex: str) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for an ACS sex/age band -- row-aligned with df."""
    codes = _codes("B01001", _SEXAGE_CELLS, band, sex)
    return aggregate_estimate(df, codes), aggregate_moe(df, codes)


def acs_poverty(df: pd.DataFrame, band: str, sex: str) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for the below-poverty-level count in an age/sex band."""
    codes = _codes("B17001", _POVERTY_CELLS, band, sex)
    return aggregate_estimate(df, codes), aggregate_moe(df, codes)


def acs_poverty_universe(df: pd.DataFrame, band: str, sex: str) -> tuple[pd.Series, pd.Series]:
    """(estimate, moe) for the poverty UNIVERSE (below + at-or-above) in a band.

    The correct denominator for a poverty rate -- not B01001's total
    population, which is a different (larger) universe. See module
    docstring and ingestion/pull_trenton_dashboard.py.
    """
    codes = _codes("B17001", _POVERTY_CELLS, band, sex) + _codes(
        "B17001", _POVERTY_ABOVE_CELLS, band, sex
    )
    return aggregate_estimate(df, codes), aggregate_moe(df, codes)


def acs_range(est: float, moe: float) -> tuple[float, float]:
    """MOE is already a 90%-confidence half-width -- the range is est +/- moe."""
    return est - moe, est + moe


def poverty_rate(
    below_est: float, below_moe: float, universe_est: float, universe_moe: float
) -> tuple[float, float]:
    """Percent below poverty (0-100) and its MOE, via the ACS ratio-MOE formula.

    `below` is a SUBSET of `universe` (poverty count within the poverty
    universe for the same age band), so this is a proportion, not two
    independent estimates -- summing MOEs in quadrature (aggregate_moe)
    would be wrong here.

    SE(p) = (1/Y) * sqrt(SE(X)^2 - p^2 * SE(Y)^2), where p = X/Y; if the
    term under the root is negative, the handbook's fallback is to ADD
    instead of subtract (this happens when X and Y are highly correlated,
    which is common for small universes). Source: U.S. Census Bureau,
    "Understanding and Using American Community Survey Data: What All Data
    Users Need to Know," Appendix on calculating MOEs for derived
    proportions (the same handbook cited in analysis/acs.py for the
    zero-cell MOE-aggregation rule).
    """
    if universe_est <= 0:
        return float("nan"), float("nan")
    p = below_est / universe_est
    se_x = below_moe / Z_90
    se_y = universe_moe / Z_90
    term = se_x**2 - (p**2) * se_y**2
    if term < 0:
        term = se_x**2 + (p**2) * se_y**2
    se_p = (1 / universe_est) * term**0.5
    return p * 100, se_p * Z_90 * 100


# ---------------------------------------------------------------------------
# DHC estimate + modeled range
# ---------------------------------------------------------------------------

def dhc_sexage(df: pd.DataFrame, band: str, sex: str) -> pd.Series:
    """Estimate only -- DHC is a full count, no MOE exists to sum."""
    codes = [f"P12_{n}N" for s in _sexes(sex) for n in _SEXAGE_CELLS[band][s]]
    return df[codes].sum(axis=1, min_count=len(codes))


def dhc_population_range(
    est: float, level: str, *, tract_pops: pd.Series | None = None
) -> tuple[float, float]:
    """Modeled 90%-comparable range for a DHC total-population count.

    "tract"/"county" look the modeled relative noise up directly (both are
    real DAS spine levels). "place" is not on the spine, so its noise is
    built as the root-sum-of-squares of the 25 constituent tracts' modeled
    absolute errors -- the same independence-assumption combination the
    ACS MOE handbook rule uses (analysis.acs.aggregate_moe) -- which
    requires tract_pops (the 25 tract population counts).
    """
    if level == "place":
        if tract_pops is None:
            raise ValueError('level="place" requires tract_pops')
        abs_errs = tract_pops * tract_pops.apply(lambda p: estimate_relative_noise("tract", p))
        place_abs = float(np.sqrt((abs_errs**2).sum()))
        rel = place_abs / est
    else:
        rel = estimate_relative_noise(level, est)
    half = Z_90 * rel * est
    return est - half, est + half


def dhc_subgroup_range(est: float, level: str) -> tuple[float, float]:
    """Modeled range for a DHC age-band subgroup, using the Black 65+
    absolute RMSE as a same-order-of-magnitude proxy (no per-subgroup
    curve exists -- notebook 09 makes and documents this same approximation).
    "place" RSS-aggregates the tract-level proxy across the 25 tracts.
    """
    if level == "place":
        abs_err = float(BLACK_65PLUS_RMSE_BY_LEVEL["tract"] * np.sqrt(N_TRENTON_TRACTS))
    elif level in BLACK_65PLUS_RMSE_BY_LEVEL.index:
        abs_err = float(BLACK_65PLUS_RMSE_BY_LEVEL[level])
    else:
        raise ValueError(f"no Black 65+ RMSE anchor for level {level!r}")
    half = Z_90 * abs_err
    return est - half, est + half


# ---------------------------------------------------------------------------
# Reliability tier
# ---------------------------------------------------------------------------

TIER_SOLID = "Solid"
TIER_CARE = "Use with care"
TIER_RISKY = "Too risky"

TIER_LINES = {
    TIER_SOLID: "Safe to cite in the grant.",
    TIER_CARE: "Fine for a citywide total. Too risky for one neighborhood alone.",
    TIER_RISKY: "Don't cite this number alone. Combine tracts, or use the city total.",
}

# Cited in analysis/viz.py::CV_REFERENCE_LINES (ESRI 0.12 high-reliability
# cutoff, NCHS 0.30 flag/caution cutoff). These are OUR proposed tiers built
# on those conventions, not adopted Census thresholds (HANDOFF.md #8).
TIER_CV_SOLID_MAX = 0.12
TIER_CV_CARE_MAX = 0.30


def cv_from_range(est: float, low: float, high: float) -> float:
    """Recover an implied CV from any est +/- range built at 90% confidence."""
    if est <= 0 or np.isnan(est):
        return float("nan")
    se = (high - low) / (2 * Z_90)
    return se / est


def tier(cv: float) -> tuple[str, str]:
    """(tier label, plain-English line) for a coefficient of variation."""
    if np.isnan(cv):
        return TIER_RISKY, "No reliable estimate available for this figure."
    if cv <= TIER_CV_SOLID_MAX:
        label = TIER_SOLID
    elif cv <= TIER_CV_CARE_MAX:
        label = TIER_CARE
    else:
        label = TIER_RISKY
    return label, TIER_LINES[label]


if __name__ == "__main__":
    # ponytail: smallest check that band membership, ranges, and tiers hold
    # together, using the real pulled data if present.
    assert TIER_LINES.keys() == {TIER_SOLID, TIER_CARE, TIER_RISKY}
    assert tier(0.05)[0] == TIER_SOLID
    assert tier(0.20)[0] == TIER_CARE
    assert tier(0.50)[0] == TIER_RISKY
    lo, hi = acs_range(1000.0, 200.0)
    assert (lo, hi) == (800.0, 1200.0)
    assert abs(cv_from_range(1000.0, 800.0, 1200.0) - (200.0 / Z_90 / 1000.0)) < 1e-9

    # poverty_rate: a clean case (independent-ish) and a forced-negative-term case.
    rate, rate_moe = poverty_rate(100.0, 20.0, 1000.0, 50.0)
    assert abs(rate - 10.0) < 1e-9 and rate_moe > 0
    # below_moe way bigger than what an independent combination could support
    # forces the sqrt term negative -> the handbook's add-instead-of-subtract
    # fallback must still return a real, positive MOE, not a NaN from sqrt(-x).
    rate2, rate2_moe = poverty_rate(100.0, 500.0, 1000.0, 50.0)
    assert rate2_moe > 0 and not np.isnan(rate2_moe)

    if (RAW_DIR / "acs5_2024_trenton_place.parquet").exists():
        place = load_acs("place")
        total = 0.0
        for band in BANDS:
            est, _ = acs_sexage(place, band, "both")
            total += float(est.iloc[0])
        assert abs(total - float(place["B01001_001E"].iloc[0])) < 1.0, (
            f"band sum {total} != published total {place['B01001_001E'].iloc[0]}"
        )
        d_lo, d_hi = dhc_population_range(90_871.0, "tract", tract_pops=pd.Series([90_871.0]))
        assert d_lo < 90_871.0 < d_hi

        # Poverty universe should be close to (never wildly off from) total
        # population for the same band -- a real but bounded gap, since the
        # two tables use slightly different universes (B17001 excludes some
        # group quarters). More than a 20% gap would mean a wiring mistake,
        # not a real universe difference.
        for band in BANDS:
            pop_est, _ = acs_sexage(place, band, "both")
            univ_est, univ_moe = acs_poverty_universe(place, band, "both")
            below_est, below_moe = acs_poverty(place, band, "both")
            gap = abs(float(univ_est.iloc[0]) - float(pop_est.iloc[0])) / float(pop_est.iloc[0])
            assert gap < 0.20, f"{band}: poverty universe vs. population gap {gap:.1%} looks wrong"
            rate, rate_moe = poverty_rate(
                float(below_est.iloc[0]), float(below_moe.iloc[0]),
                float(univ_est.iloc[0]), float(univ_moe.iloc[0]),
            )
            assert 0.0 <= rate <= 100.0 and rate_moe > 0
    print("dashboard self-check OK")
