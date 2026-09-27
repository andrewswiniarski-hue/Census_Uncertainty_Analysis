"""Is "allocation rate" a well-defined quantity? Denominator sensitivity.

What it does
------------
Computes the ACS/PUMS income allocation rate under every defensible choice
of denominator and scope, then measures how much the answer moves.

Why this exists
---------------
"X% of income was allocated" is quoted as though it were a measurement.
It is not: it is a ratio, and the denominator is a choice. This module
enumerates the choices that can be defended, computes the rate under each,
and reports whether they agree.

On NJ PUMS vintage 2024 they do not agree. Across six income sources and
eight definitions, wages rank anywhere from 1st to 6th most-allocated, and
12 of the 28 pairwise definition comparisons produce a NEGATIVE rank
correlation -- they actively reverse the ordering. Mean Kendall tau across
all pairs is +0.23.

The four denominators, and what is wrong with each
--------------------------------------------------
None is neutral. Each measures a different thing, and the differences are
not cosmetic.

  D1 all persons
      Includes children who were never asked. Confounds "this question is
      rarely imputed" with "this question is rarely asked."

  D2 in-universe (age 15+)
      The question's actual universe -- but it is the SAME universe for all
      six income questions, so it does not separate imputation propensity
      from how many people have that income type at all. On NJ 2024 every
      source returns an identical in-universe count of 376,037.

  D3 has a nonzero amount
      Intuitive -- "of people with this income, how often was it guessed."
      But it silently drops everyone whose value was allocated TO ZERO,
      and that is most allocations for rare income types: 92.6% of
      self-employment allocations and 98.2% of public assistance
      allocations are zeros. So D3 computes a rate on a small, unusual
      subset and quietly discards the majority of the events it claims to
      count.

  D4 nonzero OR allocated
      Repairs D3's exclusion and is the most internally coherent. But for
      rare income types the allocated-to-zero group swamps the genuinely-
      has-it group, so the rate approaches 100% (public assistance: 96.1%)
      and the quantity silently becomes "how often did the Bureau decide
      you do NOT have this," which is a different question again.

Two scopes, orthogonal to the denominator
-----------------------------------------
  S1 all records
  S2 item-only -- records where every income item was allocated at once
     (whole-person substitution) are removed. That is a different error
     mechanism from one skipped question and it dominates the pooled rate:
     44.3% of records carrying any flag carry all six.

The honest conclusion
---------------------
There is no correct denominator, so a single "allocation rate" cannot be
read as a property of the data. Any downstream quantity built on one
inherits whichever definition was picked, usually silently. Report the
sweep, or state the definition every time.

What it needs
-------------
pandas, numpy. No I/O of its own. Expects the frame written by
ingestion/pull_pums_alloc_flags.py.

Run the tests:
    python -m pytest tests/test_alloc_denominator.py -v
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

# Flag -> amount variable. Confirmed against the live metadata endpoint.
FLAG_TO_AMOUNT = {
    "FWAGP": "WAGP",
    "FSEMP": "SEMP",
    "FINTP": "INTP",
    "FSSP": "SSP",
    "FRETP": "RETP",
    "FPAP": "PAP",
}

# Out-of-universe code per amount variable. NOT uniform: SEMP and INTP use
# -10001 because -1 is a legitimate LOSS for those two. A blanket `< 0` or
# `== -1` test corrupts exactly those columns.
NA_CODE = {
    "WAGP": -1,
    "SEMP": -10001,
    "INTP": -10001,
    "SSP": -1,
    "RETP": -1,
    "PAP": -1,
}

PERSON_WEIGHT = "PWGTP"

DENOMINATOR_NOTES = {
    "D1 all": "every record, including children never asked",
    "D2 uni15+": "the question universe (age 15+); identical for all six sources",
    "D3 nonzero": "has a nonzero amount; DROPS allocated-to-zero cases",
    "D4 nz|alloc": "nonzero or allocated; coherent, but rare types approach 100%",
}
SCOPE_NOTES = {
    "S1 all": "all records",
    "S2 item": "whole-person substitutions removed",
}


def in_universe(df: pd.DataFrame, amount: str) -> pd.Series:
    """Eligible to be asked about this income type.

    Uses the variable's OWN N/A code. Never a blanket negative test.
    """
    return df[amount].notna() & (df[amount] != NA_CODE[amount])


def whole_record_mask(df: pd.DataFrame, flags: list[str] | None = None) -> pd.Series:
    """True where EVERY income flag is set -- whole-person substitution."""
    flags = [f for f in (flags or FLAG_TO_AMOUNT) if f in df.columns]
    if not flags:
        return pd.Series(False, index=df.index)
    return df[flags].eq(1).sum(axis=1) == len(flags)


def denominators(df: pd.DataFrame, flag: str, amount: str) -> dict[str, pd.Series]:
    """The four defensible denominator masks for one income source."""
    uni = in_universe(df, amount)
    alloc = df[flag] == 1
    nonzero = df[amount] != 0
    return {
        "D1 all": pd.Series(True, index=df.index),
        "D2 uni15+": uni,
        "D3 nonzero": uni & nonzero,
        "D4 nz|alloc": uni & (nonzero | alloc),
    }


def scopes(df: pd.DataFrame) -> dict[str, pd.Series]:
    """The two scope masks, orthogonal to the denominator choice."""
    return {
        "S1 all": pd.Series(True, index=df.index),
        "S2 item": ~whole_record_mask(df),
    }


def sweep(df: pd.DataFrame, weight: str = PERSON_WEIGHT) -> pd.DataFrame:
    """Weighted allocation rate for every source x denominator x scope.

    Returns tidy rows: source, denominator, scope, definition, rate,
    weighted_denominator, weighted_allocated, n_records.

    The numerator is always a subset of the denominator, by construction --
    so a rate can never exceed 1 regardless of which mask is chosen.
    """
    w = df[weight]
    sc = scopes(df)
    rows = []
    for flag, amount in FLAG_TO_AMOUNT.items():
        if flag not in df.columns or amount not in df.columns:
            continue
        alloc = df[flag] == 1
        for dn, dm in denominators(df, flag, amount).items():
            for sn, sm in sc.items():
                mask = dm & sm
                den = float(w[mask].sum())
                num = float(w[mask & alloc].sum())
                rows.append({
                    "source": flag,
                    "amount_var": amount,
                    "denominator": dn,
                    "scope": sn,
                    "definition": f"{dn}/{sn}",
                    "weighted_denominator": den,
                    "weighted_allocated": num,
                    "rate": (num / den) if den else np.nan,
                    "n_records": int(mask.sum()),
                })
    return pd.DataFrame(rows)


def rate_table(swept: pd.DataFrame) -> pd.DataFrame:
    """Wide table: sources down, definitions across."""
    order = [f for f in FLAG_TO_AMOUNT if f in set(swept["source"])]
    return swept.pivot(index="source", columns="definition",
                       values="rate").reindex(order)


def rank_table(swept: pd.DataFrame) -> pd.DataFrame:
    """Rank per definition. 1 = most allocated."""
    return rate_table(swept).rank(ascending=False, method="min").astype("Int64")


def volatility(swept: pd.DataFrame) -> pd.DataFrame:
    """Per source: best rank, worst rank, swing, and the rate range.

    `swing` is the headline. A swing of 5 across six sources means the
    source can be ranked anywhere -- the ordering is an artifact of the
    definition, not a property of the data.
    """
    rates, ranks = rate_table(swept), rank_table(swept)
    out = []
    for s in rates.index:
        rt = rates.loc[s].dropna()
        rk = ranks.loc[s].dropna()
        if rt.empty or rk.empty:
            continue
        out.append({
            "source": s,
            "best_rank": int(rk.min()),
            "worst_rank": int(rk.max()),
            "rank_swing": int(rk.max() - rk.min()),
            "rate_min": float(rt.min()),
            "rate_max": float(rt.max()),
            "rate_fold": float(rt.max() / rt.min()) if rt.min() > 0 else np.inf,
        })
    return pd.DataFrame(out).sort_values("rank_swing", ascending=False)


def kendall_tau_b(a, b) -> float:
    """Kendall tau-b, implemented here rather than imported.

    `pandas.Series.corr(method="kendall")` delegates to scipy, which is NOT
    in the project venv, and the brief forbids adding dependencies without
    asking. With six sources there are fifteen pairs, so the direct
    definition is cheap and removes the dependency entirely.

        tau_b = (C - D) / sqrt((C + D + Tx) * (C + D + Ty))

    C and D are concordant and discordant pairs; Tx and Ty count pairs tied
    in one ranking only. Pairs tied in BOTH are excluded from every term,
    which is what makes it tau-b rather than tau-a.
    """
    x = np.asarray(list(a), dtype="float64")
    y = np.asarray(list(b), dtype="float64")
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n = x.size
    if n < 2:
        return float("nan")
    conc = disc = tie_x = tie_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx, dy = x[i] - x[j], y[i] - y[j]
            s = dx * dy
            if s > 0:
                conc += 1
            elif s < 0:
                disc += 1
            elif dx == 0 and dy == 0:
                continue          # tied in both -- excluded from all terms
            elif dx == 0:
                tie_x += 1
            else:
                tie_y += 1
    denom = np.sqrt((conc + disc + tie_x) * (conc + disc + tie_y))
    return float((conc - disc) / denom) if denom > 0 else float("nan")


def agreement(swept: pd.DataFrame) -> pd.DataFrame:
    """Kendall tau between every pair of definitions' rankings.

    Negative tau means the two definitions put the sources in reversed
    order. Those pairs are the finding: both defensible, opposite answers.

    tau is NaN when either definition ranks every source identically --
    a constant vector has no ordering to correlate. That is reported as
    `degenerate` rather than silently dropped, because a definition that
    ties everything is itself a result about that definition.
    """
    ranks = rank_table(swept).astype(float)
    rows = []
    for a, b in itertools.combinations(ranks.columns, 2):
        deg = ranks[a].nunique(dropna=True) < 2 or ranks[b].nunique(dropna=True) < 2
        tau = np.nan if deg else kendall_tau_b(ranks[a], ranks[b])
        rows.append({"def_a": a, "def_b": b, "kendall_tau": tau, "degenerate": deg})
    return pd.DataFrame(rows).sort_values("kendall_tau", na_position="last")


def zero_allocation_share(df: pd.DataFrame) -> pd.DataFrame:
    """What fraction of allocations imputed a ZERO rather than an amount?

    This is why D3 and D4 diverge so hard. Imputing "you have none of this"
    is a different act from estimating how much you earned, and for rare
    income types it is almost the only thing "allocated" means.
    """
    rows = []
    for flag, amount in FLAG_TO_AMOUNT.items():
        if flag not in df.columns or amount not in df.columns:
            continue
        alloc = df[flag] == 1
        n = int(alloc.sum())
        zeros = int((alloc & (df[amount] == 0)).sum())
        rows.append({
            "source": flag,
            "allocated": n,
            "allocated_to_zero": zeros,
            "share_zero": (zeros / n) if n else np.nan,
        })
    return pd.DataFrame(rows).sort_values("share_zero", ascending=False)


def summary(swept: pd.DataFrame) -> dict:
    """Headline numbers for a write-up."""
    ranks = rank_table(swept)
    agr = agreement(swept)
    vol = volatility(swept)
    usable = agr[agr["kendall_tau"].notna()]
    return {
        "n_definitions": int(ranks.shape[1]),
        "n_sources": int(ranks.shape[0]),
        "max_rank_swing": int(vol["rank_swing"].max()) if len(vol) else 0,
        "n_pairs": int(len(agr)),
        "n_pairs_comparable": int(len(usable)),
        "n_pairs_degenerate": int(agr["degenerate"].sum()),
        "n_pairs_reversed": int((usable["kendall_tau"] < 0).sum()),
        "mean_tau": float(usable["kendall_tau"].mean()) if len(usable) else np.nan,
        "min_tau": float(usable["kendall_tau"].min()) if len(usable) else np.nan,
    }


__all__ = [
    "FLAG_TO_AMOUNT", "NA_CODE", "DENOMINATOR_NOTES", "SCOPE_NOTES",
    "in_universe", "whole_record_mask", "denominators", "scopes",
    "sweep", "rate_table", "rank_table", "volatility", "agreement",
    "kendall_tau_b",
    "zero_allocation_share", "summary",
]
