#!/usr/bin/env python3
"""
product_scope.py - product-level scope tracker for the Census Uncertainty capstone.

What this tool does, and just as importantly what it refuses to do:

  1. TOTAL INVENTORY of Census products, crawled from the Census API catalog
     (api.census.gov/data.json), plus the non-API products we use (DAS
     demonstration files, TIGER boundaries).

  2. IT NEVER DECIDES ANYTHING ABOUT A PRODUCT. Every product is created as
     `cataloged` with an empty uncertainty description. Promoting a product
     (reviewed / candidate / focus / set-aside) and documenting what uncertainty
     it publishes are human decisions, made by editing product_review.json.
     There is deliberately no built-in table of "what uncertainty product X
     publishes": a catalog path identifies a PROGRAM, not a METHODOLOGY, and
     acs/acs5 vs acs/acs5/pums proves it - same prefix, published MOEs vs
     replicate weights you apply yourself.

  3. GROUPING IS FACTUAL, NOT EDITORIAL. Tabs come from the Bureau's own
     published flags (c_isAggregate / c_isMicrodata / c_isTimeseries); groups
     within a tab come from the catalog path. Nothing implies value or priority.

  4. TRACK WHERE WE ARE: repo evidence (via scope_evidence.py forensics)
     computes work depth per product - Identified/Pulled/Analyzed/Validated -
     always with receipts naming the file and cell or line it came from.

  5. INGEST TEAMMATES' WORK: findings are mined from WORKLOG.md verbatim. The
     text on a card is the sentence a teammate wrote; nothing is rephrased.

Usage:
    python tools/product_scope.py --repo .            # uses the cached crawl
    python tools/product_scope.py --repo . --online   # re-crawl the API catalog
Output: product_report.html (self-contained, no CDN, no storage APIs).
"""

import argparse, ast, json, re, subprocess, sys, datetime, urllib.request
from pathlib import Path

try:
    from scope_evidence import deep_scan, locate
    DEEP = True
except ImportError:
    DEEP = False

# ============================================================================
# GIT INFO - captured once per run, embedded into the report so contextual
# affordances (freshness pill, "regenerate to refresh" prompts, evidence
# permalinks, diff snapshots) all see the same commit state.
# ============================================================================

def _git(repo: Path, args):
    """Run a git command in `repo`. Returns stripped stdout, or "" on failure.
    Silent on error - the tool must never crash because git is missing."""
    try:
        r = subprocess.run(["git", "-C", str(repo)] + list(args),
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""

def git_info(repo: Path):
    """Snapshot of the repo state the report is being generated against.

    Fields:
      head_sha    -> current HEAD SHA (full)
      branch      -> current branch name (usually 'main'); "" in detached-HEAD
      remote_url  -> origin remote URL, e.g. https://github.com/foo/bar.git
      github_slug -> "owner/repo" if origin looks like GitHub, else ""
    """
    remote = _git(repo, ["remote", "get-url", "origin"])
    slug = ""
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", remote)
    if m: slug = f"{m.group(1)}/{m.group(2)}"
    return {
        "head_sha":    _git(repo, ["rev-parse", "HEAD"]),
        "branch":      _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]),
        "remote_url":  remote,
        "github_slug": slug,
        "repo_abs":    str(repo),   # used by receipt_url() for file:// fallback
    }

# ============================================================================
# CONFIG
# ============================================================================

EMDASH = "—"   # kept out of f-string expressions: illegal before Python 3.12 (PEP 701)

STATUS_LABELS = ["Not started", "Identified", "Pulled", "Analyzed", "Validated"]
GEO_LEVELS = ["state", "county", "tract", "block group", "block"]

STAGES = ["cataloged", "reviewed", "candidate", "focus", "set-aside"]
STAGE_LABELS = {"cataloged": "Cataloged", "reviewed": "Reviewed", "candidate": "Candidate",
                "focus": "FOCUS", "set-aside": "Set aside"}
STAGE_COLORS = {"cataloged": "#EDF0F7", "reviewed": "#CADCFC", "candidate": "#E9CD7A",
                "focus": "#1F2A5C", "set-aside": "#F6F7FA"}

# Human-declared role a product plays in the composite score. Set only by a
# person, in product_review.json, and never touched by the tool. When set, a
# free-text composite_role_note is REQUIRED - the two fields must land together.
COMPOSITE_ROLES = ["cv_source", "allocation_source", "privacy_noise",
                   "geometry", "benchmark", "unused"]
COMPOSITE_ROLE_LABELS = {
    "cv_source":         "CV source",
    "allocation_source": "Allocation source",
    "privacy_noise":     "Privacy noise",
    "geometry":          "Geometry",
    "benchmark":         "Benchmark",
    "unused":            "Unused",
}

def effective_role(r):
    """Role as it should be RENDERED. Enforces the note-required contract:
    a role without a matching note is treated as unset (see validate_review
    which logs the mismatch to stderr on load)."""
    if not r: return ""
    role = (r.get("composite_role") or "").strip()
    note = (r.get("composite_role_note") or "").strip()
    if role and not note: return ""
    return role

# Tabs, from the Bureau's own dataset flags. Not our categories.
KINDS = ["Aggregate tables", "Microdata", "Time series", "Unflagged"]
KIND_BLURB = {
    "Aggregate tables": "Published estimate tables. This is where published uncertainty lives: "
                        "margins of error, allocation tables, variance replicate tables.",
    "Microdata":        "Record-level files. Nothing is published per estimate - replicate weights "
                        "ship with the data and the analyst computes their own standard errors.",
    "Time series":      "Multi-year series reached through a single endpoint.",
    "Unflagged":        "The catalog record carries none of the Bureau's aggregate / microdata / "
                        "time-series flags.",
}

# Plain-English expansion of catalog path prefixes. Bureau program names, nothing more.
PROGRAM_NAMES = {
    "acs": "American Community Survey", "acs1": "American Community Survey (1-year)",
    "dec": "Decennial Census", "cps": "Current Population Survey",
    "sipp": "Survey of Income and Program Participation", "pep": "Population Estimates",
    "timeseries": "Time-series programs", "pdb": "Planning Database",
    "cre": "Community Resilience Estimates", "cbp": "County Business Patterns",
    "zbp": "ZIP Code Business Patterns", "ecn": "Economic Census",
    "nonemp": "Nonemployer Statistics", "popproj": "Population Projections",
    "sbo": "Survey of Business Owners", "ase": "Annual Survey of Entrepreneurs",
    "surname": "Frequently Occurring Surnames", "geo": "Geography / boundary files",
    "cfspum": "Commodity Flow Survey PUM", "ewks": "Economic Census (establishments)",
}

# Many single-segment paths are one program split across dozens of endpoints
# (ecncashadv, ecnseat, ecnpurelec ... are all Economic Census subject-series tables).
# Longest prefix wins.
# "timeseries" is not a program - it is how the endpoint is reached. The real program
# sits in the second path segment. Names taken from the products' own titles.
TIMESERIES_PROGRAMS = {
    "intltrade": "International Trade", "eits": "Economic Indicators (EITS)",
    "asm": "Annual Survey of Manufactures", "aies": "Annual Integrated Economic Survey",
    "poverty": "Poverty (SAIPE / CPS)", "qwi": "Quarterly Workforce Indicators",
    "idb": "International Database", "pseo": "Post-Secondary Employment Outcomes",
    "bds": "Business Dynamics Statistics", "healthins": "Small Area Health Insurance Estimates",
    "hps": "Household Pulse Survey", "hhpulse": "Household Pulse Survey",
    "soma": "Survey of Market Absorption", "govs": "Public Sector", "govsemp": "Public Sector",
    "govspension": "Public Sector", "govsschfin": "Public Sector", "govsstatefin": "Public Sector",
    "govsstatetax": "Public Sector", "econ": "Economic Indicators (EITS)",
}

PROGRAM_PREFIXES = [
    ("ecn", "Economic Census"), ("abs", "Annual Business Survey"),
    ("vius", "Vehicle Inventory and Use Survey"), ("aies", "Annual Integrated Economic Survey"),
    ("cfs", "Commodity Flow Survey"), ("cre", "Community Resilience Estimates"),
    ("rhfs", "Rental Housing Finance Survey"), ("pub", "Public sector"),
]

def program_label(path):
    segs = path.split("/")
    top = segs[0]
    if top == "timeseries" and len(segs) > 1:
        return TIMESERIES_PROGRAMS.get(segs[1], segs[1])
    if top in PROGRAM_NAMES:
        return PROGRAM_NAMES[top]
    if "/" not in path:
        for pre, name in sorted(PROGRAM_PREFIXES, key=lambda x: -len(x[0])):
            if top.startswith(pre): return name
    return PROGRAM_NAMES.get(top, top)

# ============================================================================
# SUBJECT GROUPING
# ============================================================================
# Products are grouped for display by subject, matched against the Bureau's own
# product TITLE (falling back to the catalog path when a title carries no topic).
# Subject names follow the Census Bureau's published topic vocabulary.
#
# THIS TABLE IS MEANT TO BE EDITED. First rule that matches wins, so the specific
# rules sit above the broad ones - that is why "Population & Redistricting" appears
# twice: once at the top for named Decennial products, once at the bottom as the
# catch-all. If a product lands in the wrong place, move it by editing a pattern
# here; nothing else in the tool depends on these groupings.
#
# This affects DISPLAY ORDER ONLY. It says nothing about a product's uncertainty,
# its priority, or how far our work on it has gone.
SUBJECTS = [
    ("Population & Redistricting", r"demographic and housing|redistricting|post-enumeration|summary file|"
                                   r"decennial|congressional district|state legislative|population estimate|"
                                   r"population projection|planning database|count question|response rate|"
                                   r"demographic profile|crosstab"),
    ("International Trade",        r"international trade|\bimports?\b|\bexports?\b|commodity flow"),
    ("Government & Public Sector", r"public sector|government|tax collection|public pension|school system finance"),
    ("Business & Economy",         r"\becon|business|manufactur|wholesale|retail|nonemployer|entrepreneur|"
                                   r"industr|sector|subject series|accommodation|utilities|information:|"
                                   r"capital expend|research and development|market absorption|"
                                   r"annual integrated|vehicle"),
    ("Employment & Earnings",      r"employ|earnings|workforce|\bjob|labor|worker|occupation|displaced|"
                                   r"work schedule|contingent|post-secondary"),
    ("Income & Poverty",           r"income|poverty|program participation|unbanked|food security"),
    ("Health & Disability",        r"health|insurance|disabilit|tobacco|fertility|pulse survey|resilience"),
    ("Education",                  r"education|school enrollment|library"),
    ("Race, Ethnicity & Origin",   r"\brace|hispanic|ethnic|american indian|alaska native|equal employment|"
                                   r"selected population|surname|immigration|year of entry|nativity"),
    ("Housing",                    r"housing|household|living arrangement|migration flow|vacanc"),
    ("Geography & Boundaries",     r"boundar|tiger|cartographic|geograph"),
    ("Population & Redistricting", r"population|demographic|resident|\bage\b|\bsex\b|marital|voting|"
                                   r"veteran|civic|volunteer|\barts\b|internet|characteristics|language"),
]
# Used only when a title carries no topic word at all (e.g. "Public Use Microdata Sample").
SUBJECT_PATH_FALLBACK = [
    (r"^ecn|^ase|^sbo|^cbp|^zbp|^nonemp|^ewks|^cfspum|^abs|^vius", "Business & Economy"),
    (r"^acs|^dec|^pep|^popproj|^cps",                              "Population & Redistricting"),
]
SUBJECT_ORDER = []
for _n, _p in SUBJECTS:
    if _n not in SUBJECT_ORDER: SUBJECT_ORDER.append(_n)
SUBJECT_ORDER.append("Unclassified")

def subject_of(path, title):
    hay = (title or "").lower()
    for name, pat in SUBJECTS:
        if re.search(pat, hay): return name
    for pat, name in SUBJECT_PATH_FALLBACK:
        if re.search(pat, path): return name
    return "Unclassified"

# Non-API products that belong in a total inventory.
EXTRA_PRODUCTS = [
    {"path": "dec/das-demo", "title": "DAS Demonstration Data (privacy-noise evaluation files)",
     "vintages": [2022, 2023], "kind": "Aggregate tables",
     "desc": "Demonstration products released so researchers can measure the effect of the 2020 "
             "Disclosure Avoidance System. Not an API product; downloaded by ingestion/pull_das_demo_nj.py."},
    {"path": "geo/tiger", "title": "TIGER / Cartographic Boundary Files",
     "vintages": [2024], "kind": "Unflagged",
     "desc": "Geographic boundary files. Not an API dataset."},
]

# Map catalog families -> tracked product keys in the repo evidence model.
# EXACT matches: acs/acs5/pums, /eeo, /subject etc. are separate products with
# different uncertainty surfaces and must not inherit acs/acs5's evidence.
FAMILY_TO_PRODUCT = [
    (r"^acs/acs5$", "ACS 5-year"),
    (r"^dec/dhc$", "2020 DHC"),
    (r"^dec/dp$", "Demographic Profile"),
    (r"^dec/sf1$", "2010 SF1"),
    (r"^dec/das-demo$", "DAS demo"),
    (r"^geo/tiger$", "Boundaries"),
]
def family_product(path):
    for pat, prod in FAMILY_TO_PRODUCT:
        if re.search(pat, path): return prod
    return None

# Evidence matchers per tracked product (regexes over repo code).
# Patterns are matched against the file's basename AND its (lower-cased) text
# body - so both file-name and in-code references count. Word boundaries keep
# common words like "allocation" from matching the "Allocation analysis"
# matcher accidentally: only real code references (imports, module dotted
# access, filenames) score.
PRODUCT_MATCH = {
    "ACS 5-year": [r"acs/acs5", r"pull_acs"],
    "2020 DHC": [r"dec/dhc\b", r"dhc\.py\b", r"analysis[/\\.]dhc\b",
                 r"\bimport\s+dhc\b", r"pull_dhc"],
    "Demographic Profile": [r"dec/dp\b", r"demographic.{0,3}profile"],
    "2010 SF1": [r"dec/sf1", r"pull_sf1"],
    "DAS demo": [r"das_demo", r"demonstration"],
    "Boundaries": [r"pull_nj_geometry", r"pygris", r"cb_20", r"geoparquet"],
    # Our own analysis modules - not Census products, but tracked here so their
    # evidence surfaces in the Home tab "What is in the repo" table. They will
    # not appear on any catalog family card because no family maps to them.
    # composite.py / alloc.py / cv_model.py live on the unmerged JL_Work_Tree
    # branch today; notebooks 06 and 07 already import them, so evidence exists.
    "Composite prototype": [r"composite\.py\b", r"analysis[/\\.]composite\b",
                            r"pull_composite"],
    "Allocation analysis": [r"alloc\.py\b", r"analysis[/\\.]alloc\b",
                            r"\bfrom\s+analysis\s+import[^\n]*\balloc\b",
                            r"pull_acs_alloc"],
    "CV driver model":    [r"cv_model\.py\b", r"analysis[/\\.]cv_model\b"],
}
DOMAIN_PATTERNS = {
    "population": [r"\bB01003\b", r"\bP0*1_?0*01", r"total population"],
    "race/age subgroup": [r"\bB01001B\b", r"\bP0*12B"],
    "income": [r"\bB19013\b"],
    "poverty": [r"\bB17001\b", r"\bC17002\b", r"poverty"],
    "imputation": [r"\bB9[89]\d{3}\b", r"allocation"],
    "geometry": [r"geometry", r"boundar", r"cartographic"],
}

# Curated insight cards, written by the team, tagged with the product family they
# belong to. Mined WORKLOG findings appear separately on the Home tab; they are NOT
# attributed to a product, because WORKLOG does not record catalog paths and guessing
# the link would be exactly the kind of inference this tool avoids.
FINDINGS = [
 {"family": "acs/acs5", "stat": "1.4% → 13% → 20%", "headline": "Income error explodes as geography shrinks",
  "detail": "Median income CV at county / tract / block group; worst cases exceed the incomes measured.", "nb": "01", "kind": "finding"},
 {"family": "acs/acs5", "stat": "−0.5", "headline": "Sampling noise follows the size law almost exactly",
  "detail": "Fitted slopes −0.47 to −0.51 vs the theoretical −0.50; predictable, therefore scoreable.", "nb": "02", "kind": "finding"},
 {"family": "acs/acs5", "stat": "80%", "headline": "Tract-level poverty is low-reliability almost everywhere",
  "detail": "Poverty exceeds CV 0.30 in 80% of NJ tracts and partially defies the size law (slope −0.18).", "nb": "01-02", "kind": "finding"},
 {"family": "acs/acs5", "stat": "ρ = −0.58", "headline": "Poverty data is most reliable where poverty is highest",
  "detail": "Urban cores measure best, affluent suburbs worst: an equity-relevant blind spot.", "nb": "03", "kind": "finding"},
 {"family": "dec/das-demo", "stat": "~9×", "headline": "Block groups carry ~9× the privacy noise of tracts",
  "detail": "Same data, adjacent levels; geography type, not just size, drives DAS noise.", "nb": "04", "kind": "oddity"},
 {"family": "dec/das-demo", "stat": "807 / 427", "headline": "Ghost and vanished blocks",
  "detail": "807 empty blocks gain 4,695 phantom residents; 427 inhabited blocks publish as empty.", "nb": "04", "kind": "finding"},
 {"family": "acs/acs5", "stat": "4 in 10", "headline": "Income is imputed for ~39% of households at a typical tract",
  "detail": "Age/race under 1%: imputation is a variable-type story, concentrated in income.", "nb": "05", "kind": "finding"},
 {"family": "acs/acs5", "stat": "ρ ≈ 0", "headline": "Imputation is independent of the published error bars",
  "detail": "Every size-controlled allocation-vs-CV correlation sits in [−0.00, +0.19]: the MOE cannot see this error.", "nb": "05", "kind": "finding"},
 {"family": "acs/acs5", "stat": "22.8%", "headline": "The CV-only blind spot",
  "detail": "481 of 2,109 tracts look fine by the error bar but carry heavily imputed income.", "nb": "06", "kind": "finding"},
 {"family": "acs/acs5", "stat": "84.6%", "headline": "Combining rules disagree at the margin",
  "detail": "Equal-weight vs worst-component agree on only ~85% of the top-risk quartile.", "nb": "06", "kind": "finding"},
 {"family": "acs/acs5", "stat": "R² ≈ 0.67", "headline": "Score the estimate, not the place",
  "detail": "Estimate size alone explains ~2/3 of CV variance; place population almost nothing.", "nb": "07", "kind": "finding"},
 {"family": "acs/acs5", "stat": "131", "headline": "The quiet tracts",
  "detail": "6% of NJ tracts publish population MOEs near zero with no documented reason.", "nb": "02", "kind": "oddity"},
]

