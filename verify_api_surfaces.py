"""Verify every API surface the financial EDA depends on. Stage 3 gate.

What it does
------------
Hits the live Census metadata endpoints and confirms -- does not assume --
every table ID, variable name, bracket bound, geography level, and query
parameter the proposal relies on. Writes the confirmed surface to
docs/api-surface-verified.md. Nothing downstream may use a name this
script did not confirm.

Four checks:
  1. ACS core tables      B19013, B19001, B17001, C17002, B01003
  2. B19001 bracket set   count and dollar bounds, discovered not assumed
  3. B99 income alloc     discovered by concept filter, geography probed
  4. SAIPE                variable names, geography, and time= parameter

Anything that fails is printed as MISMATCH and written to the report.
A plausible-looking substitute is never invented.

What it needs
-------------
- Internet access.
- CENSUS_API_KEY -- set API_KEY below, or leave it blank to read the
  repo-root .env. Metadata reads work without a key; the live geography
  probes need one.
- requests. Already in requirements.txt.

What it produces
----------------
- docs/api-surface-verified.md

Run from the repo root:
    python verify_api_surfaces.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Paste your key here, or leave "" to read CENSUS_API_KEY from .env
# ---------------------------------------------------------------------------
API_KEY = ""

DATASET = "acs/acs5"
PUMS = "acs/acs5/pums"
DEFAULT_VINTAGE = 2024  # repo convention; proposal drafted against 2023
STATE_NJ = "34"
PROBE_COUNTY = "021"    # Mercer -- the county pull_acs_alloc_nj.py already samples

# Set by main() from --vintage. Everything downstream reads these.
VINTAGE = DEFAULT_VINTAGE
BASE = ""
PUMS_BASE = ""
SAIPE = "https://api.census.gov/data/timeseries/poverty/saipe"
SAIPE_YEARS = range(2019, 2025)

REPO_ROOT = Path(__file__).resolve().parent
OUT_PATH = REPO_ROOT / "docs" / "api-surface-verified.md"

# Track C source split. Confirmed to live ONLY in PUMS -- the B99 detailed
# tables split by universe, not by income source. PUMA is the geography
# floor, so these cannot be joined to a tract CV.
PUMS_ALLOC_FLAGS = ["FWAGP", "FSEMP", "FINTP", "FSSP", "FRETP", "FPAP", "FHINCP"]

CORE_TABLES = ["B19013", "B19001", "B17001", "C17002", "B01003"]

INCOME_WORDS = ("INCOME", "EARNINGS", "WAGE", "INTEREST",
                "SOCIAL SECURITY", "RETIREMENT", "PUBLIC ASSISTANCE")

SAIPE_GUESSES = ["SAEMHI_PT", "SAEMHI_LB90", "SAEMHI_UB90",
                 "SAEPOVRTALL_PT", "SAEPOVRTALL_LB90", "SAEPOVRTALL_UB90"]

PROBE_LEVELS = {
    "county":      "&for=county:*&in=state:%s" % STATE_NJ,
    "tract":       "&for=tract:*&in=state:%s%%20county:%s" % (STATE_NJ, PROBE_COUNTY),
    "block group": "&for=block%%20group:*&in=state:%s%%20county:%s" % (STATE_NJ, PROBE_COUNTY),
}
PUMS_PROBE = "&for=public%%20use%%20microdata%%20area:*&in=state:%s" % STATE_NJ

TIMEOUT = 120

# A real table cell looks like B19001_007E. The group document ALSO carries
# NAME and GEO_ID, and NAME ends in "E" -- counting it inflates every cell
# count by one. GEO_ID is worse: its "concept" is every concept in the
# dataset concatenated, so reading the concept off the first variable in
# the dict returns garbage. Match cells explicitly.
CELL_RE = re.compile(r"^[A-Z0-9]+_\d{3}[EM]$")

mismatches: list[str] = []
notes: list[str] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_key() -> str:
    if API_KEY:
        return API_KEY
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("CENSUS_API_KEY"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and val != "paste_your_key_here":
                    return val
    return os.getenv("CENSUS_API_KEY", "")


def get(url: str):
    """GET a URL, return (status, parsed-json-or-None, raw-text)."""
    req = urllib.request.Request(url, headers={"User-Agent": "census-uncertainty-analysis"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw), raw
            except ValueError:
                return resp.status, None, raw
    except urllib.error.HTTPError as exc:
        return exc.code, None, exc.read().decode("utf-8", errors="replace")[:200]
    except Exception as exc:  # network, DNS, timeout
        return 0, None, str(exc)[:200]


def flag(msg: str) -> None:
    mismatches.append(msg)
    print("  MISMATCH: " + msg)


def note(msg: str) -> None:
    notes.append(msg)
    print("  NOTE: " + msg)


def parse_bounds(label: str):
    """Pull dollar bounds out of a B19001 bracket label."""
    nums = [int(n.replace(",", "")) for n in re.findall(r"\$([\d,]+)", label)]
    up = label.upper()
    if "LESS THAN" in up and nums:
        return 0, nums[0] - 1
    if ("OR MORE" in up or "AND OVER" in up) and nums:
        return nums[0], None          # open-ended
    if len(nums) >= 2:
        return nums[0], nums[1]
    return None, None


# ---------------------------------------------------------------------------
# 1 + 2. ACS core tables and the B19001 bracket set
# ---------------------------------------------------------------------------

def verify_acs_tables() -> dict:
    print("\n=== 1. ACS core tables (%s %d) ===" % (DATASET, VINTAGE))
    out = {}
    for table in CORE_TABLES:
        status, data, raw = get("%s/groups/%s.json" % (BASE, table))
        if status != 200 or not data:
            flag("%s group endpoint returned %s -- table may not exist at vintage %d"
                 % (table, status, VINTAGE))
            continue
        variables = data.get("variables", {})
        est = {k: v.get("label", "") for k, v in variables.items()
               if CELL_RE.match(k) and k.endswith("E")}
        moe = {k for k in variables if CELL_RE.match(k) and k.endswith("M")}
        skipped = sorted(k for k in variables
                         if not CELL_RE.match(k) and not k.endswith(("EA", "MA")))

        # Read concept/universe off a REAL cell, never off NAME or GEO_ID.
        concept = universe = ""
        for k in sorted(est):
            concept = concept or variables[k].get("concept", "")
            universe = universe or variables[k].get("universe", "") or ""
            if concept and universe:
                break
        universe = universe or data.get("universe", "") or ""

        out[table] = {"concept": concept, "universe": universe,
                      "estimates": dict(sorted(est.items())), "moe": sorted(moe),
                      "skipped": skipped}
        print("  %-8s %2d estimate cells, %2d MOE cells  %s"
              % (table, len(est), len(moe), concept[:58]))
        if skipped:
            print("           (non-cell keys ignored: %s)" % ", ".join(skipped))
        if not moe and table != "B19013":
            note("%s publishes no MOE cells" % table)

    # --- B19001 brackets, counted from the API, never assumed ------------
    print("\n=== 2. B19001 bracket set ===")
    b19001 = out.get("B19001", {}).get("estimates", {})
    if not b19001:
        flag("B19001 returned no estimate cells -- cannot count brackets")
        return out
    cells = sorted(b19001, key=lambda k: int(k.split("_")[1][:3]))
    brackets = []
    for c in cells:
        label = b19001[c]
        if label.rstrip().endswith("Total:") or label.rstrip().endswith("Total"):
            continue                                    # universe row, not a bracket
        lo, hi = parse_bounds(label)
        brackets.append({"cell": c, "label": label, "lo": lo, "hi": hi})
    out["B19001"]["brackets"] = brackets
    print("  %d cells total -> %d BRACKETS (the Total row is not a bracket)"
          % (len(cells), len(brackets)))
    if len(brackets) != 17:
        note("proposal says '17 bracket counts'; live API gives %d brackets "
             "plus 1 universe total" % len(brackets))
    widths = []
    for b in brackets:
        if b["lo"] is None:
            print("    %-14s %-42s UNPARSED" % (b["cell"], b["label"][-42:]))
            continue
        if b["hi"] is None:
            print("    %-14s %-42s $%s+ OPEN-ENDED" % (b["cell"], b["label"][-42:], f"{b['lo']:,}"))
            note("%s is open-ended -- flag, never impute a top bound" % b["cell"])
            continue
        w = b["hi"] - b["lo"] + 1
        widths.append(w)
        print("    %-14s %-42s $%9s - $%9s  width $%s"
              % (b["cell"], b["label"][-42:], f"{b['lo']:,}", f"{b['hi']:,}", f"{w:,}"))
    if widths and len(set(widths)) > 1:
        note("bracket widths are IRREGULAR ($%s to $%s) -- bracket_width is a real "
             "per-tract driver for Track A, not a constant"
             % (f"{min(widths):,}", f"{max(widths):,}"))
    return out


# ---------------------------------------------------------------------------
# 3. B99 income allocation tables
# ---------------------------------------------------------------------------

def probe(cell: str, level: str, key: str):
    """Live query: is this cell actually served at this geography level?"""
    url = "%s?get=%s%s&key=%s" % (BASE, cell, PROBE_LEVELS[level], key)
    status, data, raw = get(url)
    if status == 200 and isinstance(data, list):
        return (len(data) - 1) > 0, "200, %d rows" % (len(data) - 1)
    return False, "%s: %s" % (status, raw.strip().replace("\n", " ")[:100])


def discover_b99(key: str) -> list[dict]:
    print("\n=== 3. B99 income allocation tables ===")
    status, data, _ = get("%s/groups.json" % BASE)
    if status != 200 or not data:
        flag("groups.json returned %s -- cannot discover B99 tables" % status)
        return []
    groups = data.get("groups", [])
    print("  %d tables in the dataset" % len(groups))

    found = []
    for g in groups:
        name = g.get("name", "")
        concept = g.get("description", "") or ""
        if name.startswith("B99") and any(w in concept.upper() for w in INCOME_WORDS):
            found.append({"table": name, "concept": concept})
    found.sort(key=lambda h: h["table"])
    print("  %d B99 tables match the income filter:" % len(found))
    for f in found:
        print("    %-10s %s" % (f["table"], f["concept"]))
    if not found:
        flag("no B99 table matched the income filter -- widen INCOME_WORDS or "
             "check the concept strings before trusting this")
        return found

    print("\n  Cell lists:")
    for f in found:
        status, data, _ = get("%s/groups/%s.json" % (BASE, f["table"]))
        variables = (data or {}).get("variables", {})
        f["cells"] = sorted(k for k in variables
                            if CELL_RE.match(k) and k.endswith("E"))
        f["has_moe"] = any(CELL_RE.match(k) and k.endswith("M") for k in variables)
        print("    %-10s %2d cells, MOE published: %s"
              % (f["table"], len(f["cells"]), f["has_moe"]))
        if f["has_moe"]:
            note("%s DOES publish MOE cells -- contradicts the repo's "
                 "'allocation tables have no _M' assumption" % f["table"])

    if not key:
        note("no API key -- geography levels NOT probed. Set API_KEY and rerun.")
        return found

    print("\n  Geography probe (NJ; Mercer County for sub-county):")
    for f in found:
        f["geography"] = {}
        if not f["cells"]:
            continue
        for level in PROBE_LEVELS:
            ok, why = probe(f["cells"][0], level, key)
            f["geography"][level] = (ok, why)
            print("    %-10s %-12s %-10s %s"
                  % (f["table"], level, "PUBLISHED" if ok else "no", why))
            time.sleep(0.4)
        geo = f["geography"]
        if geo.get("county", (False,))[0] and not geo.get("tract", (False,))[0]:
            note("%s is COUNTY-ONLY -- a quality metric published coarser than the "
                 "estimates it qualifies. Q1 lifecycle-map finding." % f["table"])
    return found


# ---------------------------------------------------------------------------
# 4. SAIPE
# ---------------------------------------------------------------------------

def verify_saipe(key: str) -> dict:
    print("\n=== 4. SAIPE ===")
    out = {}
    status, data, _ = get("%s/variables.json" % SAIPE)
    if status != 200 or not data:
        flag("SAIPE variables.json returned %s" % status)
        return out
    variables = data.get("variables", data)
    out["variables"] = {k: v.get("label", "") for k, v in variables.items()}
    print("  %d variables published" % len(variables))

    print("\n  Proposal's guessed names:")
    for name in SAIPE_GUESSES:
        if name in variables:
            print("    CONFIRMED  %-18s %s" % (name, variables[name].get("label", "")))
        else:
            flag("SAIPE variable %s DOES NOT EXIST -- do not use it" % name)

    extras = [k for k in variables
              if k.endswith("_MOE") and ("MHI" in k or "POVRTALL" in k)]
    if extras:
        print("\n  Also published, and the proposal does not use them:")
        for k in sorted(extras):
            print("    %-18s %s" % (k, variables[k].get("label", "")))
        note("SAIPE publishes %s directly -- pull alongside the derived "
             "(UB90-LB90)/2 half-width. Agreement validates the derivation; "
             "disagreement is itself the Track B finding." % ", ".join(sorted(extras)))

    # --- time parameter --------------------------------------------------
    if "time" in variables:
        print("\n  time: %s  -> filter with &time=%d" % (variables["time"].get("label", ""), VINTAGE))
    else:
        flag("no 'time' clause in SAIPE variables -- confirm this is a timeseries path")
    if "YEAR" in variables:
        note("YEAR is a data variable -- request it in get= so rows are "
             "self-labelling, rather than trusting the loop variable")

    # --- geography -------------------------------------------------------
    status, geo, _ = get("%s/geography.json" % SAIPE)
    levels = (geo or {}).get("fips", [])
    out["geography"] = levels
    print("\n  Geography levels:")
    for lv in levels:
        req = lv.get("requires", [])
        print("    %-10s geoLevelDisplay %-5s requires %s"
              % (lv.get("name", ""), lv.get("geoLevelDisplay", ""), req or "-"))
        if lv.get("name") == "county" and req:
            note("SAIPE county REQUIRES %s -- the proposal's bare 'for=county:*' "
                 "national call is not guaranteed to serve" % req)

    # --- live call -------------------------------------------------------
    if key:
        print("\n  Live call test:")
        for label, qs in [
            ("for=county:* (bare)", "&for=county:*"),
            ("for=county:*&in=state:*", "&for=county:*&in=state:*"),
        ]:
            url = "%s?get=NAME,SAEMHI_PT&time=%d%s&key=%s" % (SAIPE, VINTAGE, qs, key)
            status, data, raw = get(url)
            ok = status == 200 and isinstance(data, list)
            print("    %-26s %s  %s" % (
                label, "OK" if ok else "FAILED",
                "%d rows" % (len(data) - 1) if ok else "%s %s" % (status, raw[:80])))
            out.setdefault("live", {})[label] = ok
            time.sleep(0.4)

        print("\n  Year availability (Track B window):")
        years = []
        for yr in SAIPE_YEARS:
            url = "%s?get=NAME,SAEMHI_PT&time=%d&for=county:*&key=%s" % (SAIPE, yr, key)
            status, data, raw = get(url)
            ok = status == 200 and isinstance(data, list)
            rows = (len(data) - 1) if ok else 0
            print("    time=%d  %s  %s" % (yr, "OK " if ok else "NO ",
                                           "%d rows" % rows if ok else raw[:60]))
            if ok:
                years.append(yr)
            time.sleep(0.4)
        out["years"] = years
        if years:
            print("    -> usable window: %d-%d" % (min(years), max(years)))
        if 2024 in years:
            note("SAIPE has 2024 -- Track B can run 2019-2024 rather than "
                 "stopping at 2023 as the proposal scoped it")
    return out


# ---------------------------------------------------------------------------
# 5. PUMS allocation flags -- Track C source split
# ---------------------------------------------------------------------------

def verify_pums(key: str) -> dict:
    """The six income-source allocation flags, and what geography they cost.

    The B99 detailed tables split allocation by UNIVERSE (individual /
    household / family / nonfamily / earnings), not by income source. The
    source split the proposal asks for exists only here, and only down to
    PUMA -- so it cannot be joined to a tract CV and 05's controlling code
    path does not lift across.
    """
    print("\n=== 5. PUMS allocation flags (Track C source split) ===")
    out = {"flags": {}}
    for name in PUMS_ALLOC_FLAGS:
        status, data, _ = get("%s/variables/%s.json" % (PUMS_BASE, name))
        if status != 200 or not data:
            flag("PUMS %s returned %s at vintage %d -- do not use it"
                 % (name, status, VINTAGE))
            continue
        label = data.get("label", "")
        values = (data.get("values", {}) or {}).get("item", {})
        weight = data.get("suggested-weight", "")
        out["flags"][name] = {"label": label, "values": values, "weight": weight}
        print("  CONFIRMED  %-8s %-52s weight %s" % (name, label[:52], weight))
        if "-1" in values:
            note("PUMS %s carries %s -- do not treat as zero"
                 % (name, {"-1": values["-1"]}))

    status, geo, _ = get("%s/geography.json" % PUMS_BASE)
    levels = (geo or {}).get("fips", [])
    out["geography"] = levels
    print("\n  Geography levels:")
    for lv in levels:
        print("    %-28s geoLevelDisplay %-5s requires %s"
              % (lv.get("name", ""), lv.get("geoLevelDisplay", ""),
                 lv.get("requires", []) or "-"))
    names = [lv.get("name", "") for lv in levels]
    if "tract" not in names:
        note("PUMS has NO tract level (floor is %s) -- Track C source split "
             "cannot be correlated against a tract CV, and 05's geography-size "
             "controlling code does not lift across this boundary"
             % ("PUMA" if any("microdata" in n for n in names) else names[-1:]))

    if key and out["flags"]:
        first = next(iter(out["flags"]))
        url = "%s?get=%s,PWGTP%s&key=%s" % (PUMS_BASE, first, PUMS_PROBE, key)
        status, data, raw = get(url)
        ok = status == 200 and isinstance(data, list)
        rows = (len(data) - 1) if ok else 0
        print("\n  Live PUMA probe (NJ, %s): %s  %s"
              % (first, "OK" if ok else "FAILED",
                 "%d records" % rows if ok else "%s %s" % (status, raw[:80])))
        out["live_rows"] = rows
        if ok:
            note("NJ PUMS returns %d person records at PUMA level -- microdata, "
                 "so uncertainty comes from replicate weights, not an MOE column"
                 % rows)
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(acs: dict, b99: list[dict], saipe: dict, pums: dict) -> None:
    L = ["# Verified API surface -- financial EDA",
         "",
         "Generated by `verify_api_surfaces.py`. Every name below came from a live",
         "metadata endpoint. Nothing downstream may use a name absent from this file.",
         "",
         "**Dataset:** `%s` vintage **%d**" % (DATASET, VINTAGE),
         ""]

    if mismatches:
        L += ["## MISMATCHES against the proposal", "",
              "The most useful section in this file. Resolve before writing pulls.", ""]
        L += ["- %s" % m for m in mismatches] + [""]
    else:
        L += ["## MISMATCHES", "", "None. Every guessed name resolved.", ""]

    if notes:
        L += ["## Notes", ""] + ["- %s" % n for n in notes] + [""]

    L += ["## ACS core tables", ""]
    for table, meta in acs.items():
        L += ["### %s" % table, "",
              "- Concept: `%s`" % meta.get("concept", ""),
              "- Universe: `%s`" % meta.get("universe", ""),
              "- %d estimate cells, %d MOE cells"
              % (len(meta.get("estimates", {})), len(meta.get("moe", []))),
              ""]
        if table == "B19001" and meta.get("brackets"):
            br = meta["brackets"]
            L += ["**%d brackets**, plus one universe total row." % len(br), "",
                  "| Cell | Label | Lower | Upper | Width |", "|---|---|---|---|---|"]
            for b in br:
                lo = "%s" % (f"{b['lo']:,}" if b["lo"] is not None else "?")
                hi = "OPEN" if b["hi"] is None else f"{b['hi']:,}"
                w = "open" if b["hi"] is None or b["lo"] is None else f"{b['hi'] - b['lo'] + 1:,}"
                L.append("| `%s` | %s | %s | %s | %s |" % (b["cell"], b["label"], lo, hi, w))
            L.append("")
        else:
            L += ["| Cell | Label |", "|---|---|"]
            for c, lab in list(meta.get("estimates", {}).items())[:20]:
                L.append("| `%s` | %s |" % (c, lab))
            if len(meta.get("estimates", {})) > 20:
                L.append("| ... | %d more |" % (len(meta["estimates"]) - 20))
            L.append("")

    L += ["## B99 income allocation tables", "",
          "%d matched the concept filter." % len(b99), ""]
    if b99:
        probed = any("geography" in f for f in b99)
        if probed:
            L += ["| Table | Concept | Cells | county | tract | block group |",
                  "|---|---|---|---|---|---|"]
            for f in b99:
                g = f.get("geography", {})
                cols = " | ".join("yes" if g.get(lv, (False,))[0] else "no"
                                  for lv in ("county", "tract", "block group"))
                L.append("| `%s` | %s | %d | %s |"
                         % (f["table"], f["concept"], len(f.get("cells", [])), cols))
        else:
            L += ["| Table | Concept | Cells |", "|---|---|---|"]
            for f in b99:
                L.append("| `%s` | %s | %d |"
                         % (f["table"], f["concept"], len(f.get("cells", []))))
        L += ["", "### Cells", ""]
        for f in b99:
            L.append("- `%s`: %s" % (f["table"],
                     ", ".join("`%s`" % c for c in f.get("cells", [])) or "none"))
        L.append("")

    L += ["## SAIPE", "", "Endpoint: `%s`" % SAIPE, ""]
    if saipe.get("variables"):
        L += ["| Variable | Label |", "|---|---|"]
        for k in SAIPE_GUESSES + sorted(x for x in saipe["variables"]
                                        if x.endswith("_MOE")
                                        and ("MHI" in x or "POVRTALL" in x)):
            if k in saipe["variables"]:
                L.append("| `%s` | %s |" % (k, saipe["variables"][k]))
        L.append("")
    if saipe.get("geography"):
        L += ["### Geography", "", "| Level | Display | Requires |", "|---|---|---|"]
        for lv in saipe["geography"]:
            L.append("| `%s` | %s | %s |" % (lv.get("name", ""),
                     lv.get("geoLevelDisplay", ""), lv.get("requires", []) or "-"))
        L.append("")
    if saipe.get("live"):
        L += ["### Live call test", ""]
        for k, v in saipe["live"].items():
            L.append("- `%s`: %s" % (k, "OK" if v else "FAILED"))
        L.append("")
    if saipe.get("years"):
        yrs = saipe["years"]
        L += ["### Years served", "",
              "`%s` -- usable window **%d-%d**."
              % (", ".join(str(y) for y in yrs), min(yrs), max(yrs)), ""]

    L += ["## PUMS allocation flags -- Track C source split", "",
          "The B99 detailed tables split allocation by **universe**, not by income",
          "source. The source split exists only here.", ""]
    if pums.get("flags"):
        L += ["| Variable | Label | Weight | Values |", "|---|---|---|---|"]
        for k, v in pums["flags"].items():
            vals = ", ".join("`%s`=%s" % (a, b) for a, b in sorted(v["values"].items()))
            L.append("| `%s` | %s | `%s` | %s |" % (k, v["label"], v["weight"], vals))
        L.append("")
    if pums.get("geography"):
        L += ["### Geography -- PUMA is the floor, there is no tract", "",
              "| Level | Display | Requires |", "|---|---|---|"]
        for lv in pums["geography"]:
            L.append("| `%s` | %s | %s |" % (lv.get("name", ""),
                     lv.get("geoLevelDisplay", ""), lv.get("requires", []) or "-"))
        L.append("")
    if pums.get("live_rows"):
        L += ["NJ live probe returned **%d person records** at PUMA level."
              % pums["live_rows"], ""]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------

def main() -> None:
    global VINTAGE, BASE, PUMS_BASE, OUT_PATH

    parser = argparse.ArgumentParser(
        description="Verify every API surface the financial EDA depends on.")
    parser.add_argument("--vintage", type=int, default=DEFAULT_VINTAGE,
                        help="ACS 5-year vintage (default %d)" % DEFAULT_VINTAGE)
    parser.add_argument("--out", default=None,
                        help="output path (default docs/api-surface-verified.md)")
    args = parser.parse_args()

    VINTAGE = args.vintage
    BASE = "https://api.census.gov/data/%d/%s" % (VINTAGE, DATASET)
    PUMS_BASE = "https://api.census.gov/data/%d/%s" % (VINTAGE, PUMS)
    if args.out:
        OUT_PATH = Path(args.out)

    t0 = time.perf_counter()
    key = load_key()
    print("Verifying API surfaces -- %s vintage %d" % (DATASET, VINTAGE))
    print("API key: %s" % ("loaded" if key else "NONE (metadata only, no probes)"))

    acs = verify_acs_tables()
    b99 = discover_b99(key)
    saipe = verify_saipe(key)
    pums = verify_pums(key)
    write_report(acs, b99, saipe, pums)

    print("\n" + "=" * 68)
    print("Wrote %s" % OUT_PATH.relative_to(REPO_ROOT))
    print("Done in %.1fs." % (time.perf_counter() - t0))
    if mismatches:
        print("\n%d MISMATCH(ES) -- resolve before writing any pull script:"
              % len(mismatches))
        for m in mismatches:
            print("  - %s" % m)
    else:
        print("\nNo mismatches. Every guessed name resolved.")
    if notes:
        print("\n%d note(s):" % len(notes))
        for n in notes:
            print("  - %s" % n)


if __name__ == "__main__":
    main()
