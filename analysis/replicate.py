"""Error bars for PUMS estimates, via successive-difference replication.

What it does
------------
PUMS publishes no margin of error. Uncertainty comes from 80 replicate
weights (PWGTP1-PWGTP80): recompute the statistic once per replicate, and
the spread of those 80 answers is the sampling variance.

    Var(theta) = (4/80) * sum over r of (theta_r - theta)^2
    SE  = sqrt(Var)
    MOE = 1.645 * SE          90% confidence, the ACS convention

Source: U.S. Census Bureau, "PUMS Accuracy of the Data", the estimation
section on successive-difference replication. The 4/80 constant is specific
to the ACS replicate design -- it is not a generic jackknife.

The part that is easy to get wrong
----------------------------------
To ask whether two groups differ, you CANNOT combine their standard errors
as sqrt(se_a^2 + se_b^2). That formula assumes the two estimates are
independent. Subgroups of one sample are not independent -- they are drawn
from the same households, sharing the same replicate structure.

The correct route is to form the difference INSIDE each replicate:

    d_r = theta_a,r - theta_b,r      for r = 1..80
    Var(d) = (4/80) * sum (d_r - d)^2

`difference` below does that. `naive_difference_se` implements the wrong
version deliberately, labelled, so the two can be compared and so nobody
reimplements it by accident thinking it is missing.

Everything here is a sampling error bar. It says nothing about whether an
imputed value was right -- that is a different kind of uncertainty and the
replicate weights cannot see it either.

What it needs
-------------
numpy, pandas. No I/O of its own. Expects PWGTP plus PWGTP1..PWGTP80 from
ingestion/pull_pums_alloc_flags.py --replicates.

Run the tests:
    python -m pytest tests/test_replicate.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd

N_REPLICATES = 80
SDR_CONSTANT = 4.0 / N_REPLICATES   # ACS successive-difference replication
Z_90 = 1.645                        # ACS publishes MOEs at 90% confidence

BASE_WEIGHT = "PWGTP"
REPLICATE_COLS = [f"PWGTP{i}" for i in range(1, N_REPLICATES + 1)]


def has_replicates(df: pd.DataFrame) -> bool:
    """True when every replicate weight column is present."""
    return all(c in df.columns for c in REPLICATE_COLS)


def available_replicates(df: pd.DataFrame) -> list[str]:
    """Replicate columns actually present, in order."""
    return [c for c in REPLICATE_COLS if c in df.columns]


def sdr_variance(point: float, replicates) -> float:
    """Successive-difference replication variance.

    `replicates` are the statistic recomputed under each replicate weight.
    The constant is 4/80 and is specific to the ACS design.
    """
    r = np.asarray(list(replicates), dtype="float64")
    r = r[np.isfinite(r)]
    if r.size == 0 or not np.isfinite(point):
        return float("nan")
    return float(SDR_CONSTANT * np.sum((r - point) ** 2))


def _summarise(point: float, reps) -> dict:
    var = sdr_variance(point, reps)
    se = float(np.sqrt(var)) if np.isfinite(var) else float("nan")
    moe = Z_90 * se
    return {
        "estimate": float(point),
        "se": se,
        "moe": moe,
        "ci_low": float(point - moe),
        "ci_high": float(point + moe),
        "n_replicates": int(len(list(reps))) if not isinstance(reps, np.ndarray)
        else int(reps.size),
    }


def _share(df: pd.DataFrame, num: pd.Series, den: pd.Series, w: str) -> float:
    d = df.loc[den, w].sum()
    return (df.loc[num & den, w].sum() / d) if d else float("nan")


def share(
    df: pd.DataFrame,
    numerator: pd.Series,
    denominator: pd.Series | None = None,
    weight: str = BASE_WEIGHT,
) -> dict:
    """A weighted share, with its 90% margin of error.

    `numerator` and `denominator` are boolean masks over df. Denominator
    defaults to every row.
    """
    den = pd.Series(True, index=df.index) if denominator is None else denominator
    reps = available_replicates(df)
    point = _share(df, numerator, den, weight)
    if not reps:
        return {"estimate": point, "se": np.nan, "moe": np.nan,
                "ci_low": np.nan, "ci_high": np.nan, "n_replicates": 0}
    vals = np.array([_share(df, numerator, den, c) for c in reps])
    return _summarise(point, vals)


def mean(
    df: pd.DataFrame,
    column: str,
    subset: pd.Series | None = None,
    weight: str = BASE_WEIGHT,
) -> dict:
    """A weighted mean, with its 90% margin of error."""
    m = pd.Series(True, index=df.index) if subset is None else subset
    reps = available_replicates(df)
    x = pd.to_numeric(df.loc[m, column], errors="coerce")

    def calc(wcol):
        w = df.loc[m, wcol]
        ok = x.notna() & w.notna()
        tot = w[ok].sum()
        return float((x[ok] * w[ok]).sum() / tot) if tot else float("nan")

    point = calc(weight)
    if not reps:
        return {"estimate": point, "se": np.nan, "moe": np.nan,
                "ci_low": np.nan, "ci_high": np.nan, "n_replicates": 0}
    return _summarise(point, np.array([calc(c) for c in reps]))


def difference(
    df: pd.DataFrame,
    numerator: pd.Series,
    group_a: pd.Series,
    group_b: pd.Series,
    weight: str = BASE_WEIGHT,
) -> dict:
    """Difference between two groups' shares, with a CORRECT margin of error.

    The difference is formed inside each replicate before the variance is
    taken, because the two groups come from the same sample and are not
    independent. `significant` is True when the 90% interval on the
    difference excludes zero.
    """
    reps = available_replicates(df)
    a = _share(df, numerator, group_a, weight)
    b = _share(df, numerator, group_b, weight)
    point = a - b
    out = {"estimate_a": a, "estimate_b": b, "difference": point}
    if not reps:
        out.update({"se": np.nan, "moe": np.nan, "ci_low": np.nan,
                    "ci_high": np.nan, "significant": None, "n_replicates": 0})
        return out
    diffs = np.array([_share(df, numerator, group_a, c)
                      - _share(df, numerator, group_b, c) for c in reps])
    s = _summarise(point, diffs)
    out.update({k: s[k] for k in ("se", "moe", "ci_low", "ci_high", "n_replicates")})
    out["significant"] = bool(out["ci_low"] > 0 or out["ci_high"] < 0)
    return out


def naive_difference_se(se_a: float, se_b: float) -> float:
    """WRONG ON PURPOSE -- what an ordinary user would compute.

    sqrt(se_a^2 + se_b^2) assumes the two estimates are independent. For
    subgroups of one sample they are not. Kept as a labelled comparison
    target so the size of the error can be shown, and so nobody adds it back
    thinking it was an oversight. Do NOT use it for inference.
    """
    return float(np.sqrt(se_a ** 2 + se_b ** 2))


def profile_with_moe(
    df: pd.DataFrame,
    by: str,
    numerator: pd.Series,
    weight: str = BASE_WEIGHT,
    min_records: int = 100,
) -> pd.DataFrame:
    """Share + MOE for every level of one characteristic."""
    if by not in df.columns:
        return pd.DataFrame()
    rows = []
    d = df[df[by].notna()]
    for level, g in d.groupby(by, observed=True):
        if len(g) < min_records:
            continue
        idx = g.index
        res = share(df.loc[idx], numerator.loc[idx], None, weight)
        rows.append({"characteristic": by, "level": level,
                     "n_records": int(len(g)), **res})
    return pd.DataFrame(rows)


def pairwise_significance(
    df: pd.DataFrame,
    by: str,
    numerator: pd.Series,
    levels: list | None = None,
    weight: str = BASE_WEIGHT,
) -> pd.DataFrame:
    """Every pair of levels: difference, MOE, and whether it clears zero.

    Note on multiple comparisons: with k levels there are k(k-1)/2 tests, so
    some will clear a 90% threshold by chance. Read the pattern, not any one
    row, and say so in any write-up.
    """
    import itertools
    if by not in df.columns:
        return pd.DataFrame()
    lv = levels if levels is not None else sorted(df[by].dropna().unique())
    rows = []
    for a, b in itertools.combinations(lv, 2):
        ma, mb = (df[by] == a), (df[by] == b)
        if not ma.any() or not mb.any():
            continue
        res = difference(df, numerator, ma, mb, weight)
        rows.append({"characteristic": by, "level_a": a, "level_b": b, **res})
    return pd.DataFrame(rows)


__all__ = [
    "N_REPLICATES", "SDR_CONSTANT", "Z_90", "BASE_WEIGHT", "REPLICATE_COLS",
    "has_replicates", "available_replicates", "sdr_variance",
    "share", "mean", "difference", "naive_difference_se",
    "profile_with_moe", "pairwise_significance",
]
