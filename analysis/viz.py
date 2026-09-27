"""Shared chart furniture for the EDA notebooks.

What it does
------------
The styling and file-saving code every notebook was re-typing: the CV
boxplot color scheme, the ESRI/NCHS reference-line overlay, the brand
palette used by the composite-score charts, and the save-to-data/processed
ritual (mkdir + savefig + print). Centralizing this means a palette or
reference-line change happens once, and a new notebook (e.g. Phase B's
DHC/DP1 EDA) doesn't have to re-derive it.

What it needs
-------------
matplotlib. Nothing else -- this module has no data-loading logic and
does not know about ACS, DHC, or any specific product.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

# Boxplot color scheme used by every CV-distribution chart (EDA 01, 02).
BOXPLOT_STYLE = dict(
    patch_artist=True,
    boxprops=dict(facecolor="#9ecae1", edgecolor="#3182bd"),
    medianprops=dict(color="#08519c", linewidth=2),
    whiskerprops=dict(color="#3182bd"),
    capprops=dict(color="#3182bd"),
    flierprops=dict(
        marker=".", markersize=3, markerfacecolor="#3182bd",
        markeredgecolor="none", alpha=0.4,
    ),
)

# Common CV reliability conventions (ESRI / NCHS), shown for orientation
# only -- not this project's adopted tiers. See docs/glossary.md.
CV_REFERENCE_LINES: list[tuple[float, str]] = [
    (0.12, "CV 0.12 — ESRI: high reliability below this line"),
    (0.30, "CV 0.30 — NCHS: flag / interpret with caution"),
    (0.40, "CV 0.40 — ESRI: low reliability above this line"),
]


def draw_cv_reference_lines(
    ax: plt.Axes, lines: list[tuple[float, str]] = CV_REFERENCE_LINES
) -> None:
    """Draw dashed horizontal lines with labels at each CV convention."""
    for y, label in lines:
        ax.axhline(y, color="#bbbbbb", linestyle="--", linewidth=1, zorder=0)
        ax.text(
            1.02, y, label, transform=ax.get_yaxis_transform(),
            fontsize=8, va="center", color="#666666",
        )


def save_chart(fig: plt.Figure, repo_root: Path, name: str, *, dpi: int = 200) -> Path:
    """Save a figure to data/processed/<name> and print the standard message.

    Creates data/processed/ if needed. Returns the saved path.
    """
    out = repo_root / "data" / "processed" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    print(f"Chart saved to {out.relative_to(repo_root)} (local-only, regenerable)")
    return out


# Brand palette for the composite-score charts (EDA 06/07), matched to the
# biweekly deck design system.
BRAND = dict(
    NAVY="#1F2A5C",
    GOLD="#C9A227",
    ICE="#EEF2FA",
    BODY="#22283B",
    MUTED="#5A6072",
    FINE="#C7CCD6",
)
