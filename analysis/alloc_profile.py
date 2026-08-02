"""Who gets measured, and who gets inferred? Person-level allocation profile.

What it does
------------
Describes which people have their income data filled in by the Bureau
rather than reported, using ACS PUMS at person level.

Why person level
----------------
A tract-level version of this question answers "tracts with more X have
more allocation." That is an ECOLOGICAL correlation and does not support a
statement about people -- the two can point in opposite directions. Here
the characteristic and the allocation flag sit on the same record, so the
claim is about persons. The cost is geography: PUMS bottoms out at PUMA.

Why there is no denominator here
--------------------------------
analysis/alloc_denominator.py shows that an allocation *rate* needs a
denominator, that several are defensible, and that the choice can reverse
conclusions. That problem appears when you aggregate into an area rate. It
does NOT appear at person level, because these outcomes are properties of
a record rather than ratios:

    any_allocated      did this person have ANY income item filled in
    n_items_allocated  how many of the six, 0-6
    whole_record       were ALL six filled in (whole-person substitution)

Counting people in a group and asking what share carry each outcome needs
only the group as its base, which is not a modelling choice.

Universe guards, which matter more than they look
--------------------------------------------------
- Income questions are asked of people **15 and over**. Children are out of
  universe and carry flag 0 by construction. Including them would
  manufacture a finding that young people have less allocated data. Every
  function here restricts to the income universe by default.
- Educational attainment is only comparable among adults who have finished
  schooling, so the education breakdown restricts to **25 and over** by
  convention. Reporting SCHL for teenagers measures age, not education.

Framing
-------
This is a question about the measurement process -- who the statistical
system observes directly and who it describes by inference. It is not a
statement about the people in any group. Word findings accordingly.

What it needs
-------------
pandas, numpy. No I/O of its own. Expects the frame written by
ingestion/pull_pums_alloc_flags.py including AGEP, SEX, SCHL.

Run the tests:
    python -m pytest tests/test_alloc_profile.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.alloc_denominator import FLAG_TO_AMOUNT, NA_CODE, in_universe

PERSON_WEIGHT = "PWGTP"

# Income questions are asked of the population 15 years and over.
INCOME_UNIVERSE_AGE = 15
# Educational attainment is conventionally summarised for adults 25+.
EDUCATION_UNIVERSE_AGE = 25

SEX_LABELS = {1: "Male", 2: "Female"}

# AGEP bands. Chosen to straddle the transitions that plausibly matter for
# income nonresponse -- entering work, peak earning, retirement.
AGE_BANDS = [
    (15, 24, "15-24"),
    (25, 34, "25-34"),
    (35, 44, "35-44"),
    (45, 54, "45-54"),
    (55, 64, "55-64"),
    (65, 74, "65-74"),
    (75, 200, "75+"),
]

# SCHL collapsed to comparable levels. Codes verified against the live
# metadata endpoint; the raw variable has 24 categories, too thin to report
# individually at PUMA scale.
EDUCATION_BANDS = [
    (1, 15, "No HS diploma"),
    (16, 17, "HS diploma or GED"),
    (18, 19, "Some college, no degree"),
    (20, 20, "Associate degree"),
    (21, 21, "Bachelor degree"),
    (22, 24, "Graduate degree"),
]


def income_universe(df: pd.DataFrame) -> pd.Series:
    """People eligible to be asked the income questions.

    Uses the amount variables' own N/A codes where present, falling back to
    AGEP. Both routes should agree; the fallback exists so the profile still
    works on a frame pulled without the amount columns.
    """
    have_amounts = [a for a in NA_CODE if a in df.columns]
    if have_amounts:
        mask = pd.Series(False, index=df.index)
        for a in have_amounts:
            mask = mask | in_universe(df, a)
        return mask
    if "AGEP" in df.columns:
        return df["AGEP"] >= INCOME_UNIVERSE_AGE
    return pd.Series(True, index=df.index)


def add_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the three denominator-free per-person outcomes."""
    flags = [f for f in FLAG_TO_AMOUNT if f in df.columns]
    out = df.copy()
    n = out[flags].eq(1).sum(axis=1)
    out["n_items_allocated"] = n
    out["any_allocated"] = n > 0
    out["whole_record"] = n == len(flags)
    return out


