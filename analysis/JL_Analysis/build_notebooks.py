"""Generate JL_Analysis EDA notebooks."""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent


def nb(cells: list[dict]) -> dict:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12.0"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def md(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


NOTEBOOKS = {
    "00-data-at-a-glance.ipynb": [
        md(
            "# Notebook 0 — Data at a Glance\n\n"
            "Structural orientation for the NJ ACS 5-year (2020–2024) pull before any "
            "uncertainty math. We load all three geography levels, inspect shapes and "
            "missingness, and render quick boundary maps.\n\n"
            "**ACS (American Community Survey):** ongoing Census Bureau survey; every "
            "estimate ships with a **MOE (margin of error)** at 90% confidence."
        ),
        code(
            "import sys\n"
            "from pathlib import Path\n\n"
            "import geopandas as gpd\n"
            "import matplotlib.pyplot as plt\n"
            "import pandas as pd\n\n"
            "NOTEBOOK_DIR = Path.cwd()\n"
            "if NOTEBOOK_DIR.name != 'JL_Analysis':\n"
            "    NOTEBOOK_DIR = NOTEBOOK_DIR / 'analysis' / 'JL_Analysis'\n"
            "sys.path.insert(0, str(NOTEBOOK_DIR))\n\n"
            "from helpers import (\n"
            "    GEO_LABELS,\n"
            "    GEO_LEVELS,\n"
            "    VARIABLES,\n"
            "    annotation_mask,\n"
            "    estimate_moe_cols,\n"
            "    load_acs,\n"
            "    load_geo,\n"
            ")\n\n"
            "plt.rcParams['figure.dpi'] = 110"
        ),
        code(
            "acs = {level: load_acs(level) for level in GEO_LEVELS}\n"
            "geo = {level: load_geo(level) for level in GEO_LEVELS}\n\n"
            "for level in GEO_LEVELS:\n"
            "    df = acs[level]\n"
            "    print(f\"\\n{'=' * 60}\")\n"
            "    print(f\"{GEO_LABELS[level]} — {level}\")\n"
            "    print(f\"Shape: {df.shape[0]:,} rows x {df.shape[1]} columns\")\n"
            "    print('\\nColumns:')\n"
            "    print(df.columns.tolist())\n"
            "    print('\\nDtypes:')\n"
            "    print(df.dtypes)\n"
            "    display(df.head(3))"
        ),
        md(
            "## Row counts by geography level\n\n"
            "Smaller geographies nest inside larger ones, so row counts explode as we "
            "zoom in — the central empirical setup for this project."
        ),
        code(
            "counts = pd.DataFrame({\n"
            "    'Geography level': [GEO_LABELS[l] for l in GEO_LEVELS],\n"
            "    'Rows': [len(acs[l]) for l in GEO_LEVELS],\n"
            "})\n"
            "fig, ax = plt.subplots(figsize=(7, 4))\n"
            "bars = ax.bar(counts['Geography level'], counts['Rows'], color=['#2c5f8a', '#4a8fb8', '#7eb8d8'])\n"
            "ax.set_title('NJ ACS rows by geography level (vintage 2024)')\n"
            "ax.set_ylabel('Number of rows')\n"
            "for bar, val in zip(bars, counts['Rows']):\n"
            "    ax.text(bar.get_x() + bar.get_width() / 2, val + 80, f'{val:,}', ha='center', fontsize=10)\n"
            "plt.tight_layout()\n"
            "plt.show()"
        ),
        md(
            "## Missing values and annotation codes\n\n"
            "**Annotation codes** are giant negative sentinel values the Census API "
            "returns instead of real numbers (e.g. `-555555555` = controlled estimate, "
            "`-666666666` = insufficient sample). Our client library converts them to "
            "blanks, so this chart shows combined null rates. See `docs/glossary.md`."
        ),
        code(
            "null_rows = []\n"
            "for level in GEO_LEVELS:\n"
            "    df = acs[level]\n"
            "    for var_code in VARIABLES:\n"
            "        est_col, moe_col = estimate_moe_cols(var_code)\n"
            "        for col, kind in [(est_col, 'estimate'), (moe_col, 'MOE')]:\n"
            "            if col not in df.columns:\n"
            "                continue\n"
            "            s = pd.to_numeric(df[col], errors='coerce')\n"
            "            null_rows.append({\n"
            "                'Geography level': GEO_LABELS[level],\n"
            "                'Variable': VARIABLES[var_code],\n"
            "                'Column type': kind,\n"
            "                'Null rate': s.isna().mean(),\n"
            "                'Annotation rate': annotation_mask(s).mean(),\n"
            "            })\n\n"
            "null_df = pd.DataFrame(null_rows)\n"
            "pivot = null_df.pivot_table(\n"
            "    index='Variable', columns='Geography level', values='Null rate', aggfunc='max'\n"
            ")\n"
            "fig, ax = plt.subplots(figsize=(9, 5))\n"
            "pivot.plot(kind='barh', ax=ax, color=['#2c5f8a', '#4a8fb8', '#7eb8d8'])\n"
            "ax.set_title('Null rate by variable and geography level')\n"
            "ax.set_xlabel('Share of rows that are blank')\n"
            "ax.legend(title='')\n"
            "plt.tight_layout()\n"
            "plt.show()\n\n"
            "print('Block-group poverty and subgroup variables are 100% blank — expected; '\n"
            "      'those tables are not published below tract level.')"
        ),
        md("## Quick boundary maps — does this look like New Jersey?"),
        code(
            "fig, axes = plt.subplots(1, 3, figsize=(15, 7))\n"
            "colors = ['#2c5f8a', '#4a8fb8', '#7eb8d8']\n"
            "for ax, level, color in zip(axes, GEO_LEVELS, colors):\n"
            "    gdf = geo[level]\n"
            "    gdf.plot(ax=ax, color=color, edgecolor='white', linewidth=0.2)\n"
            "    ax.set_title(f\"{GEO_LABELS[level]}\\n({len(gdf):,} shapes)\")\n"
            "    ax.set_axis_off()\n"
            "fig.suptitle('New Jersey boundaries by geography level (ACS 2024 vintage)', y=1.02)\n"
            "plt.tight_layout()\n"
            "plt.show()"
        ),
    ],
    "01-cv-by-geography-size.ipynb": [
        md(
            "# Notebook 1 — CV by Geography Size\n\n"
            "The project's central empirical finding: **smaller geography = noisier "
            "estimates**. We compare **CV (coefficient of variation)** distributions "
            "across county, tract, and block group.\n\n"
            "**CV** = standard error / estimate, where `SE = MOE / 1.645` because ACS "
            "MOEs are 90% confidence intervals. Unitless — comparable across variables."
        ),
        code(
            "import sys\n"
            "from pathlib import Path\n\n"
            "import matplotlib.pyplot as plt\n"
            "import pandas as pd\n\n"
            "NOTEBOOK_DIR = Path.cwd()\n"
            "if NOTEBOOK_DIR.name != 'JL_Analysis':\n"
            "    NOTEBOOK_DIR = NOTEBOOK_DIR / 'analysis' / 'JL_Analysis'\n"
            "sys.path.insert(0, str(NOTEBOOK_DIR))\n\n"
            "from helpers import GEO_LABELS, GEO_LEVELS, VARIABLES, build_cv_long"
        ),
        code(
            "cv_all = pd.concat([build_cv_long(level) for level in GEO_LEVELS], ignore_index=True)\n"
            "cv_plot = cv_all.dropna(subset=['cv']).copy()\n"
            "cv_plot['Geography level'] = cv_plot['geography_level'].map(GEO_LABELS)\n"
            "print(f'Valid CV rows: {len(cv_plot):,}')\n"
            "cv_plot.groupby(['Geography level', 'variable']).agg(\n"
            "    n=('cv', 'count'), median_cv=('cv', 'median'), max_moe=('moe', 'max')\n"
            ").round(3)"
        ),
        md("## CV distributions by geography size"),
        code(
            "fig, axes = plt.subplots(2, 2, figsize=(12, 9))\n"
            "axes = axes.flatten()\n"
            "groups = ['population', 'income', 'poverty', 'subgroup']\n"
            "geo_order = [GEO_LABELS[l] for l in GEO_LEVELS]\n"
            "for ax, group in zip(axes, groups):\n"
            "    sub = cv_plot[cv_plot['variable_group'] == group]\n"
            "    data = [sub.loc[sub['Geography level'] == g, 'cv'].values for g in geo_order]\n"
            "    ax.boxplot(data, tick_labels=geo_order, showfliers=False)\n"
            "    ax.set_yscale('log')\n"
            "    ax.set_title(group.title())\n"
            "    ax.set_ylabel('CV (log scale)')\n"
            "    ax.tick_params(axis='x', rotation=15)\n"
            "fig.suptitle('CV distributions by geography size and variable group', y=1.02)\n"
            "plt.tight_layout()\n"
            "plt.show()"
        ),
        md(
            "## Headline check — income MOE at extremes\n\n"
            "HANDOFF.md preview: worst county income MOE ±$3,982 vs. worst block group "
            "±$247,531."
        ),
        code(
            "income = cv_all[cv_all['variable_code'] == 'B19013_001'].dropna(subset=['moe'])\n"
            "for level in GEO_LEVELS:\n"
            "    sub = income[income['geography_level'] == level]\n"
            "    row = sub.loc[sub['moe'].idxmax()]\n"
            "    print(f\"{GEO_LABELS[level]:14s}  worst income MOE: ±${row['moe']:,.0f}  ({row['NAME']})\")\n\n"
            "county_worst = income[income['geography_level'] == 'county']['moe'].max()\n"
            "bg_worst = income[income['geography_level'] == 'block_group']['moe'].max()\n"
            "print(f\"\\nRatio (block group / county worst MOE): {bg_worst / county_worst:,.1f}x\")"
        ),
        md(
            "### Takeaway\n\n"
            "CV and raw MOE both grow dramatically as geography shrinks — especially for "
            "income at block-group level. This is the empirical backbone of the "
            "reliability dashboard."
        ),
    ],
    "02-cv-by-variable-type.ipynb": [
        md(
            "# Notebook 2 — CV by Variable Type\n\n"
            "Holding geography fixed at **census tract**, we compare CV across variable "
            "types: population, income, poverty, and small subgroup cells (Black 65+)."
        ),
        code(
            "import sys\n"
            "from pathlib import Path\n\n"
            "import matplotlib.pyplot as plt\n"
            "import pandas as pd\n\n"
            "NOTEBOOK_DIR = Path.cwd()\n"
            "if NOTEBOOK_DIR.name != 'JL_Analysis':\n"
            "    NOTEBOOK_DIR = NOTEBOOK_DIR / 'analysis' / 'JL_Analysis'\n"
            "sys.path.insert(0, str(NOTEBOOK_DIR))\n\n"
            "from helpers import VARIABLES, build_cv_long"
        ),
        code(
            "cv_tract = build_cv_long('tract').dropna(subset=['cv'])\n"
            "summary = (\n"
            "    cv_tract.groupby(['variable_group', 'variable'])\n"
            "    .agg(n=('cv', 'count'), median_cv=('cv', 'median'), p90_cv=('cv', lambda s: s.quantile(0.9)))\n"
            "    .sort_values('median_cv', ascending=False)\n"
            ")\n"
            "summary.round(3)"
        ),
        code(
            "fig, axes = plt.subplots(1, 2, figsize=(14, 5))\n\n"
            "group_order = ['population', 'income', 'poverty', 'subgroup']\n"
            "group_data = [cv_tract.loc[cv_tract['variable_group'] == g, 'cv'].values for g in group_order]\n"
            "axes[0].boxplot(group_data, tick_labels=group_order, showfliers=False)\n"
            "axes[0].set_yscale('log')\n"
            "axes[0].set_title('Tract-level CV by variable group')\n"
            "axes[0].set_xlabel('Variable group')\n"
            "axes[0].set_ylabel('CV (log scale)')\n\n"
            "for group, color in zip(group_order, ['#2c5f8a', '#4a8fb8', '#7eb8d8', '#f4a261']):\n"
            "    sub = cv_tract[cv_tract['variable_group'] == group]\n"
            "    axes[1].scatter(sub['variable'], sub['cv'], alpha=0.35, s=8, label=group, c=color)\n"
            "axes[1].set_yscale('log')\n"
            "axes[1].set_title('Tract-level CV by individual variable')\n"
            "axes[1].tick_params(axis='x', rotation=45)\n"
            "axes[1].legend(title='Group', fontsize=8)\n"
            "plt.tight_layout()\n"
            "plt.show()"
        ),
        md(
            "### Takeaway\n\n"
            "Small subgroup counts (Black 65+ cells) show the highest tract-level CV — "
            "often an order of magnitude above population or income. Poverty sits in the "
            "middle; total population is the most stable at tract level."
        ),
    ],
    "03-tract-cv-choropleth.ipynb": [
        md(
            "# Notebook 3 — Tract-Level CV Choropleth\n\n"
            "A first map view of reliability: tract-level **CV** for median household "
            "income. Darker/higher CV = noisier estimate. Prototype for the dashboard's "
            "reliability-tier map.\n\n"
            "**Reliability benchmark used here:** the Census Bureau's ACS quality "
            "standard for sampling error says the coefficient of variation for key "
            "estimates should be 30% or less for the majority of those key estimates. "
            "We use `CV <= 0.30` as a sourced benchmark, not as a universal truth label "
            "for every individual estimate. Source: Census Bureau, *Quality Standards "
            "Metrics Definitions*."
        ),
        code(
            "import sys\n"
            "from pathlib import Path\n\n"
            "import geopandas as gpd\n"
            "import matplotlib.pyplot as plt\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "from matplotlib.colors import BoundaryNorm\n"
            "from matplotlib.patches import Patch\n\n"
            "NOTEBOOK_DIR = Path.cwd()\n"
            "if NOTEBOOK_DIR.name != 'JL_Analysis':\n"
            "    NOTEBOOK_DIR = NOTEBOOK_DIR / 'analysis' / 'JL_Analysis'\n"
            "sys.path.insert(0, str(NOTEBOOK_DIR))\n\n"
            "from helpers import compute_cv, estimate_moe_cols, load_acs, load_geo\n\n"
            "VAR = 'B19013_001'\n"
            "est_col, moe_col = estimate_moe_cols(VAR)"
        ),
        code(
            "acs = load_acs('tract')\n"
            "geo = load_geo('tract')\n\n"
            "acs['cv_income'] = compute_cv(acs[est_col], acs[moe_col], var_code=VAR)\n"
            "map_df = geo.merge(\n"
            "    acs[['STATE', 'COUNTY', 'TRACT', 'NAME', 'cv_income', est_col, moe_col]],\n"
            "    on=['STATE', 'COUNTY', 'TRACT'],\n"
            "    how='left',\n"
            ")\n\n"
            "valid = map_df['cv_income'].notna()\n"
            "print(f'Tracts with valid income CV: {valid.sum():,} / {len(map_df):,}')\n"
            "print(map_df.loc[valid, 'cv_income'].describe().round(3))"
        ),
        code(
            "# Census Bureau ACS quality benchmark: CV for key estimates should be 30% or less.\n"
            "# Source: Quality Standards Metrics Definitions, ACS sampling error metric.\n"
            "# This is a benchmark for context, not a universal per-estimate truth label.\n"
            "bins = [0, 0.30, np.inf]\n"
            "labels = ['CV <= 0.30 (meets Census ACS benchmark)', 'CV > 0.30 (above benchmark)']\n"
            "colors = ['#2166ac', '#d6604d']\n\n"
            "map_df['reliability_tier'] = pd.cut(map_df['cv_income'], bins=bins, labels=labels, include_lowest=True)\n\n"
            "fig, ax = plt.subplots(figsize=(8, 10))\n"
            "map_df.plot(\n"
            "    column='cv_income',\n"
            "    cmap='YlOrRd',\n"
            "    linewidth=0.15,\n"
            "    edgecolor='white',\n"
            "    legend=True,\n"
            "    legend_kwds={'label': 'CV (median household income)', 'shrink': 0.6},\n"
            "    missing_kwds={'color': '#e0e0e0', 'label': 'No valid CV'},\n"
            "    ax=ax,\n"
            ")\n"
            "ax.set_title('NJ tract-level CV — median household income\\n(ACS 2020–2024, vintage 2024)')\n"
            "ax.set_axis_off()\n"
            "plt.tight_layout()\n"
            "plt.show()"
        ),
        code(
            "fig, ax = plt.subplots(figsize=(8, 10))\n"
            "for label, color in zip(labels, colors):\n"
            "    subset = map_df[map_df['reliability_tier'] == label]\n"
            "    if len(subset):\n"
            "        subset.plot(ax=ax, color=color, linewidth=0.15, edgecolor='white')\n"
            "map_df[map_df['cv_income'].isna()].plot(ax=ax, color='#e0e0e0', linewidth=0.1, edgecolor='white')\n"
            "ax.set_title('NJ tract reliability tiers — median household income CV')\n"
            "ax.set_axis_off()\n"
            "ax.legend(handles=[Patch(facecolor=c, label=l) for l, c in zip(labels, colors)] + [Patch(facecolor='#e0e0e0', label='No valid CV')], loc='lower left')\n"
            "plt.tight_layout()\n"
            "plt.show()"
        ),
    ],
    "04-granular-error-drivers.ipynb": [
        md(
            "# Notebook 4 — Granular Error Drivers\n\n"
            "Notebooks 1–3 showed that smaller geographies and small subgroup cells have "
            "higher uncertainty. This notebook asks why.\n\n"
            "**Part A** tests whether population size explains much of the geography "
            "effect. **Part B** tests whether combining six tiny Black 65+ cells into one "
            "tract-level total improves reliability.\n\n"
            "**CV (coefficient of variation)** means standard error as a fraction of the "
            "estimate: `CV = SE / estimate`. For ACS margins of error, `SE = MOE / 1.645` "
            "because ACS MOEs are 90% confidence intervals. Source: Census Bureau, "
            "*Quality Standards Metrics Definitions*."
        ),
        code(
            "import sys\n"
            "from pathlib import Path\n\n"
            "import matplotlib.pyplot as plt\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "from IPython.display import Markdown, display\n\n"
            "NOTEBOOK_DIR = Path.cwd()\n"
            "if NOTEBOOK_DIR.name != 'JL_Analysis':\n"
            "    NOTEBOOK_DIR = NOTEBOOK_DIR / 'analysis' / 'JL_Analysis'\n"
            "sys.path.insert(0, str(NOTEBOOK_DIR))\n\n"
            "from helpers import (\n"
            "    GEO_LABELS,\n"
            "    GEO_LEVELS,\n"
            "    VARIABLE_GROUPS,\n"
            "    VARIABLES,\n"
            "    build_cv_long,\n"
            "    combine_moes_rss,\n"
            "    compute_cv,\n"
            "    estimate_moe_cols,\n"
            "    load_acs,\n"
            ")\n\n"
            "plt.rcParams['figure.dpi'] = 110"
        ),
        md(
            "## Part A — Is population size the real driver?\n\n"
            "**Population size** is the number of people in the row's geography. We use "
            "`B01003_001E` (total population estimate) as a proxy for how much sample is "
            "available in that geography. This is only a denominator/proxy here; we do "
            "not require the total-population MOE to exist, because controlled population "
            "estimates can have missing MOEs for reasons unrelated to this question.\n\n"
            "The model below fits `log(CV) ~ log(population)`. In plain English, the "
            "slope says how fast relative uncertainty falls as population grows. A slope "
            "near `-0.5` would match the common sampling pattern that uncertainty shrinks "
            "roughly with the square root of population size."
        ),
        code(
            "cv_with_population = []\n"
            "pop_col, _ = estimate_moe_cols('B01003_001')\n\n"
            "for level in GEO_LEVELS:\n"
            "    cv = build_cv_long(level)\n"
            "    acs = load_acs(level)\n"
            "    population_lookup = acs[['NAME', pop_col]].copy()\n"
            "    population_lookup['geography_level'] = level\n"
            "    population_lookup['population'] = pd.to_numeric(population_lookup[pop_col], errors='coerce')\n"
            "    if population_lookup[['geography_level', 'NAME']].duplicated().any():\n"
            "        raise ValueError(f'Duplicate population lookup rows for {level}')\n"
            "    joined = cv.merge(\n"
            "        population_lookup[['geography_level', 'NAME', 'population']],\n"
            "        on=['geography_level', 'NAME'],\n"
            "        how='left',\n"
            "        validate='many_to_one',\n"
            "    )\n"
            "    cv_with_population.append(joined)\n\n"
            "cv_population = pd.concat(cv_with_population, ignore_index=True)\n"
            "analysis_df = cv_population.dropna(subset=['cv', 'population']).copy()\n"
            "analysis_df = analysis_df[(analysis_df['cv'] > 0) & (analysis_df['population'] > 0)]\n"
            "analysis_df['log_population'] = np.log(analysis_df['population'])\n"
            "analysis_df['log_cv'] = np.log(analysis_df['cv'])\n"
            "analysis_df = analysis_df[np.isfinite(analysis_df['log_population']) & np.isfinite(analysis_df['log_cv'])]\n"
            "analysis_df['Geography level'] = analysis_df['geography_level'].map(GEO_LABELS)\n\n"
            "print(f'Rows with valid CV and population proxy: {len(analysis_df):,}')\n"
            "display(\n"
            "    analysis_df.groupby(['Geography level', 'variable_group'])\n"
            "    .agg(n=('cv', 'count'), median_population=('population', 'median'), median_cv=('cv', 'median'))\n"
            "    .round(3)\n"
            ")"
        ),
        code(
            "coeffs, cov = np.polyfit(analysis_df['log_population'], analysis_df['log_cv'], 1, cov=True)\n"
            "slope, intercept = coeffs\n"
            "slope_se = float(np.sqrt(cov[0, 0]))\n"
            "fitted = intercept + slope * analysis_df['log_population']\n"
            "ss_res = float(((analysis_df['log_cv'] - fitted) ** 2).sum())\n"
            "ss_tot = float(((analysis_df['log_cv'] - analysis_df['log_cv'].mean()) ** 2).sum())\n"
            "r_squared = 1 - (ss_res / ss_tot)\n\n"
            "fig, ax = plt.subplots(figsize=(8, 6))\n"
            "colors = {'county': '#2166ac', 'tract': '#67a9cf', 'block_group': '#f4a261'}\n"
            "for level in GEO_LEVELS:\n"
            "    sub = analysis_df[analysis_df['geography_level'] == level]\n"
            "    ax.scatter(sub['population'], sub['cv'], s=8, alpha=0.18, color=colors[level], label=GEO_LABELS[level])\n"
            "x_line_log = np.linspace(analysis_df['log_population'].min(), analysis_df['log_population'].max(), 100)\n"
            "y_line = np.exp(intercept + slope * x_line_log)\n"
            "ax.plot(np.exp(x_line_log), y_line, color='black', linewidth=2, label=f'fit slope = {slope:.3f}')\n"
            "ax.set_xscale('log')\n"
            "ax.set_yscale('log')\n"
            "ax.set_xlabel('Total population estimate (log scale)')\n"
            "ax.set_ylabel('CV (log scale)')\n"
            "ax.set_title('CV vs. population size')\n"
            "ax.legend()\n"
            "plt.tight_layout()\n"
            "plt.show()\n\n"
            "if slope <= -0.35:\n"
            "    direction_text = f'a {abs(slope):.2f}% decrease in CV'\n"
            "    slope_text = 'Population size explains a large part of the geography effect.'\n"
            "elif slope <= -0.05:\n"
            "    direction_text = f'a {abs(slope):.2f}% decrease in CV'\n"
            "    slope_text = 'Population size helps, but variable type and other factors also matter.'\n"
            "elif slope <= 0.05:\n"
            "    direction_text = 'almost no average change in CV'\n"
            "    slope_text = 'Population size alone does not explain the pooled geography pattern; variable type and table availability are also shaping the result.'\n"
            "else:\n"
            "    direction_text = f'a {slope:.2f}% increase in CV'\n"
            "    slope_text = 'Population size is not explaining the pooled pattern in the expected direction; variable mix and table availability are dominating this simple model.'\n"
            "display(Markdown(\n"
            "    f\"### Part A takeaway\\n\\n\"\n"
            "    f\"The fitted slope is **{slope:.3f}** (standard error **{slope_se:.3f}**) \"\n"
            "    f\"with R-squared **{r_squared:.3f}**. \"\n"
            "    f\"That means a 1% increase in population is associated with {direction_text}. \"\n"
            "    f\"{slope_text} Geography level is still useful, but this simple \"\n"
            "    f\"pooled model should not be treated as proof that population size by itself \"\n"
            "    f\"drives all ACS reliability differences. It also does not hold variable \"\n"
            "    f\"type constant: subgroup cells have structurally high CVs and are not \"\n"
            "    f\"available at block-group level, so a cleaner next test would fit this \"\n"
            "    f\"relationship within each variable group.\"\n"
            "))"
        ),
        md(
            "## Part B — Combining six Black 65+ cells with RSS MOE\n\n"
            "**Root-sum-of-squares (RSS) MOE combination** means we add estimates normally, "
            "but combine margins of error by squaring each MOE, adding the squares, and "
            "taking the square root: `MOE_sum = sqrt(MOE_1^2 + MOE_2^2 + ... + MOE_k^2)`. "
            "This is the Census Bureau's standard approximation for summing ACS estimates. "
            "It assumes the component MOEs are available and treats the component estimates "
            "as approximately independent for this calculation, so we treat any tract with a "
            "missing component estimate/MOE pair as missing for the combined measure. "
            "After that, we compute the combined CV the same way as before: "
            "`combined CV = (combined MOE / 1.645) / combined estimate`."
        ),
        code(
            "subgroup_codes = VARIABLE_GROUPS['subgroup']\n"
            "tract = load_acs('tract')\n"
            "est_cols = [estimate_moe_cols(code)[0] for code in subgroup_codes]\n"
            "moe_cols = [estimate_moe_cols(code)[1] for code in subgroup_codes]\n\n"
            "combined_estimate, combined_moe = combine_moes_rss(tract[est_cols], tract[moe_cols])\n"
            "missing_combined_rows = int(combined_estimate.isna().sum())\n"
            "if missing_combined_rows:\n"
            "    print(f'{missing_combined_rows:,} tracts have at least one missing/invalid component estimate or MOE; combined CV is left blank for those rows.')\n"
            "else:\n"
            "    print('All tracts have complete valid component estimates and MOEs for RSS combination.')\n"
            "combined_cv = compute_cv(combined_estimate, combined_moe, var_code=subgroup_codes[0])\n"
            "combined = pd.DataFrame({\n"
            "    'NAME': tract['NAME'],\n"
            "    'combined_estimate': combined_estimate,\n"
            "    'combined_moe': combined_moe,\n"
            "    'combined_cv': combined_cv,\n"
            "})\n\n"
            "individual = build_cv_long('tract')\n"
            "individual = individual[individual['variable_code'].isin(subgroup_codes)].dropna(subset=['cv'])\n\n"
            "def summarize_cv(label: str, series: pd.Series) -> dict:\n"
            "    s = series.dropna()\n"
            "    return {\n"
            "        'CV series': label,\n"
            "        'n': len(s),\n"
            "        'median_cv': s.median(),\n"
            "        'p75_cv': s.quantile(0.75),\n"
            "        'p90_cv': s.quantile(0.90),\n"
            "        'share_cv_at_or_below_0_30': (s <= 0.30).mean(),\n"
            "    }\n\n"
            "rss_summary = pd.DataFrame([\n"
            "    summarize_cv('Individual Black 65+ cells (pooled)', individual['cv']),\n"
            "    summarize_cv('RSS combined Black 65+ tract total', combined['combined_cv']),\n"
            "])\n"
            "display(rss_summary.round(3))"
        ),
        code(
            "fig, ax = plt.subplots(figsize=(8, 5))\n"
            "plot_data = [individual['cv'].dropna().values, combined['combined_cv'].dropna().values]\n"
            "ax.boxplot(plot_data, tick_labels=['Six individual cells\\n(pooled)', 'RSS combined\\nBlack 65+ total'], showfliers=False)\n"
            "ax.axhline(0.30, color='#d6604d', linestyle='--', linewidth=1.5, label='Census ACS 0.30 benchmark')\n"
            "ax.set_yscale('log')\n"
            "ax.set_ylabel('CV (log scale)')\n"
            "ax.set_title('RSS combination improves tract-level subgroup reliability')\n"
            "ax.legend()\n"
            "plt.tight_layout()\n"
            "plt.show()\n\n"
            "individual_median_cv = float(rss_summary.loc[0, 'median_cv'])\n"
            "combined_median_cv = float(rss_summary.loc[1, 'median_cv'])\n"
            "median_ratio = individual_median_cv / combined_median_cv\n"
            "individual_share_benchmark = float(rss_summary.loc[0, 'share_cv_at_or_below_0_30'])\n"
            "combined_share_benchmark = float(rss_summary.loc[1, 'share_cv_at_or_below_0_30'])\n\n"
            "display(Markdown(\n"
            "    f\"### Part B takeaway\\n\\n\"\n"
            "    f\"The pooled individual cells have median CV **{individual_median_cv:.3f}**, \"\n"
            "    f\"while the RSS-combined Black 65+ tract total has median CV \"\n"
            "    f\"**{combined_median_cv:.3f}**. The individual-cell median is about \"\n"
            "    f\"**{median_ratio:.1f}x** the combined median. Using the Census ACS \"\n"
            "    f\"0.30 benchmark, **{individual_share_benchmark:.1%}** of individual-cell \"\n"
            "    f\"CVs are at or below the benchmark versus **{combined_share_benchmark:.1%}** \"\n"
            "    f\"of RSS-combined tract totals. In plain English: aggregating tiny cells \"\n"
            "    f\"does not remove uncertainty, but it makes this subgroup measure much more \"\n"
            "    f\"usable than the six separate age-by-sex cells.\"\n"
            "))"
        ),
    ],
}


def main() -> None:
    for name, cells in NOTEBOOKS.items():
        path = OUT_DIR / name
        path.write_text(json.dumps(nb(cells), indent=1), encoding="utf-8")
        print(f"Wrote {path.name}")


if __name__ == "__main__":
    main()
