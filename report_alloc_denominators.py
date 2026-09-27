"""Is "allocation rate" a well-defined quantity? Report the sweep.

What it does
------------
Loads the PUMS allocation frame and computes the income allocation rate
under every defensible denominator and scope, then reports how much the
answer moves. Writes docs/allocation-denominator-sensitivity.md.

The claim being tested is not about income. It is about the metric: an
allocation rate is a ratio, the denominator is a choice, and if reasonable
choices disagree then "X% was allocated" is not a measurement.

What it needs
-------------
- data/raw/pums_2024_nj_alloc_flags.parquet
  (regenerate with: python ingestion/pull_pums_alloc_flags.py)
- pandas, numpy, pyarrow. No network, no API key.

What it produces
----------------
- docs/allocation-denominator-sensitivity.md
- console tables: rates, ranks, volatility, pairwise agreement

Run from the repo root:
    python report_alloc_denominators.py
    python report_alloc_denominators.py --parquet data/raw/pums_2024_nj_alloc_flags.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import alloc_denominator as ad  # noqa: E402
from analysis import common  # noqa: E402

DEFAULT_PARQUET = (REPO_ROOT / "data" / "raw"
                   / f"pums_{common.ACS_VINTAGE}_nj_alloc_flags.parquet")
OUT_PATH = REPO_ROOT / "docs" / "allocation-denominator-sensitivity.md"


def load(path: Path) -> pd.DataFrame:
    if not path.exists():
        sys.exit(
            f"{path} not found -- regenerate with:\n"
            f"    python ingestion/pull_pums_alloc_flags.py"
        )
    df = pd.read_parquet(path)
    missing = [c for c in list(ad.FLAG_TO_AMOUNT) + list(ad.NA_CODE)
               if c not in df.columns]
    if missing:
        sys.exit(
            f"{path} is missing {missing}.\n"
            f"This is the OLD flags-only pull. The denominator sweep needs the\n"
            f"income amount variables. Re-run: python ingestion/pull_pums_alloc_flags.py"
        )
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Denominator sensitivity of the income allocation rate.")
    parser.add_argument("--parquet", default=str(DEFAULT_PARQUET))
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    df = load(Path(args.parquet))
    print(f"Loaded {len(df):,} records from {Path(args.parquet).name}\n")

    zeros = ad.zero_allocation_share(df)
    swept = ad.sweep(df)
    rates = ad.rate_table(swept)
    ranks = ad.rank_table(swept)
    vol = ad.volatility(swept)
    agr = ad.agreement(swept)
    s = ad.summary(swept)

    print("=" * 78)
    print('WHAT DOES "ALLOCATED" MEAN? Share of allocations that imputed a ZERO')
    print("=" * 78)
    print(f"\n{'source':<8} {'allocated':>11} {'to zero':>11} {'share zero':>11}")
    for _, r in zeros.iterrows():
        print(f"{r['source']:<8} {r['allocated']:>11,} {r['allocated_to_zero']:>11,} "
              f"{r['share_zero']:>10.1%}")
    print("\nFor the rare income types, 'allocated' overwhelmingly means the Bureau")
    print("decided you have NONE of this -- not that it estimated an amount.")

    print("\n" + "=" * 78)
    print("ALLOCATION RATE (%) UNDER EVERY DEFENSIBLE DEFINITION")
    print("=" * 78 + "\n")
    print((rates * 100).round(2).to_string())

    print("\n\nRANK (1 = most allocated)\n")
    print(ranks.to_string())

    print("\n\nRANK VOLATILITY\n")
    print(f"{'source':<8} {'best':>5} {'worst':>6} {'swing':>6}   rate range")
    for _, r in vol.iterrows():
        print(f"{r['source']:<8} {r['best_rank']:>5} {r['worst_rank']:>6} "
              f"{r['rank_swing']:>6}   {r['rate_min']:6.2%} - {r['rate_max']:6.2%}"
              f"  ({r['rate_fold']:5.1f}x)")

    print("\n\nDO THE DEFINITIONS AGREE ON THE ORDERING?\n")
    comparable = agr[agr["kendall_tau"].notna()]
    print(f"  comparable pairs        : {s['n_pairs_comparable']} of {s['n_pairs']}")
    if s["n_pairs_degenerate"]:
        print(f"  degenerate (all tied)   : {s['n_pairs_degenerate']}")
    print(f"  pairs that REVERSE order: {s['n_pairs_reversed']}")
    print(f"  mean Kendall tau        : {s['mean_tau']:+.2f}")
    print(f"  worst pair              : tau={s['min_tau']:+.2f}")
    if len(comparable):
        w = comparable.iloc[0]
        print(f"                            {w['def_a']}  vs  {w['def_b']}")

    print(f"\n  Largest rank swing across definitions: {s['max_rank_swing']} "
          f"(of {s['n_sources']} sources)")
    if s["max_rank_swing"] >= s["n_sources"] - 1:
        print("  -> at least one source can be ranked ANYWHERE. The ordering is a")
        print("     property of the definition, not of the data.")

    write_report(Path(args.out), df, zeros, rates, ranks, vol, agr, s)
    print(f"\nWrote {Path(args.out).relative_to(REPO_ROOT)}")


def write_report(out: Path, df, zeros, rates, ranks, vol, agr, s) -> None:
    L = [
        "# Is \"allocation rate\" a well-defined quantity?",
        "",
        f"Generated by `report_alloc_denominators.py` from {len(df):,} PUMS person",
        f"records, ACS 5-year vintage {common.ACS_VINTAGE}, New Jersey.",
        "",
        "An allocation rate is a ratio. The numerator is fixed -- the Bureau's own",
        "flag. The denominator is a **choice**. This sweeps every choice that can be",
        "defended and asks whether they agree.",
        "",
        "## Headline",
        "",
        f"- **{s['n_definitions']} defensible definitions**, {s['n_sources']} income sources.",
        f"- Largest rank swing: **{s['max_rank_swing']}** of {s['n_sources']} places.",
        f"- **{s['n_pairs_reversed']} of {s['n_pairs_comparable']}** definition pairs put the",
        f"  sources in *reversed* order (negative Kendall tau).",
        f"- Mean tau across comparable pairs: **{s['mean_tau']:+.2f}**.",
        "",
        "A single \"X% of income was allocated\" is therefore not a property of the",
        "data. It is a property of the definition, and the definition is usually",
        "left unstated.",
        "",
        "## What \"allocated\" actually means",
        "",
        "Share of allocations that imputed a **zero** rather than an amount:",
        "",
        "| Source | Allocated | To zero | Share zero |",
        "|---|---|---|---|",
    ]
    for _, r in zeros.iterrows():
        L.append(f"| `{r['source']}` | {r['allocated']:,} | "
                 f"{r['allocated_to_zero']:,} | {r['share_zero']:.1%} |")
    L += [
        "",
        "For rare income types, \"allocated\" almost always means *the Bureau decided",
        "you have none of this* -- a different act from estimating how much you earned.",
        "This is why the denominators diverge so hard.",
        "",
        "## The four denominators, and what is wrong with each",
        "",
    ]
    for k, v in ad.DENOMINATOR_NOTES.items():
        L.append(f"- **{k}** — {v}")
    L += ["", "Two scopes, orthogonal:", ""]
    for k, v in ad.SCOPE_NOTES.items():
        L.append(f"- **{k}** — {v}")
    L += [
        "",
        "## Rates (%)",
        "",
        "```",
        (rates * 100).round(2).to_string(),
        "```",
        "",
        "## Ranks (1 = most allocated)",
        "",
        "```",
        ranks.to_string(),
        "```",
        "",
        "## Volatility",
        "",
        "| Source | Best rank | Worst rank | Swing | Rate min | Rate max | Fold |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in vol.iterrows():
        L.append(f"| `{r['source']}` | {r['best_rank']} | {r['worst_rank']} | "
                 f"**{r['rank_swing']}** | {r['rate_min']:.2%} | {r['rate_max']:.2%} | "
                 f"{r['rate_fold']:.1f}x |")
    L += [
        "",
        "## Pairwise agreement",
        "",
        "| Definition A | Definition B | Kendall tau |",
        "|---|---|---|",
    ]
    for _, r in agr.iterrows():
        tau = "n/a (tied)" if pd.isna(r["kendall_tau"]) else f"{r['kendall_tau']:+.2f}"
        L.append(f"| `{r['def_a']}` | `{r['def_b']}` | {tau} |")
    L += [
        "",
        "## Reading this",
        "",
        "There is no correct denominator. Each measures a different thing:",
        "",
        "- D1/D2 answer *how often is this question imputed*, which confounds",
        "  imputation propensity with how many people have that income at all.",
        "- D3 answers *when someone has this income, how often was the amount",
        "  guessed* -- but discards the majority of allocations for rare types.",
        "- D4 is internally coherent but, for rare types, becomes *how often did",
        "  the Bureau decide you do not have this*.",
        "",
        "The practical consequence: any downstream quantity built on \"the allocation",
        "rate\" silently inherits one of these, and swapping definitions can reverse",
        "the conclusion. State the definition, or report the sweep.",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