def band(series: pd.Series, bands: list[tuple[int, int, str]]) -> pd.Series:
    """Map a numeric code to its band label; NaN outside every band."""
    out = pd.Series(pd.NA, index=series.index, dtype="object")
    s = pd.to_numeric(series, errors="coerce")
    for lo, hi, name in bands:
        out = out.mask(s.between(lo, hi), name)
    return out


def add_demographics(df: pd.DataFrame) -> pd.DataFrame:
    """Attach age band, sex label, and education band."""
    out = df.copy()
    if "AGEP" in out.columns:
        out["age_band"] = band(out["AGEP"], AGE_BANDS)
    if "SEX" in out.columns:
        out["sex"] = pd.to_numeric(out["SEX"], errors="coerce").map(SEX_LABELS)
    if "SCHL" in out.columns:
        edu = band(out["SCHL"], EDUCATION_BANDS)
        # Only meaningful for adults who have plausibly finished schooling.
        if "AGEP" in out.columns:
            edu = edu.mask(pd.to_numeric(out["AGEP"], errors="coerce")
                           < EDUCATION_UNIVERSE_AGE)
        out["education"] = edu
    return out


def prepare(df: pd.DataFrame, restrict_universe: bool = True) -> pd.DataFrame:
    """Outcomes + demographics, restricted to the income universe."""
    out = add_demographics(add_outcomes(df))
    if restrict_universe:
        out = out[income_universe(out)].copy()
    return out


def profile(
    df: pd.DataFrame,
    by: str,
    weight: str = PERSON_WEIGHT,
    min_records: int = 100,
) -> pd.DataFrame:
    """Weighted allocation outcomes for each level of one characteristic.

    `min_records` suppresses groups too thin to report -- a rate on 20
    unweighted records is noise wearing a percent sign.
    """
    if by not in df.columns:
        return pd.DataFrame()
    d = df[df[by].notna()]
    rows = []
    for level, g in d.groupby(by, observed=True):
        w = g[weight]
        tot = w.sum()
        if len(g) < min_records or tot <= 0:
            continue
        rows.append({
            "characteristic": by,
            "level": level,
            "n_records": int(len(g)),
            "weighted_persons": float(tot),
            "share_any_allocated": float(w[g["any_allocated"]].sum() / tot),
            "share_whole_record": float(w[g["whole_record"]].sum() / tot),
            "mean_items_allocated": float((g["n_items_allocated"] * w).sum() / tot),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    order = [n for _, _, n in AGE_BANDS] + [n for _, _, n in EDUCATION_BANDS] \
        + list(SEX_LABELS.values())
    out["_o"] = out["level"].map({n: i for i, n in enumerate(order)})
    return out.sort_values(["_o", "level"]).drop(columns="_o").reset_index(drop=True)


def profile_all(df: pd.DataFrame, weight: str = PERSON_WEIGHT,
                min_records: int = 100) -> pd.DataFrame:
    """Profile every available characteristic, stacked."""
    frames = [profile(df, c, weight, min_records)
              for c in ("age_band", "sex", "education") if c in df.columns]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def spread(prof: pd.DataFrame, metric: str = "share_whole_record") -> pd.DataFrame:
    """How much does the outcome vary within each characteristic?

    `fold` is max/min. A characteristic with a large fold is one where the
    statistical system treats groups differently; near 1.0 means it does not
    distinguish them at all. Both are results.
    """
    if prof.empty:
        return pd.DataFrame()
    rows = []
    for c, g in prof.groupby("characteristic", observed=True):
        v = g[metric].dropna()
        if len(v) < 2:
            continue
        lo, hi = float(v.min()), float(v.max())
        rows.append({
            "characteristic": c,
            "metric": metric,
            "n_levels": int(len(v)),
            "min": lo,
            "max": hi,
            "fold": (hi / lo) if lo > 0 else np.inf,
            "lowest_level": g.loc[v.idxmin(), "level"],
            "highest_level": g.loc[v.idxmax(), "level"],
        })
    return pd.DataFrame(rows).sort_values("fold", ascending=False)


__all__ = [
    "INCOME_UNIVERSE_AGE", "EDUCATION_UNIVERSE_AGE",
    "AGE_BANDS", "EDUCATION_BANDS", "SEX_LABELS",
    "income_universe", "add_outcomes", "add_demographics", "band",
    "prepare", "profile", "profile_all", "spread",
]
