"""Helpers for multivariate ACS CV driver models (EDA 07).

What it does
------------
Builds a long analysis frame that separates *place population* from
*estimate size*, fits nested OLS models with numpy (no extra deps), and
flags unexpectedly high CVs given estimate size (composite V2 tooltip seed).

What it needs
-------------
ACS parquets via analysis.acs; for income estimate_size, household counts
from the allocation pull (B99192_001E) via analysis.alloc.

Plain-English design
--------------------
- place_pop: how many people live in the geography
- estimate_size: how large the published estimate is (counts), or the
  household universe for median income — never the dollar median
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from analysis import acs, alloc

# Variable groups included in the pooled driver model.
VARIABLE_GROUPS = (
    "population",
    "income",
    "poverty",
    "black65_agg",
    "black65_cell",
)

# Poverty and detailed race×age tables are not published at block group.
LEVELS_BY_GROUP: dict[str, tuple[str, ...]] = {
    "population": ("county", "tract", "block_group"),
    "income": ("county", "tract", "block_group"),
    "poverty": ("county", "tract"),
    "black65_agg": ("county", "tract"),
    "black65_cell": ("county", "tract"),
}

RESIDUAL_PERCENTILE_DEFAULT = 0.75


@dataclass(frozen=True)
class OLSResult:
    """Minimal OLS fit summary for nested model comparisons."""

    name: str
    terms: tuple[str, ...]
    coefficients: pd.Series
    r_squared: float
    n_obs: int
    fitted: pd.Series
    residuals: pd.Series


def _geo_id(df: pd.DataFrame, level: str) -> pd.Series:
    """Stable geography key for long-format rows.

    Block-group ACS pulls in this project do not always ship a BLOCK_GROUP
    column; NAME is unique per row and is used as the trailing identifier.
    """
    if level == "county":
        return df["STATE"].astype(str) + df["COUNTY"].astype(str)
    if level == "tract":
        return (
            df["STATE"].astype(str)
            + df["COUNTY"].astype(str)
            + df["TRACT"].astype(str)
        )
    if level == "block_group":
        if "BLOCK_GROUP" in df.columns:
            return (
                df["STATE"].astype(str)
                + df["COUNTY"].astype(str)
                + df["TRACT"].astype(str)
                + df["BLOCK_GROUP"].astype(str)
            )
        return (
            df["STATE"].astype(str)
            + df["COUNTY"].astype(str)
            + df["TRACT"].astype(str)
            + "|"
            + df["NAME"].astype(str)
        )
    raise ValueError(f"unknown level {level!r}")


def _join_keys(level: str, df: pd.DataFrame) -> list[str]:
    """Join keys shared by ACS and allocation pulls at a geography level."""
    keys = ["STATE", "COUNTY"]
    if level in ("tract", "block_group"):
        keys.append("TRACT")
    if level == "block_group" and "BLOCK_GROUP" in df.columns:
        keys.append("BLOCK_GROUP")
    if level == "block_group" and "BLOCK_GROUP" not in df.columns:
        # Fall back to NAME when the pull has no BLOCK_GROUP field.
        keys.append("NAME")
    return keys


def _hh_universe(level: str, acs_df: pd.DataFrame) -> pd.Series:
    """Household counts for income estimate_size (not dollar medians)."""
    alloc_df = alloc.load_level(level)
    keys = _join_keys(level, acs_df)
    # Allocation frame must expose the same keys.
    missing = [k for k in keys if k not in alloc_df.columns]
    if missing:
        raise KeyError(f"allocation frame missing join keys {missing} at {level}")
    merged = acs_df[keys].merge(
        alloc_df[keys + ["B99192_001E"]],
        on=keys,
        how="left",
        validate="one_to_one",
    )
    return pd.to_numeric(merged["B99192_001E"], errors="coerce")


def build_cv_driver_frame(
    levels: list[str] | None = None,
) -> pd.DataFrame:
    """Long frame: one row per geography × variable group with CV drivers.

    Columns: level, geo_id, variable_group, place_pop, estimate_size, cv,
    subgroup_share (NaN for income).
    """
    levels = levels or list(acs.LEVELS)
    rows: list[pd.DataFrame] = []

    for level in levels:
        df = acs.load_level(level)
        place_pop = df["B01003_001E"]
        geo_id = _geo_id(df, level)
        hh = _hh_universe(level, df) if level in LEVELS_BY_GROUP["income"] else None

        specs: list[tuple[str, pd.Series, pd.Series]] = []

        if level in LEVELS_BY_GROUP["population"]:
            specs.append(
                (
                    "population",
                    place_pop,
                    acs.cv(df["B01003_001E"], df["B01003_001M"]),
                )
            )

        if level in LEVELS_BY_GROUP["income"] and hh is not None:
            income_cv = acs.cv(df["B19013_001E"], df["B19013_001M"]).mask(
                acs.flag_topcoded_income(df)
            )
            specs.append(("income", hh, income_cv))

        if level in LEVELS_BY_GROUP["poverty"] and "B17001_002E" in df.columns:
            specs.append(
                (
                    "poverty",
                    df["B17001_002E"],
                    acs.cv(df["B17001_002E"], df["B17001_002M"]),
                )
            )

        if level in LEVELS_BY_GROUP["black65_agg"] and all(
            f"{c}E" in df.columns for c in acs.BLACK_65PLUS_CELLS
        ):
            est = acs.aggregate_estimate(df, acs.BLACK_65PLUS_CELLS)
            moe = acs.aggregate_moe(df, acs.BLACK_65PLUS_CELLS, zero_rule=True)
            specs.append(("black65_agg", est, acs.cv(est, moe)))

        if level in LEVELS_BY_GROUP["black65_cell"] and all(
            f"{c}E" in df.columns for c in acs.BLACK_65PLUS_CELLS
        ):
            for code in acs.BLACK_65PLUS_CELLS:
                cell_est = df[f"{code}E"]
                cell_cv = acs.cv(cell_est, df[f"{code}M"])
                chunk = pd.DataFrame(
                    {
                        "level": level,
                        "geo_id": geo_id,
                        "variable_group": "black65_cell",
                        "variable_code": code,
                        "place_pop": place_pop,
                        "estimate_size": cell_est,
                        "cv": cell_cv,
                    }
                )
                rows.append(chunk)

        for group, est_size, cv_s in specs:
            chunk = pd.DataFrame(
                {
                    "level": level,
                    "geo_id": geo_id,
                    "variable_group": group,
                    "variable_code": group,
                    "place_pop": place_pop,
                    "estimate_size": est_size,
                    "cv": cv_s,
                }
            )
            rows.append(chunk)

    out = pd.concat(rows, ignore_index=True)
    out["subgroup_share"] = np.where(
        out["variable_group"].eq("income"),
        np.nan,
        out["estimate_size"] / out["place_pop"].where(out["place_pop"] > 0),
    )
    return out


def model_ready(
    frame: pd.DataFrame,
    *,
    min_estimate_size: float = 1.0,
) -> pd.DataFrame:
    """Drop rows that cannot enter log(CV) ~ log(place_pop) + log(estimate_size)."""
    out = frame.copy()
    out = out[
        out["cv"].notna()
        & (out["cv"] > 0)
        & out["place_pop"].notna()
        & (out["place_pop"] > 0)
        & out["estimate_size"].notna()
        & (out["estimate_size"] >= min_estimate_size)
    ].copy()
    out["log_cv"] = np.log(out["cv"].astype(float))
    out["log_place_pop"] = np.log(out["place_pop"].astype(float))
    out["log_estimate_size"] = np.log(out["estimate_size"].astype(float))
    return out.reset_index(drop=True)


def design_matrix(
    df: pd.DataFrame,
    terms: list[str],
) -> tuple[pd.DataFrame, pd.Series]:
    """Build numeric design matrix X and response y for nested OLS specs.

    Supported terms:
    - log_place_pop, log_estimate_size
    - C(level), C(variable_group)
    - log_estimate_size:C(variable_group)  (interaction)
    """
    y = df["log_cv"].astype(float)
    pieces: list[pd.DataFrame] = [pd.DataFrame({"intercept": 1.0}, index=df.index)]

    for term in terms:
        if term in ("log_place_pop", "log_estimate_size"):
            pieces.append(df[[term]].astype(float))
        elif term == "C(level)":
            dummies = pd.get_dummies(df["level"], prefix="level", drop_first=True)
            pieces.append(dummies.astype(float))
        elif term == "C(variable_group)":
            dummies = pd.get_dummies(
                df["variable_group"], prefix="var", drop_first=True
            )
            pieces.append(dummies.astype(float))
        elif term == "log_estimate_size:C(variable_group)":
            dummies = pd.get_dummies(
                df["variable_group"], prefix="var", drop_first=True
            )
            interacted = dummies.mul(df["log_estimate_size"], axis=0)
            interacted.columns = [f"log_est×{c}" for c in interacted.columns]
            pieces.append(interacted.astype(float))
        else:
            raise ValueError(f"unsupported term {term!r}")

    X = pd.concat(pieces, axis=1)
    return X, y


def fit_ols(df: pd.DataFrame, terms: list[str], name: str) -> OLSResult:
    """Ordinary least squares via numpy lstsq; returns coefficients and R²."""
    X, y = design_matrix(df, terms)
    beta, _, _, _ = np.linalg.lstsq(X.to_numpy(dtype=float), y.to_numpy(), rcond=None)
    coef = pd.Series(beta, index=X.columns, name="coefficient")
    fitted = pd.Series(X.to_numpy(dtype=float) @ beta, index=df.index, name="fitted")
    resid = (y - fitted).rename("residual")
    ss_res = float((resid**2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return OLSResult(
        name=name,
        terms=tuple(terms),
        coefficients=coef,
        r_squared=r2,
        n_obs=int(len(df)),
        fitted=fitted,
        residuals=resid,
    )


def incremental_r2(results: list[OLSResult]) -> pd.DataFrame:
    """Incremental R² from a nested sequence of OLS fits (same rows)."""
    rows = []
    prev = 0.0
    for res in results:
        inc = res.r_squared - prev
        rows.append(
            {
                "model": res.name,
                "r_squared": res.r_squared,
                "incremental_r2": inc,
                "n_obs": res.n_obs,
            }
        )
        prev = res.r_squared
    return pd.DataFrame(rows)


def fit_income_size_model(df: pd.DataFrame) -> OLSResult:
    """Income-only: log(CV) ~ log(household universe). Used for residual flags."""
    income = model_ready(df[df["variable_group"] == "income"])
    if income.empty:
        raise ValueError("no usable income rows for residual model")
    return fit_ols(income, ["log_estimate_size"], name="income_size_only")


def flag_high_cv_residual(
    cv: pd.Series,
    estimate_size: pd.Series,
    *,
    residual_percentile: float = RESIDUAL_PERCENTILE_DEFAULT,
    train_mask: pd.Series | None = None,
) -> tuple[pd.Series, dict[str, float]]:
    """Flag rows whose CV is worse than predicted from estimate size.

    Fits log(CV) ~ log(estimate_size) on `train_mask` rows (default: all
    finite pairs), then flags residuals at/above the given percentile.

    Returns (boolean Series aligned to cv.index, metadata dict).
    """
    if not 0 < residual_percentile < 1:
        raise ValueError(
            f"residual_percentile must be in (0, 1), got {residual_percentile}"
        )

    frame = pd.DataFrame({"cv": cv, "estimate_size": estimate_size})
    usable = (
        frame["cv"].notna()
        & (frame["cv"] > 0)
        & frame["estimate_size"].notna()
        & (frame["estimate_size"] > 0)
    )
    if train_mask is not None:
        train = usable & train_mask.reindex(frame.index).fillna(False)
    else:
        train = usable

    train_df = frame.loc[train].copy()
    if len(train_df) < 10:
        raise ValueError("need at least 10 training rows for residual model")

    train_df["log_cv"] = np.log(train_df["cv"].astype(float))
    train_df["log_estimate_size"] = np.log(train_df["estimate_size"].astype(float))
    fit = fit_ols(train_df, ["log_estimate_size"], name="size_only")

    # Predict for all usable rows with the same coefficients.
    all_usable = frame.loc[usable].copy()
    all_usable["log_cv"] = np.log(all_usable["cv"].astype(float))
    all_usable["log_estimate_size"] = np.log(
        all_usable["estimate_size"].astype(float)
    )
    X_all, y_all = design_matrix(all_usable, ["log_estimate_size"])
    fitted_all = X_all.to_numpy(dtype=float) @ fit.coefficients.to_numpy()
    resid_all = pd.Series(y_all.to_numpy() - fitted_all, index=all_usable.index)

    # Threshold from training residuals only.
    train_resid = resid_all.reindex(train_df.index)
    threshold = float(train_resid.quantile(residual_percentile))

    flag = pd.Series(False, index=cv.index, dtype=bool)
    flag.loc[resid_all.index] = resid_all >= threshold
    # Unusable rows stay False (not "high residual" — simply not scored).
    meta = {
        "r_squared": float(fit.r_squared),
        "residual_threshold": threshold,
        "residual_percentile": float(residual_percentile),
        "n_train": float(len(train_df)),
        "slope_log_estimate_size": float(fit.coefficients["log_estimate_size"]),
    }
    return flag, meta