# ============================================================================
# WORKLOG MINER - the team's own words, verbatim
# ============================================================================

WL_ENTRY = r"(?m)^(?=### \d{4}-\d{2}-\d{2})"
WL_HEAD  = r"### (\d{4}-\d{2}-\d{2}) — ([^—]+?) — (.+)"
WL_BLOCK = r"(?m)^- \*\*Findings / decisions:\*\*\s*(.*?)(?=\n- \*\*|\Z)"
WL_STAT  = re.compile(
    r"(?:ρ|R²)?\s*(?:[≈=]\s*)?"
    r"[−\-+~]?\d[\d,.]*\s*(?:%|×|x)?"
    r"(?:\s*(?:/|in|→|to)\s*[−\-+~]?\d[\d,.]*\s*(?:%|×|x)?)*")
_YEAR = re.compile(r"^(19|20)\d\d$")
_UNIT = re.compile(r"[%×x≈ρ]|R²|\.\d|/")

def _strip_md(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", s)
    s = re.sub(r"\[(.+?)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    return " ".join(s.split()).strip(" ;.,")

def _stat_of(txt):
    """A stat chip only when we're confident it IS the finding's headline number.
    Conservative on purpose: a wrong chip misreads the finding, a missing one costs
    nothing, because the whole sentence is shown verbatim underneath."""
    for m in WL_STAT.finditer(txt):
        if m.start() > 80: break
        s = m.group(0).strip()
        if _YEAR.match(re.sub(r"[^\d]", "", s.replace(" ", ""))): continue
        if _UNIT.search(s): return s
    return ""

def mine_worklog(repo: Path):
    wl = repo / "WORKLOG.md"
    if not wl.exists(): return []
    text = wl.read_text(encoding="utf-8", errors="ignore")
    out = []
    for entry in re.split(WL_ENTRY, text)[1:]:
        h = re.match(WL_HEAD, entry)
        if not h: continue
        m = re.search(WL_BLOCK, entry, re.S)
        if not m: continue
        items = []
        for p in re.split(r"\(\d+\)\s*", " ".join(m.group(1).split())):
            t = _strip_md(p)
            if len(t) < 25: continue
            items.append({"stat": _stat_of(t), "text": t})
        if not items: continue
        nb = re.search(r"EDA (\d\d?)", h.group(3))
        out.append({"date": h.group(1), "author": h.group(2).strip(),
                    "title": _strip_md(h.group(3)), "nb": nb.group(1) if nb else "",
                    "items": items})
    out.sort(key=lambda e: e["date"], reverse=True)
    return out

# ============================================================================
# CATALOG
# ============================================================================

def _kind_of(flags):
    if flags.get("micro"): return "Microdata"
    if flags.get("ts"):    return "Time series"
    if flags.get("agg"):   return "Aggregate tables"
    return "Unflagged"

def fetch_catalog(cache_path: Path, online: bool):
    data = None
    if online:
        try:
            with urllib.request.urlopen("https://api.census.gov/data.json", timeout=60) as r:
                data = json.load(r)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
            print(f"  [catalog] crawled data.json: {len(data.get('dataset', []))} dataset-vintages")
        except Exception as ex:
            print(f"  [catalog] crawl failed ({ex}); trying cache")
    if data is None and cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"  [catalog] loaded cache: {len(data.get('dataset', []))} dataset-vintages")
    fams = {}
    if data:
        for ds in data.get("dataset", []):
            segs = ds.get("c_dataset") or []
            path = "/".join(segs)
            if not path: continue
            f = fams.setdefault(path, {"path": path, "title": ds.get("title", ""),
                                       "vintages": set(), "desc": "", "doc": "", "spatial": set(), "variables_url": "", "geography_url": "",
                                       "flags": {"micro": False, "agg": False, "ts": False}})
            v = ds.get("c_vintage")
            if v: f["vintages"].add(int(v))
            if not f["desc"]: f["desc"] = (ds.get("description") or "").strip()
            if not f["doc"]:  f["doc"] = ds.get("c_documentationLink") or ""
            if ds.get("c_variablesLink"): f["variables_url"] = ds["c_variablesLink"]
            if ds.get("c_geographyLink"): f["geography_url"] = ds["c_geographyLink"]
            if ds.get("spatial"): f["spatial"].add(ds["spatial"])
            for key, field in [("micro", "c_isMicrodata"), ("agg", "c_isAggregate"), ("ts", "c_isTimeseries")]:
                if ds.get(field): f["flags"][key] = True
    for ex in EXTRA_PRODUCTS:
        if ex["path"] not in fams:
            fams[ex["path"]] = {"path": ex["path"], "title": ex["title"],
                                "vintages": set(ex["vintages"]), "desc": ex["desc"], "doc": "",
                                "spatial": set(), "variables_url": "", "geography_url": "",
                                "flags": {}, "kind": ex["kind"]}
    for f in fams.values():
        f["vintages"] = sorted(f["vintages"])
        f["group"] = program_label(f["path"])
        f["subject"] = subject_of(f["path"], f["title"])
        f["product"] = family_product(f["path"])
        if not f.get("kind"): f["kind"] = _kind_of(f.get("flags") or {})
    return fams

# ============================================================================
# REVIEW FILE (team-owned funnel) - append-only, never seeded
# ============================================================================

def load_review(repo: Path, fams):
    """The tool NEVER sets a stage and NEVER writes uncertainty text or a
    composite_role.

    Every product is created as `cataloged` with empty `uncertainty_metrics`,
    empty `composite_role` and empty `composite_role_note`. An existing entry
    is never overwritten; new catalog families are appended so a fresh crawl
    cannot silently drop or reset the team's work.
    """
    p = repo / "product_review.json"
    existing, first = {}, not p.exists()
    if not first:
        existing = json.loads(p.read_text(encoding="utf-8"))
    added = 0
    default = {"stage": "cataloged", "uncertainty_metrics": "", "note": "",
               "composite_role": "", "composite_role_note": ""}
    for path in sorted(fams):
        if path not in existing:
            existing[path] = dict(default)
            added += 1
    if added or first:
        p.write_text(json.dumps(dict(sorted(existing.items())), indent=2), encoding="utf-8")
    return existing, p, first, added

def validate_review(review):
    """Check the composite_role/composite_role_note contract.

    A composite_role without a matching composite_role_note is a schema
    violation. We do NOT rewrite the file (the human's intent is captured
    even if incomplete) - the effective_role() reader downgrades it to
    unset, and we log the offense here so `python tools/product_scope.py
    --repo .` prints it once per run.
    """
    problems = []
    for path, r in review.items():
        if not isinstance(r, dict): continue
        role = (r.get("composite_role") or "").strip()
        note = (r.get("composite_role_note") or "").strip()
        if role and not note:
            problems.append((path, role, "composite_role_note is empty"))
        elif role and role not in COMPOSITE_ROLES:
            problems.append((path, role, "not one of " + "/".join(COMPOSITE_ROLES)))
    for path, role, msg in problems:
        print(f"  review: WARNING {path}: composite_role={role!r} {msg}; "
              "treating as unset until fixed", file=sys.stderr)
    return problems

# ============================================================================
# REPO EVIDENCE -> work depth per product
# ============================================================================

def fallback_scan(repo: Path):
    ev = []
    for sub, kind in [("ingestion", "ingestion"), ("analysis", "analysis")]:
        for f in sorted((repo / sub).glob("*.py")):
            t = f.read_text(encoding="utf-8", errors="ignore")
            ev.append({"file": f.name, "kind": kind, "text": t, "low": t.lower()})
    for f in sorted((repo / "notebooks").glob("*.ipynb")):
        t = f.read_text(encoding="utf-8", errors="ignore")
        ev.append({"file": f.name, "kind": "notebook", "text": t, "low": t.lower()})
    return ev

KIND_STAGE = {"docs": 1, "ingestion": 2, "analysis": 2, "notebook": 3}

# Where in the repo tree each evidence-kind lives; used to build repo-relative
# paths (and, from those, clickable jump-to-source URLs).
KIND_DIR = {"ingestion": "ingestion", "analysis": "analysis",
            "notebook":  "notebooks", "docs": "docs"}

def locate_pos(e, patterns):
    """First hit's structured position: {"line": N} or {"cell": N} or {}.
    Same detection as locate() but returns fields the URL builder can use."""
    pats = [re.compile(p, re.I) for p in patterns]
    if e.get("cells"):
        for i, src in enumerate(e["cells"], 1):
            if any(p.search(src) for p in pats):
                return {"cell": i}
    if e.get("lines"):
        for i, ln in enumerate(e["lines"], 1):
            if ln.lstrip().startswith("#"): continue
            if any(p.search(ln) for p in pats):
                return {"line": i}
    return {}

def receipt_label(r):
    """Text form of a structured receipt for the CSV export and plain-text callers."""
    label = r.get("file", "")
    if r.get("line"):  label += f" (line {r['line']})"
    elif r.get("cell"): label += f" (cell {r['cell']})"
    return label

def receipt_url(r, git):
    """Jump-to-source URL for a receipt.

    Preference order (matches feature #3):
      1. GitHub blob URL with #L<line> anchor - built from the git remote slug
         and current branch. Notebooks don't get a cell anchor because GitHub's
         .ipynb renderer doesn't expose stable cell IDs; the link still opens
         the notebook at the correct file.
      2. file:// absolute path - so the same links work in a local viewer
         even when there's no GitHub remote (e.g. detached checkouts).
      3. Empty string if we have no repo path at all (defensive fallback).
    """
    path = r.get("path")
    if not path: return ""
    slug = git.get("github_slug") if git else ""
    branch = (git.get("branch") if git else "") or "main"
    if slug:
        frag = f"#L{r['line']}" if r.get("line") else ""
        return f"https://github.com/{slug}/blob/{branch}/{path}{frag}"
    repo_abs = (git.get("repo_abs") if git else "") or ""
    if repo_abs:
        # file:// URLs on Windows use forward slashes and a leading slash.
        return "file:///" + (repo_abs + "/" + path).lstrip("/").replace("\\", "/")
    return ""

def geo_levels_in(low):
    """Keyword inference, NOT a verified record. "block-group" with a hyphen used to
    defeat the stripper and register as block-level work; the hyphen is handled now."""
    found, t = set(), low
    if re.search(r"block[\s_-]?group", t):
        found.add("block group"); t = re.sub(r"block[\s_-]?group", " ", t)
    for g, pat in [("block", r"\bblock\b"), ("tract", r"\btract"),
                   ("county", r"\bcount(y|ies)\b"), ("state", r"\bstate\b")]:
        if re.search(pat, t): found.add(g)
    return found

def build_product_status(evidence):
    """Structured receipts. Each receipt is a dict:
       {"file": basename, "path": repo-relative path, "kind": ingestion/analysis/notebook/docs,
        "line": int|None, "cell": int|None}
    Downstream renderers turn these into clickable file:line links (see receipt_url)."""
    out = {}
    for e in evidence:
        stage = KIND_STAGE.get(e["kind"], 1)
        h = e.get("health")
        if e["kind"] == "notebook":
            if h:
                stage = 3 if h["clean_run"] else 2
                if stage == 3 and h["asserts"] >= 3: stage = 4
            elif "assert" in e["low"]:
                stage = 4
        geos = geo_levels_in(e["low"])
        doms = {d for d, pats in DOMAIN_PATTERNS.items() if any(re.search(p, e["text"], re.I) for p in pats)}
        rel_dir = KIND_DIR.get(e["kind"], "")
        rel_path = f"{rel_dir}/{e['file']}" if rel_dir else e["file"]
        for prod, pats in PRODUCT_MATCH.items():
            if not any(re.search(p, e["low"]) or re.search(p, e["file"].lower()) for p in pats):
                continue
            rec = out.setdefault(prod, {"status": 0, "geos": {}, "domains": {}, "receipts": []})
            rec["status"] = max(rec["status"], stage)
            pos = locate_pos(e, sum(DOMAIN_PATTERNS.values(), [])) if DEEP else {}
            rec["receipts"].append({"file": e["file"], "path": rel_path, "kind": e["kind"],
                                    "line": pos.get("line"), "cell": pos.get("cell")})
            for g in geos: rec["geos"][g] = max(rec["geos"].get(g, 0), stage)
            for d in doms: rec["domains"][d] = max(rec["domains"].get(d, 0), stage)
    for rec in out.values():
        # Dedup by (file, line, cell); stable sort by file then position.
        seen, uniq = set(), []
        for r in rec["receipts"]:
            key = (r["file"], r.get("line"), r.get("cell"))
            if key in seen: continue
            seen.add(key); uniq.append(r)
        uniq.sort(key=lambda r: (r["file"], r.get("line") or 0, r.get("cell") or 0))
        rec["hit_count"] = len(uniq)     # full count before display cap - fuels the diff
        rec["receipts"] = uniq[:6]
    return out


# ============================================================================
# PROBE - ask the API what a product actually publishes
# ============================================================================
# Every catalog record carries variables.json and geography.json endpoints. A probe
# fetches them and reports COUNTS AND LEVELS ONLY - it never writes an uncertainty
# description. A human reads the probe and writes uncertainty_metrics. Results land
# in product_probes.json at the repo root, which IS committed so the team shares them.

ALLOC_GROUP = re.compile(r"^B9[89]\d{3}")
REPL_GROUP  = re.compile(r"^B\d{5}_VAR|^VAR_", re.I)

def _api_get(url, timeout=60):
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)

def summarise_variables(payload):
    v = payload.get("variables", payload)
    names = [n for n in v if n not in ("for", "in", "ucgid")]
    est, moe, annot, groups = [], [], [], set()
    for n in names:
        meta = v[n] if isinstance(v.get(n), dict) else {}
        g = meta.get("group") or ""
        if g and g != "N/A": groups.add(g)
        if n.endswith("M") and (n[:-1] + "E") in v: moe.append(n)
        elif n.endswith("E") and not n.endswith("NAME"): est.append(n)
        if n.endswith("EA") or n.endswith("MA"): annot.append(n)
    alloc = sorted(g for g in groups if ALLOC_GROUP.match(g))
    repl  = sorted(g for g in groups if REPL_GROUP.match(g))
    return {"variables": len(names), "estimates": len(est), "moe_variables": len(moe),
            "annotation_variables": len(annot), "groups": len(groups),
            "allocation_groups": alloc[:40], "allocation_group_count": len(alloc),
            "replicate_groups": repl[:20], "publishes_moe": len(moe) > 0}

def summarise_geography(payload):
    fips = payload.get("fips") or (payload.get("geographies") or {}).get("fips") or []
    levels, wildcards = [], []
    for g in fips:
        name = g.get("name")
        if not name: continue
        levels.append(name)
        if g.get("optionalWithWCFor") or not g.get("requires"): wildcards.append(name)
    return {"levels": levels, "level_count": len(levels), "queryable_without_parent": wildcards}

def probe_one(path, fam, today):
    out = {"path": path, "vintage": (fam["vintages"][-1] if fam["vintages"] else None),
           "probed": today, "ok": False, "error": ""}
    if not fam.get("variables_url"):
        out["error"] = "no variables.json endpoint in the catalog (non-API product)"
        return out
    try:
        out.update(summarise_variables(_api_get(fam["variables_url"])))
    except Exception as ex:
        out["error"] = f"variables: {type(ex).__name__}: {ex}"; return out
    try:
        out.update(summarise_geography(_api_get(fam["geography_url"])))
    except Exception as ex:
        out["error"] = f"geography: {type(ex).__name__}: {ex}"; return out
    out["ok"] = True
    return out

def probe_headline(p):
    if not p.get("ok"):
        return "probe failed - " + str(p.get("error", "unknown error"))
    bits = [f"{p['variables']:,} variables"]
    bits.append(f"{p['moe_variables']:,} carry an _M margin of error" if p.get("moe_variables")
                else "no _M margin-of-error variables found")
    if p.get("allocation_group_count"): bits.append(f"{p['allocation_group_count']} allocation group(s)")
    if p.get("annotation_variables"):   bits.append(f"{p['annotation_variables']} annotation variables")
    if p.get("levels"):
        bits.append("geography: " + ", ".join(p["levels"][:9]) + (" ..." if len(p["levels"]) > 9 else ""))
    return "; ".join(bits)

def load_probes(repo):
    f = repo / "product_probes.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

def run_probe_queue(repo, fams, paths, today):
    store = load_probes(repo)
    print(f"Probing {len(paths)} product(s) against api.census.gov ...")
    for path in paths:
        fam = fams.get(path)
        if not fam:
            print(f"  {path}: not in the catalog - skipped"); continue
        r = probe_one(path, fam, today)
        store[path] = r
        print(f"  {path}: {probe_headline(r)}")
    out = repo / "product_probes.json"
    out.write_text(json.dumps(dict(sorted(store.items())), indent=2), encoding="utf-8")
    print(f"Wrote {out.name} ({len(store)} probed products). Re-run without --probe-queue to rebuild the report.")

# ============================================================================
# SAMPLE / EDA MODE  (Phase 3)
# ============================================================================
# The probe (above) asks the API what a product PUBLISHES - counts and levels.
# A sample fetches an ACTUAL data slice, runs a canonical EDA on it, and caches
# the result so a teammate can triage a candidate product without opening a
# notebook.
#
# Sample cache lives in scope_data_cache.json at the repo root (gitignored) so
# a sample isn't accidentally shared as fact; if two teammates want the same
# snapshot, they each run the sample locally. Same reasoning as probes being
# committed (they're API descriptions, factual) and samples being local (they're
# a moment-in-time slice against a possibly-rate-limited endpoint).
#
# NO AUTO-JUDGMENTS. This module reports what the data LOOKS like - shape,
# dtypes, missingness, sparklines - and lets thresholds speak for themselves
# (a column at 45% missing gets flagged as ">30% missing", not "problematic").

SAMPLE_SIZE_DEFAULT       = 100
SAMPLE_FRESH_DAYS         = 7          # cache older than this is considered stale
SAMPLE_HTTP_TIMEOUT       = 30         # seconds per API call
SAMPLE_INTER_REQUEST_MS   = 500        # be a polite neighbour to api.census.gov
SAMPLE_VAR_CAP            = 20         # cap on variable count in one sample request
DATA_CACHE_FILE           = "scope_data_cache.json"   # gitignored - see .gitignore

