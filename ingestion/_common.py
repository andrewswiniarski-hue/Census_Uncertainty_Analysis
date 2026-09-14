"""Shared mechanics for the project's Census API pull scripts.

What it does
------------
The small pieces every pull_*.py script needs and would otherwise
duplicate: reading the API key from .env, fetching official variable
labels for eyeball verification, and the ACS annotation-code sanity
report (nulls / annotation counts / clean value range per column). Each
script keeps its own variable list, geography levels, and any checks
specific to its dataset -- only the mechanics live here.

What it needs
-------------
CENSUS_API_KEY in the repo-root .env file for load_api_key(); internet
access for fetch_official_labels() and download_with_retry().
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "raw"

# ACS "annotation" codes: giant negative numbers the API returns in place
# of real values (e.g. estimate suppressed, or MOE not applicable). They
# must be treated as missing, never as data.
# Reference: "Notes on ACS Estimate and Annotation Values" (census.gov).
KNOWN_ANNOTATIONS = {
    -555555555: "controlled estimate -- no sampling-error MOE published",
    -666666666: "estimate not computed (insufficient sample observations)",
}
ANNOTATION_CUTOFF = -111111111  # anything at or below this is an annotation


def load_api_key() -> str:
    """Read CENSUS_API_KEY from the repo-root .env (never from git)."""
    load_dotenv(REPO_ROOT / ".env")
    key = os.getenv("CENSUS_API_KEY")
    if not key or key == "paste_your_key_here":
        sys.exit(
            "CENSUS_API_KEY is missing. Copy .env.example to .env in the repo "
            "root and paste in your key (see README 'Getting Started')."
        )
    return key



def download_with_retry(download, *args, attempts: int = 5, base_delay: float = 2.0,
                        sleep=time.sleep, log=print, **kwargs):
    """Call `download(*args, **kwargs)`, retrying on failure with doubling delays.

    Why: censusdis looks up metadata for every requested variable before it
    downloads anything, one HTTP request per variable with no retry of its own
    (`censusdis.data._prefetch_variable_types`). Across hundreds of variables a
    single dropped request aborts the whole pull, and the failure lands on a
    different variable each attempt (observed 2026-09-08: B01001_015M,
    B01001_033M, B27001_014E), so it is not a bad variable name.

    A plain retry of the whole call is enough, because censusdis keeps looked-up
    metadata in a module-level cache (`censusdis.data.variables`) that persists
    across calls. Each retry skips what already succeeded and resumes near where
    the last attempt failed.

    The final failure is re-raised unchanged, so a genuinely wrong request still
    fails loudly. `sleep` and `log` are parameters so tests run instantly.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for attempt in range(1, attempts + 1):
        try:
            return download(*args, **kwargs)
        except Exception as exc:
            if attempt == attempts:
                raise
            delay = base_delay * 2 ** (attempt - 1)
            first_line = (str(exc).splitlines() or [""])[0][:160]
            log(f"  download attempt {attempt} of {attempts} failed ({first_line}); "
                f"retrying in {delay:.0f}s")
            sleep(delay)


def fetch_official_labels(dataset: str, vintage: int, codes: list[str]) -> dict[str, str]:
    """Ask the API for each variable's official label.

    Guards against a wrong variable code: the label is printed at run
    time so a mismatch is caught by eyeball instead of trusted silently.
    (The variables endpoint needs no API key.)
    """
    labels: dict[str, str] = {}
    for code in codes:
        url = f"https://api.census.gov/data/{vintage}/{dataset}/variables/{code}.json"
        try:
            meta = requests.get(url, timeout=30).json()
            labels[code] = meta.get("label", "<no label in response>")
        except requests.RequestException as exc:
            labels[code] = f"<label fetch failed: {exc}>"
    return labels


def annotation_mask(s: pd.Series, cutoff: int = ANNOTATION_CUTOFF) -> pd.Series:
    """True where a value is an ACS annotation code rather than real data."""
    return s.notna() & (s <= cutoff)


def sanity_report(
    df: pd.DataFrame,
    level: str,
    download_vars: list[str],
    *,
    value_fmt: str = ",.0f",
) -> None:
    """Print per-column checks: nulls, annotation codes, clean value range.

    Shared by the ACS estimate and allocation pulls (identical shape;
    `value_fmt` covers the one difference between them -- allocation's
    percent columns print with one decimal). `download_vars` may include
    "NAME", which is skipped.
    """
    print(f"\n  Sanity checks -- {level}: {len(df):,} rows x {len(df.columns)} columns")
    print(f"  {'column':<15} {'nulls':>12} {'annotations':>12}   clean min / max")
    codes_seen: dict[int, int] = {}
    for col in download_vars:
        if col == "NAME":
            continue
        if col not in df.columns:
            print(f"  {col:<15} MISSING FROM API RESPONSE")
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        n = len(s)
        nulls = int(s.isna().sum())
        ann = annotation_mask(s)
        for val, cnt in s[ann].value_counts().items():
            codes_seen[int(val)] = codes_seen.get(int(val), 0) + int(cnt)
        clean = s[s.notna() & ~ann]
        rng = (
            f"{clean.min():>14{value_fmt}} / {clean.max():<14{value_fmt}}"
            if len(clean)
            else "   (no clean values)"
        )
        print(
            f"  {col:<15} {nulls:>5} ({nulls / n:5.1%}) {int(ann.sum()):>5} "
            f"({ann.sum() / n:5.1%})   {rng}"
        )
    if codes_seen:
        print("  Annotation codes present in this file:")
        for val, cnt in sorted(codes_seen.items()):
            meaning = KNOWN_ANNOTATIONS.get(val, "look up in ACS annotation docs")
            print(f"    {val}: {cnt:,} cells -- {meaning}")
