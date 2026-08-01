"""DAS privacy-noise model, extracted from notebook 04's committed outputs.

DHC and the Demographic Profile ship no per-cell uncertainty measure (no MOE,
no CV) -- the only uncertainty signal available for them is this empirical
noise model, measured by differencing the 2010 DAS demonstration data against
published 2010 SF1 counts (EDA 04). Notebook 04 cannot re-run in this worktree
(its ~250 MB inputs are absent), so these numbers are transcribed from its
last executed output (notebooks/04-privacy-noise-das-demo.ipynb, cells
8/13/22/23) rather than recomputed.

CAVEAT: this is a 2010-demonstration-derived estimate applied to 2020
production DHC/DP as a stand-in. It is not measured on the actual product
being analyzed -- treat any DHC/DP1 noise figures derived from it as modeled,
not observed. Only total population has a full binned relative-RMSE curve
(and only at block level); every other level/variable combination below is
either a single anchor point or a fitted slope, documented per-level because
the data behind each is genuinely different in richness.

relative RMSE = sqrt(mean((demo - published)^2)) / mean(published)
              -- the noise analog of CV (see notebook 04 section 4).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --- Total population -------------------------------------------------------

# Cell 8: absolute per-level error stats, demo vs. published SF1.
TOTAL_POP_RMSE_BY_LEVEL = pd.Series(
    {"county": 2.268, "tract": 2.496, "block group": 23.215, "block": 6.890},
    name="rmse",
)

# Cell 13: fitted log-log slope of relative RMSE on population size, fit
# *within* each level (not pooled -- the DAS allocates privacy-loss budget
# level by level). Reference: constant absolute noise -> -1.00; pure
# sampling noise -> -0.50.
TOTAL_POP_LOGLOG_SLOPE = {"tract": -0.90, "block group": -0.85, "block": -0.78}

# Cell 13: the one level with a full printed binned curve (14 quarter-decade
# bins -- block had enough units to support that many). Do NOT apply this
# curve to tract/block-group sizes; each level's noise process is different
# (block-group carries ~9x the noise of a same-size tract, per cell 13's
# "12x gap at ~1,400 residents" anecdote -- also see TRACT/BG anchors below).
BLOCK_SIZE_BINS = pd.DataFrame(
    {
        "size": [1.0000, 2.4335, 4.4493, 7.4606, 13.4914, 24.6024, 43.0803,
                 74.5978, 130.4605, 231.2263, 405.2108, 710.4312, 1240.8485, 2234.7273],
        "rel_rmse": [7.1906, 2.8970, 1.4770, 0.8518, 0.4651, 0.2576, 0.1591,
                     0.1039, 0.0729, 0.0518, 0.0403, 0.0338, 0.0250, 0.0153],
    }
)

# Cell 13's one printed same-size comparison point for tract and block group
# ("At ~1,400 residents: block-group relative noise 0.0175 vs tract 0.0015").
# Not a full curve -- one anchor per level, combined with that level's slope
# above to extrapolate: rel_rmse(size) = anchor_rel_rmse * (size/1400)^slope.
TRACT_BG_ANCHOR_SIZE = 1_400
TRACT_ANCHOR_REL_RMSE = 0.0015
BLOCK_GROUP_ANCHOR_REL_RMSE = 0.0175

# Cell 13: county has only 21 units statewide -- too few to bin or fit a
# slope, so this is a single pooled point, treated as roughly constant
# across county sizes rather than extrapolated.
COUNTY_POINT = {"size": 418_662, "rel_rmse": 5.4e-06}

# Cell 8: the state total is an exact DAS invariant (RMSE == 0 asserted in
# notebook 04) -- not a rounding coincidence, a designed property of TDA.
STATE_REL_RMSE = 0.0

# --- Black alone 65+ (small-subgroup contrast) ------------------------------

# Cell 22: absolute per-level error stats.
BLACK_65PLUS_RMSE_BY_LEVEL = pd.Series(
    {"county": 34.615, "tract": 7.063, "block group": 6.853, "block": 1.644},
    name="rmse",
)

# Cell 23: fitted log-log slopes. No binned curve or tract/BG anchor was
# printed for this variable (only the slopes) -- use these for shape
# comparisons against total population, not for absolute size lookups.
BLACK_65PLUS_LOGLOG_SLOPE = {"tract": -0.78, "block group": -0.57, "block": -0.55}
BLACK_65PLUS_COUNTY_POINT = {"size": 5_541, "rel_rmse": 0.0062}


def estimate_relative_noise(level: str, size: float) -> float:
    """Modeled relative noise (RMSE / size) for a total-population count.

    Method varies by level because the source data does:
    - "state": the DAS invariant, always 0.
    - "county": the single pooled point, returned constant (no slope to
      extrapolate with -- 21 statewide units was too few to fit one).
    - "block": log-log interpolated on the real 14-bin curve (BLOCK_SIZE_BINS).
    - "tract" / "block group": power-law extrapolation from the single
      1,400-resident anchor point, using that level's fitted slope.
    """
    if level == "state":
        return STATE_REL_RMSE
    if level == "county":
        return COUNTY_POINT["rel_rmse"]
    if level == "block":
        bins = BLOCK_SIZE_BINS
        log_rel = np.interp(np.log10(size), np.log10(bins["size"]), np.log10(bins["rel_rmse"]))
        return float(10**log_rel)
    if level in ("tract", "block group"):
        anchor_rel = TRACT_ANCHOR_REL_RMSE if level == "tract" else BLOCK_GROUP_ANCHOR_REL_RMSE
        key = "tract" if level == "tract" else "block group"
        slope = TOTAL_POP_LOGLOG_SLOPE[key]
        return float(anchor_rel * (size / TRACT_BG_ANCHOR_SIZE) ** slope)
    raise ValueError(f"level must be one of state/county/tract/block group/block, got {level!r}")


if __name__ == "__main__":
    # ponytail: smallest check the transcribed numbers still make sense together.
    assert TOTAL_POP_RMSE_BY_LEVEL["block group"] > TOTAL_POP_RMSE_BY_LEVEL["tract"]
    assert BLOCK_SIZE_BINS["rel_rmse"].is_monotonic_decreasing
    assert -1.0 <= TOTAL_POP_LOGLOG_SLOPE["tract"] <= -0.5
    assert estimate_relative_noise("state", 1_000) == 0.0
    assert estimate_relative_noise("block group", 1_400) > estimate_relative_noise("tract", 1_400)
    assert estimate_relative_noise("block", 100) > estimate_relative_noise("block", 2000)
    print("noise_model self-check OK")