def load_data_cache(repo: Path):
    """Read scope_data_cache.json (Phase 3 sample cache). Returns {} when the
    file is missing or unreadable. Never raises - callers depend on this being
    a safe read even on a fresh clone."""
    p = repo / DATA_CACHE_FILE
    if not p.exists(): return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_data_cache(repo: Path, cache):
    """Write scope_data_cache.json deterministically (sorted by path). Kept
    gitignored - a sample is a moment-in-time slice against a rate-limited
    endpoint, not shareable factual state (unlike probes which describe what
    an endpoint publishes and ARE committed)."""
    p = repo / DATA_CACHE_FILE
    ordered = dict(sorted(cache.items()))
    p.write_text(json.dumps(ordered, indent=2), encoding="utf-8")

def is_sample_fresh(entry, now=None):
    """A cache entry is fresh when its 'sampled_at' timestamp is within
    SAMPLE_FRESH_DAYS of now. Missing / malformed timestamps count as stale
    (safe default: force a re-sample rather than trust an unknown-age slice)."""
    if not entry or not entry.get("sampled_at"): return False
    ts = entry["sampled_at"]
    try:
        # Accept both ...Z and +00:00 forms.
        if ts.endswith("Z"): ts = ts[:-1] + "+00:00"
        when = datetime.datetime.fromisoformat(ts)
    except Exception:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age_days = (now - when).total_seconds() / 86400.0
    return age_days < SAMPLE_FRESH_DAYS

def sample_age_pill(entry, now=None):
    """Freshness pill for a sample cache entry - mirrors the top-of-page
    freshness bar but computed Python-side (one number per card, no JS).

    Returns {"label": str, "tone": "fresh"|"stale"|"unknown"}:
      tone == "fresh" -> green (age < SAMPLE_FRESH_DAYS days)
      tone == "stale" -> amber (age >= SAMPLE_FRESH_DAYS days)
      tone == "unknown" -> grey (no or malformed timestamp)
    Label is 'Sampled Xd ago' / 'Xh ago' / 'Xm ago', matching the tone the
    reader already knows from the header bar.
    """
    if not entry or not entry.get("sampled_at"):
        return {"label": "not sampled", "tone": "unknown"}
    ts = entry["sampled_at"]
    try:
        if ts.endswith("Z"): ts = ts[:-1] + "+00:00"
        when = datetime.datetime.fromisoformat(ts)
    except Exception:
        return {"label": "sampled at unknown time", "tone": "unknown"}
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age = (now - when).total_seconds()
    if age < 0: age = 0
    if   age < 90:        label_bit = f"{max(1, int(age))}s ago"
    elif age < 3600:      label_bit = f"{int(round(age/60))}m ago"
    elif age < 86400:     label_bit = f"{int(round(age/3600))}h ago"
    else:                 label_bit = f"{int(round(age/86400))}d ago"
    tone = "fresh" if age < SAMPLE_FRESH_DAYS * 86400 else "stale"
    return {"label": f"Sampled {label_bit}", "tone": tone}

def load_env(repo: Path):
    """Minimal .env reader: no dependency, KEY=VAL lines, # comments, quotes ok.
    Returns {} when the file doesn't exist. Silent on parse errors line-by-line."""
    envp = repo / ".env"
    if not envp.exists(): return {}
    out = {}
    for line in envp.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        if "=" not in line: continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out

def _data_url(fam):
    """Data endpoint for a catalog family: 'api.census.gov/data/<vintage>/<path>'.

    Prefers the latest vintage in fam['vintages']; falls back to stripping
    /variables.json off the catalog's variables_url. Returns "" for non-API
    products (no variables endpoint = not queryable through the data API)."""
    if not fam.get("variables_url"):
        return ""
    vintages = fam.get("vintages") or []
    if vintages:
        return f"https://api.census.gov/data/{max(vintages)}/{fam['path']}"
    # Fallback: derive from variables_url. Always HTTPS.
    vu = fam["variables_url"]
    if vu.startswith("http://"): vu = "https://" + vu[len("http://"):]
    return vu.replace("/variables.json", "")

def _pick_sample_vars(variables_url):
    """Fetch variables.json once, return (NAME + up to SAMPLE_VAR_CAP estimate vars).
    Raises on transport failure (caller wraps and reports).  Returns [] only when
    the response has zero usable variable names. Estimate variables end in 'E'
    and, on aggregate tables, have a matching '_M' MOE."""
    payload = _api_get(variables_url, timeout=SAMPLE_HTTP_TIMEOUT)
    v = payload.get("variables", payload)
    all_names = [n for n in v if n not in ("for", "in", "ucgid")]
    estimates = [n for n in all_names if n.endswith("E") and not n.endswith("NAME")]
    # Prefer estimates whose '_M' counterpart exists (aggregate-table pattern),
    # then fill from remaining estimates, then any other variable if nothing else.
    with_moe = [n for n in estimates if (n[:-1] + "M") in v]
    order = with_moe + [n for n in estimates if n not in set(with_moe)]
    picked = order[:SAMPLE_VAR_CAP]
    if not picked and all_names:
        picked = all_names[:SAMPLE_VAR_CAP]
    # Always request NAME first if the variable exists (it does on ~all datasets).
    if "NAME" in v and "NAME" not in picked:
        picked = ["NAME"] + picked[:SAMPLE_VAR_CAP - 1]
    return picked

def _pick_sample_geography(fam, probe):
    """Return a 'for=<level>:*' value. Prefers a level the API says is
    queryable-without-a-parent (state, us, region). Falls back to 'state:*'."""
    if probe and probe.get("ok"):
        wildcards = probe.get("queryable_without_parent") or []
        for pref in ("state", "us", "region", "division"):
            if pref in wildcards:
                return pref
        if wildcards:
            return wildcards[0]
        levels = probe.get("levels") or []
        for pref in ("state", "us", "region"):
            if pref in levels:
                return pref
    return "state"   # safe default for national aggregate tables

def _http_get_json(url, timeout=SAMPLE_HTTP_TIMEOUT, retry=True):
    """GET + JSON decode with one retry on transient errors (HTTPError >=500,
    URLError, timeout). Returns parsed JSON, or raises the last exception.
    Requests are silent on stdout - callers own the log line."""
    last_exc = None
    for attempt in (1, 2 if retry else 1):
        try:
            if url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as ex:
            last_exc = ex
            if ex.code and ex.code < 500: raise   # 4xx: don't retry
            if attempt == 2: raise
        except (urllib.error.URLError, TimeoutError, OSError) as ex:
            last_exc = ex
            if attempt == 2: raise
        # Small backoff between attempts.
        import time as _t; _t.sleep(0.75)
    raise last_exc if last_exc else RuntimeError("unreachable")

SPARK_BARS       = "▁▂▃▄▅▆▇█"
EDA_MISSING_PCT  = 30.0       # per-column threshold flagged in the report
EDA_TOPK         = 5          # top-K values shown for categorical/string columns
EDA_MIN_CARD_TOP = 6          # ...only when the column has >= this many distinct values
EDA_SPARK_BINS   = 15
EDA_SPARK_COLS   = 3          # max numeric columns that get a sparkline
# Column NAMES that look like Census geography identifiers. Match is case-
# insensitive and substring-friendly (checked against col name lower-cased).
GEO_NAME_HINTS = [
    "state", "county", "tract", "block group", "block_group", "blockgroup",
    "place", "cbsa", "csa", "zcta", "puma", "ucgid", "geo_id", "geoid",
]
# Census null/annotation sentinels. Treat these as MISSING when computing
# per-column stats. See ACS annotation codes (public data dictionary).
CENSUS_NULLS = {"", "-", "*", "**", "***", "N", "null", "NULL",
                "-666666666", "-999999999"}

def _to_numeric(series):
    """Coerce a series to numeric where possible; NaN elsewhere. Used to
    decide 'this is really a numeric column' after Census sends everything
    over the wire as string."""
    try:
        import pandas as pd
    except ImportError:
        return None
    return pd.to_numeric(series, errors="coerce")

def _is_numeric_col(series):
    """A column counts as numeric if >=80% of its non-null values parse as
    numbers. The threshold keeps NAME columns from being called numeric just
    because a few rows happen to be all digits."""
    try:
        import pandas as pd
    except ImportError:
        return False
    non_null = series[~series.isin(CENSUS_NULLS)].dropna()
    if len(non_null) == 0: return False
    coerced = pd.to_numeric(non_null, errors="coerce")
    return coerced.notna().mean() >= 0.80

