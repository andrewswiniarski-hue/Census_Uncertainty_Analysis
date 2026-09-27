"""Who gets measured and who gets inferred? Person-level profile + PUMA map.

What it does
------------
Two clearly separated halves, because they support different claims:

  PERSON LEVEL (defensible for demographic statements)
      Characteristic and allocation flag sit on the same PUMS record, so
      "people aged 15-24 are more often wholly substituted" is a statement
      about people.

  AREA LEVEL (defensible for a map, not for demographics)
      The same outcomes aggregated to PUMA. Useful for showing where in New
      Jersey inferred data concentrates. An area pattern here does NOT
      license a statement about the people who live there -- that is the
      ecological fallacy, and it is called out in the output.

Outcomes are denominator-free per-person properties, deliberately:
`any_allocated`, `n_items_allocated` (0-6), `whole_record`. See
analysis/alloc_denominator.py for why a *rate* would not be.

What it needs
-------------
- data/raw/pums_2024_nj_alloc_flags.parquet, including AGEP, SEX, SCHL
  (regenerate with: python ingestion/pull_pums_alloc_flags.py)
- pandas, numpy, pyarrow. No network, no API key.

What it produces
----------------
- docs/allocation-profile-nj.md
- data/processed/alloc_profile_person.csv
- data/processed/alloc_profile_puma.csv

Run from the repo root:
    python report_alloc_profile.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import alloc_profile as ap  # noqa: E402
from analysis import common  # noqa: E402
from analysis import replicate as rep  # noqa: E402

DEFAULT_PARQUET = (REPO_ROOT / "data" / "raw"
                   / f"pums_{common.ACS_VINTAGE}_nj_alloc_flags.parquet")
OUT_MD = REPO_ROOT / "docs" / "allocation-profile-nj.md"
PROCESSED = REPO_ROOT / "data" / "processed"

METRICS = [
    ("share_whole_record", "wholly substituted", "{:.1%}"),
    ("share_any_allocated", "any item filled in", "{:.1%}"),
    ("mean_items_allocated", "mean items filled (0-6)", "{:.2f}"),
]


def load(path: Path) -> pd.DataFrame:
    if not path.exists():
        sys.exit(f"{path} not found -- run: python ingestion/pull_pums_alloc_flags.py")
    df = pd.read_parquet(path)
    missing = [c for c in ("AGEP", "SEX", "SCHL") if c not in df.columns]
    if missing:
        print(f"  NOTE: {missing} absent from this pull -- those breakdowns are")
        print(f"        skipped. Re-run ingestion/pull_pums_alloc_flags.py to add them.\n")
    return df


def puma_column(df: pd.DataFrame) -> str:
    for c in df.columns:
        if "microdata" in c.lower() or c.lower() == "puma":
            return c
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Person-level and PUMA-level allocation profile.")
    parser.add_argument("--parquet", default=str(DEFAULT_PARQUET))
    parser.add_argument("--min-records", type=int, default=100,
                        help="suppress groups thinner than this (default 100)")
    args = parser.parse_args()

    raw = load(Path(args.parquet))
    prep = ap.prepare(raw)
    dropped = len(raw) - len(prep)
    print(f"Records {len(raw):,} -> income universe {len(prep):,} "
          f"(dropped {dropped:,} under {ap.INCOME_UNIVERSE_AGE})")
    print("Under-15s carry flag 0 by construction; including them would")
    print("manufacture a finding that young people have less inferred data.\n")

    # ---------------- person level ----------------
    print("=" * 78)
    print("PERSON LEVEL -- supports statements about people")
    print("=" * 78)
    prof = ap.profile_all(prep, min_records=args.min_records)
    if prof.empty:
        sys.exit("No characteristic had enough records to report.")

    for char, g in prof.groupby("characteristic", sort=False, observed=True):
        print(f"\n  by {char}")
        print(f"  {'level':<26} {'records':>9} {'weighted':>12} "
              f"{'whole-rec':>10} {'any':>8} {'items':>7}")
        for _, r in g.iterrows():
            print(f"  {str(r['level']):<26} {r['n_records']:>9,} "
                  f"{r['weighted_persons']:>12,.0f} {r['share_whole_record']:>10.1%} "
                  f"{r['share_any_allocated']:>8.1%} {r['mean_items_allocated']:>7.2f}")

    print("\n  SPREAD (fold = max/min across levels)\n")
    print(f"  {'characteristic':<16} {'metric':<22} {'low':>22} {'high':>22} {'fold':>7}")
    spreads = []
    for metric, _, fmt in METRICS:
        sp = ap.spread(prof, metric)
        spreads.append(sp)
        for _, r in sp.iterrows():
            print(f"  {r['characteristic']:<16} {metric:<22} "
                  f"{fmt.format(r['min']) + ' (' + str(r['lowest_level']) + ')':>22} "
                  f"{fmt.format(r['max']) + ' (' + str(r['highest_level']) + ')':>22} "
                  f"{r['fold']:>6.2f}x")

    # ---------------- area level ----------------
    puma = puma_column(prep)
    puma_prof = pd.DataFrame()
    if puma:
        print("\n" + "=" * 78)
        print("AREA LEVEL (PUMA) -- supports a map, NOT a demographic claim")
        print("=" * 78)
        puma_prof = ap.profile(prep, puma, min_records=args.min_records)
        if not puma_prof.empty:
            s = puma_prof["share_whole_record"]
            print(f"\n  {len(puma_prof)} PUMAs reported")
            print(f"  wholly substituted: min {s.min():.1%}  median {s.median():.1%}  "
                  f"max {s.max():.1%}   fold {s.max()/s.min():.2f}x"
                  if s.min() > 0 else
                  f"  wholly substituted: min {s.min():.1%}  median {s.median():.1%}  "
                  f"max {s.max():.1%}")
            top = puma_prof.nlargest(5, "share_whole_record")
            bot = puma_prof.nsmallest(5, "share_whole_record")
            print("\n  highest 5 PUMAs")
            for _, r in top.iterrows():
                print(f"    {r['level']}  {r['share_whole_record']:.1%}  "
                      f"({r['n_records']:,} records)")
            print("  lowest 5 PUMAs")
            for _, r in bot.iterrows():
                print(f"    {r['level']}  {r['share_whole_record']:.1%}  "
                      f"({r['n_records']:,} records)")
            print("\n  These are AREA rates. A PUMA being high does not mean any")
            print("  particular group within it is high -- that inference is the")
            print("  ecological fallacy. Use the person-level table for that.")

    # ---------------- significance ----------------
    sig = pd.DataFrame()
    if rep.has_replicates(prep):
        print("\n" + "=" * 78)
        print("MARGINS OF ERROR (80 replicate weights, 90% confidence)")
        print("=" * 78)
        num = prep["whole_record"]
        for char in ("age_band", "sex", "education"):
            if char not in prep.columns:
                continue
            m = rep.profile_with_moe(prep, char, num,
                                     min_records=args.min_records)
            if m.empty:
                continue
            print(f"\n  wholly substituted, by {char}")
            print(f"  {'level':<26} {'estimate':>9} {'+/- MOE':>9} "
                  f"{'90% interval':>22}")
            for _, r in m.iterrows():
                print(f"  {str(r['level']):<26} {r['estimate']:>8.2%} "
                      f"{r['moe']:>8.2%}  [{r['ci_low']:>7.2%}, {r['ci_high']:>7.2%}]")
            pw = rep.pairwise_significance(prep, char, num,
                                           levels=list(m["level"]))
            if not pw.empty:
                pw.insert(0, "metric", "share_whole_record")
                sig = pd.concat([sig, pw], ignore_index=True)
                n_sig = int(pw["significant"].sum())
                print(f"    {n_sig}/{len(pw)} pairwise differences clear zero "
                      f"at 90%")
                adj = m.sort_values("estimate", ascending=False)
                lv = list(adj["level"])
                nb = pw.set_index(["level_a", "level_b"])
                unclear = []
                for a, b in zip(lv, lv[1:]):
                    row = nb.loc[(a, b)] if (a, b) in nb.index else (
                        nb.loc[(b, a)] if (b, a) in nb.index else None)
                    if row is not None and not bool(row["significant"]):
                        unclear.append(f"{a} vs {b}")
                if unclear:
                    print(f"    adjacent levels NOT distinguishable: "
                          f"{'; '.join(unclear)}")
                else:
                    print(f"    every adjacent pair is distinguishable")
        print("\n  Multiple comparisons: with k levels there are k(k-1)/2 tests,")
        print("  so some clear 90% by chance. Read the pattern, not one row.")
        print("  Differences are formed INSIDE each replicate -- combining")
        print("  separate SEs would be wrong, these subgroups share a sample.")
    else:
        print("\n  No replicate weights in this pull -- every number above is a")
        print("  point estimate with no error bar. Re-run the pull with")
        print("  --replicates to find out which differences are real.")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    prof.to_csv(PROCESSED / "alloc_profile_person.csv", index=False, encoding="utf-8")
    if not sig.empty:
        sig.to_csv(PROCESSED / "alloc_significance.csv", index=False, encoding="utf-8")
    if not puma_prof.empty:
        puma_prof.to_csv(PROCESSED / "alloc_profile_puma.csv",
                         index=False, encoding="utf-8")

    write_report(prof, spreads, puma_prof, len(raw), len(prep))
    print(f"\nWrote {OUT_MD.relative_to(REPO_ROOT)}")
    print(f"      {(PROCESSED / 'alloc_profile_person.csv').relative_to(REPO_ROOT)}")
    if not puma_prof.empty:
        print(f"      {(PROCESSED / 'alloc_profile_puma.csv').relative_to(REPO_ROOT)}")


def write_report(prof, spreads, puma_prof, n_raw, n_universe) -> None:
    L = [
        "# Who gets measured, and who gets inferred? New Jersey",
        "",
        f"Generated by `report_alloc_profile.py`. ACS 5-year PUMS vintage "
        f"{common.ACS_VINTAGE}, New Jersey.",
        f"{n_raw:,} person records, {n_universe:,} in the income universe "
        f"(age {ap.INCOME_UNIVERSE_AGE}+).",
        "",
        "This describes the **measurement process** -- who the statistical system",
        "observes directly and who it describes by inference. It is not a statement",
        "about the people in any group.",
        "",
        "## Why there is no \"rate\" here",
        "",
        "`analysis/alloc_denominator.py` shows an allocation *rate* needs a",
        "denominator, that several are defensible, and that the choice can reverse",
        "conclusions. These outcomes avoid that entirely -- they are properties of a",
        "record, not ratios:",
        "",
        "- `any_allocated` — any of the six income items filled in",
        "- `n_items_allocated` — how many, 0 to 6",
        "- `whole_record` — all six, i.e. whole-person substitution",
        "",
        "## Universe guards",
        "",
        f"- Income questions are asked of people **{ap.INCOME_UNIVERSE_AGE} and over**. "
        f"Under-15s carry flag 0 by construction; including them would manufacture a "
        f"finding that young people have less inferred data.",
        f"- Educational attainment is reported for **{ap.EDUCATION_UNIVERSE_AGE}+** only. "
        f"SCHL for a teenager measures age, not attainment.",
        "",
        "## Person level",
        "",
        "Supports statements about people: characteristic and flag are on the same record.",
        "",
        "| Characteristic | Level | Records | Weighted | Wholly substituted | Any filled | Mean items |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in prof.iterrows():
        L.append(f"| {r['characteristic']} | {r['level']} | {r['n_records']:,} | "
                 f"{r['weighted_persons']:,.0f} | {r['share_whole_record']:.1%} | "
                 f"{r['share_any_allocated']:.1%} | {r['mean_items_allocated']:.2f} |")
    L += ["", "### Spread within each characteristic", "",
          "| Characteristic | Metric | Lowest | Highest | Fold |", "|---|---|---|---|---|"]
    for sp in spreads:
        for _, r in sp.iterrows():
            fmt = "{:.2f}" if r["metric"] == "mean_items_allocated" else "{:.1%}"
            L.append(f"| {r['characteristic']} | `{r['metric']}` | "
                     f"{fmt.format(r['min'])} ({r['lowest_level']}) | "
                     f"{fmt.format(r['max'])} ({r['highest_level']}) | "
                     f"**{r['fold']:.2f}x** |")
    if not puma_prof.empty:
        s = puma_prof["share_whole_record"]
        L += [
            "", "## Area level (PUMA)", "",
            "**Supports a map. Does not support a demographic claim.** A PUMA being",
            "high does not mean any particular group within it is high -- that is the",
            "ecological fallacy. Use the person-level table above for that.",
            "",
            f"{len(puma_prof)} PUMAs. Wholly substituted: min **{s.min():.1%}**, "
            f"median **{s.median():.1%}**, max **{s.max():.1%}**.",
            "",
            "| PUMA | Records | Weighted | Wholly substituted | Any filled | Mean items |",
            "|---|---|---|---|---|---|",
        ]
        for _, r in puma_prof.sort_values("share_whole_record",
                                          ascending=False).iterrows():
            L.append(f"| {r['level']} | {r['n_records']:,} | "
                     f"{r['weighted_persons']:,.0f} | {r['share_whole_record']:.1%} | "
                     f"{r['share_any_allocated']:.1%} | {r['mean_items_allocated']:.2f} |")
    L += [
        "", "## Caveats", "",
        "- **No error bars.** These are weighted point estimates. PUMS uncertainty",
        "  comes from replicate weights (`PWGTP1`-`PWGTP80`), which are not pulled.",
        "  Whether two levels differ *significantly* is currently unknown.",
        "- **PUMA is the geography floor.** There is no tract-level version of this",
        "  table, and the tract B99 tables cannot separate whole-record substitution",
        "  from item allocation.",
        "- **One state, one vintage.** Nothing here is established outside NJ.",
        "",
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