def _sparkline(values, bins=EDA_SPARK_BINS):
    """Unicode block-histogram of a numeric-like sequence, e.g. '▁▂▄▆█▇▄▂▁▁'.
    Returns '' when there aren't enough values or the range is degenerate.
    No numpy dependency - this is a hand-rolled histogram to keep the tool
    stdlib + pandas only."""
    vals = []
    for v in values:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv != fv:  # NaN
            continue
        vals.append(fv)
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if lo == hi:
        # constant series: fill with the middle bar so the reader sees "flat".
        return SPARK_BARS[len(SPARK_BARS) // 2] * bins
    counts = [0] * bins
    step = (hi - lo) / bins
    for v in vals:
        i = int((v - lo) / step)
        if i >= bins: i = bins - 1
        counts[i] += 1
    m = max(counts)
    return "".join(SPARK_BARS[min(len(SPARK_BARS) - 1,
                                   int(c / m * (len(SPARK_BARS) - 1)))]
                   for c in counts)

def _detect_geo_cols(df, probe):
    """Return the DataFrame column names that look like Census geo identifiers.
    Two signals: (a) exact match against the probe's known geography level names,
    (b) name hints like 'state', 'county', 'geo_id'. Returns the union."""
    cols = list(df.columns)
    found = set()
    if probe and probe.get("ok"):
        for level in probe.get("levels", []):
            for c in cols:
                if c.lower() == level.lower(): found.add(c)
    for c in cols:
        cl = c.lower()
        for hint in GEO_NAME_HINTS:
            if hint in cl:
                found.add(c); break
    # Return in original column order so the report reads naturally.
    return [c for c in cols if c in found]

def _rank_numeric_for_spark(df, numeric_cols):
    """Rank numeric columns for sparkline inclusion. Priority:
    (1) columns whose name suggests an estimate ('estimate', ends in E and long
    Census-style like B01003_001E), (2) by descending variance (more shape to
    show), (3) alphabetical for ties. Returns the top EDA_SPARK_COLS names."""
    try:
        import pandas as pd
    except ImportError:
        return []
    scored = []
    for c in numeric_cols:
        name_l = c.lower()
        looks_estimate = ("estimate" in name_l or
                          (c.endswith("E") and "_" in c and c[0].isalpha()))
        num = _to_numeric(df[c])
        try:
            var = float(num.var()) if num is not None else 0.0
            if var != var: var = 0.0   # NaN -> 0
        except Exception:
            var = 0.0
        scored.append((not looks_estimate, -var, c))  # False sorts before True
    scored.sort()
    return [c for _, _, c in scored[:EDA_SPARK_COLS]]

def compute_eda(df, probe):
    """Canonical EDA on one sample. Returns a JSON-serialisable dict:

      { "shape": [rows, cols],
        "columns": {name: {"dtype": str, "missing_pct": float,
                           "numeric": {"min","max","mean","median"} | None,
                           "top_values": [[val, count, pct]] | None,
                           "cardinality": int,
                           "flag_missing_over_30": bool} },
        "geography": {geo_col: {"distinct_populated": int}},
        "sparklines": {col: "▁▂▃…"} }

    No auto-editorialisation: computes what the data looks like and returns
    it. Thresholds (>30% missing) are flagged in the output as booleans so
    the renderer can style them; nothing is called 'bad' or 'good' here.
    """
    try:
        import pandas as pd
    except ImportError:
        return {"error": "pandas not installed"}
    if df is None or df.empty:
        return {"shape": [0, 0], "columns": {}, "geography": {}, "sparklines": {}}
    rows, cols = df.shape
    out = {"shape": [int(rows), int(cols)], "columns": {}, "geography": {},
           "sparklines": {}}
    numeric_names = []
    for c in df.columns:
        s = df[c]
        # Treat Census annotation sentinels as missing for stats only.
        s_null_flag = s.isna() | s.astype(str).isin(CENSUS_NULLS)
        miss_pct = round(float(s_null_flag.mean()) * 100.0, 1)
        non_null = s[~s_null_flag]
        card = int(non_null.nunique(dropna=True))
        entry = {
            "dtype":               str(s.dtype),
            "missing_pct":         miss_pct,
            "cardinality":         card,
            "numeric":             None,
            "top_values":          None,
            "flag_missing_over_30": miss_pct > EDA_MISSING_PCT,
        }
        if _is_numeric_col(s):
            numeric_names.append(c)
            num = _to_numeric(non_null)
            if num is not None and len(num.dropna()) > 0:
                nn = num.dropna()
                entry["numeric"] = {
                    "min":    float(nn.min()),
                    "max":    float(nn.max()),
                    "mean":   float(nn.mean()),
                    "median": float(nn.median()),
                }
                # Refine dtype to something more useful than "object".
                entry["dtype"] = "float" if nn.dtype.kind == "f" else "int"
        else:
            if card >= EDA_MIN_CARD_TOP:
                counts = non_null.astype(str).value_counts().head(EDA_TOPK)
                total = int(non_null.shape[0]) or 1
                entry["top_values"] = [[str(k), int(v),
                                        round(v * 100.0 / total, 1)]
                                       for k, v in counts.items()]
        out["columns"][c] = entry

    # Geography breakdown: distinct populated values per detected geo column.
    for gc in _detect_geo_cols(df, probe):
        s = df[gc]
        s_null_flag = s.isna() | s.astype(str).isin(CENSUS_NULLS)
        out["geography"][gc] = {"distinct_populated":
                                int(s[~s_null_flag].nunique(dropna=True))}

    # Sparklines on the top-priority numeric columns only. Keep the payload
    # slim - one sparkline is ~15 chars, three is enough to communicate shape.
    for c in _rank_numeric_for_spark(df, numeric_names):
        num = _to_numeric(df[c]).dropna()
        if len(num) >= 2:
            out["sparklines"][c] = _sparkline(num.tolist())
    return out

def fetch_sample(fam, probe, size, api_key):
    """Fetch a small data slice for one product. Returns (df, source_url, err).

    On success: df is a pandas DataFrame with 'size' or fewer rows; err = "".
    On non-API product: (None, "", "not sample-able via API").
    On any other failure: (None, url, "<message>"). Never raises to the caller."""
    if not fam.get("variables_url"):
        return None, "", "not sample-able via API (bulk-download product)"
    data_ep = _data_url(fam)
    if not data_ep:
        return None, "", "no data endpoint could be constructed"
    variables_url = fam["variables_url"]
    if variables_url.startswith("http://"):
        variables_url = "https://" + variables_url[len("http://"):]
    try:
        picked = _pick_sample_vars(variables_url)
    except Exception as ex:
        return None, data_ep, f"variables.json fetch failed: {type(ex).__name__}: {ex}"
    if not picked:
        return None, data_ep, "no usable variables in variables.json"
    geo = _pick_sample_geography(fam, probe)
    getparam = ",".join(picked)
    url = f"{data_ep}?get={getparam}&for={geo}:*"
    if api_key:
        url += f"&key={api_key}"
    try:
        payload = _http_get_json(url, timeout=SAMPLE_HTTP_TIMEOUT, retry=True)
    except urllib.error.HTTPError as ex:
        return None, url, f"HTTP {ex.code}: {ex.reason}"
    except Exception as ex:
        return None, url, f"{type(ex).__name__}: {ex}"
    # The Census data API returns a 2D list: header row + data rows.
    if not isinstance(payload, list) or len(payload) < 2:
        return None, url, "response was not a data table (unexpected shape)"
    try:
        import pandas as pd
    except ImportError:
        return None, url, "pandas not installed (pip install pandas)"
    header = payload[0]
    rows = payload[1:]
    df = pd.DataFrame(rows, columns=header)
    if len(df) > size:
        df = df.head(size)
    return df, url, ""

def sample_products(repo, fams, review, probes, only_product, size, refresh, git=None):
    """Run one or many samples. When only_product is set, sample just that one;
    otherwise batch through every product currently marked 'candidate' in the
    review file. Skips fresh cache entries (age < SAMPLE_FRESH_DAYS days) unless
    refresh is True; skips non-API products with a clear message. Persists
    successful samples to scope_data_cache.json. Returns a summary dict with
    counts and per-product results for the caller to display."""
    env = load_env(repo)
    api_key = env.get("CENSUS_API_KEY", "")
    cache = load_data_cache(repo)
    head_sha = (git or {}).get("head_sha", "")

    if only_product:
        targets = [only_product]
    else:
        targets = sorted(p for p, r in review.items()
                         if (r.get("stage") or "").lower() == "candidate")
    if not targets:
        print("[sample] nothing to sample: no products marked 'candidate' in "
              "product_review.json (or pass --product <ID> to sample one directly).")
        return {"sampled": [], "skipped_fresh": [], "skipped_non_api": [],
                "failed": [], "diffs": {}}

    print(f"[sample] {len(targets)} target(s); size={size}; "
          f"api_key={'yes' if api_key else 'no (public rate limits apply)'}; "
          f"refresh={'yes' if refresh else 'no'}")
    summary = {"sampled": [], "skipped_fresh": [], "skipped_non_api": [],
               "failed": [], "diffs": {}}
    for i, path in enumerate(targets):
        fam = fams.get(path)
        if not fam:
            print(f"  [sample] {path}: not in the catalog - skipped")
            summary["failed"].append({"path": path, "reason": "not in catalog"})
            continue
        if not fam.get("variables_url"):
            print(f"  [sample] {path}: not sample-able via API (bulk-download "
                  f"product); skipping")
            summary["skipped_non_api"].append(path)
            continue
        # Fresh-cache short-circuit: skip HTTP entirely when a recent entry
        # exists and the user didn't force --refresh.
        cached = cache.get(path)
        if not refresh and is_sample_fresh(cached):
            print(f"  [sample] {path}: fresh cache from "
                  f"{cached.get('sampled_at','?')} - skipping (use --refresh "
                  f"to force)")
            summary["skipped_fresh"].append(path)
            continue

        probe = probes.get(path) or {}
        df, url, err = fetch_sample(fam, probe, size, api_key)
        if err:
            print(f"  [sample] {path}: FAILED - {err}")
            summary["failed"].append({"path": path, "reason": err, "url": url})
        else:
            eda = compute_eda(df, probe)
            over30 = sum(1 for c in eda.get("columns", {}).values()
                         if c.get("flag_missing_over_30"))
            n_geo = len(eda.get("geography", {}))
            n_spark = len(eda.get("sparklines", {}))
            print(f"  [sample] {path}: {len(df)} rows x {len(df.columns)} cols "
                  f"from {url}")
            print(f"           EDA: {over30} col(s) >{EDA_MISSING_PCT:g}% missing, "
                  f"{n_geo} geo col(s), {n_spark} sparkline(s)")
            new_entry = {
                "sampled_at":    datetime.datetime.now(datetime.timezone.utc)
                                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sample_size":   size,
                "shape":         eda.get("shape", [len(df), len(df.columns)]),
                "columns":       eda.get("columns", {}),
                "geography":     eda.get("geography", {}),
                "sparklines":    eda.get("sparklines", {}),
                "source_url":    url,
                "sha_at_sample": head_sha,
            }
            cache[path] = new_entry
            summary["sampled"].append({"path": path, "url": url,
                                        "rows": len(df), "cols": len(df.columns),
                                        "eda": eda})
        # Be network-polite between requests.
        if i < len(targets) - 1:
            import time as _t; _t.sleep(SAMPLE_INTER_REQUEST_MS / 1000.0)

    # Persist cache once (single write, deterministic key order).
    save_data_cache(repo, cache)
    return summary

# ============================================================================
# REPORT
# ============================================================================

TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Product Scope - Census Uncertainty Analytics</title>
<style>
:root{--navy:#1F2A5C;--deep:#16204A;--gold:#C9A227;--ice:#EEF2FA;--line:#CADCFC;--ink:#22283B;--muted:#5A6072;}
*{box-sizing:border-box;margin:0;}
body{font:14.5px/1.5 "Segoe UI",system-ui,sans-serif;color:var(--ink);background:#fff;padding:0 0 60px;}
header{background:var(--deep);color:#fff;padding:26px 44px 0;}
.kicker{color:var(--gold);font-weight:700;font-size:11.5px;letter-spacing:.22em;text-transform:uppercase;}
h1{font-family:Georgia,Cambria,serif;font-size:29px;margin:6px 0 4px;}
header p{color:#CADCFC;font-size:13px;max-width:940px;}
.tabs{display:flex;gap:4px;margin-top:18px;flex-wrap:wrap;}
.tab{padding:9px 17px;border-radius:8px 8px 0 0;background:#28356B;color:#CADCFC;cursor:pointer;
     font-size:13px;font-weight:600;border:0;font-family:inherit;}
.tab .n{opacity:.65;font-weight:400;margin-left:5px;}
.tab.on{background:#fff;color:var(--navy);}
.wrap{padding:20px 44px;max-width:1300px;}
.panel{display:none;} .panel.on{display:block;}
.blurb{font-size:12.5px;color:var(--muted);background:var(--ice);border-left:3px solid var(--line);
       padding:8px 12px;border-radius:4px;margin-bottom:14px;max-width:920px;}
.filter{margin:0 0 14px;}
.filter input{width:340px;padding:7px 11px;border:1px solid var(--line);border-radius:7px;font:inherit;font-size:13px;}
.filter span{font-size:11.5px;color:var(--muted);margin-left:10px;}
.funnel{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 18px;}
.fstep{border:1px solid var(--line);border-radius:10px;padding:8px 15px;text-align:center;background:var(--ice);}
.fstep b{font-family:Georgia,serif;font-size:22px;color:var(--navy);display:block;}
.fstep span{font-size:10px;color:var(--muted);line-height:1.25;display:block;}
.f-focus{background:var(--navy);} .f-focus b{color:#F5D77A;} .f-focus span{color:#CADCFC;}
.f-cand{background:#FBF6E7;border-color:var(--gold);}
.farrow{color:var(--muted);font-size:17px;}
h2{font-family:Georgia,serif;color:var(--navy);font-size:20px;margin:26px 0 4px;}
.sub{font-size:12px;color:var(--muted);margin-bottom:10px;max-width:900px;}
table.rep{border-collapse:collapse;width:100%;max-width:1020px;font-size:13px;margin-bottom:6px;}
table.rep th{text-align:left;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
             color:var(--muted);border-bottom:2px solid var(--ice);padding:6px 9px;}
table.rep td{border-bottom:1px solid var(--ice);padding:7px 9px;vertical-align:top;}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:var(--muted);}
.gsec{margin:12px 0 6px;}
.ghead{font-family:Georgia,serif;color:var(--navy);font-size:17px;cursor:pointer;padding:4px 0;border-bottom:2px solid var(--ice);}
.ghead:before{content:"\25BE  ";color:var(--gold);}
.gsec.gfold .ghead:before{content:"\25B8  ";}
.gsec.gfold .prod{display:none;} .gsec.gfold .psec{display:none;}
.psec{margin:6px 0 6px 18px;}
.phead{font-size:13px;font-weight:700;color:#50639B;cursor:pointer;padding:3px 0;border-bottom:1px solid var(--ice);}
.phead:before{content:"\25BE  ";color:var(--line);}
.psec.pfold .phead:before{content:"\25B8  ";}
.psec.pfold .prod{display:none;}
.phead em{font-style:normal;color:var(--muted);font-size:11px;margin-left:7px;font-weight:400;}
.ghead em{font-family:"Segoe UI",sans-serif;font-style:normal;color:var(--muted);font-size:12px;margin-left:8px;}
.prod{display:table;width:100%;margin:9px 0;}
.pnode,.branches{display:table-cell;vertical-align:top;}
.pnode{width:350px;min-width:350px;}
.pcard{border:1px solid var(--line);border-left:6px solid var(--line);border-radius:8px;padding:9px 12px;cursor:pointer;background:#fff;}
.pcard .path{font-family:ui-monospace,Consolas,monospace;font-size:12px;font-weight:700;color:var(--navy);word-break:break-all;}
.pcard .title{font-size:11.5px;color:var(--muted);line-height:1.3;margin-top:1px;}
.pcard .mini{margin-top:5px;}
.qbox{float:right;font-size:10px;color:var(--muted);cursor:pointer;user-select:none;
      border:1px solid var(--line);border-radius:10px;padding:1px 7px;margin-left:6px;}
.qbox input{vertical-align:-1px;margin:0 3px 0 0;}
.qbox.probed{border-color:var(--gold);color:#8a6d1c;}
#qbar{position:fixed;right:22px;bottom:18px;background:var(--navy);color:#fff;border-radius:10px;
      padding:10px 16px;font-size:12.5px;box-shadow:0 3px 14px rgba(0,0,0,.28);display:none;z-index:9;}
#qbar b{color:#F5D77A;} #qbar button{margin-left:10px;font:inherit;font-size:12px;border:0;
      border-radius:6px;padding:5px 11px;cursor:pointer;background:#F5D77A;color:#16204A;font-weight:700;}
#qbar button.sec{background:#28356B;color:#CADCFC;font-weight:400;}
#qbar code{background:#16204A;padding:2px 6px;border-radius:4px;display:block;margin-top:7px;font-size:11px;}
.stagechip,.workchip,.kindchip,.rolechip{display:inline-block;padding:2px 9px;border-radius:10px;font-size:10px;
      font-weight:700;border:1px solid var(--line);margin-right:5px;}
.workchip{font-weight:600;}
.kindchip{font-weight:600;background:#fff;color:var(--muted);}
.rolechip{background:#F1E7C8;color:#6B4E11;border-color:var(--gold);font-weight:700;cursor:help;}
.w4{background:var(--navy);color:#F5D77A;} .w3{background:#50639B;color:#fff;} .w2{background:#8FA8D8;color:#16204A;}
.w1{background:var(--ice);color:var(--navy);} .w0{background:#F6F7FA;color:#9AA0B0;}
.fcount{font-size:10px;color:var(--gold);font-weight:700;}
.branches{padding-left:34px;position:relative;}
.prod.folded .branches{display:none;}
.branch{position:relative;margin:0 0 8px 0;max-width:820px;}
.branch:before{content:"";position:absolute;left:-24px;top:16px;width:24px;border-top:2px solid var(--line);}
.branch:after{content:"";position:absolute;left:-24px;top:-8px;height:24px;border-left:2px solid var(--line);}
.branch:first-child:after{top:16px;height:0;}
.branch + .branch:after{top:-14px;height:30px;}
.bcard{border:1px solid var(--line);border-radius:8px;padding:8px 12px;background:#fff;}
.blabel{font-size:9.5px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-bottom:3px;}
.unc{font-size:12px;background:var(--ice);border-left:3px solid var(--gold);padding:6px 9px;border-radius:4px;}
.unc.todo{border-left-color:#c96a27;font-style:italic;color:#8a4d1c;}
.desc{font-size:11.5px;color:var(--muted);line-height:1.45;}
.krow{display:table;width:100%;max-width:430px;border-collapse:separate;border-spacing:3px 0;margin-top:4px;}
.kbox{display:table-cell;height:22px;border-radius:4px;text-align:center;vertical-align:middle;border:1px solid var(--line);font-size:8.5px;font-weight:600;width:20%;}
.s0{background:#EDF0F7;color:#5A6072;} .s1{background:#CADCFC;color:#1F2A5C;} .s2{background:#8FA8D8;color:#16204A;}
.s3{background:#50639B;color:#fff;} .s4{background:#1F2A5C;color:#F5D77A;}
.inferred{font-size:10px;color:#8a4d1c;font-style:italic;margin-top:3px;}
.receipts{font-size:10px;color:var(--muted);font-family:ui-monospace,Consolas,monospace;line-height:1.5;margin-top:5px;}
.receipt-link{color:#3A4890;text-decoration:none;border-bottom:1px dotted #8FA8D8;}
.receipt-link:hover{color:var(--navy);border-bottom-style:solid;}
/* Contextual affordances: state-driven copyable commands / JSON nudges. */
.aff-row{padding:6px 8px;border-radius:5px;margin:4px 0;font-size:11.5px;line-height:1.4;
     display:flex;flex-wrap:wrap;align-items:center;gap:8px;}
.aff-row.aff-info{background:#F1F5FF;border-left:3px solid #8FA8D8;}
.aff-row.aff-amber{background:#FBF0D6;border-left:3px solid #C9A227;color:#6E4E11;}
.aff-row.aff-nudge{background:#F6F7FA;border-left:3px solid var(--line);color:var(--muted);}
.aff-text{flex:1;min-width:200px;}
/* Diff banner (Home tab, top). Baseline mode is grey; active diff uses ice. */
.diff-banner{background:var(--ice);border-left:4px solid var(--navy);border-radius:6px;
     padding:11px 15px;margin:0 0 16px;max-width:1020px;}
.diff-banner.baseline{background:#F6F7FA;border-left-color:var(--line);}
.diff-headline{font-size:13.5px;color:var(--navy);line-height:1.4;}
.diff-headline b{color:var(--navy);}
.diff-when{font-size:10.5px;color:var(--muted);margin-top:3px;font-family:ui-monospace,Consolas,monospace;}
.diff-banner details{margin-top:8px;font-size:12px;}
.diff-banner summary{cursor:pointer;color:#3A4890;font-weight:600;}
.diff-list{list-style:none;padding:8px 0 0;margin:0;max-height:280px;overflow-y:auto;}
.diff-list li{padding:2px 0;color:var(--muted);font-size:11.5px;line-height:1.5;border-bottom:1px solid #E1E7F0;}
.diff-list code{font-family:ui-monospace,Consolas,monospace;font-size:11px;background:#fff;
     padding:1px 5px;border-radius:3px;color:var(--navy);}
/* Composite code references (JL_Work_Tree AST hits). */
.jl-refs{list-style:none;padding:0;margin:0;font-size:11px;line-height:1.5;}
.jl-refs li{padding:2px 0;border-bottom:1px dotted #E1E7F0;}
.jl-refs li:last-child{border-bottom:0;}
.jl-sym{font-family:ui-monospace,Consolas,monospace;color:var(--navy);}
.jl-kind{color:var(--muted);font-size:10px;}
.jl-src{font-family:"Segoe UI",sans-serif;font-weight:400;color:var(--muted);font-size:10.5px;
     text-transform:none;letter-spacing:0;margin-left:6px;}
.jl-parse-err{font-size:10.5px;color:#8a4d1c;font-style:italic;margin-top:5px;}
/* Divergences (Home tab) - composite code vs. declared role reconciliation. */
.div-block{background:#FBF0D6;border-left:4px solid var(--gold);border-radius:6px;
     padding:10px 15px;margin:8px 0;max-width:1020px;}
.div-head{font-size:12.5px;font-weight:700;color:#6E4E11;margin-bottom:5px;}
.div-head code{background:#F1E7C8;color:#6B4E11;padding:0 4px;border-radius:3px;
     font-family:ui-monospace,Consolas,monospace;font-size:11.5px;}
.div-list{list-style:none;padding:0;margin:0;font-size:11.5px;line-height:1.55;color:var(--ink);}
.div-list li{padding:2px 0;}
.div-list code{background:#fff;padding:1px 5px;border-radius:3px;
     font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--navy);}
.meta{font-size:11px;color:var(--muted);margin-top:3px;}
.tk{border-left:3px solid var(--line);padding:4px 8px;margin:5px 0;}
.tk.odd{border-left-color:var(--gold);}
.tkh{font-size:11.5px;} .tkh b{color:var(--navy);margin-right:6px;} .tkh em{float:right;font-style:normal;color:var(--muted);font-size:9.5px;}
.tkd{font-size:10.5px;color:var(--muted);line-height:1.35;margin-top:1px;}
.nowork{font-size:11.5px;color:var(--muted);font-style:italic;}
.wl{border:1px solid var(--line);border-radius:8px;padding:10px 13px;margin:9px 0;max-width:1020px;}
.wlh{font-size:12.5px;color:var(--navy);font-weight:700;}
.wlh span{font-weight:400;color:var(--muted);font-size:11px;margin-left:8px;}
.wli{font-size:12px;line-height:1.45;margin:5px 0 0;padding-left:10px;border-left:2px solid var(--ice);}
.wli b{display:inline-block;background:var(--ice);color:var(--navy);border-radius:9px;padding:1px 8px;
       font-size:10.5px;margin-right:6px;font-family:ui-monospace,Consolas,monospace;}
.nohit{display:none;font-size:12.5px;color:var(--muted);font-style:italic;padding:10px 0;}
footer{padding:22px 44px;color:var(--muted);font-size:11.5px;}
/* Freshness pill bar (shown on every page - reads data-generated-at at page load). */
.freshbar{background:#0F1738;color:#CADCFC;padding:9px 44px;font-size:12px;
     display:flex;align-items:center;gap:14px;flex-wrap:wrap;border-bottom:1px solid #263466;}
.freshbar .pill{display:inline-block;padding:3px 12px;border-radius:11px;font-weight:700;font-size:11.5px;
     letter-spacing:.02em;background:#2A356C;color:#CADCFC;}
.freshbar .pill.fresh{background:#1F7A3A;color:#E6F5EA;}
.freshbar .pill.stale{background:#E9CD7A;color:#3A2F0A;}
.freshbar .pill.old{background:#C0392B;color:#FFF;}
.freshbar .sha{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;opacity:.7;}
/* Reusable click-to-copy control: <span class="copy-cmd"><code>...</code><button data-copy="...">Copy</button></span> */
.copy-cmd{display:inline-flex;align-items:center;gap:6px;background:#16204A;border:1px solid #28356B;
     border-radius:6px;padding:2px 4px 2px 8px;font-family:ui-monospace,Consolas,monospace;font-size:11px;
     color:#CADCFC;max-width:100%;}
.copy-cmd code{background:transparent;color:inherit;padding:0;font-size:inherit;white-space:nowrap;
     overflow:hidden;text-overflow:ellipsis;max-width:520px;}
.copy-cmd button{background:#28356B;color:#F5D77A;border:0;border-radius:4px;padding:2px 8px;
     font:inherit;font-size:10.5px;font-weight:700;cursor:pointer;letter-spacing:.03em;}
.copy-cmd button:hover{background:#3A4890;}
.copy-cmd button.done{background:#1F7A3A;color:#fff;}
/* Light variant, for use inside product cards on white backgrounds. */
.copy-cmd.light{background:#F6F7FA;border-color:var(--line);color:var(--ink);}
.copy-cmd.light button{background:var(--line);color:var(--navy);}
.copy-cmd.light button.done{background:#1F7A3A;color:#fff;}
/* EDA snapshot card section (Phase 3). Reader-first table styling: light
   background, monospace for numeric cells, unicode sparklines rendered inline
   in a slightly larger font so the shape is legible. */
.eda-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:5px;}
.eda-shape{font-size:11.5px;color:var(--navy);font-weight:600;font-family:ui-monospace,Consolas,monospace;}
.eda-src{font-size:10px;color:var(--muted);font-family:ui-monospace,Consolas,monospace;
     overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%;flex:1;min-width:0;}
.eda-src a{color:#3A4890;text-decoration:none;border-bottom:1px dotted #8FA8D8;}
.pill.sample-fresh{background:#1F7A3A;color:#E6F5EA;}
.pill.sample-stale{background:#E9CD7A;color:#3A2F0A;}
.pill.sample-unknown{background:#F6F7FA;color:#5A6072;border:1px solid var(--line);}
.eda-tbl{border-collapse:collapse;width:100%;font-size:10.5px;margin:4px 0;}
.eda-tbl th{text-align:left;font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;
     color:var(--muted);border-bottom:1px solid var(--ice);padding:3px 6px;font-weight:700;}
.eda-tbl td{border-bottom:1px solid #F1F3F8;padding:3px 6px;vertical-align:top;}
.eda-tbl td.mono{font-family:ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums;}
.eda-tbl tr.miss-flag td.miss-cell{background:#FBF0D6;color:#6E4E11;font-weight:700;}
.eda-tbl td.spark{font-family:ui-monospace,"DejaVu Sans Mono",Consolas,monospace;font-size:12px;
     color:var(--navy);letter-spacing:0;line-height:1;padding-top:5px;padding-bottom:5px;}
.eda-cap{font-size:10px;color:var(--muted);margin:5px 0 2px;font-weight:600;
     letter-spacing:.05em;text-transform:uppercase;}
.eda-tv{font-size:10.5px;line-height:1.5;color:var(--ink);}
.eda-tv .val{font-family:ui-monospace,Consolas,monospace;color:var(--navy);}
.eda-tv .cnt{color:var(--muted);font-size:10px;margin-left:4px;}
.eda-geo{font-size:11px;color:var(--ink);font-family:ui-monospace,Consolas,monospace;line-height:1.5;}
.eda-geo b{color:var(--navy);}
.eda-empty{font-size:11px;color:var(--muted);font-style:italic;padding:6px 0;}
/* Diff banner variant used on cards to flag EDA changes on --refresh. */
.eda-diff{background:#FBF0D6;border-left:3px solid #C9A227;border-radius:4px;
     padding:5px 8px;margin:4px 0;font-size:11px;color:#6E4E11;line-height:1.45;}
.eda-diff b{color:#6E4E11;}
/* Faceted browsing sidebar (only on the Products tabs). */
.products-shell{display:flex;gap:22px;align-items:flex-start;}
.products-main{flex:1;min-width:0;}
.facets{width:218px;flex:0 0 218px;position:sticky;top:8px;max-height:calc(100vh - 20px);
     overflow-y:auto;padding-right:4px;font-size:12px;}
.facets-head{display:flex;align-items:baseline;justify-content:space-between;margin:0 0 8px;}
.facets-head h3{font-family:Georgia,serif;color:var(--navy);font-size:14.5px;margin:0;}
.facet-clear{font-size:11px;color:#B8532F;font-weight:600;text-decoration:none;}
.facet-clear:hover{text-decoration:underline;}
.facet{border-top:1px solid var(--ice);padding:8px 0 6px;}
.facet h4{font-size:10px;letter-spacing:.11em;text-transform:uppercase;color:var(--muted);
     font-weight:800;margin:0 0 4px;}
.facet ul{list-style:none;padding:0;margin:0;}
.facet li{padding:0;}
.facet label{display:flex;align-items:center;gap:5px;padding:2px 4px;border-radius:4px;cursor:pointer;
     font-size:11.5px;color:var(--ink);}
.facet label:hover{background:var(--ice);}
.facet input[type=checkbox]{margin:0;transform:scale(0.9);cursor:pointer;}
.facet .lbl{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.facet .cnt{font-size:10.5px;color:var(--muted);font-variant-numeric:tabular-nums;
     background:var(--ice);border-radius:8px;padding:0 6px;line-height:15px;min-width:22px;text-align:center;}
.facet li.on label{background:var(--ice);font-weight:600;color:var(--navy);}
.facet li.empty{opacity:.4;}
.facet li.empty label{cursor:default;}
.facet .fhint{font-size:10.5px;color:var(--muted);font-style:italic;padding:2px 4px 0;}
.facet .fhint code{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;
     background:var(--ice);color:var(--navy);padding:0 4px;border-radius:3px;font-style:normal;}
@media(max-width:900px){.products-shell{flex-direction:column;} .facets{position:static;width:100%;flex:none;}}
</style></head><body>
<header>
  <div class="kicker">PRODUCT SCOPE &bull; GENERATED __DATE__ &bull; __CATNOTE__</div>
  <h1>What the Bureau publishes, and where our work has reached</h1>
  <p>Products are grouped by the Census catalog's own dataset flags, then by program, then by subject where a program spans more than one. Funnel stage and
  uncertainty notes are written only by the team; work depth and work-log findings are read from the repo.
  Repo: <b>__REPO__</b>.</p>
  <div class="tabs">__TABS__</div>
</header>
<div class="freshbar" data-generated-at="__GEN_ISO__" data-head-sha="__HEAD_SHA__">
  <span>Regenerated <span id="fresh-pill" class="pill">just now</span></span>
  <span>Rerun:</span>
  <span class="copy-cmd"><code>python tools/product_scope.py --repo .</code>
    <button data-copy="python tools/product_scope.py --repo .">Copy</button></span>
  <span class="sha" title="HEAD SHA at generation time">__HEAD_SHORT__ &bull; __BRANCH__</span>
</div>
<div class="wrap">__PANELS__</div>
<div id="qbar"><span><b id="qn">0</b> queued for probe</span>
  <button id="qdl">Download queue</button><button class="sec" id="qcl">Clear</button>
  <code>python tools\product_scope.py --repo . --probe-queue &lt;downloaded file&gt;</code></div>
<script>
/* --- Click-to-copy (reused by freshness bar, per-card action prompts, etc.) --- */
function _copyText(txt, btn){
  var done = function(){
    if(!btn) return;
    var old = btn.textContent; btn.textContent = 'Copied'; btn.classList.add('done');
    setTimeout(function(){ btn.textContent = old; btn.classList.remove('done'); }, 1200);
  };
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(txt).then(done, function(){});
  } else {
    var ta = document.createElement('textarea'); ta.value = txt;
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); done(); } catch(_){}
    document.body.removeChild(ta);
  }
}
document.addEventListener('click', function(e){
  var b = e.target.closest && e.target.closest('button[data-copy]');
  if(!b) return;
  e.preventDefault(); e.stopPropagation();
  _copyText(b.getAttribute('data-copy'), b);
});
/* --- Freshness pill: computes age from data-generated-at on every load --- */
(function(){
  var bar = document.querySelector('.freshbar'); if(!bar) return;
  var pill = document.getElementById('fresh-pill'); if(!pill) return;
  var iso = bar.getAttribute('data-generated-at'); if(!iso) return;
  var gen = new Date(iso); var age = (Date.now() - gen.getTime()) / 1000;
  if (isNaN(age) || age < 0) age = 0;
  var label;
  if (age < 90)              label = Math.max(1, Math.round(age)) + 's ago';
  else if (age < 3600)       label = Math.round(age / 60) + 'm ago';
  else if (age < 86400)      label = Math.round(age / 3600) + 'h ago';
  else                       label = Math.round(age / 86400) + 'd ago';
  pill.textContent = label;
  if      (age < 86400)      pill.classList.add('fresh');   /* < 24h */
  else if (age < 3 * 86400)  pill.classList.add('stale');   /* 24-72h */
  else                       pill.classList.add('old');     /* > 3d */
})();
document.querySelectorAll('.tab').forEach(function(t){
  t.addEventListener('click', function(){
    document.querySelectorAll('.tab').forEach(function(x){ x.classList.remove('on'); });
    document.querySelectorAll('.panel').forEach(function(x){ x.classList.remove('on'); });
    t.classList.add('on');
    document.getElementById('panel-' + t.dataset.k).classList.add('on');
  });
});
document.querySelectorAll('.pcard').forEach(function(c){
  c.addEventListener('click', function(){ c.closest('.prod').classList.toggle('folded'); });
});
document.querySelectorAll('.ghead').forEach(function(h){
  h.addEventListener('click', function(){ h.closest('.gsec').classList.toggle('gfold'); });
});
document.querySelectorAll('.phead').forEach(function(h){
  h.addEventListener('click', function(e){ e.stopPropagation(); h.closest('.psec').classList.toggle('pfold'); });
});
var QUEUE = [];
function qsync(){
  document.getElementById('qn').textContent = QUEUE.length;
  document.getElementById('qbar').style.display = QUEUE.length ? 'block' : 'none';
}
document.querySelectorAll('.qbox').forEach(function(l){
  l.addEventListener('click', function(e){ e.stopPropagation(); });
});
document.querySelectorAll('.qbox input').forEach(function(cb){
  cb.addEventListener('change', function(){
    var p = cb.dataset.p, i = QUEUE.indexOf(p);
    if (cb.checked && i === -1) QUEUE.push(p);
    if (!cb.checked && i !== -1) QUEUE.splice(i, 1);
    qsync();
  });
});
document.getElementById('qdl').addEventListener('click', function(){
  var blob = new Blob([JSON.stringify({paths: QUEUE}, null, 2)], {type: 'application/json'});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'probe_queue.json';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
});
document.getElementById('qcl').addEventListener('click', function(){
  QUEUE = [];
  document.querySelectorAll('.qbox input').forEach(function(c){ c.checked = false; });
  qsync();
});
/* --- Faceted browsing (Products tabs) ---
   Filters combine as AND across facets, OR within a facet (multi-select). Facet
   counts recompute against the intersection of the OTHER active facets, so the
   sidebar always shows "how many products would you have if you clicked this
   next". Falls back to the text filter above; both stack. */
function _prodPasses(p, filters, textQuery){
  if (textQuery && (p.dataset.s || '').indexOf(textQuery) === -1) return false;
  for (var f in filters){
    var set = filters[f];
    if (!set.size) continue;
    if (!set.has(p.dataset[f] || '')) return false;
  }
  return true;
}
function _applyFacets(panel){
  var filters = {};
  panel.querySelectorAll('.facet').forEach(function(fc){
    filters[fc.dataset.f] = new Set();
  });
  panel.querySelectorAll('.facet input:checked').forEach(function(cb){
    filters[cb.dataset.f].add(cb.value);
  });
  var textInput = panel.querySelector('.filter input');
  var q = textInput ? textInput.value.toLowerCase().trim() : '';
  var shown = 0;
  var prods = panel.querySelectorAll('.prod');
  prods.forEach(function(p){
    var ok = _prodPasses(p, filters, q);
    p.style.display = ok ? '' : 'none';
    if (ok) shown++;
  });
  panel.querySelectorAll('.facet').forEach(function(fc){
    var f = fc.dataset.f;
    fc.querySelectorAll('li').forEach(function(li){
      var v = li.dataset.v;
      var n = 0;
      prods.forEach(function(p){
        var passes = true;
        for (var ff in filters){
          if (ff === f) continue;
          var set = filters[ff];
          if (set.size && !set.has(p.dataset[ff] || '')) { passes = false; break; }
        }
        if (passes && q && (p.dataset.s || '').indexOf(q) === -1) passes = false;
        if (passes && (p.dataset[f] || '') === v) n++;
      });
      li.querySelector('.cnt').textContent = n;
      var checked = li.querySelector('input:checked');
      li.classList.toggle('on', !!checked);
      li.classList.toggle('empty', n === 0 && !checked);
    });
  });
  var anyActive = Object.keys(filters).some(function(k){ return filters[k].size > 0; });
  var clear = panel.querySelector('.facet-clear');
  if (clear) clear.style.display = anyActive ? '' : 'none';
  panel.querySelectorAll('.psec').forEach(function(ps){
    var any = Array.prototype.some.call(ps.querySelectorAll('.prod'), function(p){ return p.style.display !== 'none'; });
    ps.style.display = any ? '' : 'none';
  });
  panel.querySelectorAll('.gsec').forEach(function(g){
    var any = Array.prototype.some.call(g.querySelectorAll('.prod'), function(p){ return p.style.display !== 'none'; });
    g.style.display = any ? '' : 'none';
  });
  var nh = panel.querySelector('.nohit'); if (nh) nh.style.display = shown ? 'none' : 'block';
  var c = panel.querySelector('.fcnt');   if (c) c.textContent = shown + ' shown';
}
document.querySelectorAll('.facet input').forEach(function(cb){
  cb.addEventListener('change', function(){ _applyFacets(cb.closest('.panel')); });
});
document.querySelectorAll('.facet-clear').forEach(function(a){
  a.addEventListener('click', function(e){
    e.preventDefault();
    var panel = a.closest('.panel');
    panel.querySelectorAll('.facet input:checked').forEach(function(cb){ cb.checked = false; });
    _applyFacets(panel);
  });
});
document.querySelectorAll('.filter input').forEach(function(inp){
  inp.addEventListener('input', function(){
    var q = inp.value.toLowerCase().trim();
    var panel = inp.closest('.panel'), shown = 0;
    /* If any facet checkboxes are active, defer to the facet applier so text+facets combine. */
    if (panel.querySelector('.facet input:checked')) { _applyFacets(panel); return; }
    panel.querySelectorAll('.prod').forEach(function(p){
      var hit = !q || p.dataset.s.indexOf(q) !== -1;
      p.style.display = hit ? '' : 'none';
      if (hit) shown++;
    });
    panel.querySelectorAll('.psec').forEach(function(ps){
      var any = Array.prototype.some.call(ps.querySelectorAll('.prod'), function(p){ return p.style.display !== 'none'; });
      ps.style.display = any ? '' : 'none';
      if (q && any) ps.classList.remove('pfold');
    });
    panel.querySelectorAll('.gsec').forEach(function(g){
      var any = Array.prototype.some.call(g.querySelectorAll('.prod'), function(p){ return p.style.display !== 'none'; });
      g.style.display = any ? '' : 'none';
      if (q && any) g.classList.remove('gfold');
    });
    var nh = panel.querySelector('.nohit'); if (nh) nh.style.display = shown ? 'none' : 'block';
    var c = panel.querySelector('.fcnt');   if (c) c.textContent = shown + ' shown';
  });
});
</script>
<footer>product_scope.py &bull; re-run before each biweekly &bull; --online refreshes the catalog &bull;
tabs come from the catalog's own dataset flags; subjects are matched from product titles (SUBJECTS in this file, editable) &bull; stages and uncertainty notes are written only
by the team in product_review.json &bull; work depth and work-log findings are read from the repo.</footer>
</body></html>"""

def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _vint(f):
    v = f["vintages"]
    if len(v) > 1: return f"{v[0]}–{v[-1]}"
    return str(v[0]) if v else EMDASH

def product_facet_values(f, review, work, probes, top_families):
    """Facet metadata for one product family - emitted as data-* on the .prod card
    and consumed by the sidebar JS to filter and recount without a page reload.

    Kept small on purpose: adding a facet here + a facet block in build_kind_panel
    is all it takes to make a new filter live in the UI.
    """
    r = review.get(f["path"], {})
    st = r.get("stage", "cataloged")
    w = work.get(f["product"], {}) if f["product"] else {}
    ws = w.get("status", 0)
    family = f.get("group") or ""
    fbucket = family if family in top_families else "Other"
    role = effective_role(r)   # empty when composite_role_note is missing
    return {
        "stage":     st,
        "family":    family,
        "fbucket":   fbucket,
        "agency":    "U.S. Census Bureau",   # only agency in the current catalog
        "evidence":  "yes" if ws > 0 else "no",
        "probe":     "yes" if probes.get(f["path"], {}).get("ok") else "no",
        "validated": "yes" if ws >= 4 else "no",
        "role":      role or "(unset)",
    }

FACET_DEFS = [
    ("stage",     "Status",              None),   # None -> use display order from below
    ("fbucket",   "Family",              "count"), # sort by count desc
    ("agency",    "Agency",              "count"),
    ("evidence",  "Has repo evidence",   None),
    ("probe",     "Has API probe",       None),
    ("validated", "Notebook validated",  None),
    ("role",      "Composite role",      "count"),
]
FACET_ORDER = {
    "stage":     ["focus", "candidate", "reviewed", "cataloged", "set-aside"],
    "evidence":  ["yes", "no"],
    "probe":     ["yes", "no"],
    "validated": ["yes", "no"],
}
FACET_VALUE_LABELS = {
    "stage": STAGE_LABELS,
    "evidence":  {"yes": "yes", "no": "no"},
    "probe":     {"yes": "yes", "no": "no"},
    "validated": {"yes": "yes", "no": "no"},
    "role":      {**COMPOSITE_ROLE_LABELS, "(unset)": "(unset)"},
}

SNAPSHOT_FILE = ".product_scope_last_run.json"

# ============================================================================
# COMPOSITE CODE REFERENCES (feature #6)
# ============================================================================
# The three composite/allocation/cv-model modules live only on the unmerged
# origin/JL_Work_Tree branch today. We AST-parse them straight out of that
# branch (git show, no worktree, no checkout) to surface, per product, the
# exact file:line where the composite code references it.
#
# Machine-derived only. This does not assign composite_role - a human does
# that, in product_review.json (feature #7).

JL_BRANCH = "origin/JL_Work_Tree"
JL_FILES  = ["analysis/composite.py", "analysis/cv_model.py", "analysis/alloc.py"]

# Which composite/analysis symbols map to which tracked products. Kept
# separate from PRODUCT_MATCH so the composite-refs pass never widens
# ordinary evidence detection.
COMPOSITE_REF_MAP = [
    (re.compile(r"^analysis\.acs\b"),        "ACS 5-year"),
    (re.compile(r"^analysis\.alloc\b"),      "Allocation analysis"),
    (re.compile(r"^analysis\.cv_model\b"),   "CV driver model"),
    (re.compile(r"^analysis\.composite\b"),  "Composite prototype"),
    (re.compile(r"^analysis\.dhc\b"),        "2020 DHC"),
]

CENSUS_PATH_RE = re.compile(r"^[a-z]+/[a-z0-9_]+$")

def fetch_jl_file(repo: Path, path: str):
    """git show origin/JL_Work_Tree:<path>. Returns str, or None if the branch
    is missing / the file doesn't exist on it (silent - the tool must still run
    in a clone that only has main)."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "show", f"{JL_BRANCH}:{path}"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return r.stdout
    except Exception:
        pass
    return None

def _collect_ast_symbols(src):
    """Walk one file's AST. Returns list of (symbol, lineno, kind) tuples,
    or None on syntax error. Kinds: 'import', 'call', 'string'."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    syms = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names: syms.append((a.name, n.lineno, "import"))
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            for a in n.names:
                nm = f"{base}.{a.name}" if base else a.name
                syms.append((nm, n.lineno, "import"))
        elif isinstance(n, ast.Call):
            fn = n.func
            nm = (fn.attr if isinstance(fn, ast.Attribute) else
                  fn.id  if isinstance(fn, ast.Name)      else "")
            if nm: syms.append((nm, getattr(n, "lineno", 0), "call"))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            v = n.value
            if v and len(v) < 200:
                syms.append((v, getattr(n, "lineno", 0), "string"))
    return syms

def build_jl_refs(repo: Path, fams):
    """Parse composite/cv_model/alloc from origin/JL_Work_Tree. Returns
       ({key: [refs]}, {file: error_msg}).

    Keys are either:
      - a catalog path (like 'acs/acs5') for a direct string-literal match
      - a tracked product name (like 'CV driver model') for a symbol match
        via COMPOSITE_REF_MAP

    Each ref is {"file","path","line","symbol","kind"}. Rendering code merges
    both keying styles when populating a single card.
    """
    refs = {}
    errors = {}
    catalog_paths = set(fams.keys())
    files_ok = 0
    for jl_path in JL_FILES:
        src = fetch_jl_file(repo, jl_path)
        if src is None:
            errors[jl_path] = f"unavailable (branch {JL_BRANCH!r} not fetched or file missing)"
            continue
        syms = _collect_ast_symbols(src)
        if syms is None:
            errors[jl_path] = "AST parse failed (WIP syntax?)"
            print(f"  jl-refs: WARNING - could not parse {jl_path} (skipped)", file=sys.stderr)
            continue
        files_ok += 1
        basename = jl_path.rsplit("/", 1)[-1]
        for sym, ln, kind in syms:
            # (a) direct string literal that IS a catalog path
            if kind == "string" and CENSUS_PATH_RE.match(sym) and sym in catalog_paths:
                refs.setdefault(sym, []).append({
                    "file": basename, "path": jl_path, "line": ln,
                    "symbol": sym, "kind": kind})
                continue
            # (b) tracked-product match via COMPOSITE_REF_MAP
            for pat, prod in COMPOSITE_REF_MAP:
                if pat.search(sym):
                    refs.setdefault(prod, []).append({
                        "file": basename, "path": jl_path, "line": ln,
                        "symbol": sym, "kind": kind})
                    break
    # Dedup by (file, line) per key so an `from X import A, B` (both firing
    # the same product match at the same lineno) collapses to one visible ref.
    # First occurrence wins; sort by file then line for stable rendering.
    for key, hits in refs.items():
        seen = set(); uniq = []
        for h in hits:
            k = (h["file"], h["line"])
            if k in seen: continue
            seen.add(k); uniq.append(h)
        uniq.sort(key=lambda h: (h["file"], h["line"]))
        refs[key] = uniq
    if files_ok:
        print(f"  jl-refs: parsed {files_ok}/{len(JL_FILES)} composite modules; "
              f"{len(refs)} product(s)/family(ies) referenced")
    return refs, errors

def _card_jl_refs_for(f, jl_refs):
    """Merge string-literal (catalog-path) hits and symbol (product) hits for
    one product card. Returns a list of refs (possibly empty)."""
    out = list(jl_refs.get(f["path"], []))
    if f.get("product"):
        out += jl_refs.get(f["product"], [])
    return out

# ============================================================================
# DIVERGENCE FLAG (feature #8)
# ============================================================================
# Cross-references machine-derived composite code refs (#6) against the
# human-declared composite_role (#7). Two failure modes:
#   - code references a product but no role is declared for it
#   - a role is declared but the code doesn't reference the product
# Both surface on the affected card AND on a Home-tab summary so the team
# sees the full list in one place.

def compute_divergences(fams, review, jl_refs):
    """Returns two lists of dicts:
       referenced_no_role: [{path, ref_count, ref_files}]
       role_no_reference:  [{path, role, note}]
    """
    ref_no_role = []
    role_no_ref = []
    for path, f in sorted(fams.items()):
        r = review.get(path, {}) or {}
        role = effective_role(r)
        refs = _card_jl_refs_for(f, jl_refs)
        if refs and not role:
            files = sorted({x["file"] for x in refs})
            ref_no_role.append({"path": path, "ref_count": len(refs), "ref_files": files})
        elif role and not refs:
            role_no_ref.append({"path": path, "role": role,
                                "note": (r.get("composite_role_note") or "").strip()})
    return {"referenced_no_role": ref_no_role, "role_no_reference": role_no_ref}

def card_divergence_banners(f, r, jl_refs):
    """Return card-level divergence affordances (same shape as _affordances)."""
    out = []
    role = effective_role(r)
    refs = _card_jl_refs_for(f, jl_refs)
    if refs and not role:
        files = sorted({x["file"] for x in refs})
        out.append({"tone": "amber",
                    "text": f"Referenced in composite code ({', '.join(files)}) but no "
                            f"composite_role declared. Set one in product_review.json:",
                    "cmd":  None})
    elif role and not refs:
        out.append({"tone": "amber",
                    "text": f"Declared as {role!r} but not referenced in any composite module. "
                            "Either the role is stale or the composite hasn't wired this product yet.",
                    "cmd":  None})
    return out

def load_snapshot(repo: Path):
    """Read the previous run's snapshot if it exists (written by feature #5).

    Returned shape:
      {"head_sha": "...", "generated_at": "ISO", "products": {path: {...}}}
    None on first-ever run or when the file is missing/corrupt.
    """
    p = repo / SNAPSHOT_FILE
    if not p.exists(): return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def build_snapshot(fams, review, work, probes, git):
    """Snapshot of the fields the diff tracks - one entry per catalog family.

    Kept intentionally slim (stage / evidence hits / probe presence / composite
    role) so the .product_scope_last_run.json file stays under 100 KB on the
    ~570-family catalog. Full data lives in product_review.json / probes /
    the evidence engine - the snapshot exists only so successive runs can diff.
    """
    prods = {}
    for path, f in fams.items():
        r = review.get(path, {}) or {}
        w = work.get(f.get("product"), {}) if f.get("product") else {}
        pr = probes.get(path, {}) or {}
        prods[path] = {
            "stage":           r.get("stage", "cataloged"),
            "evidence_count":  int(w.get("hit_count", 0)),
            "has_probe":       bool(pr.get("ok")),
            "composite_role":  effective_role(r),   # note-required rule enforced
            "head_sha":        git.get("head_sha", "") if git else "",
        }
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head_sha":     git.get("head_sha", "") if git else "",
        "products":     prods,
    }

def save_snapshot(repo: Path, snap):
    """Write .product_scope_last_run.json in a stable, deterministic form."""
    p = repo / SNAPSHOT_FILE
    ordered = dict(snap); ordered["products"] = dict(sorted(snap.get("products", {}).items()))
    p.write_text(json.dumps(ordered, indent=2), encoding="utf-8")

def compute_diff(prev, curr):
    """Product-level diff between two snapshots.

    Returns:
      {"is_baseline": bool, "generated_at_prev": str,
       "totals": {"new_evidence_by_family": {family: N}, "status_changes": N,
                  "new_probes": N, "role_changes": N,
                  "added_products": N, "removed_products": N},
       "changes": [{"path": p, "kind": "status"|"evidence"|"probe"|"role"|"added"|"removed",
                    "old": ..., "new": ...}, ...]}
    """
    if not prev:
        return {"is_baseline": True, "generated_at_prev": None,
                "totals": {}, "changes": []}
    pp = prev.get("products", {}) or {}
    cp = curr.get("products", {}) or {}
    changes = []
    new_ev_by_family, status_changes, new_probes, role_changes = {}, 0, 0, 0
    added, removed = 0, 0
    all_paths = sorted(set(pp) | set(cp))
    for path in all_paths:
        p_row = pp.get(path)
        c_row = cp.get(path)
        if p_row is None and c_row is not None:
            added += 1
            changes.append({"path": path, "kind": "added", "old": None, "new": c_row.get("stage")})
            continue
        if p_row is not None and c_row is None:
            removed += 1
            changes.append({"path": path, "kind": "removed", "old": p_row.get("stage"), "new": None})
            continue
        if p_row.get("stage") != c_row.get("stage"):
            status_changes += 1
            changes.append({"path": path, "kind": "status", "old": p_row.get("stage"), "new": c_row.get("stage")})
        d = int(c_row.get("evidence_count", 0)) - int(p_row.get("evidence_count", 0))
        if d != 0:
            # Bucket by family (the coarse label users recognise) for the headline.
            fam = path.split("/")[0]
            new_ev_by_family[fam] = new_ev_by_family.get(fam, 0) + d
            changes.append({"path": path, "kind": "evidence",
                            "old": p_row.get("evidence_count", 0), "new": c_row.get("evidence_count", 0)})
        if bool(p_row.get("has_probe")) != bool(c_row.get("has_probe")):
            if c_row.get("has_probe"): new_probes += 1
            changes.append({"path": path, "kind": "probe",
                            "old": p_row.get("has_probe"), "new": c_row.get("has_probe")})
        if (p_row.get("composite_role") or "") != (c_row.get("composite_role") or ""):
            role_changes += 1
            changes.append({"path": path, "kind": "role",
                            "old": p_row.get("composite_role", ""), "new": c_row.get("composite_role", "")})
    return {
        "is_baseline": False,
        "generated_at_prev": prev.get("generated_at"),
        "totals": {
            "new_evidence_by_family": new_ev_by_family,
            "status_changes":         status_changes,
            "new_probes":             new_probes,
            "role_changes":           role_changes,
            "added_products":         added,
            "removed_products":       removed,
        },
        "changes": changes,
    }

def build_diff_banner(diff):
    """Home-tab 'Since last regeneration' banner. Baseline mode on first run."""
    if diff.get("is_baseline"):
        return ('<div class="diff-banner baseline">'
                '<b>Baseline snapshot recorded.</b> Diff will appear on the next regeneration.'
                '</div>')
    t = diff.get("totals", {})
    new_ev = sum(t.get("new_evidence_by_family", {}).values())
    parts = []
    if new_ev:
        by_fam = t.get("new_evidence_by_family", {})
        # Only surface positive family additions in the headline; drops go into details.
        pos = [(fam, n) for fam, n in sorted(by_fam.items(), key=lambda kv: -kv[1]) if n > 0]
        if pos:
            bits = ", ".join(f"{fam} ×{n}" for fam, n in pos[:5])
            parts.append(f"<b>+{sum(n for _, n in pos)} new evidence hits</b> ({bits})")
    if t.get("status_changes"):
        parts.append(f"<b>{t['status_changes']}</b> status change" + ("s" if t['status_changes'] != 1 else ""))
    if t.get("new_probes"):
        parts.append(f"<b>{t['new_probes']}</b> new probe" + ("s" if t['new_probes'] != 1 else ""))
    if t.get("role_changes"):
        parts.append(f"<b>{t['role_changes']}</b> composite-role change" + ("s" if t['role_changes'] != 1 else ""))
    if t.get("added_products"):
        parts.append(f"<b>+{t['added_products']}</b> newly catalogued")
    if t.get("removed_products"):
        parts.append(f"<b>-{t['removed_products']}</b> removed from catalog")
    if not parts:
        headline = "No changes since the last regeneration."
    else:
        headline = "Since last regeneration: " + ", ".join(parts) + "."
    # Details list (collapsible) - product-level, in stable order.
    detail_rows = []
    for c in diff.get("changes", []):
        kind = c["kind"]; old = c.get("old"); new = c.get("new")
        if kind == "evidence":
            lbl = f"evidence hits {old} → {new}"
        elif kind == "status":
            lbl = f"status {old} → {new}"
        elif kind == "probe":
            lbl = "probe added" if new else "probe removed"
        elif kind == "role":
            o = old or "(unset)"; n = new or "(unset)"
            lbl = f"composite_role {o} → {n}"
        elif kind == "added":
            lbl = f"newly catalogued (initial stage: {new})"
        elif kind == "removed":
            lbl = f"removed from catalog (was: {old})"
        else:
            lbl = kind
        detail_rows.append(f'<li><code>{_esc(c["path"])}</code> — {_esc(lbl)}</li>')
    details = ""
    if detail_rows:
        details = ('<details><summary>Show '
                   f'{len(detail_rows)} product-level change'
                   + ("s" if len(detail_rows) != 1 else "")
                   + '</summary><ul class="diff-list">'
                   + "".join(detail_rows) + '</ul></details>')
    prev_when = diff.get("generated_at_prev") or ""
    when_bit = (f'<div class="diff-when">Previous snapshot: {_esc(prev_when)}</div>' if prev_when else "")
    return f'<div class="diff-banner"><div class="diff-headline">{headline}</div>{when_bit}{details}</div>'

# --- Contextual affordances ---------------------------------------------------
# The design principle is behavior over description: every UI element either
# shows state or offers an action. These helpers turn per-product state into
# copyable commands and JSON snippets - never paragraphs of tutorial text.

def _affordances(f, r, ws, has_probe, git, snapshot):
    """Return a list of {"tone", "text", "cmd"} banners for one product card.

    Rules (documented in the redesign spec):
      1. No repo evidence           -> probe command
      2. Candidate without a probe  -> amber probe command
      3. FOCUS + snapshot's captured SHA != current HEAD -> regen command
      4. Still cataloged            -> nudge to edit product_review.json
    """
    path = f["path"]
    stage = r.get("stage", "cataloged")
    out = []
    probe_cmd = f'python tools/product_scope.py --repo . --probe {path}'
    regen_cmd = 'python tools/product_scope.py --repo .'
    if ws == 0:
        out.append({"tone": "info",
                    "text": "No repo evidence yet - ask the API what this product publishes:",
                    "cmd":  probe_cmd})
    if stage == "candidate" and not has_probe:
        out.append({"tone": "amber",
                    "text": "Candidate without a probe. Probe first, then document what it publishes:",
                    "cmd":  probe_cmd})
    if stage == "focus" and snapshot:
        snap_head = (snapshot.get("head_sha") or "")
        cur_head  = (git.get("head_sha") or "") if git else ""
        prods = snapshot.get("products", {}) or {}
        prev = prods.get(path, {}) if isinstance(prods, dict) else {}
        prev_sha = prev.get("head_sha") or snap_head
        if prev_sha and cur_head and prev_sha != cur_head:
            out.append({"tone": "amber",
                        "text": f"Evidence for this FOCUS product was captured at {prev_sha[:7]}; "
                                f"HEAD is now {cur_head[:7]}. Regenerate to refresh:",
                        "cmd":  regen_cmd})
    if stage == "cataloged":
        # Not a warning - just a nudge with the exact JSON key to open.
        out.append({"tone": "nudge",
                    "text": f'Still cataloged. Set a Status by editing product_review.json at key "{path}".',
                    "cmd":  None})
    return out

def _affordance_html(banners):
    """Render a list of affordance banners into the card's Actions bcard."""
    if not banners: return ""
    rows = []
    for b in banners:
        cmd = b.get("cmd")
        line = f'<div class="aff-text">{_esc(b["text"])}</div>'
        if cmd:
            line += (f'<span class="copy-cmd light"><code>{_esc(cmd)}</code>'
                     f'<button data-copy="{_esc(cmd)}">Copy</button></span>')
        rows.append(f'<div class="aff-row aff-{_esc(b["tone"])}">{line}</div>')
    return ('<div class="branch"><div class="bcard"><div class="blabel">Suggested next step</div>'
            + "".join(rows) + '</div></div>')

def _fmt_num(v):
    """Format a numeric summary value for the EDA table: floats compact,
    ints without trailing .0, none/inf handled. Kept small on purpose so the
    table stays scannable."""
    try:
        if v is None: return ""
        fv = float(v)
        if fv != fv: return ""       # NaN
        if abs(fv) >= 1e12: return f"{fv:.2e}"
        if fv == int(fv):  return f"{int(fv):,}"
        if abs(fv) >= 1000: return f"{fv:,.1f}"
        if abs(fv) >= 1:   return f"{fv:.3g}"
        return f"{fv:.3g}"
    except Exception:
        return str(v)

def render_eda_card_section(f, cache_entry, diff_note=None):
    """HTML for the 'EDA snapshot' branch on one product card.

    cache_entry: dict from scope_data_cache.json (may be None -> renders the
                 'not sampled yet' state).
    diff_note:   optional string describing changes since a previous sample
                 (produced by #6 on --refresh). Rendered as a small amber
                 banner above the table when present.

    Consistent with the probe branch's structure: header + headline + tables.
    Never editorialises: reports what the data looks like and lets the >30%
    missing highlight speak for itself.
    """
    pill = sample_age_pill(cache_entry)
    src_url = (cache_entry or {}).get("source_url", "")
    if cache_entry:
        shape = (cache_entry.get("shape") or [0, 0])
        rows, cols = int(shape[0]), int(shape[1])
        sha = (cache_entry.get("sha_at_sample") or "")[:7]
        shape_str = f"{rows:,} rows &times; {cols:,} cols"
    else:
        shape_str = ""
        sha = ""

    head_bits = [f'<span class="pill sample-{_esc(pill["tone"])}">{_esc(pill["label"])}</span>']
    if shape_str:
        head_bits.append(f'<span class="eda-shape">{shape_str}</span>')
    if sha:
        head_bits.append(f'<span class="eda-shape" title="repo HEAD at sample time">'
                         f'@ {_esc(sha)}</span>')
    if src_url:
        head_bits.append(f'<span class="eda-src"><a href="{_esc(src_url)}" target="_blank" '
                         f'rel="noopener" title="{_esc(src_url)}">{_esc(src_url)}</a></span>')
    header = '<div class="eda-head">' + "".join(head_bits) + '</div>'

    if not cache_entry:
        body = ('<div class="eda-empty">No sample cached yet. Run '
                '<code>python tools/product_scope.py --repo . --sample --product '
                + _esc(f["path"]) + '</code> to fetch one.</div>')
        return ('<div class="branch"><div class="bcard"><div class="blabel">EDA snapshot</div>'
                + header + body + '</div></div>')

    parts = [header]
    if diff_note:
        parts.append(f'<div class="eda-diff">{_esc(diff_note)}</div>')

    # ---- Column-level table (dtype + missingness) ----
    cols_dict = cache_entry.get("columns", {}) or {}
    if cols_dict:
        parts.append('<div class="eda-cap">Columns</div>')
        rows_html = []
        for name, col in cols_dict.items():
            flag = " miss-flag" if col.get("flag_missing_over_30") else ""
            miss = f'{col.get("missing_pct", 0)}%'
            rows_html.append(
                f'<tr class="{flag.strip()}">'
                f'<td class="mono">{_esc(name)}</td>'
                f'<td class="mono">{_esc(col.get("dtype",""))}</td>'
                f'<td class="mono miss-cell">{_esc(miss)}</td>'
                f'<td class="mono">{col.get("cardinality","")}</td>'
                f'</tr>')
        parts.append(
            '<table class="eda-tbl"><tr><th>column</th><th>dtype</th>'
            '<th>missing</th><th>distinct</th></tr>'
            + "".join(rows_html) + '</table>')

    # ---- Numeric summaries ----
    numeric_cols = [(n, c["numeric"]) for n, c in cols_dict.items() if c.get("numeric")]
    if numeric_cols:
        parts.append('<div class="eda-cap">Numeric summaries</div>')
        rows_html = []
        for name, num in numeric_cols:
            rows_html.append(
                f'<tr><td class="mono">{_esc(name)}</td>'
                f'<td class="mono">{_fmt_num(num.get("min"))}</td>'
                f'<td class="mono">{_fmt_num(num.get("max"))}</td>'
                f'<td class="mono">{_fmt_num(num.get("mean"))}</td>'
                f'<td class="mono">{_fmt_num(num.get("median"))}</td></tr>')
        parts.append(
            '<table class="eda-tbl"><tr><th>column</th><th>min</th><th>max</th>'
            '<th>mean</th><th>median</th></tr>'
            + "".join(rows_html) + '</table>')

    # ---- Categorical top-5 (only for cols with >= EDA_MIN_CARD_TOP distinct values) ----
    cat_cols = [(n, c["top_values"]) for n, c in cols_dict.items() if c.get("top_values")]
    if cat_cols:
        parts.append('<div class="eda-cap">Top values (top 5)</div>')
        for name, tvs in cat_cols:
            bits = " &middot; ".join(
                f'<span class="val">{_esc(v)}</span>'
                f'<span class="cnt">{c} ({pct}%)</span>'
                for v, c, pct in tvs)
            parts.append(f'<div class="eda-tv"><b>{_esc(name)}:</b> {bits}</div>')

    # ---- Geography breakdown ----
    geo = cache_entry.get("geography", {}) or {}
    if geo:
        parts.append('<div class="eda-cap">Geography</div>')
        bits = []
        for gc, info in geo.items():
            bits.append(f'<b>{_esc(gc)}</b>: '
                        f'{int(info.get("distinct_populated", 0)):,} distinct')
        parts.append('<div class="eda-geo">' + " &middot; ".join(bits) + '</div>')

    # ---- Sparklines ----
    sparks = cache_entry.get("sparklines", {}) or {}
    if sparks:
        parts.append('<div class="eda-cap">Distribution shape (top numeric)</div>')
        rows_html = []
        for name, bars in sparks.items():
            num = (cols_dict.get(name) or {}).get("numeric") or {}
            rng = ""
            if "min" in num and "max" in num:
                rng = f"{_fmt_num(num['min'])} &ndash; {_fmt_num(num['max'])}"
            rows_html.append(
                f'<tr><td class="mono">{_esc(name)}</td>'
                f'<td class="spark">{_esc(bars)}</td>'
                f'<td class="mono">{rng}</td></tr>')
        parts.append(
            '<table class="eda-tbl"><tr><th>column</th><th>histogram</th>'
            '<th>range</th></tr>'
            + "".join(rows_html) + '</table>')

    return ('<div class="branch"><div class="bcard"><div class="blabel">EDA snapshot</div>'
            + "".join(parts) + '</div></div>')

def product_row(f, review, work, probes, ctx=None):
    ctx = ctx or {}
    top_families = ctx.get("top_families", set())
    git = ctx.get("git") or {}
    snapshot = ctx.get("snapshot")
    jl_refs = ctx.get("jl_refs") or {}
    jl_errors = ctx.get("jl_errors") or {}
    facets = product_facet_values(f, review, work, probes, top_families)
    r = review.get(f["path"], {})
    st = r.get("stage", "cataloged")
    w = work.get(f["product"], {}) if f["product"] else {}
    ws = w.get("status", 0)
    finds = [x for x in FINDINGS if x["family"] == f["path"]]
    chipcolor = "#F5D77A" if st == "focus" else "#1F2A5C"

    mini = (f'<span class="stagechip" style="background:{STAGE_COLORS[st]};color:{chipcolor}">'
            f'{STAGE_LABELS[st]}</span><span class="workchip w{ws}">{STATUS_LABELS[ws]}</span>')
    role = effective_role(r)  # feature #7: human-set, note required
    if role:
        role_lbl = COMPOSITE_ROLE_LABELS.get(role, role)
        mini += f'<span class="rolechip" title="{_esc(r.get("composite_role_note",""))}">{_esc(role_lbl)}</span>'
    if finds:
        plural = "s" if len(finds) > 1 else ""
        mini += f'<span class="fcount">{len(finds)} insight{plural}</span>'
    probed = " probed" if probes.get(f["path"], {}).get("ok") else ""
    node = (f'<div class="pcard" style="border-left-color:{STAGE_COLORS[st]}">'
            f'<label class="qbox{probed}" title="queue this product for a probe">'
            f'<input type="checkbox" data-p="{_esc(f["path"])}"> probe</label>'
            f'<div class="path">{_esc(f["path"])}</div>'
            f'<div class="title">{_esc(f["title"][:96])}</div>'
            f'<div class="title" style="opacity:.75">{_esc(f["group"])} &bull; {_vint(f)}</div>'
            f'<div class="mini">{mini}</div></div>')

    branches = []
    # Contextual affordances first: state-driven copyable commands that fill
    # what would otherwise be a blank section. Rules in _affordances().
    has_probe = bool(probes.get(f["path"], {}).get("ok"))
    banners = _affordances(f, r, ws, has_probe, git, snapshot)
    banners += card_divergence_banners(f, r, jl_refs)   # feature #8
    aff = _affordance_html(banners)
    if aff: branches.append(aff)
    unc = r.get("uncertainty_metrics", "")
    unc_html = (f'<div class="unc">{_esc(unc)}</div>' if unc else
                '<div class="unc todo">Not yet documented. Documenting what this product publishes IS '
                'the review: fill uncertainty_metrics in product_review.json.</div>')
    branches.append('<div class="branch"><div class="bcard"><div class="blabel">Uncertainty surface</div>'
                    + unc_html + '</div></div>')

    facts = [f'<span class="kindchip">{_esc(f["kind"])}</span>',
             f'<span class="kindchip">{_esc(f["group"])}</span>',
             f'<span class="meta">vintages {_vint(f)}</span>']
    if f.get("spatial"):
        facts.append('<span class="meta"> &bull; ' + _esc(sorted(f["spatial"])[0]) + '</span>')
    if f.get("doc"):
        facts.append('<span class="meta"> &bull; <a href="' + _esc(f["doc"]) + '">Bureau documentation</a></span>')
    d = f.get("desc") or ""
    tail = "..." if len(d) > 420 else ""
    dhtml = ('<div class="desc" style="margin-top:5px">' + _esc(d[:420]) + tail + '</div>') if d else ""
    branches.append('<div class="branch"><div class="bcard"><div class="blabel">From the Census catalog</div>'
                    + "".join(facts) + dhtml + '</div></div>')

    pr = probes.get(f["path"])
    if pr:
        cls = "unc" if pr.get("ok") else "unc todo"
        det = []
        if pr.get("ok"):
            if pr.get("allocation_groups"):
                det.append("allocation groups: " + ", ".join(pr["allocation_groups"][:12]))
            if pr.get("replicate_groups"):
                det.append("replicate groups: " + ", ".join(pr["replicate_groups"][:8]))
            if pr.get("queryable_without_parent"):
                det.append("queryable without a parent geography: "
                           + ", ".join(pr["queryable_without_parent"][:8]))
        dhtml = ('<div class="meta">' + _esc(" | ".join(det)) + '</div>') if det else ""
        branches.append(
            '<div class="branch"><div class="bcard"><div class="blabel">What the API reports</div>'
            f'<div class="{cls}">{_esc(probe_headline(pr))}</div>{dhtml}'
            f'<div class="inferred" style="color:var(--muted);font-style:normal">Retrieved from '
            f'variables.json and geography.json on {_esc(pr.get("probed", "?"))}. Counts only '
            f'{EMDASH} someone still has to read this and write the uncertainty description.</div>'
            '</div></div>')

    if ws > 0:
        boxes = "".join(f'<div class="kbox s{w.get("geos", {}).get(gl, 0)}">{gl}</div>' for gl in GEO_LEVELS)
        # Each receipt is a jump-to-source anchor; label is "file (line N)" or "file (cell N)".
        rc_parts = []
        for rc_item in w.get("receipts", []):
            lbl = receipt_label(rc_item)
            url = receipt_url(rc_item, git)
            if url:
                rc_parts.append(f'<a class="receipt-link" href="{_esc(url)}" target="_blank" rel="noopener">{_esc(lbl)}</a>')
            else:
                rc_parts.append(_esc(lbl))
        rc = "<br>".join(rc_parts)
        note = ('<div class="meta">note: ' + _esc(r["note"]) + '</div>') if r.get("note") else ""
        branches.append(
            f'<div class="branch"><div class="bcard"><div class="blabel">Our progress</div>'
            f'<span class="workchip w{ws}">{STATUS_LABELS[ws]}</span>'
            f'<div class="krow">{boxes}</div>'
            f'<div class="inferred">Levels we appear to have worked at, inferred from repo text '
            f'{EMDASH} a rough indicator, not a verified record.</div>{note}'
            f'<div class="receipts">{rc}</div></div></div>')
    else:
        note = (' note: ' + _esc(r["note"])) if r.get("note") else ""
        branches.append('<div class="branch"><div class="bcard"><div class="blabel">Our progress</div>'
                        f'<span class="nowork">No repo work yet.{note}</span></div></div>')

    # Phase 3 EDA snapshot - what the fetched data actually looks like. Only
    # renders when a sample has been taken (Candidate products without cache
    # get an affordance instead, see #8). Data cache is passed through ctx.
    data_cache = ctx.get("data_cache") or {}
    eda_entry = data_cache.get(f["path"])
    eda_diffs = ctx.get("eda_diffs") or {}
    if eda_entry:
        branches.append(render_eda_card_section(f, eda_entry, eda_diffs.get(f["path"])))

    # Composite code references (feature #6) - AST-derived hits from JL_Work_Tree.
    card_refs = _card_jl_refs_for(f, jl_refs)
    if card_refs:
        rows = []
        for ref in card_refs[:12]:
            url_r = {"path": ref["path"], "line": ref["line"], "file": ref["file"], "kind": "analysis"}
            url = receipt_url(url_r, {"github_slug": (git.get("github_slug") if git else ""),
                                       "branch": JL_BRANCH.split("/")[-1],
                                       "repo_abs": (git.get("repo_abs") if git else "")})
            lbl = f'{ref["file"]}:{ref["line"]}'
            symlbl = (ref["symbol"][:60] + ("..." if len(ref["symbol"]) > 60 else ""))
            link = (f'<a class="receipt-link" href="{_esc(url)}" target="_blank" rel="noopener">{_esc(lbl)}</a>'
                    if url else _esc(lbl))
            rows.append(f'<li>{link} — <span class="jl-sym">{_esc(symlbl)}</span> '
                        f'<span class="jl-kind">({ref["kind"]})</span></li>')
        note = ""
        if jl_errors:
            note = ('<div class="jl-parse-err">' +
                    "; ".join(f"parse error in {_esc(fp)} - try regenerating after next JL_Work_Tree update"
                              for fp in jl_errors) + '</div>')
        branches.append(
            '<div class="branch"><div class="bcard"><div class="blabel">Composite code references '
            '<span class="jl-src">(from JL_Work_Tree)</span></div>'
            f'<ul class="jl-refs">{"".join(rows)}</ul>{note}</div></div>')

    if finds:
        cards = "".join(
            '<div class="tk' + (" odd" if x["kind"] == "oddity" else "") + '">'
            f'<div class="tkh"><b>{_esc(x["stat"])}</b>{_esc(x["headline"])}<em>nb {x["nb"]}</em></div>'
            f'<div class="tkd">{_esc(x["detail"])}</div></div>' for x in finds)
        branches.append('<div class="branch"><div class="bcard"><div class="blabel">'
                        f'Curated insights ({len(finds)})</div>{cards}</div></div>')

    search = (f["path"] + " " + f["title"] + " " + f["group"] + " " + f["subject"]).lower()
    folded = "" if st == "focus" else " folded"
    facet_attrs = " ".join(f'data-{k}="{_esc(v)}"' for k, v in facets.items())
    return (f'<div class="prod{folded}" data-s="{_esc(search)}" data-path="{_esc(f["path"])}" '
            f'{facet_attrs}><div class="pnode">{node}</div>'
            f'<div class="branches">{"".join(branches)}</div></div>')

def build_facet_sidebar(prods, review, work, probes, top_families):
    """Left-column facet blocks for the Products tabs.

    For each facet we render every value present in this tab's product set, with
    its (current, unfiltered) count. When the user clicks a value the JS filters
    the cards AND rewrites every other facet's counts to reflect the intersection.
    """
    # Collect all facet values across the tab's products.
    rows = [product_facet_values(f, review, work, probes, top_families) for f in prods]
    blocks = []
    for key, label, sortmode in FACET_DEFS:
        vals = {}
        for r in rows:
            v = r.get(key, "")
            vals[v] = vals.get(v, 0) + 1
        if not vals: continue
        if key in FACET_ORDER:
            ordered = [v for v in FACET_ORDER[key] if v in vals]
            # any extras (defensive - a new stage etc.) sort at the end alphabetically
            ordered += sorted(v for v in vals if v not in FACET_ORDER[key])
        elif sortmode == "count":
            # keep "Other" last regardless of its count so the long-tail bucket is visually last
            ordered = sorted(vals, key=lambda v: (v == "Other", -vals[v], v))
        else:
            ordered = sorted(vals)
        items = []
        for v in ordered:
            n = vals[v]
            lbl = FACET_VALUE_LABELS.get(key, {}).get(v, v)
            items.append(
                f'<li data-v="{_esc(v)}"><label>'
                f'<input type="checkbox" data-f="{_esc(key)}" value="{_esc(v)}"> '
                f'<span class="lbl">{_esc(lbl)}</span>'
                f'<span class="cnt">{n}</span></label></li>')
        note = ""
        if key == "role" and set(vals.keys()) == {"(unset)"}:
            # Feature #7 not yet applied (nothing declared); leave a plain hint,
            # no static tutorial - just a nudge that this facet becomes live once
            # someone edits composite_role in product_review.json.
            note = '<div class="fhint">Set <code>composite_role</code> on a product to populate this facet.</div>'
        blocks.append(
            f'<div class="facet" data-f="{_esc(key)}">'
            f'<h4>{_esc(label)}</h4>'
            f'<ul>{"".join(items)}</ul>{note}</div>')
    return ('<aside class="facets"><div class="facets-head">'
            '<h3>Filter</h3><a class="facet-clear" href="#" style="display:none">Clear filters</a>'
            '</div>' + "".join(blocks) + '</aside>')

def build_kind_panel(kind, fams, review, work, probes, git=None, snapshot=None,
                     jl_refs=None, jl_errors=None, data_cache=None, eda_diffs=None):
    prods = [f for f in fams.values() if f["kind"] == kind]
    # Compute per-panel "top families" bucket for the Family facet.
    fam_counts = {}
    for f in prods: fam_counts[f["group"]] = fam_counts.get(f["group"], 0) + 1
    top_families = set(sorted(fam_counts, key=lambda g: -fam_counts[g])[:12])
    ctx = {"top_families": top_families, "git": git or {}, "snapshot": snapshot,
           "jl_refs": jl_refs or {}, "jl_errors": jl_errors or {},
           "data_cache": data_cache or {}, "eda_diffs": eda_diffs or {}}

    groups = {}
    for f in prods: groups.setdefault(f["group"], []).append(f)
    secs = []
    for g in sorted(groups, key=lambda x: (-len(groups[x]), x)):
        subs = {}
        for f in groups[g]: subs.setdefault(f["subject"], []).append(f)
        inner = []
        for sname in sorted(subs, key=lambda x: SUBJECT_ORDER.index(x) if x in SUBJECT_ORDER else 99):
            items = sorted(subs[sname], key=lambda x: x["path"])
            rows = "".join(product_row(f, review, work, probes, ctx) for f in items)
            if len(subs) == 1:
                inner.append(rows)          # single subject: skip a level that adds nothing
            else:
                inner.append(f'<div class="psec pfold"><div class="phead">{_esc(sname)} '
                             f'<em>{len(items)}</em></div>{rows}</div>')
        n = len(groups[g])
        tail = (f'{n} product{"s" if n != 1 else ""}' +
                (f' across {len(subs)} subjects' if len(subs) > 1 else ""))
        secs.append(f'<div class="gsec gfold"><div class="ghead">{_esc(g)} '
                    f'<em>{tail}</em></div>{"".join(inner)}</div>')
    sidebar = build_facet_sidebar(prods, review, work, probes, top_families)
    body = ('<div class="blurb">' + KIND_BLURB.get(kind, "") + '</div>'
            f'<div class="filter"><input type="text" placeholder="Filter {len(prods)} products '
            f'by path, title, subject or program..."><span class="fcnt">{len(prods)} shown</span></div>'
            '<div class="nohit">Nothing matches that filter.</div>' + "".join(secs))
    return ('<div class="products-shell">' + sidebar
            + f'<div class="products-main">{body}</div></div>')

def build_divergence_section(divergences):
    """Home-tab summary of composite-code vs composite_role mismatches (feature #8)."""
    a = divergences.get("referenced_no_role", [])
    b = divergences.get("role_no_reference",  [])
    if not a and not b:
        return ('<h2>Divergences <span style="font-size:12px;color:var(--muted);'
                'font-weight:400">(composite code vs. declared role)</span></h2>'
                '<div class="sub">Every product referenced by composite code has a declared '
                '<code>composite_role</code>, and every declared role points at code the '
                'composite actually touches. Nothing to reconcile.</div>')
    parts = ['<h2>Divergences <span style="font-size:12px;color:var(--muted);font-weight:400">'
             '(composite code vs. declared role)</span></h2>'
             '<div class="sub">Where machine-derived composite references (from JL_Work_Tree) '
             'and human-declared <code>composite_role</code> disagree. Reconcile in '
             '<code>product_review.json</code>, then regenerate.</div>']
    if a:
        parts.append('<div class="div-block"><div class="div-head">Referenced in composite code '
                     'but no <code>composite_role</code> declared</div><ul class="div-list">')
        for d in a:
            files = ", ".join(d["ref_files"])
            parts.append(f'<li><code>{_esc(d["path"])}</code> — {d["ref_count"]} hit(s) in {_esc(files)}</li>')
        parts.append('</ul></div>')
    if b:
        parts.append('<div class="div-block"><div class="div-head">Role declared but not '
                     'referenced in composite code</div><ul class="div-list">')
        for d in b:
            note = (" — " + d["note"]) if d["note"] else ""
            parts.append(f'<li><code>{_esc(d["path"])}</code> — declared as '
                         f'<b>{_esc(d["role"])}</b>{_esc(note)}</li>')
        parts.append('</ul></div>')
    return "".join(parts)

def build_home(fams, review, work, counts, worklog, notebooks, probes, git=None, diff=None, jl_refs=None, jl_errors=None, divergences=None):
    h = []
    if diff is not None:
        h.append(build_diff_banner(diff))
    h.append('<div class="funnel">'
             f'<div class="fstep"><b>{counts["cataloged"]}</b><span>cataloged<br>(the wide start)</span></div><div class="farrow">&rarr;</div>'
             f'<div class="fstep"><b>{counts["reviewed"]}</b><span>reviewed<br>(uncertainty documented)</span></div><div class="farrow">&rarr;</div>'
             f'<div class="fstep f-cand"><b>{counts["candidate"]}</b><span>candidates</span></div><div class="farrow">&rarr;</div>'
             f'<div class="fstep f-focus"><b>{counts["focus"]}</b><span>FOCUS</span></div>'
             f'<div class="fstep" style="margin-left:12px"><b>{counts["set-aside"]}</b><span>set aside</span></div></div>')

    kc = {}
    for f in fams.values(): kc[f["kind"]] = kc.get(f["kind"], 0) + 1
    h.append('<h2>The inventory</h2><div class="sub">Product families in the Census API catalog, split by the '
             "Bureau's own dataset flags. The split matters: published uncertainty exists on aggregate tables "
             "and does not exist on microdata.</div>"
             "<table class='rep'><tr><th>Type</th><th>Families</th><th>What that means here</th></tr>")
    for k in KINDS:
        if kc.get(k):
            h.append(f'<tr><td><b>{k}</b></td><td>{kc[k]}</td>'
                     f'<td>{_esc(KIND_BLURB.get(k, ""))}</td></tr>')
    h.append("</table>")

    h.append('<h2>What is in the repo</h2><div class="sub">Recomputed from the code and notebooks on every run, '
             "with receipts naming the file and cell or line. Never hand-set.</div>")
    if work:
        h.append("<table class='rep'><tr><th>Product</th><th>Work depth</th><th>Receipts</th></tr>")
        for prod in sorted(work, key=lambda p: (-work[p]["status"], p)):
            w = work[prod]
            rc_parts = []
            for r in w["receipts"]:
                lbl = receipt_label(r); url = receipt_url(r, git or {})
                if url: rc_parts.append(f'<a class="receipt-link" href="{_esc(url)}" target="_blank" rel="noopener">{_esc(lbl)}</a>')
                else:   rc_parts.append(_esc(lbl))
            h.append(f'<tr><td><b>{_esc(prod)}</b></td>'
                     f'<td><span class="workchip w{w["status"]}">{STATUS_LABELS[w["status"]]}</span></td>'
                     f'<td class="mono">{"<br>".join(rc_parts)}</td></tr>')
        h.append("</table>")
    else:
        h.append('<div class="nowork">No repo evidence found.</div>')

    if jl_refs or jl_errors:
        gh = (git or {}).get("github_slug") or ""
        h.append('<h2>Composite code references '
                 '<span style="font-size:12px;color:var(--muted);font-weight:400">(from JL_Work_Tree)</span></h2>'
                 '<div class="sub">AST-derived from the three composite/allocation/CV-model modules '
                 f"on <code>{_esc(JL_BRANCH)}</code>. Every hit is a line the composite code touches "
                 "a product we're tracking; use this to sanity-check which products the composite "
                 "actually depends on. Not merged to main yet.</div>")
        if jl_errors:
            errs = "; ".join(f"<code>{_esc(fp)}</code>: {_esc(m)}" for fp, m in jl_errors.items())
            h.append(f'<div class="unc todo" style="max-width:1020px">Parse issues: {errs}</div>')
        if jl_refs:
            h.append("<table class='rep'><tr><th>Referenced product / family</th>"
                     "<th>Hits</th><th>Locations</th></tr>")
            for key in sorted(jl_refs, key=lambda k: (-len(jl_refs[k]), k)):
                hits = jl_refs[key][:8]
                links = []
                for ref in hits:
                    url_r = {"path": ref["path"], "line": ref["line"], "file": ref["file"], "kind": "analysis"}
                    url = receipt_url(url_r, {"github_slug": gh,
                                               "branch": JL_BRANCH.split("/")[-1],
                                               "repo_abs": (git or {}).get("repo_abs", "")})
                    lbl = f'{ref["file"]}:{ref["line"]}'
                    if url:
                        links.append(f'<a class="receipt-link" href="{_esc(url)}" target="_blank" rel="noopener">{_esc(lbl)}</a>')
                    else:
                        links.append(_esc(lbl))
                h.append(f'<tr><td><b>{_esc(key)}</b></td>'
                         f'<td>{len(jl_refs[key])}</td>'
                         f'<td class="mono">{" &bull; ".join(links)}</td></tr>')
            h.append("</table>")

    if divergences is not None:
        h.append(build_divergence_section(divergences))

    if notebooks:
        h.append('<h2>Notebook health</h2><div class="sub">Read from the committed notebooks: whether execution '
                 "counts run in order, whether any cell stored an error, and how many assert statements the code "
                 "contains. This is what earns a Validated depth.</div>"
                 "<table class='rep'><tr><th>Notebook</th><th>Code cells</th><th>Ran in order</th>"
                 "<th>Errors</th><th>Asserts</th></tr>")
        for n in sorted(notebooks, key=lambda x: x["file"]):
            hh = n["health"]
            h.append(f'<tr><td class="mono">{_esc(n["file"])}</td><td>{hh["code_cells"]}</td>'
                     f'<td>{"yes" if hh["mono"] else "no"}</td><td>{hh["errors"]}</td>'
                     f'<td>{hh["asserts"]}</td></tr>')
        h.append("</table>")

    if FINDINGS:
        h.append(f'<h2>Curated insights ({len(FINDINGS)})</h2>'
                 '<div class="sub">Hand-written headline cards, edited in FINDINGS in product_scope.py. '
                 'Each also appears on its product card.</div>')
        for x in FINDINGS:
            odd = " odd" if x["kind"] == "oddity" else ""
            h.append(f'<div class="tk{odd}" style="max-width:1020px"><div class="tkh">'
                     f'<b>{_esc(x["stat"])}</b>{_esc(x["headline"])}'
                     f'<em>{_esc(x["family"])} &bull; nb {x["nb"]}</em></div>'
                     f'<div class="tkd">{_esc(x["detail"])}</div></div>')

    total = sum(len(e["items"]) for e in worklog)
    h.append(f'<h2>From the work log ({total} findings, {len(worklog)} entries)</h2>'
             '<div class="sub">Read straight from WORKLOG.md, newest first. Every sentence is quoted as the '
             'teammate wrote it - nothing is summarised, rephrased or scored. Add an entry to the log and it '
             'appears here on the next run.</div>')
    for e in worklog:
        nb = (' &bull; EDA ' + e["nb"]) if e["nb"] else ""
        items = "".join('<div class="wli">' + (('<b>' + _esc(i["stat"]) + '</b>') if i["stat"] else "")
                        + _esc(i["text"]) + '</div>' for i in e["items"])
        h.append(f'<div class="wl"><div class="wlh">{_esc(e["title"])}'
                 f'<span>{e["date"]} &bull; {_esc(e["author"])}{nb}</span></div>{items}</div>')
    if not worklog:
        h.append('<div class="nowork">No parseable entries in WORKLOG.md.</div>')
    return "".join(h)

# ============================================================================
# TABULAR EXPORT - one row per product family, for external review workflows
# ============================================================================
# Reuses the same internal structures the HTML build reads from - fams (catalog),
# review (product_review.json), work (repo evidence per tracked product), and
# probes (product_probes.json) - so the export can never drift from the report.
# Some columns are not part of the tool's data model today (Agency, Last
# Reviewed By, Last Reviewed Date) and export as empty; product_scope has
# always kept two orthogonal axes for status, so Status carries both:
# "<stage> / <work depth>" (e.g. "Cataloged / Validated").

EXPORT_COLUMNS = [
    "Product ID", "Name", "Family", "Agency", "Status",
    "Repo Evidence", "MOE Var Count", "Allocation Groups",
    "Geography Levels", "Notes", "Last Reviewed By", "Last Reviewed Date",
]

def product_export_row(f, review, work, probes):
    """Assemble one export row from the tool's existing data structures.

    Sources per column:
      Product ID, Name, Family    -> catalog family record (fams)
      Status                       -> review.stage + work.status  (both axes)
      Repo Evidence, Geography     -> work (repo evidence, per tracked product)
      MOE Var Count, Alloc Groups  -> probes (variables.json summary)
      Notes                        -> review.note (uncertainty_metrics if none)
      Agency, Last Reviewed By/Date -> not tracked -> empty string
    """
    r = review.get(f["path"], {})
    w = work.get(f["product"], {}) if f.get("product") else {}
    pr = probes.get(f["path"], {}) or {}
    ok = pr.get("ok")

    stage_label = STAGE_LABELS.get(r.get("stage", "cataloged"), "Cataloged")
    work_label = STATUS_LABELS[w.get("status", 0)]
    status = f"{stage_label} / {work_label}"

    # Repo evidence: semicolon-joined "file (cell N)" or "file (line N)" list.
    # These are the same receipts the HTML shows under "Our progress".
    evidence = "; ".join(receipt_label(r) for r in w.get("receipts", []))

    # Geography levels: prefer the probe's verified list (what the Bureau says
    # the product supports); fall back to the inferred set from repo scanning
    # (what our own code appears to have touched). Both are labelled below by
    # the source so downstream reviewers can tell which is which.
    if ok and pr.get("levels"):
        geo = ", ".join(pr["levels"])
    elif w.get("geos"):
        geo = ", ".join(sorted(w["geos"])) + " (inferred from repo)"
    else:
        geo = ""

    # Notes: prefer the free-text `note` (why a stage was set / caveats).
    # If empty, fall through to the review's uncertainty_metrics description,
    # since that IS the review deliverable per the tool's design.
    note = r.get("note") or r.get("uncertainty_metrics") or ""

    return {
        "Product ID":         f["path"],
        "Name":               f.get("title", ""),
        "Family":             f.get("group", ""),
        "Agency":             "",   # not modelled (all products are U.S. Census Bureau)
        "Status":             status,
        "Repo Evidence":      evidence,
        "MOE Var Count":      pr.get("moe_variables", "") if ok else "",
        "Allocation Groups":  pr.get("allocation_group_count", "") if ok else "",
        "Geography Levels":   geo,
        "Notes":              note,
        "Last Reviewed By":   "",   # not tracked in product_review.json today
        "Last Reviewed Date": "",   # not tracked in product_review.json today
    }

def build_export_rows(fams, review, work, probes):
    """One row per catalog family, ordered by path (stable and diff-friendly)."""
    return [product_export_row(fams[p], review, work, probes) for p in sorted(fams)]

def export_csv(rows, out_path):
    """Write rows as UTF-8 CSV using the stdlib csv module (zero-dep)."""
    import csv
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=EXPORT_COLUMNS)
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in EXPORT_COLUMNS})

def export_xlsx(rows, out_path):
    """Write rows as a single-sheet .xlsx workbook using openpyxl directly.

    One sheet named 'Products'. First row is the header, columns match
    EXPORT_COLUMNS. Kept intentionally plain - no styling, no formulas -
    so downstream tools (Excel, LibreOffice, pandas) read it identically."""
    try:
        from openpyxl import Workbook
    except ImportError:
        sys.exit("error: --export xlsx needs openpyxl (pip install openpyxl); "
                 "or export csv instead")
    wb = Workbook()
    ws = wb.active
    ws.title = "Products"
    ws.append(EXPORT_COLUMNS)
    for row in rows:
        ws.append(["" if row.get(k) is None else row.get(k) for k in EXPORT_COLUMNS])
    wb.save(out_path)


def render(fams, review, work, worklog, notebooks, probes, repo_name, catnote, out_path, git,
           snapshot=None, diff=None, jl_refs=None, jl_errors=None, divergences=None,
           data_cache=None, eda_diffs=None):
    counts = {s: 0 for s in STAGES}
    for path in fams:
        counts[review.get(path, {}).get("stage", "cataloged")] += 1

    kinds_present = [k for k in KINDS if any(f["kind"] == k for f in fams.values())]
    tabs = ['<button class="tab on" data-k="home">Home</button>']
    panels = ['<div class="panel on" id="panel-home">'
              + build_home(fams, review, work, counts, worklog, notebooks, probes, git, diff, jl_refs, jl_errors, divergences) + '</div>']
    for i, k in enumerate(kinds_present):
        n = sum(1 for f in fams.values() if f["kind"] == k)
        tabs.append(f'<button class="tab" data-k="k{i}">{_esc(k)}<span class="n">{n}</span></button>')
        panels.append(f'<div class="panel" id="panel-k{i}">'
                      + build_kind_panel(k, fams, review, work, probes, git, snapshot,
                                          jl_refs, jl_errors, data_cache, eda_diffs) + '</div>')

    gen_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    head_short = (git.get("head_sha") or "")[:7] or "no-git"
    branch = git.get("branch") or "detached"
    html = (TEMPLATE
            .replace("__DATE__", datetime.date.today().strftime("%B %d, %Y"))
            .replace("__CATNOTE__", catnote).replace("__REPO__", repo_name)
            .replace("__TABS__", "".join(tabs))
            .replace("__PANELS__", "".join(panels))
            .replace("__GEN_ISO__", gen_iso)
            .replace("__HEAD_SHA__", _esc(git.get("head_sha") or ""))
            .replace("__HEAD_SHORT__", _esc(head_short))
            .replace("__BRANCH__", _esc(branch)))
    Path(out_path).write_text(html, encoding="utf-8")
    return counts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default=None,
                    help="default: <repo>/product_report.html (or product_review.<ext> with --export)")
    ap.add_argument("--online", action="store_true")
    ap.add_argument("--probe-queue", metavar="FILE",
                    help="probe the products listed in a probe_queue.json downloaded from the report")
    ap.add_argument("--probe", metavar="PATH", action="append",
                    help="probe a single catalog path, e.g. --probe acs/acs5 (repeatable)")
    ap.add_argument("--export", choices=("csv", "xlsx"), default=None,
                    help="write a per-product review table instead of the HTML report. "
                         "Default output file is product_review.csv or product_review.xlsx "
                         "at the repo root; override with --out.")
    # ---- Phase 3: sample / EDA mode (see SAMPLE / EDA MODE section above) --
    ap.add_argument("--sample", action="store_true",
                    help="fetch actual data slices and run a canonical EDA. Combined "
                         "with --product X, samples one product; alone, batch-samples "
                         "every product currently marked 'candidate' in product_review.json. "
                         "Skips fresh cache entries (< 7 days) unless --refresh is given.")
    ap.add_argument("--sample-size", type=int, default=SAMPLE_SIZE_DEFAULT, metavar="N",
                    help=f"row count per sample (default: {SAMPLE_SIZE_DEFAULT}). "
                         "The Census data API truncates automatically; smaller = faster.")
    ap.add_argument("--refresh", action="store_true",
                    help="force re-sampling even if a fresh cache entry exists (used "
                         "with --sample). Diff against the previous sample is surfaced "
                         "in the report.")
    ap.add_argument("--product", metavar="ID", default=None,
                    help="target product for --sample (single-product mode). "
                         "Ignored otherwise.")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    if not (repo / "ingestion").exists():
        sys.exit(f"error: {repo} doesn't look like the project repo")
    if args.export:
        default_name = f"product_review.{args.export}"
        out = Path(args.out).resolve() if args.out else repo / default_name
    else:
        out = Path(args.out).resolve() if args.out else repo / "product_report.html"

    print(f"Scanning {repo} ...")
    evidence = deep_scan(repo) if DEEP else fallback_scan(repo)
    print(f"  {len(evidence)} files scanned ({'deep forensics' if DEEP else 'regex fallback'})")
    if not DEEP:
        print("  WARNING: scope_evidence.py was not found next to this script. Evidence is a shallow")
        print("           text scan and work depth is less reliable. Put it in the same folder.")
    work = build_product_status(evidence)
    notebooks = [e for e in evidence if e.get("health")]

    worklog = mine_worklog(repo)
    print(f"  work log: {sum(len(e['items']) for e in worklog)} findings across {len(worklog)} entries")
    _pv = load_probes(repo)
    if _pv: print(f"  probes: {sum(1 for v in _pv.values() if v.get('ok'))} product(s) probed against the API")

    fams = fetch_catalog(repo / "scope_field_cache.json", args.online)
    if len(fams) > len(EXTRA_PRODUCTS):
        catnote = f"catalog: {len(fams)} product families"
    else:
        catnote = "catalog: not yet crawled (run --online)"
        print("  [catalog] NO CRAWL AVAILABLE - only the non-API products are listed.")
        print("            Delete product_review.json and re-run with --online once you are online.")

    probes = load_probes(repo)
    queued = list(args.probe or [])
    if args.probe_queue:
        qf = Path(args.probe_queue).expanduser()
        if not qf.exists(): sys.exit(f"error: queue file not found: {qf}")
        qdata = json.loads(qf.read_text(encoding="utf-8"))
        queued += qdata.get("paths", []) if isinstance(qdata, dict) else list(qdata)
    if queued:
        seen, uniq = set(), []
        for x in queued:
            if x not in seen: seen.add(x); uniq.append(x)
        run_probe_queue(repo, fams, uniq, datetime.date.today().isoformat())
        probes = load_probes(repo)

    review, rpath, first, added = load_review(repo, fams)
    if first:
        print(f"  review file: {rpath.name} created with {added} products, all 'cataloged'")
        print("               stages and uncertainty notes are yours to fill in - the tool sets neither")
    elif added:
        print(f"  review file: {added} new product(s) appended; existing entries untouched")
    validate_review(review)   # feature #7: composite_role requires composite_role_note

    # git info is captured once and reused: --sample stamps sha_at_sample on
    # each cache entry (Phase 3), and the HTML render uses branch + slug for
    # jump-to-source URLs.
    git = git_info(repo)
    if git.get("head_sha"):
        print(f"  git: HEAD {git['head_sha'][:7]} on '{git.get('branch') or 'detached'}'"
              + (f" | github: {git['github_slug']}" if git.get("github_slug") else ""))

    # Phase 3: --sample runs before HTML render; results feed back into the report.
    if args.sample:
        sample_products(repo, fams, review, probes, args.product,
                        args.sample_size, args.refresh, git)

    if args.export:
        # Export mode skips HTML generation entirely - the export IS the deliverable.
        # This keeps the default `python tools/product_scope.py` HTML path unchanged.
        rows = build_export_rows(fams, review, work, probes)
        if args.export == "csv":
            export_csv(rows, out)
        else:
            export_xlsx(rows, out)
        print(f"Wrote {len(rows)} product row(s) to {out} ({args.export})")
        return
    snapshot_prev = load_snapshot(repo)   # previous run - feeds diff + FOCUS-SHA affordance
    current_snap  = build_snapshot(fams, review, work, probes, git)
    diff          = compute_diff(snapshot_prev, current_snap)
    save_snapshot(repo, current_snap)
    jl_refs, jl_errors = build_jl_refs(repo, fams)
    divergences = compute_divergences(fams, review, jl_refs)
    dsum = (len(divergences["referenced_no_role"]), len(divergences["role_no_reference"]))
    if any(dsum):
        print(f"  divergences: {dsum[0]} referenced-without-role, {dsum[1]} role-without-reference")
    if diff.get("is_baseline"):
        print(f"  snapshot: baseline recorded to {SNAPSHOT_FILE} (diff will appear on next run)")
    else:
        t = diff["totals"]
        newev = sum(t.get("new_evidence_by_family", {}).values())
        print(f"  snapshot: {newev:+d} evidence hits, {t['status_changes']} status change(s), "
              f"{t['new_probes']} new probe(s)")
    # Phase 3: load the sample cache after sample_products() has (possibly)
    # updated it, so the HTML render sees the latest EDA slice on every card.
    data_cache = load_data_cache(repo)
    counts = render(fams, review, work, worklog, notebooks, probes, repo.name, catnote, out, git,
                    snapshot_prev, diff, jl_refs, jl_errors, divergences, data_cache)
    print("  funnel: " + " -> ".join(f"{STAGE_LABELS[s]} {counts.get(s, 0)}" for s in STAGES))
    print(f"Report written to {out}")

if __name__ == "__main__":
    main()
