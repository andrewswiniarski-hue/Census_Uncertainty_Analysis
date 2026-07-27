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
    python tools/product_scope.py             # uses the cached crawl
    python tools/product_scope.py --online    # re-crawl the API catalog
Output: product_report.html (self-contained, no CDN, no storage APIs).
"""

import argparse, json, os, re, subprocess, sys, datetime, time, urllib.request, webbrowser
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
# Beginner-UX pass commit #3: visible-label rename. Internal enum values in
# STAGES stay stable (schema, CLI flag values, JSON keys all still speak the
# enum); only the display labels change. Old label was "Cataloged" (jargon);
# new label is "Listed only" (plain English: it's in the Census catalog but the
# team hasn't looked at it yet).
STAGE_LABELS = {"cataloged": "Listed only", "reviewed": "Reviewed", "candidate": "Candidate",
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

# ---- Phase 5 #1: insights schema --------------------------------------------
# Each entry in review[path]["insights"] is one of:
#   {"when": ISO8601Z, "who": "Andrew", "source": "human"|"auto:*", "text": "..."}
# Append-only: no writer mutates or deletes existing entries. Auto-insights
# dedup on hash(source + text)[:16] against existing entries from the same
# source for the same product; human insights are never deduped (a teammate
# saying the same thing twice is intentional).
INSIGHT_SOURCES  = ["human", "auto:repo", "auto:cache_diff", "auto:divergence"]
INSIGHT_HUMAN    = "human"
INSIGHT_AUTO_REPO       = "auto:repo"
INSIGHT_AUTO_CACHE_DIFF = "auto:cache_diff"
INSIGHT_AUTO_DIVERGENCE = "auto:divergence"

# Icons shown next to each insight in both the TL;DR and drill-down feed.
# Written with explicit \U escapes so the source file stays pure ASCII.
INSIGHT_SOURCE_ICON = {
    INSIGHT_HUMAN:            "\U0001F464",   # bust in silhouette
    INSIGHT_AUTO_CACHE_DIFF:  "\U0001F527",   # wrench
    INSIGHT_AUTO_REPO:        "\U0001F4DD",   # memo
    INSIGHT_AUTO_DIVERGENCE:  "⚠",       # warning sign
}

INSIGHT_SOURCE_LABEL = {
    INSIGHT_HUMAN:            "human",
    INSIGHT_AUTO_REPO:        "repo",
    INSIGHT_AUTO_CACHE_DIFF:  "cache diff",
    INSIGHT_AUTO_DIVERGENCE:  "divergence",
}

def insight_hash(source, text):
    """Content hash used for auto-insight dedup: hex-16 of sha256(source+text).
    Human insights are NEVER hashed for dedup (the spec explicitly excludes
    them so a repeated observation from two teammates lands as two entries)."""
    import hashlib
    return hashlib.sha256((str(source) + str(text)).encode("utf-8")).hexdigest()[:16]

# ---- data.census.gov cross-links (2026-07-26) -------------------------------
# The Bureau's interactive query tool is the "actually use this product" call
# to action - filter, preview, download tables + maps in a browser. Every card
# gets a prominent link so a reviewer opening the tool has a one-click path to
# real data. Structure of the `all` search page: `d=<Program+Name>` narrows to
# a program; falling back to `q=<Program+Name>` treats it as a keyword search
# for the rare cases (e.g. Public Sector split across ~seven `govs*` prefixes)
# where the program filter isn't a clean match.
DCGOV_BASE = "https://data.census.gov"

# Explicit path -> canonical URL. Beats the program lookup for non-API
# products (TIGER shapefiles, DAS demo) that have their own Bureau landing
# pages and would look wrong on data.census.gov.
DCGOV_URL_BY_PATH = {
    "geo/tiger":    "https://www.census.gov/geographies/mapping-files.html",
    "dec/das-demo": "https://www.census.gov/library/reference/das/2010-2020.html",
}

# Program-name -> `d=<...>` value on data.census.gov. Names taken from the
# Bureau's own "Datasets" facet on data.census.gov, spot-checked against the
# tool that generates it. Missing programs fall back to a keyword search on
# the program label (see program_dcgov_url below), which still lands on a
# useful results page rather than an error.
DCGOV_PROGRAM_D_PARAM = {
    "American Community Survey":                     "ACS+5-Year+Estimates+Detailed+Tables",
    "American Community Survey (1-year)":            "ACS+1-Year+Estimates+Detailed+Tables",
    "Decennial Census":                              "Decennial+Census",
    "Current Population Survey":                     "Current+Population+Survey",
    "Survey of Income and Program Participation":    "Survey+of+Income+and+Program+Participation",
    "Population Estimates":                          "Population+Estimates+Program",
    "Population Projections":                        "Population+Projections",
    "Economic Census":                               "Economic+Census",
    "Annual Business Survey":                        "Annual+Business+Survey",
    "County Business Patterns":                      "County+Business+Patterns",
    "ZIP Code Business Patterns":                    "ZIP+Codes+Business+Patterns",
    "Nonemployer Statistics":                        "Nonemployer+Statistics",
    "Survey of Business Owners":                     "Survey+of+Business+Owners",
    "Annual Survey of Entrepreneurs":                "Annual+Survey+of+Entrepreneurs",
    "Community Resilience Estimates":                "Community+Resilience+Estimates",
    "Planning Database":                             "Planning+Database",
    "International Trade":                           "USA+Trade+Online",
    "Annual Survey of Manufactures":                 "Annual+Survey+of+Manufactures",
    "Annual Integrated Economic Survey":             "Annual+Integrated+Economic+Survey",
    "Commodity Flow Survey":                         "Commodity+Flow+Survey",
    "Commodity Flow Survey PUM":                     "Commodity+Flow+Survey",
    "Rental Housing Finance Survey":                 "Rental+Housing+Finance+Survey",
    "Vehicle Inventory and Use Survey":              "Vehicle+Inventory+and+Use+Survey",
    "Quarterly Workforce Indicators":                "Quarterly+Workforce+Indicators",
    "Business Dynamics Statistics":                  "Business+Dynamics+Statistics",
    "Small Area Health Insurance Estimates":         "Small+Area+Health+Insurance+Estimates",
    "Post-Secondary Employment Outcomes":            "Post-Secondary+Employment+Outcomes",
    "Household Pulse Survey":                        "Household+Pulse+Survey",
    "Economic Indicators (EITS)":                    "Economic+Indicators",
    "International Database":                        "International+Database",
    "Public sector":                                 "Annual+Survey+of+Public+Employment+and+Payroll",
    "Poverty (SAIPE / CPS)":                         "Small+Area+Income+and+Poverty+Estimates",
    "Frequently Occurring Surnames":                 "Frequently+Occurring+Surnames+from+the+Census",
}

def program_dcgov_url(path):
    """Return a data.census.gov (or Bureau-page) URL for `path`. Never None -
    a keyword-search fallback always produces a link the reviewer can click.

    Precedence, from most specific to least:
      1. DCGOV_URL_BY_PATH  - explicit path override (non-API products, etc.)
      2. DCGOV_PROGRAM_D_PARAM - program name maps to a `d=` filter value
      3. keyword-search fallback on the program label (`q=<program>`) - lands
         on a search results page instead of erroring
    """
    if not path:
        return f"{DCGOV_BASE}/all"
    if path in DCGOV_URL_BY_PATH:
        return DCGOV_URL_BY_PATH[path]
    prog = program_label(path)
    d = DCGOV_PROGRAM_D_PARAM.get(prog)
    if d:
        return f"{DCGOV_BASE}/all?d={d}"
    # Fallback: keyword search on the program name. Spaces -> +, no escaping of
    # ASCII program names needed (the Bureau's URL scheme accepts them raw).
    import urllib.parse
    q = urllib.parse.quote_plus(prog)
    return f"{DCGOV_BASE}/all?q={q}"

# ---- Phase-1 findings report anchors (2026-07-26) ---------------------------
# Repo-relative path to the plain-language Phase 1 findings report. Used by
# the Team Pulse tail link on Home and by the per-card "Related in the
# Phase 1 report" footer link. (The Home hero card that also used it was
# retired 2026-07-26 - findings now lead as stat cards in Team Pulse.) The path resolves against wherever product_report.html
# sits (repo root), so any teammate opening the report locally lands in the
# same file, and on GitHub the same href resolves to the rendered .md.
PHASE1_REPORT_PATH = "docs/phase1-findings-report.md"
PHASE1_REPORT_MIN_READ = "10 min read"

# Products the phase-1 findings report EXPLICITLY discusses. Section anchors
# use GitHub's slugified-header rules (lowercase, punctuation stripped, spaces
# and em-dashes collapsed to '-') so the same href works on github.com and,
# when unresolved, gracefully falls back to the top of the .md file locally.
# Additions here must trace back to a specific report section - no guessing.
PHASE1_REPORT_SECTIONS = {
    # Section 3 - Sampling noise (EDA 01-03). ACS 5-year is the primary CV
    # source across findings 1, 2, 3.
    "acs/acs5":         ("3-sampling-noise-the-law-of-shrinking-places-eda-0103",
                         "Section 3 - Sampling noise"),
    "acs/acs5/subject": ("3-sampling-noise-the-law-of-shrinking-places-eda-0103",
                         "Section 3 - Sampling noise (subject tables)"),
    "acs/acs5/profile": ("3-sampling-noise-the-law-of-shrinking-places-eda-0103",
                         "Section 3 - Sampling noise"),
    "acs/acs5/cprofile":("3-sampling-noise-the-law-of-shrinking-places-eda-0103",
                         "Section 3 - Sampling noise"),
    # Section 4 - Privacy noise (EDA 04). DHC, SF1 baseline, DAS demo.
    "dec/dhc":          ("4-privacy-noise-a-fixed-cost-that-small-places-pay-eda-04",
                         "Section 4 - Privacy noise"),
    "dec/sf1":          ("4-privacy-noise-a-fixed-cost-that-small-places-pay-eda-04",
                         "Section 4 - 2010 SF1 baseline used against DHC noise"),
    "dec/das-demo":     ("4-privacy-noise-a-fixed-cost-that-small-places-pay-eda-04",
                         "Section 4 - DAS demonstration data"),
}

# Tabs, from the Bureau's own dataset flags. Not our categories.
KINDS = ["Aggregate tables", "Microdata", "Time series", "Uncategorized"]
KIND_BLURB = {
    "Aggregate tables": "Published estimate tables. This is where published uncertainty lives: "
                        "margins of error, allocation tables, variance replicate tables.",
    "Microdata":        "Record-level files. Nothing is published per estimate - replicate weights "
                        "ship with the data and the analyst computes their own standard errors.",
    "Time series":      "Multi-year series reached through a single endpoint.",
    "Uncategorized":    "Tool fallback bucket, not a Bureau label: the catalog record carries "
                        "none of the aggregate / microdata / time-series flags.",
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
     "vintages": [2024], "kind": "Uncategorized",
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
    # composite.py / alloc.py / cv_model.py live on an unmerged branch today;
    # notebooks 06 and 07 already import them, so evidence exists.
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

# Start-here curriculum (UX pass 2026-07-26 commit #4). Five hand-ordered
# products a first-time reader can walk through to build a working mental
# model of Census data reliability. Each entry pairs the product with the
# uncertainty concept it best illustrates. Every blurb is grounded in
# either the phase-1 findings report or the seeded FOCUS product_review
# entry - no fabrication. See the SOURCE citation on each line.
#
# Placement: right column of the Get-oriented grid on Home, beside the
# "Find a product" search ("have a question? search; no idea where to
# start? walk this list").
# Order chosen so each concept builds on the previous one - sampling noise
# is the intuitive starting point, then privacy noise (a totally different
# mechanism), then a demo dataset that lets you SEE the privacy noise, then
# imputation (the third dimension), then the pre-DP baseline as a compare.
CURRICULUM = [
    {"path":  "acs/acs5",
     "title": "American Community Survey 5-year",
     "concept": "sampling noise",
     "why":   "How margins of error work, and why small subgroups get noisy "
              "fast. This is the noise the Bureau publishes.",
     "source":"seeded FOCUS entry + findings report Section 3"},
    {"path":  "dec/dhc",
     "title": "2020 Decennial Demographic and Housing Characteristics",
     "concept": "differential privacy",
     "why":   "How the Bureau injects deliberate noise to protect "
              "confidentiality, and when that noise affects usability.",
     "source":"seeded FOCUS entry + findings report Section 4"},
    {"path":  "dec/das-demo",
     "title": "2020 DAS Demonstration files",
     "concept": "privacy noise in action",
     "why":   "Real before-and-after data showing DP noise scale by "
              "geography. The dataset used to measure privacy noise directly.",
     "source":"seeded uncertainty_metrics + findings report Section 4"},
    {"path":  "acs/acs5/subject",
     "title": "ACS 5-year Subject Tables",
     "concept": "imputation",
     "why":   "Includes allocation tables - which values were filled in by "
              "the Census when respondents left them blank. Independent of "
              "the published margin of error.",
     "source":"seeded FOCUS entry (allocation_source) + findings report Section 5"},
    {"path":  "dec/sf1",
     "title": "2010 Summary File 1",
     "concept": "the pre-DP baseline",
     "why":   "Compare against DHC/DAS-demo to see what the 2020 DP system "
              "changed. Protected by the older 'swapping' method - a "
              "documented residue remains.",
     "source":"seeded FOCUS entry (benchmark) + findings report Section 4"},
]

# Curated insight cards, written by the team, tagged with the product family they
# belong to. Entries flagged `hero: True` render as the big-number stat cards at
# the top of "What we've learned" (stat-first redesign 2026-07-26); the rest render
# as compact one-liners below. Mined WORKLOG findings no longer render on Home at
# all - demoted to a single WORKLOG.md link after Garrett's live-test feedback
# ("massive wall of text"). WORKLOG items are NOT attributed to a product, because
# WORKLOG does not record catalog paths and guessing the link would be exactly the
# kind of inference this tool avoids.
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
  "detail": "Same data, adjacent levels; geography type, not just size, drives DAS noise.", "nb": "04", "kind": "oddity",
  "hero": True},
 {"family": "dec/das-demo", "stat": "807 / 427", "headline": "Ghost and vanished blocks",
  "detail": "807 empty blocks gain 4,695 phantom residents; 427 inhabited blocks publish as empty.", "nb": "04", "kind": "finding"},
 {"family": "acs/acs5", "stat": "4 in 10", "headline": "Income is imputed for ~39% of households at a typical tract",
  "detail": "Age/race under 1%: imputation is a variable-type story, concentrated in income.", "nb": "05", "kind": "finding",
  "hero": True},
 {"family": "acs/acs5", "stat": "ρ ≈ 0", "headline": "Imputation is independent of the published error bars",
  "detail": "Every size-controlled allocation-vs-CV correlation sits in [−0.00, +0.19]: the MOE cannot see this error.", "nb": "05", "kind": "finding"},
 {"family": "acs/acs5", "stat": "22.8%", "headline": "The CV-only blind spot",
  "detail": "481 of 2,109 tracts look fine by the error bar but carry heavily imputed income.", "nb": "06", "kind": "finding",
  "hero": True},
 {"family": "acs/acs5", "stat": "84.6%", "headline": "Combining rules disagree at the margin",
  "detail": "Equal-weight vs worst-component agree on only ~85% of the top-risk quartile.", "nb": "06", "kind": "finding"},
 {"family": "acs/acs5", "stat": "R² ≈ 0.67", "headline": "Score the estimate, not the place",
  "detail": "Estimate size alone explains ~2/3 of CV variance; place population almost nothing.", "nb": "07", "kind": "finding",
  "hero": True},
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

# --- Phase A ceiling-push #3: stat-carrying heuristics for WORKLOG mining ---
# Historical (pre-#3) behaviour: mine_worklog() extracted every sub-clause in
# a Findings block indiscriminately, feeding 158 items into the What-we've-
# learned aggregator. Most were pure process notes ("regen'd HTML", "added
# WORKLOG entry") that flooded the Show-all drawer and hid the actual
# statistics-carrying findings. This pass scores each mined item by how many
# stat-shaped signals it carries; zero-score items drop entirely, and the
# aggregator caps Show-all at 30 mined+auto items to keep the drawer scannable.
#
# The scoring is deliberately additive rather than a single regex-OR so a row
# with three signals ("median CV rose 12% at n=42, p<0.01") ranks above a
# row with only one; ties break by timestamp (newest first).

# Numbers with an inline unit or an equation operator. Rows scoring
# 1 for each match, capped at +3 to prevent a single sentence with
# dozens of numbers from dominating.
WL_NUM_UNITS = re.compile(
    r"(?:\bρ\s*=|\bR\s*[²2]|\br\s*=|\bn\s*=|\bN\s*=|σ|\bp\s*<)|"
    r"\d[\d,.]*\s*(?:%|×|\bx\b|/|→|to\s+\d)|"
    r"\b\d+\.\d+\b"
)
# Statistics vocabulary. One point per unique term (case-insensitive).
WL_STAT_VOCAB = re.compile(
    r"\b(?:median|mean|share|count|correlation|spike|drops?|jumps?|ratio|"
    r"distribution|outlier|variance|stddev|std\s*dev|moe|"
    r"95\s*%?\s*ci|confidence\s+interval|"
    r"skew|kurtosis|percentile|quartile|"
    r"significant|significance)\b",
    re.I,
)
# Finding-shaped verbs at the start of the row (or near-start after markdown).
WL_STAT_LEADS = re.compile(
    r"^\s*(?:\*\*)?(?:found|observed|shows?|showed|reveals?|revealed|"
    r"indicates?|suggests?|confirms?|proves?)\b",
    re.I,
)
# Explicit process-note markers (down-weight, never elevate). A row that
# EXCLUSIVELY talks about the tool/regen/commit ships to the demoted tail.
WL_PROCESS_MARKERS = re.compile(
    r"\b(?:regen(?:'?d)?|regenerated|committed|commit\s+hash|"
    r"loc\s*(?:on|line)|"
    r"added?\s+(?:file|entry|worklog)|"
    r"scan(?:ned)?|before/after\s+measurements|baseline\s+vs|"
    r"grep\s+audit|help\s+line\s+count)\b",
    re.I,
)

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

def _wl_score(text):
    """Rank a mined WORKLOG row by how stat-carrying it is.

    Signals (each contributes to the score):
      + up to +3 for number-with-unit matches (%, ×, /, ρ=, n=, decimals...)
      + +1 per unique statistics-vocab term
      + +2 for a finding-shaped leading verb (found / observed / shows...)
      + -2 penalty if the row looks like a pure process note (regen /
        committed / grep audit / LOC delta) so it drops to the tail.

    Zero-or-negative score returned by callers as "drop from mining".
    The scoring is intentionally simple and additive so the ranking is
    inspectable in-place; see the module comment above for the design
    rationale."""
    if not text:
        return 0
    n_units = min(3, len(WL_NUM_UNITS.findall(text)))
    vocab_terms = set(m.group(0).lower() for m in WL_STAT_VOCAB.finditer(text))
    n_vocab = len(vocab_terms)
    n_leads = 2 if WL_STAT_LEADS.search(text) else 0
    penalty = -2 if WL_PROCESS_MARKERS.search(text) else 0
    return n_units + n_vocab + n_leads + penalty

def mine_worklog(repo: Path):
    """Extract mined-findings rows from WORKLOG.md, scored by stat-carrying
    heuristic. Returns list-of-dicts (same shape as before, plus a `score`
    field on each item and a `max_score` on each entry) so downstream
    build_what_learned() can rank + cap; readers that ignore `score` still
    work as they did pre-#3."""
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
            score = _wl_score(t)
            # Drop zero-or-negative rows entirely: they're process chatter
            # (regen'd HTML, committed X) with no statistical payload.
            if score <= 0: continue
            items.append({"stat": _stat_of(t), "text": t, "score": score})
        if not items: continue
        nb = re.search(r"EDA (\d\d?)", h.group(3))
        out.append({"date": h.group(1), "author": h.group(2).strip(),
                    "title": _strip_md(h.group(3)), "nb": nb.group(1) if nb else "",
                    "items": items,
                    "max_score": max(i["score"] for i in items)})
    out.sort(key=lambda e: e["date"], reverse=True)
    return out

# ============================================================================
# CATALOG
# ============================================================================

def _kind_of(flags):
    if flags.get("micro"): return "Microdata"
    if flags.get("ts"):    return "Time series"
    if flags.get("agg"):   return "Aggregate tables"
    return "Uncategorized"

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

    Phase 5 #1: newly created entries also get `insights: []` (append-only
    list of {when, who, source, text} dicts) plus `last_reviewed_by` /
    `last_reviewed_date` (auto-populated by the --review CLI helper). Every
    reader must use `entry.get("insights", [])` etc. so the 573 existing
    entries (which lack these fields) continue to work without a migration.

    Backward compat: existing entries may still carry a leftover
    `sample_config` field from the (removed in the audit cut) warm-cache
    path. The tool reads it via `.get()` and ignores it; we do NOT strip it
    from existing entries on load so team members' files continue to diff
    cleanly.
    """
    p = repo / "product_review.json"
    existing, first = {}, not p.exists()
    if not first:
        existing = json.loads(p.read_text(encoding="utf-8"))
    added = 0
    default = {"stage": "cataloged", "uncertainty_metrics": "", "note": "",
               "composite_role": "", "composite_role_note": "",
               "insights": [],
               "last_reviewed_by": "", "last_reviewed_date": ""}
    for path in sorted(fams):
        if path not in existing:
            existing[path] = dict(default)
            added += 1
    # Normalize on load: if the file's on-disk key order doesn't match the
    # canonical sort_keys=True layout, rewrite it once. This means a first
    # regen after the pivot produces a "one big diff" but every subsequent
    # --review CLI write shows only the actually-changed lines - critical
    # for reviewer diff-hygiene.
    canonical = json.dumps(existing, indent=2, sort_keys=True)
    needs_normalize = False
    if not first:
        try:
            needs_normalize = (p.read_text(encoding="utf-8") != canonical)
        except Exception:
            needs_normalize = True
    if added or first or needs_normalize:
        p.write_text(canonical, encoding="utf-8")
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
# PHASE 5 #2 - AUTO-INSIGHT LOGGING (regen)
# ============================================================================
# Auto-insights document what changed since the last regen so the team feed
# on every card carries the paper trail of drift, not just the current state.
# Two sources (auto:repo dropped in audit cut 2 - noisy commit-log paraphrase
# that duplicated what git blame already shows; existing auto:repo entries in
# product_review.json are still rendered on read for backward compat):
#   auto:cache_diff   - a sample refresh changed shape / dtype / missingness
#   auto:divergence   - composite_role declared or removed while composite code
#                        refs also crossed the on/off boundary
#
# Both go through _append_insight() which handles:
#   (a) dedup - never store the same (source, text) twice per product
#   (b) file locking - a threading.Lock() (in-process) + fcntl.flock() best-
#       effort (cross-process, when the OS supports it) so the --review CLI
#       helper and any other writer cannot corrupt each other's writes
#   (c) writing the whole review file back deterministically

# Module-level lock so any thread of this process (main regen, --review
# helper) serializes review-file writes. Cross-process locking sits on top
# via fcntl.flock() where available; see with_review_locked() below.
import threading as _threading
_REVIEW_LOCK = _threading.Lock()

# fcntl is Unix-only; on Windows we degrade to threading.Lock() alone.
# Import guarded here so the tool runs on Garrett's Windows target without
# hitting a missing-module error at import time.
try:
    import fcntl as _fcntl  # noqa: F401
    _HAVE_FCNTL = True
except ImportError:
    _HAVE_FCNTL = False

def _now_iso_z():
    """Current UTC time as an ISO-8601 string with 'Z' suffix. Kept as its
    own helper so every code path that stamps a 'when' uses the same format."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _ensure_review_shape(entry):
    """Return `entry` with the Phase 5 shape guaranteed - insights list present,
    last_reviewed fields present. Does NOT mutate any pre-existing fields; only
    adds the missing ones. Idempotent."""
    if "insights" not in entry: entry["insights"] = []
    if "last_reviewed_by" not in entry: entry["last_reviewed_by"] = ""
    if "last_reviewed_date" not in entry: entry["last_reviewed_date"] = ""
    return entry

def _append_insight(review, path, source, text, when=None, who=None):
    """Append one insight to review[path]["insights"] IN MEMORY.

    Rules (spec):
      * Human insights are appended unconditionally (no dedup).
      * Auto-insights dedup on hash(source+text)[:16] against every existing
        insight from the same source on the same product; if the hash matches,
        skip silently.
    Returns the appended entry dict on success, or None if deduped.

    Does NOT write the file. Callers batch multiple appends then call
    save_review_locked() once - the lock protects the write, not the compute.
    """
    if path not in review or not isinstance(review[path], dict):
        return None
    entry = _ensure_review_shape(review[path])
    text = str(text or "").strip()
    if not text: return None
    who = str(who or ("auto" if source != INSIGHT_HUMAN else "")).strip() or "auto"
    if source not in INSIGHT_SOURCES:
        # Unknown source - refuse rather than let a typo pollute the feed.
        return None
    # Dedup for auto-insights only.
    if source != INSIGHT_HUMAN:
        h = insight_hash(source, text)
        for existing in entry["insights"]:
            if existing.get("source") == source and \
               insight_hash(source, existing.get("text", "")) == h:
                return None
    ins = {"when": when or _now_iso_z(),
           "who":  who,
           "source": source,
           "text": text}
    entry["insights"].append(ins)
    return ins

def with_review_locked(repo: Path, mutate_fn):
    """Read product_review.json, call mutate_fn(review_dict), write it back -
    all under BOTH the module threading.Lock AND the fcntl.flock advisory lock
    on the companion lock file. This is the atomic read-modify-write helper
    that every writer MUST use to avoid the classic RMW race: without the
    load happening under the same lock as the save, two concurrent inserts
    can read the same 'before' state and each clobber the other's append.

    mutate_fn should return whatever the caller wants to hand back to its
    own caller (or None); its return value is passed through unchanged.
    The current on-disk review dict is passed in mutable, and its post-mutate
    state is what gets written out."""
    p = repo / "product_review.json"
    lock_p = repo / ".product_review.json.lock"
    tmp_p  = repo / f".product_review.json.tmp.{os.getpid()}"
    with _REVIEW_LOCK:
        lock_fh = None
        if _HAVE_FCNTL:
            try:
                lock_fh = open(lock_p, "a+")
                _fcntl.flock(lock_fh.fileno(), _fcntl.LOCK_EX)
            except (OSError, AttributeError):
                if lock_fh is not None:
                    try: lock_fh.close()
                    except Exception: pass
                lock_fh = None
        try:
            # Read INSIDE the lock so nobody can write between our read and
            # our write. This is the point of the whole helper.
            if p.exists():
                try:
                    review = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    review = {}
            else:
                review = {}
            result = mutate_fn(review)
            # sort_keys=True enforces alphabetical order top-level AND within
            # each entry so `git diff product_review.json` after a --review
            # CLI write stays minimal (only the changed lines move).
            payload = json.dumps(review, indent=2, sort_keys=True)
            with open(tmp_p, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                try: os.fsync(fh.fileno())
                except OSError: pass
            os.replace(tmp_p, p)
            return result
        finally:
            if lock_fh is not None:
                try: _fcntl.flock(lock_fh.fileno(), _fcntl.LOCK_UN)
                except Exception: pass
                try: lock_fh.close()
                except Exception: pass
            try:
                if tmp_p.exists(): tmp_p.unlink()
            except OSError:
                pass

def save_review_locked(repo: Path, review):
    """Overwrite product_review.json with the given dict, wholesale. Used by
    the regen path (main()) which already has an in-memory review dict it
    wants to persist as-is. WRITERS THAT NEED TO APPEND SHOULD USE
    with_review_locked() INSTEAD - this helper does NOT re-read the on-disk
    file, so a concurrent writer's appends can be clobbered if the caller's
    in-memory `review` is stale.

    Kept as a wrapper around with_review_locked() so the atomic-rename +
    fcntl semantics are shared with the append path."""
    def _replace(existing):
        existing.clear()
        existing.update(review)
    with_review_locked(repo, _replace)

# ---- Source B: auto:cache_diff ----------------------------------------------
# Piggyback on the existing diff_eda() output (Phase 3 #6). eda_diffs comes
# from --sample writes to .scope_last_eda_diff.json.

def collect_auto_cache_diff_insights(eda_diffs):
    """Return (path, source, text, when, who) tuples for every eda_diffs entry.
    eda_diffs shape (from load_eda_diffs()): {path: [change_string, ...]}.
    """
    tuples = []
    if not eda_diffs: return tuples
    for path, changes in eda_diffs.items():
        if not changes: continue
        summary = _summarize_eda_changes(changes)
        tuples.append((path, INSIGHT_AUTO_CACHE_DIFF, summary, None, "auto"))
    return tuples

def _summarize_eda_changes(changes):
    """Compact 'Sample refreshed. ...' line from a list of diff_eda strings."""
    if not changes: return "Sample refreshed. No material changes."
    # Just concatenate with '; '; the diff_eda strings are already scannable.
    return "Sample refreshed. " + "; ".join(changes) + "."

# ---- Source C: auto:divergence ----------------------------------------------
# Fire an insight when a product's composite_role STATE CHANGES vs. the
# previous snapshot (declared or removed). Steady-state emits nothing so the
# feed doesn't get re-flooded every regen. Compared to the pre-audit version,
# this collector no longer cross-checks role against AST-parsed composite code
# refs (the JL_Work_Tree code-refs feature was removed in the audit-simplify
# pass); the emit trigger is now purely a role state transition.

def collect_auto_divergence_insights(fams, review, snapshot_prev):
    """Return (path, source, text, when, who) tuples for products whose
    composite_role changed since the previous snapshot (added or removed).
    """
    tuples = []
    prev_prods = ((snapshot_prev or {}).get("products") or {})
    for path, f in fams.items():
        r = review.get(path, {}) or {}
        role = effective_role(r)
        cur_role = bool(role)
        prev_role = bool((prev_prods.get(path, {}) or {}).get("composite_role") or "")
        if prev_role == cur_role:
            continue  # steady-state; nothing to emit
        if cur_role:
            text = f"{role} role declared with note."
        else:
            text = "Composite role removed."
        tuples.append((path, INSIGHT_AUTO_DIVERGENCE, text, None, "auto"))
    return tuples

# ============================================================================
# Beginner-UX pass commit #5: notes/ folder ingestion (browser-only note flow)
# ============================================================================
# The browser "+ Add a note" button downloads a small plain-text stub. Teammate
# edits it, saves it into notes/<something>.txt, next regen picks it up.
# Format is intentionally forgiving:
#   * Lines starting with # are comments (ignored)
#   * `Key: value` header lines up to the first blank line
#   * Everything after the first blank line is the body text
#   * Required keys: product_id, who
# Ingested files move to notes/ingested/ so the git log shows what got absorbed
# and the tool doesn't re-ingest them next run. Content-hash dedup prevents
# re-inserting a duplicate that was already added on this product from the
# same author.

NOTE_FILE_EXTS = (".txt", ".md")

def _parse_note_text(text):
    """Parse a plain-text note file. Returns dict{product_id, who, body} or
    None if required fields are missing or the body is empty.

    Format (human-friendly; no YAML/TOML dependency needed):
      # any line starting with # is a comment
      product_id: acs/acs5
      who: Katie Doe
      <blank line>
      <body text - free-form, may span many lines>
    """
    if not text: return None
    # Pre-strip: remove all comment lines (any line whose first non-whitespace
    # is '#'). Comments can appear both before and inside the header block -
    # a beginner who follows the downloaded template will have several # lines
    # at the top before the first `product_id:` line, and we must not treat
    # the blank line between comments and the header as end-of-header.
    cleaned = [ln for ln in text.splitlines()
               if not ln.lstrip().startswith("#")]
    # Skip any leading blank lines so the header block starts at the first
    # actual `Key: value`.
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    header = {}
    body_lines = []
    in_body = False
    for raw in cleaned:
        if not in_body:
            stripped = raw.strip()
            if not stripped:
                # First real blank line after the header starts -> body begins.
                in_body = True
                continue
            if ":" not in raw:
                # Non-blank, non-key while still in header: treat as start of body.
                in_body = True
                body_lines.append(raw)
                continue
            k, v = raw.split(":", 1)
            header[k.strip().lower()] = v.strip()
        else:
            body_lines.append(raw)
    pid = header.get("product_id", "").strip()
    who = header.get("who", "").strip() or "unknown"
    # Strip trailing blank lines from body.
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    body = "\n".join(body_lines).strip()
    if not pid or not body:
        return None
    return {"product_id": pid, "who": who, "body": body}

def ingest_notes(repo: Path, review, fams):
    """Scan repo/notes/*.txt (and .md), parse each, and _append_insight() any
    non-dedup ones as source='human'. Move processed files into
    notes/ingested/ so the same note doesn't re-ingest on the next regen.
    Returns list of (product_id, who) tuples actually ingested (for logging).

    Dedup rule (spec): don't append if identical (who, text) exists on that
    product from source='human'. Belt-and-suspenders alongside the file-move
    step - the move is what stops re-scans, this stops manual re-drops of the
    same content. Uses insight_hash() so the semantics match auto-insights."""
    notes_dir = repo / "notes"
    if not notes_dir.exists():
        return []
    ingested_dir = notes_dir / "ingested"
    ingested = []
    to_move = []  # (src_path, dst_path)
    for p in sorted(notes_dir.iterdir()):
        if p.is_dir(): continue
        if p.suffix.lower() not in NOTE_FILE_EXTS: continue
        if p.name.lower().startswith("readme"): continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            print(f"  [notes] skipping {p.name}: read failed ({ex})",
                  file=sys.stderr)
            continue
        parsed = _parse_note_text(text)
        if not parsed:
            print(f"  [notes] skipping {p.name}: missing product_id or body "
                  "(see notes/README.md for the format)", file=sys.stderr)
            continue
        pid = parsed["product_id"]
        if pid not in review:
            # Not in the catalog - don't create a stub, don't ingest, but do
            # tell the user so they can fix the typo.
            print(f"  [notes] skipping {p.name}: product_id {pid!r} not in "
                  "the catalog (typo? use the full catalog path such as "
                  "acs/acs5)", file=sys.stderr)
            continue
        # Content-hash dedup: same (who, body) already logged? Skip AND still
        # move the file so we don't re-report on every regen.
        who = parsed["who"]
        body = parsed["body"]
        entry = review.get(pid) or {}
        h = insight_hash("human:" + who, body)
        dup = any(
            (ins.get("source") == INSIGHT_HUMAN
             and (ins.get("who") or "") == who
             and insight_hash("human:" + who, ins.get("text") or "") == h)
            for ins in (entry.get("insights") or []))
        # File mtime -> ISO 8601 UTC 'when'. Falls back to current time on
        # any oddity (e.g. mtime read failure).
        try:
            mt = datetime.datetime.utcfromtimestamp(p.stat().st_mtime)
            when_iso = mt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            when_iso = _now_iso_z()
        if dup:
            print(f"  [notes] {p.name}: duplicate (who + text already on "
                  f"{pid}); moving to notes/ingested/ without re-inserting")
        else:
            _append_insight(review, pid, INSIGHT_HUMAN, body,
                            when=when_iso, who=who)
            ingested.append((pid, who))
        # Stage the move (do the actual filesystem move after the loop so a
        # mid-loop error doesn't leave a partial ingest state).
        to_move.append((p, ingested_dir / p.name))
    if to_move:
        try:
            ingested_dir.mkdir(parents=True, exist_ok=True)
        except OSError as ex:
            print(f"  [notes] could not create {ingested_dir}: {ex}",
                  file=sys.stderr)
            return ingested
        for src, dst in to_move:
            # If a same-named file already lives in ingested/, add a suffix
            # rather than overwrite (rare edge case: two teammates land the
            # same filename on the same day).
            final_dst = dst
            n = 1
            while final_dst.exists():
                final_dst = dst.with_name(f"{dst.stem}.{n}{dst.suffix}")
                n += 1
            try:
                os.replace(str(src), str(final_dst))
            except OSError as ex:
                print(f"  [notes] move failed for {src.name}: {ex}",
                      file=sys.stderr)
    return ingested

def emit_auto_insights(repo: Path, review, tuples, log_prefix="auto-insight"):
    """Apply a batch of (path, source, text, when, who) tuples, save once at
    the end under the review lock, and print a one-line summary. Returns the
    count actually appended (i.e. after dedup).

    Uses with_review_locked() so a concurrent --review CLI write to the same
    file cannot clobber the batch: we read the on-disk state INSIDE the lock,
    append onto it, and write out - so any human insight that landed between
    the caller's read and this call still survives. The `review` argument is
    also mutated in place with the merged post-write state so the caller's
    in-memory view stays consistent with disk."""
    if not tuples:
        return 0
    appended_count = [0]
    def _mutate(disk_review):
        # Merge caller's in-memory review dict onto the fresh disk read - any
        # human edit from a concurrent --review CLI invocation that landed
        # between the caller's read and now sits in disk_review, and we want
        # to keep it. Then apply the auto-insight appends onto the merged state.
        for path, entry in review.items():
            if path not in disk_review:
                disk_review[path] = entry
        for (path, source, text, when, who) in tuples:
            if _append_insight(disk_review, path, source, text, when=when, who=who):
                appended_count[0] += 1
        # Write disk_review's post-mutate state back to the caller's dict so
        # the rest of the run sees the auto-insights we just added.
        review.clear()
        review.update(disk_review)
    with_review_locked(repo, _mutate)
    if appended_count[0]:
        by_src = {}
        for (_, s, _, _, _) in tuples:
            by_src[s] = by_src.get(s, 0) + 1
        bits = ", ".join(f"{k}={v}" for k, v in sorted(by_src.items()))
        print(f"  [{log_prefix}] appended {appended_count[0]} new insight(s) ({bits})")
    return appended_count[0]

# ============================================================================
# PHASE 5 (post-pivot) - CLI REVIEW HELPER (--review + action flags)
# ============================================================================
# Additive `python tools/product_scope.py --review <id>` subcommand: takes
# one or more of --insight/--status/--role/--note/--sample-config/--notes
# and applies them atomically to product_review.json under the shared review
# lock. All value validation happens BEFORE the write, so a bad --status
# input can't leave a half-applied entry behind. Every successful write also
# stamps last_reviewed_by (from --author or `git config user.name`) and
# last_reviewed_date (today's ISO).
#
# Exit codes: 0 success, 2 validation / usage error, 1 other (write failed,
# JSON parse error, product not found).

def _git_user_name(repo: Path):
    """Return `git config user.name` for the repo, or "" on any failure.
    Kept as its own helper so both the CLI helper's author-default and any
    future auto-insight attribution use the same subprocess call."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "config", "user.name"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""

def cli_review_action(repo: Path, args):
    """Run one --review invocation. `args` is the argparse namespace from
    main() with all --review-family flags attached.

    Returns the process exit code. Side effect: at most one atomic write to
    product_review.json under with_review_locked(). No writes happen unless
    every validation step passes first (transactional)."""
    product_id = (args.review or "").strip()
    if not product_id:
        print("error: --review requires a product id (e.g. --review acs/acs5)",
              file=sys.stderr)
        return 2

    # ---- Author attribution -------------------------------------------------
    # Phase A #2 (2026-07-26): --author flag removed alongside --role/--note
    # (they only mattered for composite-role attribution). All writes now
    # attribute to git config user.name (with "unknown" fallback).
    author = _git_user_name(repo) or "unknown"

    # ---- Which actions did the caller pass? ---------------------------------
    action_flags = {
        "insight":       args.insight,
        "status":        args.status,
        "notes":         args.notes,
    }
    passed = {k: v for k, v in action_flags.items() if v is not None}
    if not passed:
        print("error: --review requires at least one action flag "
              "(--insight/--status/--notes)",
              file=sys.stderr)
        return 2

    # ---- Pre-flight value validation (nothing on disk changes here) ---------
    # Every value is normalised into `patch` up front so the mutator only has
    # to apply verified inputs. Any failure returns 2 immediately - no write.
    patch = {}

    if "insight" in passed:
        text = str(passed["insight"] or "").strip()
        if not text:
            print("error: --insight text is empty (nothing to append)",
                  file=sys.stderr)
            return 2
        patch["insight"] = text

    if "status" in passed:
        raw = str(passed["status"] or "").strip()
        canon = raw.lower()
        if canon not in STAGES:
            print(f"error: --status must be one of "
                  f"{'/'.join(STAGE_LABELS[s] for s in STAGES)} "
                  f"(got {raw!r})", file=sys.stderr)
            return 2
        patch["stage"] = canon

    if "notes" in passed:
        patch["note"] = str(passed["notes"] or "")

    # Phase A #2 (2026-07-26): --role / --note / --author validation, plus
    # the interactive TTY prompt for --role-without---note, all removed. The
    # composite framing is on hold, so this CLI helper no longer sets or
    # clears composite_role / composite_role_note. Existing role values in
    # product_review.json still round-trip on read (schema preserved); only
    # the write path is retired.

    # ---- Atomic read-modify-write under the review lock ---------------------
    outcome = {"code": 0, "err": None, "summary": []}

    def _mutate(review):
        if product_id not in review or not isinstance(review.get(product_id), dict):
            outcome["code"] = 1
            outcome["err"] = (f"no review entry for {product_id!r} - "
                              "run `python tools/product_scope.py` "
                              "first so the catalog is loaded into "
                              "product_review.json.")
            return
        entry = _ensure_review_shape(review[product_id])

        # Phase A #2 (2026-07-26): composite_role / composite_role_note
        # patching removed - the CLI no longer accepts --role/--note, so the
        # write path never sees those keys. Schema-read of both fields is
        # preserved by _ensure_review_shape() so existing FOCUS entries
        # round-trip cleanly.

        # Apply the patch. Summary bits track what changed for the success line.
        bits = []
        if "stage" in patch:
            entry["stage"] = patch["stage"]
            bits.append(f"status -> {STAGE_LABELS[patch['stage']]}")
        if "note" in patch:
            entry["note"] = patch["note"]
            bits.append("notes updated")

        if "insight" in patch:
            ins = _append_insight(review, product_id, INSIGHT_HUMAN,
                                   patch["insight"], who=author)
            if ins:
                bits.append("+1 insight")
            else:
                # Only auto-insight dedup would swallow an append silently.
                # Human insights never dedup, so ins=None here means the
                # append helper rejected the input; surface it.
                bits.append("insight rejected (empty text?)")

        # Always stamp the reviewer + date on any successful write.
        entry["last_reviewed_by"]   = author
        entry["last_reviewed_date"] = datetime.date.today().isoformat()

        outcome["summary"] = bits

    try:
        with_review_locked(repo, _mutate)
    except Exception as ex:
        print(f"error: write failed: {ex!r}", file=sys.stderr)
        return 1

    if outcome["err"]:
        print(f"error: {outcome['err']}", file=sys.stderr)
        return outcome["code"]

    print(f"updated {product_id}: " + ", ".join(outcome["summary"]))
    return 0

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
    print(f"Wrote {out.name} ({len(store)} probed products). Re-run without --probe to rebuild the report.")

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
EDA_DIFF_FILE             = ".scope_last_eda_diff.json"  # gitignored via .product_scope pattern

def load_eda_diffs(repo: Path):
    """Read {path: [change_string, ...]} from the last --sample run. Returns {}
    when the file is missing (no refresh has happened, or nothing changed)."""
    p = repo / EDA_DIFF_FILE
    if not p.exists(): return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        return payload.get("diffs", {}) or {}
    except Exception:
        return {}

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

EDA_MISS_DELTA_PP  = 10.0     # per-column missingness change flagged as material
EDA_ROW_DELTA_PCT  = 10.0     # row-count delta flagged as material (percent)

def diff_eda(old_entry, new_entry):
    """Compare two cache entries for the same product. Returns a list of
    plain-English change strings (empty when nothing material changed).

    Materiality rules (from spec):
      - new/removed columns (any)
      - per-column dtype changed
      - per-column missingness delta > EDA_MISS_DELTA_PP percentage points
      - row-count delta > EDA_ROW_DELTA_PCT percent
    Deltas that fall below the threshold are silent by design - the diff exists
    to catch material drift, not to catalog every rounding wiggle."""
    changes = []
    if not old_entry:
        return changes    # no baseline means everything is new (not a 'change')

    old_shape = old_entry.get("shape") or [0, 0]
    new_shape = new_entry.get("shape") or [0, 0]
    old_rows = int(old_shape[0]) if old_shape else 0
    new_rows = int(new_shape[0]) if new_shape else 0
    if old_rows > 0:
        delta_pct = abs(new_rows - old_rows) * 100.0 / old_rows
        if delta_pct > EDA_ROW_DELTA_PCT:
            direction = "gained" if new_rows > old_rows else "lost"
            changes.append(f"row count {direction} {abs(new_rows - old_rows):,} "
                           f"({delta_pct:.1f}%): {old_rows:,} -> {new_rows:,}")

    old_cols = old_entry.get("columns", {}) or {}
    new_cols = new_entry.get("columns", {}) or {}
    added   = sorted(c for c in new_cols if c not in old_cols)
    removed = sorted(c for c in old_cols if c not in new_cols)
    if added:
        preview = ", ".join(f"`{c}`" for c in added[:4])
        more = f" (+{len(added)-4} more)" if len(added) > 4 else ""
        changes.append(f"gained {len(added)} column(s): {preview}{more}")
    if removed:
        preview = ", ".join(f"`{c}`" for c in removed[:4])
        more = f" (+{len(removed)-4} more)" if len(removed) > 4 else ""
        changes.append(f"lost {len(removed)} column(s): {preview}{more}")

    for col in sorted(set(old_cols) & set(new_cols)):
        oc, nc = old_cols[col], new_cols[col]
        if (oc.get("dtype") or "") != (nc.get("dtype") or ""):
            changes.append(f"dtype changed for `{col}`: "
                           f"{oc.get('dtype','')} -> {nc.get('dtype','')}")
        om = float(oc.get("missing_pct") or 0.0)
        nm = float(nc.get("missing_pct") or 0.0)
        if abs(nm - om) > EDA_MISS_DELTA_PP:
            direction = "jumped" if nm > om else "dropped"
            changes.append(f"missingness in `{col}` {direction} "
                           f"{abs(nm - om):.0f}pp: {om:.0f}% -> {nm:.0f}%")
    return changes

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
    Requests are silent on stdout - callers own the log line. 429 (rate-limited)
    is retried once even in the 4xx range - the one case where 4xx retry is correct."""
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
            # Rate-limited: retry once even in the 4xx range.
            if ex.code == 429 and attempt == 1 and retry:
                import time as _t; _t.sleep(1.0)
                continue
            if ex.code and ex.code < 500: raise   # other 4xx: don't retry
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

def _print_sample_summary(summary, single_mode):
    """End-of-run summary, human-readable. Called by sample_products() once
    all targets have been processed. Kept plain-text - it goes to stdout, not
    the HTML report."""
    sampled = summary.get("sampled", [])
    fresh   = summary.get("skipped_fresh", [])
    nonapi  = summary.get("skipped_non_api", [])
    failed  = summary.get("failed", [])
    diffs   = summary.get("diffs", {})
    banner  = "sample" if single_mode else "sample batch"
    total   = len(sampled) + len(fresh) + len(nonapi) + len(failed)
    print(f"[{banner}] finished: {total} target(s) processed")
    print(f"           sampled ok      : {len(sampled)}")
    print(f"           skipped (fresh) : {len(fresh)}")
    print(f"           skipped (non-API): {len(nonapi)}")
    print(f"           failed          : {len(failed)}")
    if diffs:
        n_ch = sum(len(v) for v in diffs.values())
        print(f"           EDA drift       : {len(diffs)} product(s), "
              f"{n_ch} material change(s) (see 'Since last regeneration' banner)")
    if failed:
        print("           failure details:")
        for f in failed:
            reason = f.get("reason", "unknown")
            print(f"             - {f['path']}: {reason}")

def sample_products(repo, fams, review, probes, only_product, size, refresh, git=None):
    """Run one or many samples. When only_product is set, sample just that one;
    otherwise batch through every product currently marked 'candidate' in the
    review file. Skips fresh cache entries (age < SAMPLE_FRESH_DAYS days) unless
    refresh is True; skips non-API products with a clear message. Persists
    successful samples to scope_data_cache.json. Returns a summary dict with
    counts and per-product results for the caller to display.

    Note - on-demand semantics:
      * --sample <PRODUCT_ID> (single-product mode) -> hits the API immediately.
        The freshness short-circuit below only applies when we're batch-iterating
        candidates without --refresh. Requesting one product by ID is a
        deliberate reviewer action, and re-fetching is what the reviewer asked
        for; the tool should not silently skip it based on a 7-day cache.
    """
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
              "product_review.json (or pass --sample <ID> to sample one directly).")
        return {"sampled": [], "skipped_fresh": [], "skipped_non_api": [],
                "failed": [], "diffs": {}}

    print(f"[sample] {len(targets)} target(s); size={size}; "
          f"api_key={'yes' if api_key else 'no'}; "
          f"refresh={'yes' if refresh else 'no'}")
    if not api_key:
        print("  [note] No CENSUS_API_KEY set - using anonymous access "
              "(500 req/day/IP limit).")
        print("         Get a key at https://api.census.gov/data/key_signup.html "
              "and add to .env if you need more volume.")
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
        # exists and the user didn't force --refresh. Only applies in BATCH
        # mode (only_product is None). Single --sample <PRODUCT_ID> always
        # hits the API - the reviewer explicitly asked for that product, and
        # silently returning a stale-ish cache instead is surprising.
        cached = cache.get(path)
        if only_product is None and not refresh and is_sample_fresh(cached):
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
            # #6: diff against the previous cache entry (if any) BEFORE we
            # overwrite it, so the report can flag what changed on rerun.
            prev = cache.get(path)
            changes = diff_eda(prev, new_entry) if prev else []
            if changes:
                summary["diffs"][path] = changes
                for ch in changes:
                    print(f"           DIFF: {ch}")
            cache[path] = new_entry
            summary["sampled"].append({"path": path, "url": url,
                                        "rows": len(df), "cols": len(df.columns),
                                        "eda": eda, "diff": changes})
        # Be network-polite between requests.
        if i < len(targets) - 1:
            import time as _t; _t.sleep(SAMPLE_INTER_REQUEST_MS / 1000.0)

    # Persist cache once (single write, deterministic key order).
    save_data_cache(repo, cache)
    _print_sample_summary(summary, only_product is not None)
    # #6: dump per-product diffs to a small file so the next HTML regen can
    # surface them - overwritten on every --sample run (empty when nothing
    # changed materially). Kept alongside the diff snapshot for symmetry.
    diff_path = repo / EDA_DIFF_FILE
    if summary["diffs"]:
        diff_path.write_text(json.dumps(
            {"written_at": datetime.datetime.now(datetime.timezone.utc)
                              .strftime("%Y-%m-%dT%H:%M:%SZ"),
             "diffs": dict(sorted(summary["diffs"].items()))},
            indent=2), encoding="utf-8")
    else:
        # Clear any stale diff from a previous refresh so the banner doesn't
        # keep showing week-old changes.
        if diff_path.exists():
            try: diff_path.unlink()
            except OSError: pass
    return summary

# ============================================================================
# REPORT
# ============================================================================

TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Product Scope - Census Uncertainty Analytics</title>
<style>
:root{
  --navy:#1F2A5C;--deep:#16204A;--gold:#C9A227;--ice:#EEF2FA;--line:#CADCFC;--ink:#22283B;--muted:#5A6072;
  /* ----- Radix Themes 9-step type scale (adopted 2026-07-26) -----
     Rip-replaces the pre-existing 21-distinct-font-size mess. Every visible
     size on the page now resolves to one of these tokens, and every line-
     height is a 4px multiple that pairs with its step. The weight ladder is
     400 body / 500 emphasis / 600 headline (no 300, no 700 anywhere).
     Font stacks: sans (body/UI), mono (numbers, code, paths), display
     (hero moments only - H1, section transitions, hero numbers).
     External WOFF2 bundling for IBM Plex Sans / IBM Plex Mono / Fraunces
     could not land in this commit: the sandbox blocks Google Fonts,
     Fontsource, jsDelivr, unpkg, and raw.githubusercontent.com. Instead we
     use tight system-font stacks that match the DNA of those faces (Plex
     is a modern humanist grotesque, so Segoe UI Variable / system-ui hits
     the same slot; Fraunces is a warm serif, Georgia is the closest
     Windows/Mac shared fallback). When network access lands, one @font-face
     block at the top of this <style> is the only change needed to bundle
     the real WOFF2 files inline. */
  --f-sans:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;
  --f-mono:ui-monospace,"Cascadia Mono","SF Mono",Consolas,"Liberation Mono",Menlo,monospace;
  --f-display:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif;
  /* Nine steps, each with its own paired line-height. */
  --fs-1:12px; --lh-1:16px;   /* micro-labels, badges, source pointers        */
  --fs-2:14px; --lh-2:20px;   /* metadata, table cells, secondary UI          */
  --fs-3:16px; --lh-3:24px;   /* BODY default                                 */
  --fs-4:18px; --lh-4:26px;   /* callouts, card titles                        */
  --fs-5:20px; --lh-5:28px;   /* subheads                                     */
  --fs-6:24px; --lh-6:32px;   /* section headers                              */
  --fs-7:28px; --lh-7:36px;   /* panel titles                                 */
  --fs-8:36px; --lh-8:40px;   /* hero secondary                               */
  --fs-9:60px; --lh-9:60px;   /* hero primary number                          */
  /* Weight ladder - ban 300 and 700; use 400/500/600 only. */
  --w-body:400; --w-emph:500; --w-head:600;
  /* Negative letter-spacing on headlines (Vercel Geist convention). */
  --lsp-tight:-0.02em; --lsp-tighter:-0.03em;
}
*{box-sizing:border-box;margin:0;}
/* Base body: 16px/24 Radix step 3 sans, per the type system rip-replace. */
body{font-family:var(--f-sans);font-size:var(--fs-3);line-height:var(--lh-3);font-weight:var(--w-body);color:var(--ink);background:#fff;padding:0 0 60px;font-feature-settings:"ss01","cv11";}
/* Every headline gets weight 600 + tight tracking. 24px+ -> -.02em, 36px+ -> -.03em. */
h1,h2,h3,.starthere .sh-title,.wti-recent h3,.lscape-fallback-head{font-family:var(--f-display);font-weight:var(--w-head);letter-spacing:var(--lsp-tight);}
h1{letter-spacing:var(--lsp-tighter);}
header{background:var(--deep);color:#fff;padding:26px 44px 0;}
.kicker{color:var(--gold);font-weight:var(--w-head);font-size:var(--fs-2);letter-spacing:.22em;text-transform:uppercase;}
h1{font-family:var(--f-display);font-size:var(--fs-7);margin:6px 0 4px;}
header p{color:#CADCFC;font-size:var(--fs-2);max-width:940px;}
.tabs{display:flex;gap:4px;margin-top:18px;flex-wrap:wrap;}
.tab{padding:9px 17px;border-radius:8px 8px 0 0;background:#28356B;color:#CADCFC;cursor:pointer;
     font-size:var(--fs-2);font-weight:var(--w-emph);border:0;font-family:inherit;}
.tab .n{opacity:.65;font-weight:400;margin-left:5px;}
.tab.on{background:#fff;color:var(--navy);}
.wrap{padding:20px 44px;max-width:1300px;}
.panel{display:none;} .panel.on{display:block;}
.blurb{font-size:var(--fs-2);color:var(--muted);background:var(--ice);border-left:3px solid var(--line);
       padding:8px 12px;border-radius:4px;margin-bottom:14px;max-width:920px;}
.filter{margin:0 0 14px;}
.filter input{width:340px;padding:7px 11px;border:1px solid var(--line);border-radius:7px;font:inherit;font-size:var(--fs-2);}
.filter span{font-size:var(--fs-2);color:var(--muted);margin-left:10px;}
/* Phase A ceiling-push #2: keyboard-hint chip injected at load time under
   every products-panel filter input. Wraps if the filter row gets narrow. */
.filter-kbd-hint{display:inline-block;font-size:var(--fs-1);color:var(--muted);
     margin-left:12px;letter-spacing:.01em;}
.filter-kbd-hint kbd{display:inline-block;padding:0 5px;font-family:var(--f-mono);
     font-size:var(--fs-1);background:var(--ice);color:var(--navy);border:1px solid var(--line);
     border-radius:3px;box-shadow:inset 0 -1px 0 #CADCFC;font-weight:var(--w-head);line-height:14px;
     margin:0 1px;}
/* Beginner-UX pass commit #2. First-visit "Start here" banner: dismissible via
   localStorage. Sits between the freshness bar and the tab panels. Renders on
   every page but hides itself once dismissed on this machine. */
.starthere{background:#FBF8EC;border:1px solid var(--gold);border-radius:8px;
     padding:12px 46px 12px 16px;margin:14px 44px 0;max-width:1300px;
     position:relative;font-size:var(--fs-2);color:#4E3E11;line-height:1.55;}
.starthere.dismissed{display:none;}
.starthere .sh-title{font-family:var(--f-display);color:var(--navy);font-size:var(--fs-3);
     font-weight:var(--w-head);margin:0 0 5px;letter-spacing:.005em;}
.starthere ol{margin:2px 0 0 22px;padding:0;}
.starthere li{margin:3px 0;padding-left:2px;}
.starthere .sh-dismiss{position:absolute;top:8px;right:10px;background:transparent;
     border:0;color:var(--muted);font-size:var(--fs-3);line-height:1;cursor:pointer;
     padding:4px 6px;border-radius:4px;font-family:inherit;}
.starthere .sh-dismiss:hover{background:var(--ice);color:var(--navy);}
/* Home-tab "Find a product" search (2026-07-26). Leads the Get-oriented
   chapter (the Phase-1 hero card that used to sit above it was retired
   2026-07-26 per Garrett's live test - the findings now live in the Team
   Pulse stat cards, with a small report link in the wwl tail).
   Curriculum is the "no idea where to start" path; search is the
   "I have a question" path. Both are first-order discovery moves.
   Neutral palette; navy header + ice input surfaces match the report chrome. */
.home-search{background:#F7F9FC;border:1px solid var(--line);border-radius:9px;
     padding:16px 20px 18px;margin:0 0 26px;max-width:1020px;}
.home-search h2{font-family:var(--f-display);font-size:var(--fs-5);color:var(--navy);
     font-weight:var(--w-head);margin:0 0 4px;letter-spacing:var(--lsp-tight);}
.home-search h2 .hs-emoji{margin-right:8px;}
.home-search .hs-sub{font-size:var(--fs-2);color:var(--muted);line-height:var(--lh-2);
     margin:0 0 12px;max-width:820px;}
.home-search .hs-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;
     margin:0 0 10px;}
.home-search input[type=search]{flex:1 1 340px;min-width:220px;
     padding:9px 12px;border:1px solid var(--line);border-radius:7px;
     font:inherit;font-size:var(--fs-3);background:#fff;color:var(--ink);
     transition:border-color .12s ease, box-shadow .12s ease;}
.home-search input[type=search]:focus{outline:none;border-color:var(--navy);
     box-shadow:0 0 0 3px rgba(31,42,92,0.12);}
.home-search select{padding:8px 10px;border:1px solid var(--line);border-radius:7px;
     font:inherit;font-size:var(--fs-2);background:#fff;color:var(--ink);
     min-width:170px;cursor:pointer;}
.home-search select:focus{outline:none;border-color:var(--navy);
     box-shadow:0 0 0 3px rgba(31,42,92,0.12);}
.home-search .hs-clear{background:transparent;color:var(--muted);
     border:1px solid var(--line);border-radius:6px;padding:7px 12px;
     font:inherit;font-size:var(--fs-2);cursor:pointer;
     transition:background .12s ease, color .12s ease;}
.home-search .hs-clear:hover{background:var(--ice);color:var(--navy);}
.home-search .hs-clear:focus-visible{outline:2px solid var(--gold);outline-offset:2px;}
.home-search .hs-kbd{font-size:var(--fs-1);color:var(--muted);margin-left:auto;
     letter-spacing:.01em;flex:0 0 auto;}
.home-search .hs-kbd kbd{display:inline-block;padding:0 5px;font-family:var(--f-mono);
     font-size:var(--fs-1);background:var(--ice);color:var(--navy);
     border:1px solid var(--line);border-radius:3px;
     box-shadow:inset 0 -1px 0 #CADCFC;font-weight:var(--w-head);line-height:14px;
     margin:0 1px;}
.home-search .hs-results{margin-top:10px;}
.home-search .hs-summary{font-size:var(--fs-2);color:var(--muted);margin:0 0 6px;
     font-family:var(--f-mono);font-variant-numeric:tabular-nums;}
.home-search .hs-list{list-style:none;padding:0;margin:0;
     border-top:1px solid var(--line);}
.home-search .hs-item{padding:9px 4px 9px 4px;border-bottom:1px solid var(--ice);
     display:flex;gap:12px;align-items:flex-start;}
.home-search .hs-emoji-col{flex:0 0 auto;font-size:var(--fs-4);line-height:1;
     padding-top:2px;}
.home-search .hs-body-col{flex:1;min-width:0;}
.home-search .hs-title{font-family:var(--f-display);font-size:var(--fs-4);
     color:var(--navy);font-weight:var(--w-head);letter-spacing:var(--lsp-tight);
     margin:0 0 3px;line-height:1.3;}
.home-search .hs-title code{font-family:var(--f-mono);font-size:var(--fs-2);
     color:var(--muted);background:transparent;margin-left:8px;
     font-weight:var(--w-body);letter-spacing:0;}
.home-search .hs-desc{font-size:var(--fs-2);color:var(--ink);line-height:var(--lh-2);
     margin:0 0 4px;max-width:760px;}
.home-search .hs-meta{font-size:var(--fs-1);color:var(--muted);line-height:1.4;
     font-family:var(--f-mono);}
.home-search .hs-meta .hs-matched{color:var(--navy);font-weight:var(--w-emph);}
.home-search .hs-meta mark{background:#FFF3B0;color:var(--navy);padding:0 2px;
     border-radius:2px;font-weight:var(--w-emph);}
.home-search .hs-open{background:var(--navy);color:#fff;text-decoration:none;
     font-weight:var(--w-head);font-size:var(--fs-1);letter-spacing:.02em;
     padding:5px 11px;border-radius:5px;flex:0 0 auto;align-self:flex-start;
     margin-top:3px;transition:background .12s ease-out;}
.home-search .hs-open:hover{background:#0F1740;}
.home-search .hs-open:focus-visible{outline:2px solid var(--gold);outline-offset:2px;}
.home-search .hs-open .arrow{margin-left:4px;font-weight:400;}
.home-search .hs-showall{display:inline-block;margin-top:10px;color:var(--navy);
     text-decoration:none;font-size:var(--fs-2);font-weight:var(--w-emph);
     border-bottom:1px dotted var(--navy);}
.home-search .hs-showall:hover{color:#0F1740;border-bottom-style:solid;}
.home-search .hs-empty{padding:12px 4px;color:var(--muted);font-size:var(--fs-2);
     line-height:var(--lh-2);}
.home-search .hs-empty b{color:var(--navy);}
.home-search .hs-empty .hs-sugg a{color:var(--navy);text-decoration:none;
     border-bottom:1px dotted var(--navy);margin:0 4px;cursor:pointer;}
.home-search .hs-empty .hs-sugg a:hover{color:#0F1740;border-bottom-style:solid;}
.home-search .hs-hidden{display:none;}
/* "Explore data" primary CTA (2026-07-26). Sits at the top of every card's
   Quick Look block so it's the first link a reviewer's eye goes to. Warmer
   than the neutral text around it and heavier than the secondary command
   copy-buttons - the point is that data.census.gov is what people actually
   use to look at Census data, and every card should surface that path in
   one click. */
.ql-dcgov{background:var(--ice);border:1px solid var(--line);border-radius:6px;
     padding:8px 12px;margin:0 0 10px;display:flex;align-items:center;
     gap:12px;flex-wrap:wrap;}
.ql-dcgov-btn{display:inline-flex;align-items:center;gap:6px;
     background:var(--navy);color:#fff;text-decoration:none;
     font-weight:var(--w-head);font-size:var(--fs-2);letter-spacing:.02em;
     padding:6px 12px;border-radius:5px;flex:0 0 auto;
     transition:background .12s ease-out;}
.ql-dcgov-btn:hover{background:#0F1740;}
.ql-dcgov-btn:focus-visible{outline:2px solid var(--gold);outline-offset:2px;}
.ql-dcgov-btn .arrow{font-weight:400;}
.ql-dcgov-tag{color:var(--muted);font-size:var(--fs-2);line-height:1.35;flex:1;
     min-width:220px;}
.ql-dcgov-tag b{color:var(--navy);font-weight:var(--w-emph);}
/* Phase-1 report footer link on card drill-downs (2026-07-26). Small tinted
   row anchoring the drill-down back to the report section that covers this
   product. Gold-family palette matches the report's identity elsewhere in
   the tool (e.g. the Team Pulse report link). */
.ql-d-p1link{background:#FBF6E4;border:1px solid #E8D9A5;border-radius:5px;
     padding:8px 11px;margin:8px 0 2px;font-size:var(--fs-2);color:#4E3E11;
     line-height:1.45;}
.ql-d-p1link .p1-label{color:#7A5C0F;font-weight:var(--w-head);font-size:var(--fs-1);
     letter-spacing:.10em;text-transform:uppercase;margin-right:8px;}
.ql-d-p1link a{color:var(--navy);text-decoration:none;
     border-bottom:1px dotted #B69B45;font-weight:var(--w-emph);}
.ql-d-p1link a:hover{color:#3A4890;border-bottom-style:solid;}
/* Beginner-UX pass commit #2. Inline glossary tooltip. Circle-question after a
   term; hover reveals the definition. Pure CSS (no JS needed). ::after tooltip
   positions above the ? and pointer-events:none so it can't intercept clicks.
   Falls back to native title= attribute in browsers without :hover (touch). */
.gloss{display:inline-block;width:14px;height:14px;line-height:14px;text-align:center;
     background:var(--ice);color:var(--navy);border:1px solid var(--line);
     border-radius:50%;font-size:var(--fs-1);font-weight:var(--w-head);font-style:normal;
     cursor:help;margin:0 3px;position:relative;vertical-align:2px;
     font-family:var(--f-sans);}
.gloss:hover{background:var(--gold);color:#16204A;border-color:var(--gold);}
.gloss::after{content:attr(data-tip);position:absolute;bottom:calc(100% + 6px);
     left:50%;transform:translateX(-50%);background:var(--navy);color:#fff;
     font-size:var(--fs-1);font-weight:400;text-align:left;line-height:1.4;
     padding:7px 10px;border-radius:5px;width:max-content;max-width:280px;
     white-space:normal;box-shadow:0 3px 12px rgba(0,0,0,.24);z-index:20;
     opacity:0;pointer-events:none;transition:opacity .14s ease-in .04s;}
.gloss::before{content:"";position:absolute;bottom:calc(100% + 1px);left:50%;
     transform:translateX(-50%);border:5px solid transparent;
     border-top-color:var(--navy);opacity:0;pointer-events:none;
     transition:opacity .14s ease-in .04s;}
.gloss:hover::after,.gloss:hover::before,.gloss:focus::after,.gloss:focus::before{
     opacity:1;}
/* Phase A 2026-07-26 commit #3: inline-body variant of .gloss for auto-
   tooltipped jargon in body copy. Instead of a standalone ? badge, wraps
   the term itself with a dotted underline + tiny superscript ? mark so a
   reader can tell the word is defined without breaking the sentence flow.
   Shares the .gloss tooltip machinery via a re-used pattern below. */
.gloss-inline{position:relative;display:inline;cursor:help;
     border-bottom:1px dotted #8FA8D8;color:inherit;font-style:normal;
     text-decoration:none;}
.gloss-inline:hover,.gloss-inline:focus{color:var(--navy);outline:none;
     border-bottom-style:solid;border-bottom-color:var(--gold);}
.gloss-inline .gloss-mark{color:var(--muted);font-weight:var(--w-head);
     font-size:0.72em;margin-left:1px;vertical-align:0.25em;line-height:1;}
.gloss-inline:hover .gloss-mark,.gloss-inline:focus .gloss-mark{
     color:var(--navy);}
.gloss-inline::after{content:attr(data-tip);position:absolute;
     bottom:calc(100% + 6px);left:0;background:var(--navy);color:#fff;
     font-size:var(--fs-1);font-weight:400;text-align:left;line-height:1.4;
     padding:7px 10px;border-radius:5px;width:max-content;max-width:280px;
     white-space:normal;box-shadow:0 3px 12px rgba(0,0,0,.24);z-index:20;
     opacity:0;pointer-events:none;
     transition:opacity .14s ease-in .04s;}
.gloss-inline::before{content:"";position:absolute;bottom:calc(100% + 1px);
     left:12px;border:5px solid transparent;border-top-color:var(--navy);
     opacity:0;pointer-events:none;
     transition:opacity .14s ease-in .04s;}
.gloss-inline:hover::after,.gloss-inline:hover::before,
.gloss-inline:focus::after,.gloss-inline:focus::before{opacity:1;}
/* Beginner-UX pass commit #4. Single "Learn more" one-command button pinned
   to the top of every card drill-down. Bold gold background so it reads as
   the primary action; keyboard focus ring included. The "More options for
   advanced users" collapsible below holds the individual probe / sample
   commands for the (few) users who want to run them separately. */
.ql-lm-wrap{background:#FBF8EC;border:1px solid var(--gold);border-radius:6px;
     padding:8px 10px;margin:2px 0 8px;}
.ql-lm-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px;}
.ql-lm-btn{font:inherit;font-size:var(--fs-2);font-weight:var(--w-head);padding:7px 14px;
     border:0;border-radius:6px;background:var(--gold);color:#16204A;
     cursor:pointer;line-height:1.3;letter-spacing:.01em;}
.ql-lm-btn:hover{background:#B7912A;color:#fff;}
.ql-lm-btn:focus-visible{outline:2px solid var(--navy);outline-offset:2px;}
.ql-lm-btn.done{background:#5FA76F;color:#fff;}
.ql-lm-note{font-size:var(--fs-1);color:#8a4d1c;font-style:italic;flex:1;min-width:0;}
.ql-lm-more{margin-top:8px;font-size:var(--fs-1);color:var(--muted);}
/* Caret + marker handling now comes from the unified `details.disc` grammar
   (condense pass 2026-07-26); only the type-scale tweak stays local. */
.ql-lm-more > summary{letter-spacing:.02em;}
.ql-lm-more-body{padding:5px 4px 2px;}
.ql-lm-sub{font-size:var(--fs-1);color:var(--muted);font-weight:var(--w-head);letter-spacing:.05em;
     text-transform:uppercase;margin-bottom:2px;}
/* Beginner-UX pass commit #5. "+ Add a note" button + hint. Small ice-blue
   button so it doesn't compete with the gold "Learn more" primary action;
   sits at the bottom of every card's insights feed. */
.ql-addnote-wrap{display:flex;flex-wrap:wrap;align-items:center;gap:8px;
     padding:8px 4px 2px;margin-top:6px;border-top:1px dotted #E1E7F0;}
.ql-addnote-btn{font:inherit;font-size:var(--fs-2);font-weight:var(--w-head);padding:5px 12px;
     border:1px solid var(--line);border-radius:5px;background:var(--ice);
     color:var(--navy);cursor:pointer;line-height:1.3;}
.ql-addnote-btn:hover{background:var(--navy);color:#F5D77A;border-color:var(--navy);}
.ql-addnote-btn:focus-visible{outline:2px solid var(--gold);outline-offset:2px;}
.ql-addnote-btn.done{background:#5FA76F;color:#fff;border-color:#5FA76F;}
.ql-addnote-hint{font-size:var(--fs-1);color:var(--muted);flex:1;min-width:200px;
     line-height:1.4;}
.ql-addnote-hint code{background:var(--ice);color:var(--navy);
     font-family:var(--f-mono);font-size:var(--fs-1);padding:0 4px;
     border-radius:3px;}
/* .funnel / .fstep / .farrow / .f-cand / .f-focus removed Phase A #3
   alongside _build_reviewer_mode_details() — the pre-reframe funnel bar
   was 568 -> 0 -> 0 -> 5 -> 0 (depressing without being informative). */
h2{font-family:var(--f-display);color:var(--navy);font-size:var(--fs-5);margin:26px 0 4px;}
.sub{font-size:var(--fs-2);color:var(--muted);margin-bottom:10px;max-width:900px;}
table.rep{border-collapse:collapse;width:100%;max-width:1020px;font-size:var(--fs-2);margin-bottom:6px;}
table.rep th{text-align:left;font-size:var(--fs-1);letter-spacing:.08em;text-transform:uppercase;
             color:var(--muted);border-bottom:2px solid var(--ice);padding:6px 9px;}
table.rep td{border-bottom:1px solid var(--ice);padding:7px 9px;vertical-align:top;}
.mono{font-family:var(--f-mono);font-size:var(--fs-2);color:var(--muted);}
.gsec{margin:12px 0 6px;}
.ghead{font-family:var(--f-display);color:var(--navy);font-size:var(--fs-4);cursor:pointer;padding:4px 0;border-bottom:2px solid var(--ice);}
.ghead:before{content:"\25BE  ";color:var(--gold);}
.gsec.gfold .ghead:before{content:"\25B8  ";}
.gsec.gfold .prod{display:none;} .gsec.gfold .psec{display:none;}
.psec{margin:6px 0 6px 18px;}
.phead{font-size:var(--fs-2);font-weight:var(--w-head);color:#50639B;cursor:pointer;padding:3px 0;border-bottom:1px solid var(--ice);}
.phead:before{content:"\25BE  ";color:var(--line);}
.psec.pfold .phead:before{content:"\25B8  ";}
.psec.pfold .prod{display:none;}
.phead em{font-style:normal;color:var(--muted);font-size:var(--fs-1);margin-left:7px;font-weight:400;}
.ghead em{font-family:var(--f-sans);font-style:normal;color:var(--muted);font-size:var(--fs-2);margin-left:8px;}
.prod{display:table;width:100%;margin:9px 0;}
/* Phase A ceiling-push #2: subtle focus ring for keyboard j/k nav so the
   reader knows which card Enter would toggle. :focus-visible so a mouse
   click doesn't paint the ring; :focus is a fallback for browsers that
   don't yet support :focus-visible. */
.prod:focus{outline:none;}
.prod:focus-visible{outline:2px solid #C9A227;outline-offset:2px;
     border-radius:5px;}
.pnode,.branches{display:table-cell;vertical-align:top;}
.pnode{width:350px;min-width:350px;}
.pcard{border:1px solid var(--line);border-left:6px solid var(--line);border-radius:8px;padding:9px 12px;cursor:pointer;background:#fff;}
.pcard .path{font-family:var(--f-mono);font-size:var(--fs-2);font-weight:var(--w-head);color:var(--navy);word-break:break-all;}
.pcard .title{font-size:var(--fs-2);color:var(--muted);line-height:1.3;margin-top:1px;}
.pcard .mini{margin-top:5px;}
/* .qbox / #qbar (per-card probe checkbox + bottom-right queue slideout) removed
   in the beginner-UX pass (commit #1). The single-shot `--probe <path>` CLI +
   the per-card "Suggested next step" copy button are the one true path now. */
.stagechip,.workchip,.kindchip,.rolechip{display:inline-block;padding:2px 9px;border-radius:10px;font-size:var(--fs-1);
      font-weight:var(--w-head);border:1px solid var(--line);margin-right:5px;}
.workchip{font-weight:var(--w-emph);}
.kindchip{font-weight:var(--w-emph);background:#fff;color:var(--muted);}
.rolechip{background:#F1E7C8;color:#6B4E11;border-color:var(--gold);font-weight:var(--w-head);cursor:help;}
.w4{background:var(--navy);color:#F5D77A;} .w3{background:#50639B;color:#fff;} .w2{background:#8FA8D8;color:#16204A;}
.w1{background:var(--ice);color:var(--navy);} .w0{background:#F6F7FA;color:#9AA0B0;}
.fcount{font-size:var(--fs-1);color:var(--gold);font-weight:var(--w-head);}
.branches{padding-left:34px;position:relative;}
.prod.folded .branches{display:none;}
.branch{position:relative;margin:0 0 8px 0;max-width:820px;}
.branch:before{content:"";position:absolute;left:-24px;top:16px;width:24px;border-top:2px solid var(--line);}
.branch:after{content:"";position:absolute;left:-24px;top:-8px;height:24px;border-left:2px solid var(--line);}
.branch:first-child:after{top:16px;height:0;}
.branch + .branch:after{top:-14px;height:30px;}
.bcard{border:1px solid var(--line);border-radius:8px;padding:8px 12px;background:#fff;}
.blabel{font-size:var(--fs-1);font-weight:var(--w-head);letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-bottom:3px;}
.unc{font-size:var(--fs-2);background:var(--ice);border-left:3px solid var(--gold);padding:6px 9px;border-radius:4px;}
.unc.todo{border-left-color:#c96a27;font-style:italic;color:#8a4d1c;}
.desc{font-size:var(--fs-2);color:var(--muted);line-height:1.45;}
.krow{display:table;width:100%;max-width:430px;border-collapse:separate;border-spacing:3px 0;margin-top:4px;}
.kbox{display:table-cell;height:22px;border-radius:4px;text-align:center;vertical-align:middle;border:1px solid var(--line);font-size:var(--fs-1);font-weight:var(--w-emph);width:20%;}
.s0{background:#EDF0F7;color:#5A6072;} .s1{background:#CADCFC;color:#1F2A5C;} .s2{background:#8FA8D8;color:#16204A;}
.s3{background:#50639B;color:#fff;} .s4{background:#1F2A5C;color:#F5D77A;}
.inferred{font-size:var(--fs-1);color:#8a4d1c;font-style:italic;margin-top:3px;}
.receipts{font-size:var(--fs-1);color:var(--muted);font-family:var(--f-mono);line-height:1.5;margin-top:5px;}
.receipt-link{color:#3A4890;text-decoration:none;border-bottom:1px dotted #8FA8D8;}
.receipt-link:hover{color:var(--navy);border-bottom-style:solid;}
/* Contextual affordances: state-driven copyable commands / JSON nudges. */
.aff-row{padding:6px 8px;border-radius:5px;margin:4px 0;font-size:var(--fs-2);line-height:1.4;
     display:flex;flex-wrap:wrap;align-items:center;gap:8px;}
.aff-row.aff-info{background:#F1F5FF;border-left:3px solid #8FA8D8;}
.aff-row.aff-amber{background:#FBF0D6;border-left:3px solid #C9A227;color:#6E4E11;}
.aff-row.aff-nudge{background:#F6F7FA;border-left:3px solid var(--line);color:var(--muted);}
.aff-text{flex:1;min-width:200px;}
/* Diff banner (Home tab, top). Condense pass 2026-07-26: restyled from a
   content-weight band into a slim one-line utility strip that sits directly
   under the sticky chapter nav - together with the freshbar (freshness pill
   + tour launcher) it reads as ONE meta/utility layer above the chapters,
   not three separate content bands. Product-level detail stays one click
   away behind the existing <details> toggle. */
.diff-banner{background:#F6F8FC;border:1px solid var(--ice);border-left:3px solid #8FA8D8;
     border-radius:6px;padding:5px 12px;margin:0 0 20px;max-width:1020px;
     display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;}
.diff-banner.baseline{background:#F6F7FA;border-left-color:var(--line);}
.diff-headline{font-size:var(--fs-1);color:var(--muted);line-height:1.5;flex:1;min-width:220px;}
.diff-headline b{color:var(--navy);}
.diff-when{font-size:var(--fs-1);color:var(--muted);font-family:var(--f-mono);}
.diff-banner details{font-size:var(--fs-1);flex:0 0 auto;}
.diff-banner summary{cursor:pointer;color:#3A4890;font-weight:var(--w-emph);}
.diff-list{list-style:none;padding:8px 0 0;margin:0;max-height:280px;overflow-y:auto;}
.diff-list li{padding:2px 0;color:var(--muted);font-size:var(--fs-2);line-height:1.5;border-bottom:1px solid #E1E7F0;}
.diff-list code{font-family:var(--f-mono);font-size:var(--fs-1);background:#fff;
     padding:1px 5px;border-radius:3px;color:var(--navy);}
/* --- Unified disclosure grammar (condense pass 2026-07-26) -----------------
   Every collapsible on the page now speaks ONE visual language so a reader
   can always tell what is expandable and which sections are currently open:
     * same caret - a small \25B8 that rotates 90 deg when open
     * same header affordance - pointer cursor, ice hover, gold focus ring
     * same open signal - a 3px gold left-edge accent while expanded
   <details class="disc"> opts a native disclosure in. The Quick Look
   drill-down (.ql-details, which already had this caret grammar via its
   .ql-chevron span) and the button-based section collapses (landscape
   treemap, Bureau feed - via the .is-open class the persistence JS toggles)
   implement the same grammar with their own machinery. */
details.disc > summary{list-style:none;cursor:pointer;display:flex;align-items:center;
     gap:8px;padding:3px 8px 3px 6px;margin-left:-6px;border-radius:6px;
     font-weight:var(--w-emph);color:#3A4890;user-select:none;}
details.disc > summary::-webkit-details-marker{display:none;}
details.disc > summary::marker{content:"";}
details.disc > summary::before{content:"\25B8";display:inline-block;flex:0 0 auto;
     color:var(--muted);font-size:var(--fs-1);line-height:1;
     transition:transform .15s ease;}
details.disc[open] > summary::before{transform:rotate(90deg);color:var(--navy);}
details.disc > summary:hover{background:var(--ice);color:var(--navy);}
details.disc > summary:focus-visible{outline:2px solid var(--gold);outline-offset:2px;}
details.disc[open]{border-left:3px solid var(--gold);padding-left:8px;}
/* Button-based section collapses share the open-state signal. */
.lscape-section.is-open,.cpress-section.is-open{border-left:3px solid var(--gold);
     padding-left:12px;}
/* Quick Look drill-down joins the open-state grammar (its caret already
   rotates via .ql-chevron). */
.ql-details[open]{border-left:3px solid var(--gold);}
/* One-line preview inside a closed disclosure's summary - tells the reader
   what they'd get by opening it. Hidden while open (the content is there). */
details.disc > summary .disc-preview{font-weight:var(--w-body);color:var(--muted);
     font-size:var(--fs-1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
     min-width:0;flex:1;}
details.disc[open] > summary .disc-preview{display:none;}
/* Home chapter structure (condense-home pass 2026-07-26). Groups the
   ~9 Home sections into 3 labeled chapters ("Get oriented" / "The landscape"
   / "Team pulse") so a first-time reader sees structure instead of a wall of
   density. Each chapter carries a small muted small-caps label at the top and
   a subtle hairline below; spacing WITHIN a chapter is tightened (~30% less
   than the pre-condense per-section margins) and spacing BETWEEN chapters is
   loosened (~50% more) so the rhythm change makes chapter boundaries obvious
   without any new visual weight. */
.home-chapter{margin:0 0 40px;padding:0;max-width:1020px;
     border-bottom:1px solid var(--ice);padding-bottom:32px;}
.home-chapter:last-child{border-bottom:0;padding-bottom:0;margin-bottom:0;}
.home-chapter-label{font-family:var(--f-sans);font-size:var(--fs-2);
     font-weight:var(--w-head);color:var(--muted);letter-spacing:0.14em;
     text-transform:uppercase;margin:0 0 14px;line-height:1.4;
     display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;}
.home-chapter-label .hc-tag{color:var(--navy);}
.home-chapter-label .hc-sep{color:var(--line);font-weight:var(--w-body);
     letter-spacing:0.02em;}
.home-chapter-label .hc-caption{color:var(--muted);font-size:var(--fs-1);
     letter-spacing:0.06em;text-transform:none;font-weight:var(--w-body);}
/* Within-chapter section spacing (overrides each section's default
   bottom-margin so the chapter body reads as one tight block). */
.home-chapter > .home-search,
.home-chapter > .curriculum-section,
.home-chapter > .onboard-grid,
.home-chapter > .wti-section,
.home-chapter > .lscape-section,
.home-chapter > .cpress-section,
.home-chapter > .wwl-section{margin-bottom:16px;}
.home-chapter > *:last-child{margin-bottom:0;}
/* Get-oriented two-column onboarding grid (condense pass 2026-07-26;
   Phase-1 hero card retired 2026-07-26 - findings live in the Team Pulse
   stat cards now). Left column: "Find a product" search. Right column:
   the 5-product curriculum. One "get started" moment instead of stacked
   full-width bands; collapses to a single column under 960px. */
.onboard-grid{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,6fr);
     gap:18px;align-items:start;max-width:1020px;}
.onboard-col{min-width:0;display:flex;flex-direction:column;gap:16px;}
.onboard-col > *{margin-bottom:0 !important;}
@media(max-width:960px){.onboard-grid{grid-template-columns:1fr;}}
/* Sticky in-page chapter nav (condense-home pass 2026-07-26 commit #3).
   Slim secondary nav rendered at the top of the Home panel, above the diff
   banner. Three chapter chips ("Get oriented" / "The landscape" /
   "Team pulse") that smooth-scroll to the corresponding chapter on click
   and highlight the currently-visible chapter as the reader scrolls
   (IntersectionObserver-driven). Sticky-positioned within body scroll so
   it stays visible while the reader moves down the page. Because it lives
   inside #panel-home, the tab-switch machinery automatically hides it when
   the reader is on a Products tab - no extra visibility JS needed. */
.home-chapternav{position:sticky;top:0;z-index:40;
     background:rgba(255,255,255,0.94);backdrop-filter:blur(6px);
     -webkit-backdrop-filter:blur(6px);
     border-bottom:1px solid var(--ice);
     margin:0 0 12px;padding:8px 0 8px;
     display:flex;align-items:center;gap:8px;flex-wrap:wrap;
     max-width:1020px;}
.home-chapternav-lead{font-family:var(--f-sans);font-size:var(--fs-1);
     color:var(--muted);font-weight:var(--w-emph);letter-spacing:0.10em;
     text-transform:uppercase;margin-right:4px;}
.home-chapternav-chip{display:inline-flex;align-items:center;gap:6px;
     background:transparent;color:var(--muted);
     border:1px solid var(--line);border-radius:14px;
     padding:4px 12px;font-family:inherit;font-size:var(--fs-2);
     font-weight:var(--w-emph);cursor:pointer;text-decoration:none;
     letter-spacing:.01em;line-height:1.3;
     transition:background .12s ease,color .12s ease,border-color .12s ease;}
.home-chapternav-chip:hover{background:var(--ice);color:var(--navy);
     border-color:var(--line);}
.home-chapternav-chip:focus-visible{outline:2px solid var(--gold);outline-offset:2px;}
.home-chapternav-chip.on{background:var(--navy);color:#fff;border-color:var(--navy);}
.home-chapternav-chip.on:hover{background:var(--deep);color:#fff;}
.home-chapternav-chip .hcn-idx{font-family:var(--f-mono);color:inherit;
     opacity:.6;font-weight:var(--w-body);font-size:var(--fs-1);}
/* Scroll target offset - so smooth-scroll lands the chapter label just
   below the sticky nav bar instead of behind it. */
.home-chapter{scroll-margin-top:64px;}
.meta{font-size:var(--fs-1);color:var(--muted);margin-top:3px;}
.tk{border-left:3px solid var(--line);padding:4px 8px;margin:5px 0;}
.tk.odd{border-left-color:var(--gold);}
.tkh{font-size:var(--fs-2);} .tkh b{color:var(--navy);margin-right:6px;} .tkh em{float:right;font-style:normal;color:var(--muted);font-size:var(--fs-1);}
.tkd{font-size:var(--fs-1);color:var(--muted);line-height:1.35;margin-top:1px;}
.nowork{font-size:var(--fs-2);color:var(--muted);font-style:italic;}
.wl{border:1px solid var(--line);border-radius:8px;padding:10px 13px;margin:9px 0;max-width:1020px;}
.wlh{font-size:var(--fs-2);color:var(--navy);font-weight:var(--w-head);}
.wlh span{font-weight:400;color:var(--muted);font-size:var(--fs-1);margin-left:8px;}
.wli{font-size:var(--fs-2);line-height:1.45;margin:5px 0 0;padding-left:10px;border-left:2px solid var(--ice);}
.wli b{display:inline-block;background:var(--ice);color:var(--navy);border-radius:9px;padding:1px 8px;
       font-size:var(--fs-1);margin-right:6px;font-family:var(--f-mono);}
/* "Where the team is" section (reframe pass commit #1). Answers a cold
   teammate's first two questions on opening the report: how far has the team
   reached into the ~573-product catalog, and which products are we actually
   working with today? Replaces the funnel + curated-findings-first framing. */
.wti-section{margin:0 0 24px;max-width:1020px;}
/* Pipeline legend (condense pass 2026-07-26). The old segmented tier bar
   was retired - it duplicated the Sankey flow, which now leads the merged
   "Where the team is" section as its single visual. The swatch + count
   labels survive here as the Sankey's legend, and the plain-English stage
   caption stays below them. */
.pipeline-rail{margin:2px 0 6px;}
.pipeline-labels{display:flex;margin-top:10px;font-size:var(--fs-2);
       color:var(--muted);flex-wrap:wrap;gap:22px;line-height:var(--lh-2);}
.pipeline-label{display:inline-flex;align-items:baseline;gap:8px;}
.pipeline-swatch{display:inline-block;width:11px;height:11px;border-radius:3px;
       transform:translateY(1px);}
.pipeline-swatch[data-stage="cataloged"]{background:#DDE3EE;}
.pipeline-swatch[data-stage="probed"]   {background:#B7CDF6;}
.pipeline-swatch[data-stage="sampled"]  {background:#8BD3CC;}
.pipeline-swatch[data-stage="reviewed"] {background:#8FCD97;}
.pipeline-label-n{font-family:var(--f-mono);font-variant-numeric:tabular-nums;
       font-weight:var(--w-head);color:var(--navy);font-size:var(--fs-2);}
.pipeline-label-name{color:var(--ink);}
.pipeline-caption{font-size:var(--fs-2);color:var(--muted);
       line-height:var(--lh-3);margin-top:12px;max-width:860px;}
/* Sankey embedded in the wti section: tighten the gap to its legend. */
.wti-section .sankey-wrap{margin:10px 0 0;}
/* Deprecated wti-cov-* rules kept for one release cycle in case a plugin
   or a stale HTML snippet still references them; unused after 2026-07-26. */
.wti-cov-list{display:flex;flex-direction:column;gap:8px;margin:8px 0 6px;}
.wti-cov-row{display:flex;align-items:center;gap:12px;font-size:var(--fs-2);}
.wti-cov-label{flex:0 0 200px;color:var(--navy);font-weight:var(--w-emph);font-size:var(--fs-2);}
.wti-cov-bar{flex:1;height:14px;background:#F6F7FA;border-radius:7px;overflow:hidden;
       position:relative;border:1px solid var(--ice);min-width:60px;}
.wti-cov-bar-fill{height:100%;border-radius:6px;transition:width .18s ease-out;}
.wti-cov-bar-fill.green{background:#7ABF89;}
.wti-cov-bar-fill.amber{background:#E9CD7A;}
.wti-cov-bar-fill.red{background:#D0876E;}
.wti-cov-cnt{flex:0 0 128px;font-family:var(--f-mono);
       font-size:var(--fs-1);color:var(--muted);text-align:right;}
.wti-recent{margin-top:16px;}
.wti-recent h3{font-family:var(--f-display);font-size:var(--fs-3);color:var(--navy);margin:0 0 6px;}
.wti-recent-list{list-style:none;padding:0;margin:0;border-top:1px solid var(--ice);}
.wti-recent-list li{padding:6px 8px;border-bottom:1px solid var(--ice);
       display:flex;gap:10px;align-items:baseline;font-size:var(--fs-2);flex-wrap:wrap;}
.wti-recent-list li a.wti-path{font-family:var(--f-mono);
       font-weight:var(--w-head);color:var(--navy);text-decoration:none;flex:0 0 auto;
       border-bottom:1px dotted #8FA8D8;cursor:pointer;}
.wti-recent-list li a.wti-path:hover{color:#3A4890;border-bottom-style:solid;}
.wti-recent-list li .wti-what{color:var(--ink);flex:1;min-width:180px;line-height:1.4;}
.wti-recent-list li .wti-when{font-family:var(--f-mono);
       font-size:var(--fs-1);color:var(--muted);flex:0 0 auto;}
.wti-tier-chip{display:inline-block;padding:1px 7px;border-radius:8px;font-size:var(--fs-1);
       font-weight:var(--w-head);letter-spacing:.03em;margin-right:2px;text-transform:uppercase;}
.wti-tier-chip.t2{background:#D6EDD9;color:#1F5A2E;}
.wti-tier-chip.t1{background:#DCE7FA;color:#1F2A5C;}
.wti-tier-chip.t0{background:#EDF0F7;color:#5A6072;}
.wti-empty{font-size:var(--fs-2);color:var(--muted);font-style:italic;padding:8px 0;}
.wti-empty code{font-family:var(--f-mono);background:var(--ice);
       color:var(--navy);padding:1px 5px;border-radius:3px;font-style:normal;}
/* "What we've learned" section - stat-first redesign (2026-07-26, after
   Garrett's live test called the old all-sources feed "a massive wall of
   text"). Hero stat cards (curated findings flagged `hero`) lead; team
   notes and compact curated one-liners follow; WORKLOG prose is demoted
   to one outbound link. */
.wwl-section{margin:0 0 24px;max-width:1020px;}
.wwl-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;
       margin:14px 0 6px;}
@media (max-width:900px){.wwl-stats{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media (max-width:480px){.wwl-stats{grid-template-columns:minmax(0,1fr);}}
.wwl-stat{background:#FBFCFE;border:1px solid var(--line);
       border-top:3px solid var(--gold);border-radius:8px;
       padding:14px 16px 12px;display:flex;flex-direction:column;gap:6px;}
.wwl-stat-num{font-family:var(--f-display);font-size:var(--fs-9);
       line-height:var(--lh-9);color:var(--navy);
       font-variant-numeric:tabular-nums;letter-spacing:-.01em;}
.wwl-stat-num.long{font-size:var(--fs-8);line-height:var(--lh-8);padding:10px 0;}
.wwl-stat-take{font-size:var(--fs-2);line-height:var(--lh-2);color:var(--ink);
       font-weight:var(--w-emph);flex:1;}
.wwl-stat-meta{font-size:var(--fs-1);color:var(--muted);}
.wwl-stat-meta a.wti-path{font-family:var(--f-mono);font-weight:var(--w-head);
       color:var(--navy);text-decoration:none;
       border-bottom:1px dotted #8FA8D8;cursor:pointer;}
.wwl-stat-meta a.wti-path:hover{color:#3A4890;border-bottom-style:solid;}
.wwl-stat-nb{font-family:var(--f-mono);}
.wwl-subhead{font-family:var(--f-display);font-size:var(--fs-4);
       color:var(--navy);margin:18px 0 4px;}
.wwl-list{list-style:none;padding:0;margin:8px 0 0;border-top:1px solid var(--ice);}
.wwl-list li{padding:7px 8px;border-bottom:1px solid var(--ice);
       display:flex;gap:10px;align-items:baseline;font-size:var(--fs-2);line-height:1.45;
       flex-wrap:wrap;}
.wwl-list li:last-child{border-bottom:0;}
.wwl-ico{flex:0 0 20px;font-size:var(--fs-3);line-height:1;padding-top:1px;text-align:center;}
.wwl-body{flex:1;min-width:220px;}
.wwl-head{color:var(--ink);font-weight:var(--w-emph);}
.wwl-head b{color:var(--navy);margin-right:6px;}
.wwl-meta{color:var(--muted);font-size:var(--fs-1);margin-top:2px;
       display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;}
.wwl-meta a{color:#3A4890;text-decoration:none;border-bottom:1px dotted #8FA8D8;}
.wwl-meta code{font-family:var(--f-mono);font-size:var(--fs-1);
       background:var(--ice);color:var(--navy);padding:0 4px;border-radius:3px;}
.wwl-detail{color:var(--muted);font-size:var(--fs-1);line-height:1.4;margin-top:2px;}
.wwl-empty-team{font-size:var(--fs-2);color:var(--muted);font-style:italic;padding:6px 0;}
.wwl-empty-team code{font-family:var(--f-mono);background:var(--ice);
       color:var(--navy);padding:1px 5px;border-radius:3px;font-style:normal;
       font-size:var(--fs-1);}
.wwl-more{margin-top:10px;font-size:var(--fs-2);}
.wwl-more > summary{cursor:pointer;color:#3A4890;font-weight:var(--w-emph);padding:3px 0;
       list-style:none;}
.wwl-more > summary::-webkit-details-marker{display:none;}
.wwl-more > summary::marker{content:"";}
.wwl-more > summary:before{content:"\25B8  ";}
.wwl-more[open] > summary:before{content:"\25BE  ";}
/* Phase A ceiling-push #3: footer inside the Show-all drawer telling the
   reader how many mined items were dropped by the 30-cap, with a link
   into the raw WORKLOG for the full record. Sits below the last <li>. */
.wwl-tail{padding:9px 10px;font-size:var(--fs-1);color:var(--muted);line-height:1.5;
     background:#F6F7FA;border-top:1px solid var(--ice);border-radius:0 0 5px 5px;
     margin-top:0;}
.wwl-tail b{color:var(--navy);font-weight:var(--w-head);}
.wwl-tail a{color:#3A4890;text-decoration:none;border-bottom:1px dotted #8FA8D8;}
/* "Up next" action queue (mission-statement pass 2026-07-26). Team Pulse
   chapter lead: a state-derived punch list of the 3-5 highest-priority
   next actions, each with a rank chip, an action-type icon, a one-line
   why, and a copyable one-command action (reusing the .copy-cmd control).
   Gold-tinted card (same family as the Start-here banner) so it reads as
   "do something" rather than "read something". Overflow suggestions sit
   behind the unified details.disc grammar. */
.upnext-section{margin:0 0 20px;max-width:1020px;
    border:1px solid var(--gold);border-radius:8px;
    background:linear-gradient(180deg,#FBF8EC 0%,#FDFEFF 100%);
    padding:14px 18px;}
.upnext-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
    margin-bottom:2px;}
.upnext-head h2{font-family:var(--f-display);font-size:var(--fs-5);
    color:var(--navy);margin:0;font-weight:var(--w-head);
    letter-spacing:var(--lsp-tight);}
.upnext-tag{display:inline-block;padding:1px 8px;border-radius:8px;
    font-size:var(--fs-1);font-weight:var(--w-head);letter-spacing:.03em;
    text-transform:uppercase;background:#F5E9C8;color:#6E4E11;}
.upnext-caption{font-size:var(--fs-1);color:var(--muted);margin:0 0 8px;
    line-height:1.4;}
.upnext-list{list-style:none;padding:0;margin:0;border-top:1px solid #EADFB8;}
.upnext-list li{display:flex;gap:10px;align-items:center;padding:7px 0;
    border-bottom:1px solid #F0EAD2;font-size:var(--fs-2);line-height:1.4;
    flex-wrap:wrap;}
.upnext-list li:last-child{border-bottom:0;}
.una-rank{flex:0 0 22px;height:22px;border-radius:50%;background:var(--navy);
    color:#F5D77A;font-size:var(--fs-1);font-weight:var(--w-head);
    display:flex;align-items:center;justify-content:center;
    font-family:var(--f-mono);}
.una-ico{flex:0 0 20px;text-align:center;font-size:var(--fs-3);line-height:1;}
.una-body{flex:1;min-width:240px;}
.una-name{color:var(--navy);font-weight:var(--w-emph);text-decoration:none;
    border-bottom:1px dotted #8FA8D8;}
.una-name:hover{border-bottom-style:solid;}
.una-act{color:var(--ink);font-weight:var(--w-emph);}
.una-why{color:var(--muted);font-size:var(--fs-1);margin-top:1px;line-height:1.4;}
.upnext-list .copy-cmd{margin-left:auto;}
.upnext-list .copy-cmd code{max-width:340px;}
.upnext-more{margin-top:8px;font-size:var(--fs-2);}
.upnext-done{display:flex;gap:10px;align-items:center;padding:8px 0;
    color:#1F5A2E;font-size:var(--fs-2);line-height:1.45;}
.upnext-done .una-ico{flex:0 0 20px;}
.upnext-done b{color:#1F5A2E;font-weight:var(--w-head);}
/* Bureau press-release mini-feed (Phase A 2026-07-26 commit #2). Compact
   5-item list showing the newest census.gov press releases so a reader has
   external "what did the Bureau publish this week?" recency signal alongside
   the internal team feed. Sits directly above the What-we've-learned feed
   on Home so both activity feeds visually cluster. */
.cpress-section{margin:0 0 20px;max-width:1020px;
    border:1px solid var(--line);border-radius:8px;
    background:linear-gradient(180deg,#F7FAFC 0%,#FDFEFF 100%);
    padding:14px 18px;}
.cpress-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
    margin-bottom:6px;}
/* Section-scale header (condense pass 2026-07-26): one heading style per
   level across Home - chapters use the small-caps kicker, sections use the
   fs-5 display face, cards/subsections use fs-3. The press feed's expanded
   panel is a section, so its header matches the other section h2s. */
.cpress-head h2{font-family:var(--f-display);font-size:var(--fs-5);
    color:var(--navy);margin:0;font-weight:var(--w-head);
    letter-spacing:var(--lsp-tight);}
.cpress-source{font-family:var(--f-mono);font-size:var(--fs-1);
    color:#3A4890;text-decoration:none;
    border-bottom:1px dotted #8FA8D8;}
.cpress-source:hover{color:var(--navy);}
.cpress-tag{display:inline-block;padding:1px 8px;border-radius:8px;
    font-size:var(--fs-1);font-weight:var(--w-head);
    letter-spacing:.03em;text-transform:uppercase;}
.cpress-tag.fresh{background:#D6EDD9;color:#1F5A2E;}
.cpress-tag.stale{background:#FCEBCE;color:#8A5A16;}
.cpress-tag.miss{background:#F5D9D5;color:#8A2A1D;}
.cpress-caption{font-size:var(--fs-1);color:var(--muted);margin:0 0 8px;
    line-height:1.4;}
.cpress-list{list-style:none;padding:0;margin:0;
    border-top:1px solid var(--ice);}
.cpress-list li{padding:7px 0;border-bottom:1px solid var(--ice);
    display:flex;gap:12px;align-items:baseline;font-size:var(--fs-2);
    line-height:1.4;flex-wrap:wrap;}
.cpress-list li:last-child{border-bottom:0;}
.cpress-date{font-family:var(--f-mono);font-size:var(--fs-1);color:var(--muted);
    flex:0 0 82px;letter-spacing:.02em;}
.cpress-title{color:var(--ink);flex:1;min-width:200px;text-decoration:none;
    border-bottom:1px dotted transparent;}
.cpress-title:hover{color:var(--navy);border-bottom-color:#8FA8D8;}
.cpress-empty{font-size:var(--fs-2);color:var(--muted);font-style:italic;
    padding:8px 0;}
.cpress-empty a{color:#3A4890;text-decoration:none;
    border-bottom:1px dotted #8FA8D8;}
/* Start-here curriculum (UX pass 2026-07-26 commit #4).
   Five-item ordered list that walks a first-time reader through the four
   uncertainty mechanisms via the products that illustrate them best. Sits
   in the right column of the Get-oriented grid. Type steps 7 & 8 anchor the
   numbers so the eye lands on 1..5 first; each item is scannable in <5s. */
.curriculum-section{margin:0 0 30px;max-width:1020px;}
.curriculum-intro{font-size:var(--fs-3);color:var(--ink);line-height:var(--lh-3);
       margin:8px 0 18px;max-width:820px;font-weight:var(--w-body);}
.curriculum-intro b{color:var(--navy);font-weight:var(--w-emph);}
.curriculum-list{display:flex;flex-direction:column;gap:12px;}
.curriculum-item{display:grid;grid-template-columns:72px 1fr auto;gap:16px;
       align-items:flex-start;padding:16px 20px;border:1px solid var(--line);
       border-radius:10px;background:#FBFCFE;transition:border-color .12s ease,
       box-shadow .12s ease;}
.curriculum-item:hover{border-color:var(--navy);
       box-shadow:0 2px 6px rgba(31,42,92,0.08);}
.curriculum-num{font-family:var(--f-display);font-size:var(--fs-8);
       line-height:1;color:var(--gold);font-weight:var(--w-head);
       letter-spacing:var(--lsp-tighter);text-align:center;
       font-variant-numeric:tabular-nums;padding-top:2px;}
.curriculum-body{min-width:0;}
.curriculum-title-row{display:flex;align-items:baseline;gap:10px;
       flex-wrap:wrap;margin-bottom:4px;}
.curriculum-title{font-family:var(--f-display);font-size:var(--fs-5);
       color:var(--navy);font-weight:var(--w-head);
       letter-spacing:var(--lsp-tight);line-height:var(--lh-4);}
.curriculum-path{font-family:var(--f-mono);font-size:var(--fs-1);
       color:var(--muted);background:var(--ice);padding:1px 8px;
       border-radius:5px;font-weight:var(--w-emph);letter-spacing:0;}
.curriculum-concept{font-family:var(--f-sans);font-size:var(--fs-2);
       color:var(--gold);font-weight:var(--w-head);text-transform:uppercase;
       letter-spacing:.10em;margin-bottom:6px;}
.curriculum-why{font-size:var(--fs-2);color:var(--ink);line-height:var(--lh-3);
       max-width:640px;}
.curriculum-cta{align-self:center;background:var(--navy);color:#fff;
       text-decoration:none;font-weight:var(--w-emph);font-size:var(--fs-2);
       padding:9px 16px;border-radius:6px;white-space:nowrap;
       transition:background .12s ease-out;letter-spacing:.01em;
       border:0;font-family:inherit;cursor:pointer;line-height:1.2;}
.curriculum-cta:hover{background:#0F1740;}
.curriculum-cta:focus-visible{outline:2px solid var(--gold);outline-offset:2px;}
.curriculum-cta .arrow{margin-left:5px;}
@media(max-width:700px){
  .curriculum-item{grid-template-columns:56px 1fr;grid-template-rows:auto auto;}
  .curriculum-num{font-size:var(--fs-7);}
  .curriculum-cta{grid-column:2;justify-self:flex-start;margin-top:4px;}
}
/* Sankey research pipeline hero (UX pass 2026-07-26 commit #3).
   Sits ABOVE the landscape treemap on Home. Answers a different question
   from the treemap: 'where in the pipeline are we?' vs. 'what's the shape of
   what exists?'. Pure inline SVG - no libraries, ~150 LOC of Python emits
   Bezier ribbons + stacked-bar nodes. Compact by design (~180px tall).
   Click on a stage node jumps to the Products tab. */
.sankey-section{margin:0 0 22px;max-width:1020px;}
.sankey-caption-top{font-size:var(--fs-2);color:var(--muted);
       line-height:var(--lh-3);margin:6px 0 8px;max-width:920px;}
.sankey-caption-top b{color:var(--navy);font-weight:var(--w-emph);}
.sankey-wrap{border:1px solid var(--line);border-radius:10px;
       background:#FBFCFE;padding:14px 18px 10px;
       box-shadow:0 1px 2px rgba(31,42,92,0.05);}
.sankey-svg{display:block;width:100%;height:auto;}
.sankey-node{cursor:pointer;transition:filter .12s ease;}
.sankey-node:hover .sankey-node-rect{filter:brightness(0.92);}
.sankey-node:focus{outline:none;}
.sankey-node:focus-visible .sankey-node-rect{stroke:var(--navy);stroke-width:2;}
.sankey-node-rect{stroke:rgba(31,42,92,0.35);stroke-width:1;
       transition:filter .12s ease;}
.sankey-node-label{font-family:var(--f-sans);font-size:var(--fs-1);
       font-weight:var(--w-head);fill:var(--navy);
       text-anchor:middle;pointer-events:none;letter-spacing:-0.01em;}
.sankey-node-count{font-family:var(--f-mono);
       font-size:var(--fs-3);font-weight:var(--w-head);fill:var(--navy);
       font-variant-numeric:tabular-nums;text-anchor:middle;pointer-events:none;}
.sankey-node-sub{font-family:var(--f-sans);font-size:var(--fs-1);
       fill:var(--muted);text-anchor:middle;pointer-events:none;}
.sankey-ribbon{opacity:.55;transition:opacity .14s ease;pointer-events:none;}
.sankey-node:hover ~ .sankey-ribbon-group .sankey-ribbon{opacity:.35;}
.sankey-caption-bottom{font-size:var(--fs-1);color:var(--muted);
       margin:10px 2px 0;text-align:center;font-style:italic;}
/* "Census data landscape" viz (Phase A ceiling-push #1). SVG squarified
   treemap: Kind (outer 4-way partition) -> Program (inner partition), area
   proportional to product count, color shaded by max team-reach tier.
   Self-contained pure SVG - no D3, no external CSS, no JS-only rendering.
   Hover tooltips via native <title> and click-to-drill via delegated JS
   are pure enhancement; the geometry + labels convey the whole message
   with JS off. See build_landscape_viz() for the rendering pipeline. */
.lscape-section{margin:0 0 24px;max-width:1020px;}
.lscape-caption{font-size:var(--fs-2);color:var(--muted);margin:6px 0 10px;
       max-width:900px;line-height:1.45;}
/* Redesign 2026-07-26: stacked full-width rows, one per dataset kind. Each
   row is its own SVG (kind header + squarified program treemap) with a
   subtle per-kind tint background, plus an optional <details> spill for
   programs squeezed below the min-legibility floor. */
.lscape-viz{display:flex;flex-direction:column;gap:10px;margin:6px 0 12px;}
/* Slim header-only rows for the smaller kinds (condense pass 2026-07-26).
   Native <details> in the unified disc grammar; the summary mirrors the
   kind header (name + count + top-3) so the collapsed row still reads. */
.lscape-kind-details{border:1px solid var(--line);border-radius:10px;
       background:#FBFCFE;overflow:hidden;}
.lscape-kind-details > summary{padding:10px 14px;margin-left:0;border-radius:0;}
details.lscape-kind-details[open]{padding-left:0;}
.lscape-kind-details > .lscape-kind-row{margin:0 8px 8px;border-radius:8px;}
.lscape-kind-sum-name{font-family:var(--f-display);color:var(--navy);
       font-weight:var(--w-head);font-size:var(--fs-3);
       letter-spacing:var(--lsp-tight);}
.lscape-kind-sum-count{font-family:var(--f-mono);color:var(--navy);
       font-weight:var(--w-head);font-variant-numeric:tabular-nums;
       font-size:var(--fs-3);}
.lscape-kind-row{border:1px solid var(--line);border-radius:10px;
       overflow:hidden;background:#FFF;
       box-shadow:0 1px 2px rgba(31,42,92,0.05);}
.lscape-kind-svg{display:block;width:100%;height:auto;}
.lscape-kind-svg .lscape-prog{cursor:pointer;transition:filter .12s ease,
       stroke-width .12s ease;}
.lscape-kind-svg .lscape-prog:hover rect{filter:brightness(0.94);
       stroke-width:2;}
.lscape-kind-svg .lscape-prog:focus{outline:none;}
.lscape-kind-svg .lscape-prog:focus-visible rect{stroke:var(--gold);stroke-width:2.5;}
.lscape-kind-svg .lscape-prog:focus rect{stroke:var(--gold);stroke-width:2.5;}
/* Alternate-row hint: pair rows share a very subtle brightness shift on the
   shell shadow so the eye can zebra them. Tint is already row-specific. */
.lscape-kind-row:nth-child(even){box-shadow:0 1px 2px rgba(31,42,92,0.08);}
/* Spill disclosure - shown when squarify + min-box floor pushes small
   programs out of the treemap. Native <details> so it works with JS off. */
.lscape-spill{border-top:1px solid var(--ice);padding:8px 14px 10px;
       background:rgba(255,255,255,0.55);}
/* Caret + marker + hover handling now comes from the unified `details.disc`
   grammar (condense pass 2026-07-26); local rules keep only sizing/wrap. */
.lscape-spill > summary{font-size:var(--fs-2);color:var(--muted);flex-wrap:wrap;}
.lscape-spill .lscape-spill-count{font-weight:var(--w-head);color:var(--navy);
       font-size:var(--fs-2);}
.lscape-spill .lscape-spill-preview{color:var(--ink);opacity:.75;
       font-size:var(--fs-2);}
.lscape-spill .lscape-spill-total{font-family:var(--f-mono);
       font-size:var(--fs-1);color:var(--muted);}
.lscape-spill-chips{margin-top:8px;}
/* Fallback flex row rendered per-kind when squarify fully fails (all-zero
   sizes, degenerate rect) - kept as a hard-failsafe path. */
.lscape-fallback{margin:8px 0;padding:8px 10px;border:1px dashed var(--line);
       border-radius:6px;background:#FFF8E8;}
.lscape-fallback-head{font-family:var(--f-display);font-weight:var(--w-head);
       color:var(--navy);font-size:var(--fs-2);margin-bottom:5px;}
.lscape-fallback-row{display:flex;flex-wrap:wrap;gap:5px;}
.lscape-fallback-chip{padding:4px 9px;font-size:var(--fs-1);border-radius:5px;
       border:1px solid transparent;cursor:pointer;color:var(--ink);
       transition:filter .12s ease;}
.lscape-fallback-chip:hover{filter:brightness(0.94);}
.lscape-fallback-chip:focus-visible{outline:2px solid var(--gold);outline-offset:1px;}
.lscape-fallback-chip em{font-style:normal;font-family:var(--f-mono);
       font-size:var(--fs-1);color:var(--muted);margin-left:5px;}
/* Tier fill/stroke - bumped in vividness during 2026-07-26 redesign so the
   3 touched programs actually pop off the mostly-grey wall. Grey stayed
   muted so untouched programs read as background. */
.lscape-tier-0{background:#ECEEF5;border-color:#CBD1E0;}
.lscape-tier-1{background:#B7CDF6;border-color:#5A7ED1;}
.lscape-tier-2{background:#8BD3CC;border-color:#3D9E93;}
.lscape-tier-3{background:#8FCD97;border-color:#3E9152;}
.lscape-legend{display:flex;gap:14px;align-items:center;font-size:var(--fs-2);
       color:var(--muted);margin:8px 0 0;flex-wrap:wrap;padding:6px 12px;
       background:var(--ice);border-radius:6px;}
.lscape-legend b{color:var(--navy);font-weight:var(--w-head);}
.lscape-legend .lscape-legend-item{display:inline-flex;align-items:center;gap:2px;}
.lscape-legend .lscape-legend-cnt{font-family:var(--f-mono);
       font-size:var(--fs-1);color:var(--muted);margin-left:2px;}
.lscape-legend .lscape-swatch{display:inline-block;width:13px;height:13px;
       border-radius:3px;margin-right:6px;vertical-align:-2px;
       border:1px solid transparent;}
.lscape-legend .lscape-legend-summary{margin-left:auto;color:var(--muted);
       font-size:var(--fs-1);font-family:var(--f-mono);}
/* Condense-home pass 2026-07-26 commit #2. Compact landscape view + expand
   toggle. Default state shows kind row headers + top-3 programs per kind as
   inline text (~200 px total vs. the full SVG's ~1,143 px). The full SVG
   treemap lives inside the sibling `.lscape-expanded` div which stays
   `hidden` until the user (or persisted localStorage state) opens it.
   `data-landscape-toggle` buttons flip between the two views. */
/* Scope statement under the landscape h2 (2026-07-26). Always visible in
   both compact and expanded states - it frames what the count means. */
.lscape-scope-note{font-size:var(--fs-1);color:var(--muted);margin:2px 0 10px;
       max-width:900px;line-height:1.55;}
.lscape-compact{margin:6px 0 0;}
.lscape-compact-caption{font-size:var(--fs-2);color:var(--muted);
       line-height:1.45;margin:0 0 10px;max-width:900px;}
.lscape-compact-caption b{color:var(--navy);font-weight:var(--w-emph);}
.lscape-compact-rows{display:flex;flex-direction:column;gap:6px;margin:0 0 12px;}
.lscape-compact-row{display:grid;grid-template-columns:120px 62px 1fr;
       align-items:baseline;gap:12px;padding:9px 12px 9px 14px;
       background:#FBFCFE;border:1px solid var(--ice);
       border-left:4px solid var(--line);border-radius:6px;font-size:var(--fs-2);
       line-height:var(--lh-2);}
.lscape-compact-name{font-family:var(--f-display);color:var(--navy);
       font-weight:var(--w-head);letter-spacing:var(--lsp-tight);
       font-size:var(--fs-3);}
.lscape-compact-count{font-family:var(--f-mono);color:var(--navy);
       font-weight:var(--w-head);font-size:var(--fs-3);
       font-variant-numeric:tabular-nums;text-align:right;}
.lscape-compact-top{color:var(--ink);font-size:var(--fs-2);
       line-height:1.4;min-width:0;overflow:hidden;text-overflow:ellipsis;
       white-space:nowrap;}
.lscape-compact-topprefix{color:var(--muted);font-weight:var(--w-head);
       font-size:var(--fs-1);letter-spacing:.04em;text-transform:uppercase;
       margin-right:4px;}
.lscape-compact-num{font-family:var(--f-mono);color:var(--muted);
       font-size:var(--fs-1);font-variant-numeric:tabular-nums;}
@media(max-width:640px){
  .lscape-compact-row{grid-template-columns:1fr auto;grid-template-rows:auto auto;}
  .lscape-compact-top{grid-column:1/-1;white-space:normal;}
}
.lscape-expand-btn,.lscape-collapse-btn{display:inline-flex;align-items:center;
       gap:6px;background:var(--ice);color:var(--navy);border:1px solid var(--line);
       border-radius:6px;padding:8px 14px;font-family:inherit;font-size:var(--fs-2);
       font-weight:var(--w-emph);cursor:pointer;transition:background .12s ease;
       letter-spacing:.01em;}
.lscape-expand-btn:hover,.lscape-collapse-btn:hover{background:#DDE7F7;}
.lscape-expand-btn:focus-visible,.lscape-collapse-btn:focus-visible{outline:2px solid var(--gold);
       outline-offset:2px;}
.lscape-expand-caret{color:var(--navy);font-size:var(--fs-3);line-height:1;
       transform:translateY(1px);}
.lscape-collapse-btn{margin-top:10px;background:transparent;border-color:var(--line);
       color:var(--muted);font-weight:var(--w-body);font-size:var(--fs-1);}
.lscape-collapse-btn:hover{background:var(--ice);color:var(--navy);}
/* Bureau press-release compact preview (2026-07-26 commit #2). Single-line
   preview showing today's top headline + a "N more" button that opens the
   full 5-item list. Both compact and full states are pre-rendered; the
   `hidden` attribute swaps them via the persistence JS. */
.cpress-preview{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;
       padding:2px 0;font-size:var(--fs-2);line-height:1.5;color:var(--ink);}
.cpress-preview-label{color:var(--navy);font-weight:var(--w-head);
       font-family:var(--f-display);letter-spacing:var(--lsp-tight);
       font-size:var(--fs-3);}
.cpress-preview-title{color:var(--ink);text-decoration:none;flex:1;
       min-width:200px;border-bottom:1px dotted transparent;}
.cpress-preview-title:hover{color:var(--navy);border-bottom-color:#8FA8D8;}
.cpress-expand-btn{display:inline-flex;align-items:center;gap:4px;
       background:transparent;color:#3A4890;border:0;padding:2px 6px;
       font-family:inherit;font-size:var(--fs-2);font-weight:var(--w-emph);
       cursor:pointer;border-bottom:1px dotted #8FA8D8;letter-spacing:.01em;}
.cpress-expand-btn:hover{color:var(--navy);border-bottom-style:solid;}
.cpress-expand-btn:focus-visible{outline:2px solid var(--gold);outline-offset:2px;}
.cpress-collapse-btn{display:inline-flex;align-items:center;gap:6px;
       margin-top:8px;background:transparent;color:var(--muted);
       border:1px solid var(--line);border-radius:6px;padding:4px 10px;
       font-family:inherit;font-size:var(--fs-1);cursor:pointer;
       font-weight:var(--w-body);}
.cpress-collapse-btn:hover{background:var(--ice);color:var(--navy);}
.cpress-collapse-btn:focus-visible{outline:2px solid var(--gold);outline-offset:2px;}
/* .rev-mode-details / .rev-mode-body removed Phase A #3 (2026-07-26) - the
   Home tab no longer carries a collapsed 'Reviewer mode data' block; the
   funnel + inventory + work-depth table + notebook-health it contained were
   ~13 KB of dead scaffolding after the reframe. */
.nohit{display:none;font-size:var(--fs-2);color:var(--muted);font-style:italic;padding:10px 0;}
footer{padding:22px 44px;color:var(--muted);font-size:var(--fs-2);}
/* Freshness pill bar (shown on every page - reads data-generated-at at page load). */
.freshbar{background:#0F1738;color:#CADCFC;padding:9px 44px;font-size:var(--fs-2);
     display:flex;align-items:center;gap:14px;flex-wrap:wrap;border-bottom:1px solid #263466;}
.freshbar .pill{display:inline-block;padding:3px 12px;border-radius:11px;font-weight:var(--w-head);font-size:var(--fs-2);
     letter-spacing:.02em;background:#2A356C;color:#CADCFC;}
.freshbar .pill.fresh{background:#1F7A3A;color:#E6F5EA;}
.freshbar .pill.stale{background:#E9CD7A;color:#3A2F0A;}
.freshbar .pill.old{background:#C0392B;color:#FFF;}
.freshbar .sha{font-family:var(--f-mono);font-size:var(--fs-1);opacity:.7;}
.freshbar .kbd-hint{margin-left:auto;font-size:var(--fs-1);opacity:.75;letter-spacing:.01em;}
/* UX pass 2026-07-26 commit #6 - guided tour launcher + overlay.
   The launcher sits inside the freshbar; the overlay is a fixed-position
   div outside the normal flow, revealed only when the tour is running. */
.tour-launch{background:var(--gold);color:#16204A;border:0;border-radius:6px;
     padding:5px 12px;font:inherit;font-size:var(--fs-1);font-weight:var(--w-head);
     cursor:pointer;letter-spacing:.02em;transition:background .12s ease;
     margin-left:8px;line-height:1.3;}
.tour-launch:hover{background:#B7912A;color:#fff;}
.tour-launch:focus-visible{outline:2px solid #fff;outline-offset:2px;}
.tour-launch.hidden{display:none;}
.tour-relaunch{background:transparent;color:#F5D77A;border:1px solid #3A4890;
     border-radius:50%;width:22px;height:22px;padding:0;font:inherit;
     font-size:var(--fs-1);font-weight:var(--w-head);cursor:pointer;
     margin-left:8px;line-height:1;display:none;align-items:center;justify-content:center;}
.tour-relaunch:hover{background:#28356B;color:#fff;}
.tour-relaunch:focus-visible{outline:2px solid var(--gold);outline-offset:2px;}
.tour-relaunch.visible{display:inline-flex;}
.tour-overlay{position:fixed;inset:0;z-index:5000;pointer-events:none;}
.tour-overlay[hidden]{display:none;}
.tour-overlay .tour-dim{position:absolute;background:rgba(15,23,56,.55);
     pointer-events:auto;transition:all .18s ease-out;}
.tour-halo{position:absolute;border:2px solid var(--gold);border-radius:10px;
     box-shadow:0 0 0 4px rgba(201,162,39,.25),0 8px 30px rgba(0,0,0,.35);
     pointer-events:none;transition:all .22s cubic-bezier(.4,.0,.2,1);
     background:transparent;}
.tour-callout{position:absolute;width:280px;max-width:calc(100vw - 40px);
     background:#fff;border-radius:10px;padding:14px 16px 12px;
     box-shadow:0 12px 32px rgba(0,0,0,.35),0 2px 6px rgba(0,0,0,.15);
     pointer-events:auto;transition:top .22s cubic-bezier(.4,.0,.2,1),
                                    left .22s cubic-bezier(.4,.0,.2,1);
     border:1px solid var(--line);}
.tour-callout-head{display:flex;align-items:center;justify-content:space-between;
     margin-bottom:8px;}
.tour-step-idx{font-family:var(--f-mono);font-size:var(--fs-1);
     color:var(--gold);font-weight:var(--w-head);letter-spacing:.08em;
     text-transform:uppercase;}
.tour-skip{background:transparent;border:0;color:var(--muted);
     font-size:var(--fs-1);cursor:pointer;padding:2px 6px;border-radius:4px;
     font-family:inherit;font-weight:var(--w-emph);letter-spacing:.02em;}
.tour-skip:hover{background:var(--ice);color:var(--navy);}
.tour-callout-title{font-family:var(--f-display);color:var(--navy);
     font-size:var(--fs-4);font-weight:var(--w-head);letter-spacing:var(--lsp-tight);
     line-height:var(--lh-4);margin-bottom:6px;}
.tour-callout-body{font-size:var(--fs-2);color:var(--ink);
     line-height:var(--lh-3);margin-bottom:12px;}
.tour-callout-foot{display:flex;justify-content:space-between;gap:8px;}
.tour-prev,.tour-next{font:inherit;font-size:var(--fs-2);font-weight:var(--w-emph);
     padding:6px 12px;border-radius:5px;cursor:pointer;line-height:1.2;
     letter-spacing:.01em;}
.tour-prev{background:transparent;color:var(--muted);border:1px solid var(--line);}
.tour-prev:hover{background:var(--ice);color:var(--navy);border-color:var(--navy);}
.tour-prev[disabled]{opacity:.35;cursor:not-allowed;}
.tour-next{background:var(--navy);color:#fff;border:1px solid var(--navy);}
.tour-next:hover{background:#0F1740;}
.tour-next:focus-visible,.tour-prev:focus-visible,.tour-skip:focus-visible{
     outline:2px solid var(--gold);outline-offset:2px;}
.tour-callout-kbd{margin-top:8px;font-size:var(--fs-1);color:var(--muted);
     text-align:center;padding-top:8px;border-top:1px dotted var(--line);}
.tour-callout-kbd kbd{display:inline-block;padding:0 5px;font-family:var(--f-mono);
     font-size:var(--fs-1);background:var(--ice);color:var(--navy);
     border:1px solid var(--line);border-radius:3px;font-weight:var(--w-head);
     margin:0 2px;}
/* When the tour is running, lift the header/freshbar out of the dimming so
   they're not confusing dead pixels behind the halo. */
body.tour-running{overflow:hidden;}
.freshbar .kbd-hint kbd{display:inline-block;padding:0 5px;margin:0 2px;font-family:var(--f-mono);
     font-size:var(--fs-1);background:#28356B;color:#F5D77A;border:1px solid #3A4890;border-radius:3px;
     box-shadow:inset 0 -1px 0 #0F1738;font-weight:var(--w-head);line-height:14px;}
/* Reusable click-to-copy control: <span class="copy-cmd"><code>...</code><button data-copy="...">Copy</button></span> */
.copy-cmd{display:inline-flex;align-items:center;gap:6px;background:#16204A;border:1px solid #28356B;
     border-radius:6px;padding:2px 4px 2px 8px;font-family:var(--f-mono);font-size:var(--fs-1);
     color:#CADCFC;max-width:100%;}
.copy-cmd code{background:transparent;color:inherit;padding:0;font-size:inherit;white-space:nowrap;
     overflow:hidden;text-overflow:ellipsis;max-width:520px;}
.copy-cmd button{background:#28356B;color:#F5D77A;border:0;border-radius:4px;padding:2px 8px;
     font:inherit;font-size:var(--fs-1);font-weight:var(--w-head);cursor:pointer;letter-spacing:.03em;}
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
.eda-shape{font-size:var(--fs-2);color:var(--navy);font-weight:var(--w-emph);font-family:var(--f-mono);}
.eda-src{font-size:var(--fs-1);color:var(--muted);font-family:var(--f-mono);
     overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%;flex:1;min-width:0;}
.eda-src a{color:#3A4890;text-decoration:none;border-bottom:1px dotted #8FA8D8;}
.pill.sample-fresh{background:#1F7A3A;color:#E6F5EA;}
.pill.sample-stale{background:#E9CD7A;color:#3A2F0A;}
.pill.sample-unknown{background:#F6F7FA;color:#5A6072;border:1px solid var(--line);}
.eda-tbl{border-collapse:collapse;width:100%;font-size:var(--fs-1);margin:4px 0;}
.eda-tbl th{text-align:left;font-size:var(--fs-1);letter-spacing:.06em;text-transform:uppercase;
     color:var(--muted);border-bottom:1px solid var(--ice);padding:3px 6px;font-weight:var(--w-head);}
.eda-tbl td{border-bottom:1px solid #F1F3F8;padding:3px 6px;vertical-align:top;}
.eda-tbl td.mono{font-family:var(--f-mono);font-variant-numeric:tabular-nums;}
.eda-tbl tr.miss-flag td.miss-cell{background:#FBF0D6;color:#6E4E11;font-weight:var(--w-head);}
.eda-tbl td.spark{font-family:ui-monospace,"DejaVu Sans Mono",Consolas,monospace;font-size:var(--fs-2);
     color:var(--navy);letter-spacing:0;line-height:1;padding-top:5px;padding-bottom:5px;}
.eda-cap{font-size:var(--fs-1);color:var(--muted);margin:5px 0 2px;font-weight:var(--w-emph);
     letter-spacing:.05em;text-transform:uppercase;}
.eda-tv{font-size:var(--fs-1);line-height:1.5;color:var(--ink);}
.eda-tv .val{font-family:var(--f-mono);color:var(--navy);}
.eda-tv .cnt{color:var(--muted);font-size:var(--fs-1);margin-left:4px;}
.eda-geo{font-size:var(--fs-1);color:var(--ink);font-family:var(--f-mono);line-height:1.5;}
.eda-geo b{color:var(--navy);}
.eda-empty{font-size:var(--fs-1);color:var(--muted);font-style:italic;padding:6px 0;}
/* Diff banner variant used on cards to flag EDA changes on --refresh. */
.eda-diff{background:#FBF0D6;border-left:3px solid #C9A227;border-radius:4px;
     padding:5px 8px;margin:4px 0;font-size:var(--fs-1);color:#6E4E11;line-height:1.45;}
.eda-diff b{color:#6E4E11;}
/* Quick Look (Phase 4 #1) - tiered summary section at the top of every card.
   Tier chip colors: grey (catalog), blue (probe), green (sample). */
.tier-chip{display:inline-block;padding:2px 10px;border-radius:11px;font-size:var(--fs-1);
     font-weight:var(--w-head);letter-spacing:.02em;border:1px solid var(--line);}
.tier-chip.tier-catalog{background:#EDF0F7;color:#5A6072;border-color:#D6DBE8;}
.tier-chip.tier-probe{background:#DCE7FA;color:#1F2A5C;border-color:#8FA8D8;}
.tier-chip.tier-sample{background:#D6EDD9;color:#1F5A2E;border-color:#7ABF89;}
.ql-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:4px;}
.ql-sub{font-size:var(--fs-1);color:var(--muted);font-style:italic;}
/* Phase 4b: three-line TL;DR. Each line is one glance's worth of information -
   dense but scannable. Middle-dot separators keep the visual rhythm consistent
   across tiers; small caps 'ql-k' labels distinguish keys from values without
   bolding the whole line. Tint the line background at very low opacity in the
   tier's own color family so eye can track catalog/probe/sample lineage. */
.ql-line{font-size:var(--fs-2);color:var(--ink);line-height:1.55;margin:3px 0;
     padding:3px 8px;border-radius:4px;border-left:3px solid transparent;
     overflow-wrap:anywhere;}
.ql-t0{background:#F6F7FA;border-left-color:#D6DBE8;}
.ql-t1{background:#F1F5FF;border-left-color:#8FA8D8;}
.ql-t2{background:#EEF7EF;border-left-color:#7ABF89;}
.ql-k{font-size:var(--fs-1);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
     font-weight:var(--w-head);margin-right:2px;}
.ql-sep{color:#B8BFCE;margin:0 2px;}
.ql-nonapi{font-size:var(--fs-1);color:#8a4d1c;font-style:italic;margin:4px 0;}
/* Reframe pass commit #5: reframed TL;DR lines. `.ql-desc` renders the
   catalog description (moved up from the drill-down); `.ql-inside` styles
   the "what's inside" line so its trailing tier chip sits flush-right.
   `.tier-chip.tier-mini` is the shrunken cache-tier marker at the end of
   the "what's inside" line - readable but not the visual anchor it was
   pre-reframe. `.ql-d-reviewer` is the stage+role chip row promoted into
   the drill-down header. */
.ql-desc{font-size:var(--fs-2);color:var(--muted);line-height:1.45;margin:3px 0 2px;
     padding:3px 8px;font-style:italic;overflow-wrap:anywhere;}
.ql-inside{display:flex;flex-wrap:wrap;gap:6px;align-items:center;}
.ql-tier-tail{margin-left:auto;}
.tier-chip.tier-mini{font-size:var(--fs-1);padding:1px 6px;font-weight:var(--w-emph);
     opacity:0.85;text-transform:lowercase;letter-spacing:.02em;}
.ql-d-reviewer{display:flex;align-items:center;gap:6px;flex-wrap:wrap;
     padding:6px 8px;margin:2px 0 6px;background:#F6F7FA;border-radius:5px;
     border-left:3px solid var(--line);}
.ql-d-reviewer .ql-d-cap{margin-bottom:0;flex:0 0 auto;}
/* More-details toggle (Phase 4b #3). Native <details>/<summary>: works with
   JS off; the localStorage persistence in the inline script layers on top.
   Chevron rotates purely in CSS on open. Expanded background is tinted with
   the tier's own color family at very low opacity so the visual link to the
   TL;DR line's stripe is preserved on drill-in. */
.ql-details{margin-top:7px;border:1px solid var(--line);border-radius:6px;
     background:#fff;transition:background-color .18s ease-in;}
.ql-details[open]{background:#FBFCFE;}
.ql-details.ql-d-tier0[open]{background:#F9FAFC;}
.ql-details.ql-d-tier1[open]{background:#F5F9FF;}
.ql-details.ql-d-tier2[open]{background:#F3FAF4;}
.ql-summary{list-style:none;padding:5px 10px;cursor:pointer;user-select:none;
     display:flex;align-items:center;gap:6px;font-size:var(--fs-1);color:var(--navy);
     font-weight:var(--w-emph);letter-spacing:.02em;border-radius:6px;}
.ql-summary::-webkit-details-marker{display:none;}     /* Safari */
.ql-summary::marker{content:"";}                       /* Firefox/Chrome */
.ql-summary:hover{background:var(--ice);}
.ql-summary:focus-visible{outline:2px solid #8FA8D8;outline-offset:1px;}
.ql-chevron{display:inline-block;font-size:var(--fs-1);line-height:1;color:var(--muted);
     transition:transform .16s ease-in-out;transform-origin:50% 50%;}
.ql-details[open] .ql-chevron{transform:rotate(90deg);color:var(--navy);}
.ql-summary-label{flex:1;}
.ql-details-body{padding:7px 12px 10px;border-top:1px solid var(--ice);
     animation:ql-fade-in .18s ease-out;}
@keyframes ql-fade-in{from{opacity:0;transform:translateY(-2px);}
                      to{opacity:1;transform:translateY(0);}}
.ql-d-block{margin:6px 0;padding:6px 8px;border-radius:5px;background:#FDFDFE;
     border:1px solid #F0F2F7;}
.ql-d-block.ql-d-t0{background:#F8F9FC;}
.ql-d-block.ql-d-t1{background:#F1F5FF;border-color:#E1E8F6;}
.ql-d-block.ql-d-t2{background:#EEF7EF;border-color:#DAEBDE;}
.ql-d-block.ql-d-empty-wrap{background:#FBFAF6;border-color:#EEE6D3;}
.ql-d-cap{font-size:var(--fs-1);letter-spacing:.08em;text-transform:uppercase;
     color:var(--muted);font-weight:var(--w-head);margin-bottom:4px;}
.ql-d-row{font-size:var(--fs-1);color:var(--ink);line-height:1.55;margin:2px 0;
     overflow-wrap:anywhere;}
.ql-d-desc{font-size:var(--fs-1);color:var(--ink);line-height:1.5;margin:2px 0 6px;}
.ql-d-link{color:#3A4890;text-decoration:none;border-bottom:1px dotted #8FA8D8;
     font-family:var(--f-mono);font-size:var(--fs-1);}
.ql-d-empty{font-size:var(--fs-1);color:var(--muted);line-height:1.5;margin:2px 0;}
.ql-d-cmd{margin-top:4px;}
.ql-muted{color:var(--muted);font-size:var(--fs-1);}
/* Faceted browsing sidebar (only on the Products tabs). */
.products-shell{display:flex;gap:22px;align-items:flex-start;}
.products-main{flex:1;min-width:0;}
.facets{width:218px;flex:0 0 218px;position:sticky;top:8px;max-height:calc(100vh - 20px);
     overflow-y:auto;padding-right:4px;font-size:var(--fs-2);}
.facets-head{display:flex;align-items:baseline;justify-content:space-between;margin:0 0 8px;}
.facets-head h3{font-family:var(--f-display);color:var(--navy);font-size:var(--fs-3);margin:0;}
.facet-clear{font-size:var(--fs-1);color:#B8532F;font-weight:var(--w-emph);text-decoration:none;}
.facet-clear:hover{text-decoration:underline;}
.facet{border-top:1px solid var(--ice);padding:8px 0 6px;}
.facet h4{font-size:var(--fs-1);letter-spacing:.11em;text-transform:uppercase;color:var(--muted);
     font-weight:var(--w-head);margin:0 0 4px;}
.facet ul{list-style:none;padding:0;margin:0;}
.facet li{padding:0;}
.facet label{display:flex;align-items:center;gap:5px;padding:2px 4px;border-radius:4px;cursor:pointer;
     font-size:var(--fs-2);color:var(--ink);}
.facet label:hover{background:var(--ice);}
.facet input[type=checkbox]{margin:0;transform:scale(0.9);cursor:pointer;}
.facet .lbl{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.facet .cnt{font-size:var(--fs-1);color:var(--muted);font-variant-numeric:tabular-nums;
     background:var(--ice);border-radius:8px;padding:0 6px;line-height:15px;min-width:22px;text-align:center;}
.facet li.on label{background:var(--ice);font-weight:var(--w-emph);color:var(--navy);}
.facet li.empty{opacity:.4;}
.facet li.empty label{cursor:default;}
.facet .fhint{font-size:var(--fs-1);color:var(--muted);font-style:italic;padding:2px 4px 0;}
/* Reviewer-mode toggle (reframe pass commit #4). Sits above the facets and
   inverts the pre-reframe default: default view now shows ALL 573 products in
   4 kind panels; ticking the box flips into "reviewer mode" - hides everything
   but Candidate/FOCUS/newly-changed cards, revealing the AM tab instead. The
   goal is exploration first, review-workflow second. Persists via localStorage
   under 'product_scope:show_all_products' (same key as the pre-reframe toggle
   for continuity; JS handles the migration so returning readers don't get an
   unexpected view change). */
.am-toggle{padding:8px 6px 10px;margin:0 0 10px;border-bottom:1px solid var(--line);}
.am-toggle label{display:flex;align-items:center;gap:5px;font-size:var(--fs-2);
     color:var(--navy);font-weight:var(--w-emph);cursor:pointer;line-height:1.3;}
.am-toggle input[type=checkbox]{margin:0;transform:scale(1.05);cursor:pointer;}
.am-toggle .lbl{flex:0 1 auto;}
.am-toggle .cnt{color:var(--muted);font-weight:400;font-variant-numeric:tabular-nums;}
.am-hint{font-size:var(--fs-1);color:var(--muted);font-style:italic;margin-top:4px;line-height:1.4;}
/* Default: all cards visible. Only in reviewer mode (body.am-reviewer +
   panel.am-reviewer) do non-actively-managed cards hide. The visibility rule
   is opt-in - all-cards is the default and reviewer-mode is the ticked
   state. Class renamed from the pre-reframe .am-showall to make the polarity
   explicit at read time; the localStorage KEY is unchanged for continuity
   and migrated in the toggle handler below. */
.panel.am-reviewer .prod:not([data-actively-managed]){display:none;}
/* Reframe pass commit #4: default view shows the 4 kind tabs + panels; when
   the reviewer ticks the toggle, body.am-reviewer flips, kind tabs hide, and
   the small AM tab/panel becomes visible. Inversion of the pre-reframe rules. */
body.am-reviewer .tab.tab-kind,
body.am-reviewer .panel.panel-kind{display:none;}
body:not(.am-reviewer) .tab.tab-am,
body:not(.am-reviewer) .panel.panel-am{display:none;}
.facet .fhint code{font-family:var(--f-mono);font-size:var(--fs-1);
     background:var(--ice);color:var(--navy);padding:0 4px;border-radius:3px;font-style:normal;}
/* Reviewer-mode facets group (reframe pass commit #4). Collapsed by default so
   the sidebar reads as discovery-first (Family, Agency, Frequency); tapping
   the summary expands to reveal the Status / Composite role / Has evidence /
   Has probe / Notebook validated facets used by the review workflow. */
.facet-reviewer-group{margin-top:12px;padding-top:8px;border-top:1px solid var(--ice);}
/* Caret + marker + hover handling now comes from the unified `details.disc`
   grammar (condense pass 2026-07-26); local rules keep only the small-caps
   facet-header typography. */
.facet-reviewer-group > summary{font-size:var(--fs-1);color:var(--muted);
     font-weight:var(--w-head);letter-spacing:.09em;text-transform:uppercase;}
.facet-reviewer-group[open] > summary{color:var(--navy);}
.facet-reviewer-body .facet{border-top-color:var(--ice);}
@media(max-width:900px){.products-shell{flex-direction:column;} .facets{position:static;width:100%;flex:none;}}
/* Insight feed (Phase 5 #6 dual-render). Read-only display used by the Quick
   Look drill-down. Writes come from `python tools/product_scope.py --review
   <id> --insight "..."`; nothing in this page mutates the JSON. */
.scope-insights-feed{list-style:none;padding:0;margin:4px 0 0;
     max-height:340px;overflow-y:auto;}
.ins-empty{font-size:var(--fs-1);color:var(--muted);font-style:italic;padding:4px 0;}
.ins-empty code{font-family:var(--f-mono);font-size:var(--fs-1);
     background:var(--ice);color:var(--navy);padding:0 4px;border-radius:3px;
     font-style:normal;}
/* UX pass 2026-07-26 commit #5 - empty states as teaching moments.
   Every "No X yet" empty state on the page gets replaced with either a
   click-to-copy scaffold, a keyboard cheatsheet, or both. Nothing that
   just says "empty." Selectors below dress up the new empty variants. */
.ins-empty-scaffolds{padding:8px 4px;font-style:normal;color:var(--ink);}
.ins-empty-lead{font-size:var(--fs-2);color:var(--ink);margin-bottom:8px;
       line-height:var(--lh-2);font-style:normal;}
.ins-empty-scaffold-list{list-style:none;padding:0;margin:0 0 10px;
       display:flex;flex-direction:column;gap:8px;}
.ins-empty-scaffold{display:flex;flex-direction:column;gap:4px;
       padding:8px 10px;background:#FBFCFE;border:1px dashed var(--line);
       border-radius:6px;}
.ins-empty-scaffold-label{font-size:var(--fs-1);color:var(--gold);
       font-weight:var(--w-head);letter-spacing:.08em;text-transform:uppercase;}
.ins-empty-kbd{margin-top:6px;padding-top:8px;border-top:1px dotted var(--line);
       font-size:var(--fs-1);color:var(--muted);line-height:var(--lh-2);}
.ins-empty-kbd-lbl{color:var(--navy);font-weight:var(--w-head);
       letter-spacing:.05em;text-transform:uppercase;font-size:var(--fs-1);}
.ins-empty-kbd kbd{display:inline-block;padding:0 6px;font-family:var(--f-mono);
       font-size:var(--fs-1);background:var(--ice);color:var(--navy);
       border:1px solid var(--line);border-radius:3px;font-weight:var(--w-head);
       box-shadow:inset 0 -1px 0 var(--line);margin:0 2px;}
/* Per-card uncertainty_metrics empty state - inline copyable scaffold. */
.ql-unc-empty{display:inline-flex;flex-wrap:wrap;gap:8px;align-items:center;
       font-style:normal;color:var(--muted);}
.ql-unc-empty .copy-cmd{margin-top:2px;}
/* (Keyboard-cheatsheet "wwl-teach" empty-state block removed 2026-07-26 in
   the de-walling pass - the teach content was part of the text wall.) */
/* "No products touched yet" teaching block. */
.wti-teach{background:#FBFCFE;padding:12px 14px;border:1px solid var(--line);
       border-radius:8px;font-style:normal;color:var(--ink);}
.wti-teach-more{margin-top:10px;font-size:var(--fs-1);color:var(--muted);
       line-height:var(--lh-2);}
.wti-teach kbd{display:inline-block;padding:0 6px;font-family:var(--f-mono);
       font-size:var(--fs-1);background:var(--ice);color:var(--navy);
       border:1px solid var(--line);border-radius:3px;font-weight:var(--w-head);
       margin:0 2px;}
.ins-row{display:flex;gap:8px;align-items:flex-start;padding:5px 0;
     border-bottom:1px dotted #E1E7F0;font-size:var(--fs-2);}
.ins-row:last-child{border-bottom:0;}
.ins-ico{font-size:var(--fs-3);line-height:1;padding-top:2px;flex:0 0 18px;text-align:center;}
.ins-body{flex:1;min-width:0;}
.ins-meta{display:flex;gap:6px;align-items:baseline;font-size:var(--fs-1);
     color:var(--muted);flex-wrap:wrap;}
.ins-when{font-family:var(--f-mono);}
.ins-who{color:var(--navy);font-weight:var(--w-emph);font-size:var(--fs-1);}
.ins-badge{background:var(--ice);color:var(--navy);border-radius:8px;
     padding:0 6px;font-size:var(--fs-1);letter-spacing:.03em;font-weight:var(--w-head);
     text-transform:uppercase;}
.ins-badge.ins-src-auto-repo{background:#F1F5FF;color:#1F2A5C;}
.ins-badge.ins-src-auto-cache_diff{background:#EEF7EF;color:#1F5A2E;}
.ins-badge.ins-src-auto-divergence{background:#FBF0D6;color:#6E4E11;}
.ins-badge.ins-src-human{background:#F1E7C8;color:#6B4E11;}
.ins-text{color:var(--ink);line-height:1.45;margin-top:1px;
     overflow-wrap:anywhere;}
/* Phase 5 #6 - Quick Look TL;DR insight sub-line. Compact list, no borders,
   inherits the tier stripe so the eye reads it as part of the TL;DR pack. */
.ql-insights{list-style:none;padding:0;margin:3px 0 0;font-size:var(--fs-1);
     line-height:1.55;color:var(--muted);}
.ql-insights li.ins-tldr{display:flex;gap:5px;align-items:baseline;padding:1px 0;
     overflow-wrap:anywhere;}
.ql-insights .ins-ico{font-size:var(--fs-1);line-height:1;flex:0 0 15px;padding-top:1px;
     text-align:center;}
.ql-insights .ins-when{font-family:var(--f-mono);color:var(--muted);}
.ql-insights .ins-who{color:var(--navy);font-weight:var(--w-emph);font-size:var(--fs-1);}
.ql-insights .ins-text{color:var(--ink);}
.ql-ins-more{font-size:var(--fs-1);color:#3A4890;cursor:pointer;font-weight:var(--w-emph);
     background:none;border:0;padding:1px 0;letter-spacing:.02em;
     text-decoration:underline dotted;font-family:inherit;}
.ql-ins-more:hover{color:var(--navy);}
</style>
</head><body>
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
  <span class="copy-cmd"><code>python tools/product_scope.py</code>
    <button data-copy="python tools/product_scope.py">Copy</button></span>
  <span class="sha" title="HEAD SHA at generation time">__HEAD_SHORT__ &bull; __BRANCH__</span>
  <!-- UX pass 2026-07-26 commit #6: Guided tour launcher. Hidden by default
       once the reader has finished the tour once (localStorage flag).
       The compact ? version stays visible as a re-entry. -->
  <button type="button" id="tour-launch" class="tour-launch" title="Take the guided tour (~2 min)">Take the tour (2 min)</button>
  <button type="button" id="tour-relaunch" class="tour-relaunch" title="Take the guided tour again" aria-label="Take the tour again">?</button>
  <span class="kbd-hint" title="Press E on any product card to open or close its drill-down">Press <kbd>E</kbd> on a card to toggle details</span>
</div>
<!-- UX pass 2026-07-26 commit #6: Guided tour overlay + callout box. Pure
     vanilla JS + fixed-position DOM. Hidden until launched; then the overlay
     dims the page except for a cutout around the current step's target, and
     the callout box floats near that target with 1-line copy + next/skip. -->
<div id="tour-overlay" class="tour-overlay" role="dialog" aria-modal="true"
     aria-labelledby="tour-title" hidden>
  <div class="tour-dim" data-tour-dim="top"></div>
  <div class="tour-dim" data-tour-dim="right"></div>
  <div class="tour-dim" data-tour-dim="bottom"></div>
  <div class="tour-dim" data-tour-dim="left"></div>
  <div class="tour-halo" aria-hidden="true"></div>
  <div class="tour-callout" role="document">
    <div class="tour-callout-head">
      <span class="tour-step-idx" id="tour-step-idx">1 / 6</span>
      <button type="button" class="tour-skip" id="tour-skip" aria-label="Skip the tour">Skip tour</button>
    </div>
    <div class="tour-callout-title" id="tour-title">&nbsp;</div>
    <div class="tour-callout-body" id="tour-body">&nbsp;</div>
    <div class="tour-callout-foot">
      <button type="button" class="tour-prev" id="tour-prev" aria-label="Previous step">&larr; Back</button>
      <button type="button" class="tour-next" id="tour-next" aria-label="Next step">Next &rarr;</button>
    </div>
    <div class="tour-callout-kbd">
      <kbd>&larr;</kbd> / <kbd>&rarr;</kbd> navigate &middot; <kbd>Enter</kbd> next &middot; <kbd>Esc</kbd> exit
    </div>
  </div>
</div>
<div id="starthere" class="starthere" role="note">
  <button type="button" class="sh-dismiss" id="sh-dismiss" title="Hide this on this machine" aria-label="Dismiss the Start here banner">&times;</button>
  <div class="sh-title">&#128075; First time here? Start with these 3 things:</div>
  <ol>
    <li>Scroll to <b>"The Census data landscape"</b> &mdash; the treemap below shows all 573 Census data products, sized by count. Click any box to drill in.</li>
    <li>Any card's <b>"More details &#9656;"</b> toggle opens what's inside that dataset.</li>
    <li>Every card has a <b>copyable command</b> that runs in PowerShell to fetch more data or record a note.</li>
  </ol>
</div>
<div class="wrap">__PANELS__</div>
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
/* --- Beginner-UX pass commit #5. "+ Add a note" download handler.
   Delegated click handler on buttons with data-addnote-path=<product_id>.
   Constructs a small plain-text stub in memory, downloads it as
   note_<path-slug>_<timestamp>.txt via Blob + programmatic anchor click.
   The user edits the file, drops it into notes/ in the repo, and the next
   `python tools/product_scope.py` regen ingests it as a human insight. */
document.addEventListener('click', function(e){
  var b = e.target.closest && e.target.closest('button[data-addnote-path]');
  if(!b) return;
  e.preventDefault(); e.stopPropagation();
  var pid = b.getAttribute('data-addnote-path') || 'unknown';
  var ts = new Date().toISOString().replace(/[:.]/g, '-').replace('T', '_')
             .split('.')[0];
  var slug = pid.replace(/[^a-zA-Z0-9]+/g, '_');
  var fname = 'note_' + slug + '_' + ts + '.txt';
  var body = [
    '# Note for ' + pid,
    '# Save this file into the notes/ folder in the repo. Next regen',
    '# picks it up and drops it into notes/ingested/.',
    '# Lines starting with # are comments and get ignored on ingest.',
    '# The blank line below separates the header from the body.',
    '',
    'product_id: ' + pid,
    'who: Your Name',
    '',
    '(Write your thought here — what did you notice? What surprised you?',
    ' What might it be useful for?)',
    ''
  ].join('\n');
  var blob = new Blob([body], {type: 'text/plain'});
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = fname;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  // Visual confirmation on the button.
  var old = b.textContent; b.textContent = 'Downloaded ✓';
  b.classList.add('done');
  setTimeout(function(){ b.textContent = old; b.classList.remove('done'); }, 1800);
});
/* --- UX pass 2026-07-26 commit #3. Sankey pipeline stage click handler.
   Clicks on a Sankey node (a stacked bar for one pipeline stage) jump the
   reader into the Products tab so they can start exploring products at
   that stage. Keeps the click behaviour discoverable but doesn't apply a
   hard filter (facet system is orthogonal and adding a fifth facet just
   for pipeline stage would be more mechanism than the click needs). */
document.addEventListener('click', function(e){
  var n = e.target.closest && e.target.closest('.sankey-node[data-pipeline-stage]');
  if(!n) return;
  e.preventDefault();
  // Focus a Products tab that is VISIBLE in the current mode (bug fix
  // 2026-07-26): the AM tab is CSS-hidden outside reviewer mode, and
  // clicking it left every panel invisible.
  var first = document.body.classList.contains('am-reviewer')
              ? document.querySelector('.tab.tab-am')
              : document.querySelector('.tab.tab-kind');
  if(!first){ first = document.querySelector('.tab.tab-am') ||
                      document.querySelector('.tab.tab-kind'); }
  if(first){ first.click(); }
  // Keep the reader roughly where they were - scroll the panel container into
  // view. Native anchor scrolling would jump past the freshbar.
  var wrap = document.querySelector('.wrap');
  if(wrap && wrap.scrollIntoView){ wrap.scrollIntoView({behavior:'smooth',block:'start'}); }
});
document.addEventListener('keydown', function(e){
  if(e.key !== 'Enter' && e.key !== ' ') return;
  var n = e.target && e.target.classList &&
          e.target.classList.contains('sankey-node') ? e.target : null;
  if(!n) return;
  e.preventDefault(); n.click();
});
/* --- Beginner-UX pass commit #2. Start-here banner dismissal.
   Reads localStorage on load; if set, hides the banner. Click the &times;
   button to dismiss (writes the key). If localStorage isn't available (private
   mode), the banner still renders and dismissal is best-effort. */
(function(){
  var STORE_KEY = 'product_scope:start_here_dismissed';
  var el = document.getElementById('starthere');
  if(!el) return;
  try {
    if (window.localStorage && window.localStorage.getItem(STORE_KEY) === '1') {
      el.classList.add('dismissed');
    }
  } catch(_){ /* private mode / storage disabled: leave banner visible */ }
  var btn = document.getElementById('sh-dismiss');
  if (btn) btn.addEventListener('click', function(){
    el.classList.add('dismissed');
    try { window.localStorage && window.localStorage.setItem(STORE_KEY, '1'); }
    catch(_){}
  });
})();
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
/* Per-card probe checkboxes + queue slideout removed in the beginner-UX pass
   (commit #1). The one true probe path is now: click a card's "Suggested next
   step" copy button (or a single-shot --probe <path> CLI invocation). */
/* --- Faceted browsing (Products tabs) ---
   Filters combine as AND across facets, OR within a facet (multi-select). Facet
   counts recompute against the intersection of the OTHER active facets, so the
   sidebar always shows "how many products would you have if you clicked this
   next". Falls back to the text filter above; both stack. */
function _prodPasses(p, filters, textQuery, amOnly){
  if (amOnly && p.dataset.activelyManaged !== 'true') return false;
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
  // Reviewer mode: default is show-all (post-reframe). Panels flagged with
  // .am-reviewer restrict visibility to actively-managed cards only. Facet
  // counts recompute against the same visibility rule so sidebar numbers
  // match what the reader actually sees.
  var amOnly = panel.classList.contains('am-reviewer');
  var shown = 0;
  var prods = panel.querySelectorAll('.prod');
  prods.forEach(function(p){
    var ok = _prodPasses(p, filters, q, amOnly);
    p.style.display = ok ? '' : 'none';
    if (ok) shown++;
  });
  panel.querySelectorAll('.facet').forEach(function(fc){
    var f = fc.dataset.f;
    fc.querySelectorAll('li').forEach(function(li){
      var v = li.dataset.v;
      var n = 0;
      prods.forEach(function(p){
        if (amOnly && p.dataset.activelyManaged !== 'true') return;
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
/* --- Reviewer-mode toggle (reframe pass commit #4) ---
   Default: ALL 573 cards visible, split by kind (4 tabs). Ticking the toggle
   flips to reviewer mode - hides everything but Candidate/FOCUS/newly-changed
   cards and swaps the kind tabs for a single "Actively managed" tab. Inverts
   the pre-reframe default of "AM only on first load"; the goal now is
   exploration first, review workflow second. State persists across page loads
   via localStorage under the same 'product_scope:show_all_products' key the
   pre-reframe toggle used. Semantic inversion is handled with a one-time
   migration flag so returning readers keep whatever view they last had. Fails
   silently on hostile storage envs (in-private mode, quota, disabled). */
(function(){
  var LS_KEY       = 'product_scope:show_all_products';
  var LS_MIGRATED  = 'product_scope:show_all_products:migrated_v2';
  function _lsGet(k){ try { return localStorage.getItem(k); } catch(_){ return null; } }
  function _lsSet(k, v){ try { localStorage.setItem(k, v); } catch(_){} }
  /* Pre-reframe semantics: value=='true' meant "show all", default hide-AM.
     Post-reframe semantics: value=='true' means "reviewer mode ON", default
     show all. To keep returning readers on the same visual state without
     flipping views under them, migrate on first load in the new version. */
  var raw = _lsGet(LS_KEY);
  if (_lsGet(LS_MIGRATED) !== 'true'){
    if (raw === 'true')       { _lsSet(LS_KEY, 'false'); raw = 'false'; }
    else if (raw === 'false') { _lsSet(LS_KEY, 'true');  raw = 'true';  }
    _lsSet(LS_MIGRATED, 'true');
  }
  var reviewerMode = raw === 'true';
  /* body.am-reviewer drives both tab-visibility CSS (hides kind tabs, shows AM
     tab) and the per-panel filter that hides non-AM cards. Renamed from the
     pre-reframe .am-showall to make the polarity explicit at read time. */
  document.body.classList.toggle('am-reviewer', reviewerMode);
  document.querySelectorAll('.panel').forEach(function(panel){
    if (!panel.querySelector('.am-cb')) return;   /* Home tab has no toggle */
    panel.classList.toggle('am-reviewer', reviewerMode);
    panel.querySelectorAll('.am-cb').forEach(function(cb){ cb.checked = reviewerMode; });
  });
  /* Server-renders the Home tab as active on load. When the persisted state
     puts us in reviewer mode but the currently-active tab (defensive fallback
     for future changes) is a kind tab, jump to the AM tab so a hidden tab
     doesn't dead-end the reader. Symmetric case handled too. */
  var activeInit = document.querySelector('.tab.on');
  if (activeInit && reviewerMode && activeInit.classList.contains('tab-kind')){
    var amInit = document.querySelector('.tab.tab-am');
    if (amInit) amInit.click();
  } else if (activeInit && !reviewerMode && activeInit.classList.contains('tab-am')){
    var firstKindInit = document.querySelector('.tab.tab-kind');
    if (firstKindInit) firstKindInit.click();
  }
  document.querySelectorAll('.am-cb').forEach(function(cb){
    cb.addEventListener('change', function(){
      var reviewer = cb.checked;
      _lsSet(LS_KEY, reviewer ? 'true' : 'false');
      /* Body class first - drives the tab collapse via CSS. */
      document.body.classList.toggle('am-reviewer', reviewer);
      /* Update every products panel in sync so switching tabs keeps the same
         view. The toggle lives inside each panel's sidebar; the visibility
         rule is panel-scoped via .am-reviewer. */
      document.querySelectorAll('.panel').forEach(function(panel){
        if (!panel.querySelector('.am-cb')) return;
        panel.classList.toggle('am-reviewer', reviewer);
        panel.querySelectorAll('.am-cb').forEach(function(x){ x.checked = reviewer; });
        _applyFacets(panel);
      });
      /* Tab-switch if the currently active tab just got hidden. Ticking
         reviewer mode while on a kind tab -> jump to the AM tab. Unticking
         while on the AM tab -> jump to the first kind tab. */
      var active = document.querySelector('.tab.on');
      if (!active) return;
      var hideActive = (reviewer && active.classList.contains('tab-kind')) ||
                       (!reviewer && active.classList.contains('tab-am'));
      if (!hideActive) return;
      var target = reviewer ? document.querySelector('.tab.tab-am')
                            : document.querySelector('.tab.tab-kind');
      if (target) target.click();
    });
  });
  /* Initial pass: recompute facet counts against the toggle's current state
     so the sidebar numbers match what the reader actually sees on load. */
  document.querySelectorAll('.panel').forEach(function(panel){
    if (panel.querySelector('.am-cb')) _applyFacets(panel);
  });
})();
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
    /* Same story if reviewer mode is on (opt-in post-reframe) - defer to the
       facet applier so its combined visibility rule fires. */
    if (panel.classList.contains('am-reviewer')) { _applyFacets(panel); return; }
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
/* --- Quick Look drill-down persistence (Phase 4b #4) ---
   Each <details data-product-id="..."> in Quick Look remembers whether the
   reader had it open via localStorage, keyed by product id. The <details>
   element works with JS off; this is a pure enhancement layer.
   Errors (in-private mode, quota exceeded, disabled storage) silently no-op
   so a hostile storage environment still leaves the toggle functional. */
(function(){
  var LS_PREFIX = 'product_scope:card_expanded:';
  function _lsGet(k){ try { return localStorage.getItem(k); } catch(_){ return null; } }
  function _lsSet(k, v){ try { localStorage.setItem(k, v); } catch(_){} }
  // Restore per-card state at page load.
  document.querySelectorAll('details[data-product-id]').forEach(function(el){
    var key = LS_PREFIX + el.dataset.productId;
    if (_lsGet(key) === 'true') el.open = true;
  });
  // Persist on every toggle. Capture-phase listener because the 'toggle'
  // event does not bubble - has to be caught at the document level.
  document.addEventListener('toggle', function(e){
    var el = e.target;
    if (el && el.tagName === 'DETAILS' && el.dataset && el.dataset.productId){
      _lsSet(LS_PREFIX + el.dataset.productId, el.open ? 'true' : 'false');
    }
  }, true);
})();
/* --- Condense-home pass 2026-07-26 commit #2. Section-level collapse
   persistence for the three heavy Home sections (landscape treemap, WWL
   Show-all drawer, Bureau press feed). Extends the existing localStorage
   pattern under keyed namespaces:
     * product_scope:landscape_expanded  ('true'/'false')
     * product_scope:wwl_show_all        ('true'/'false')  -- <details> based
     * product_scope:bureau_expanded     ('true'/'false')
   Any hostile storage env (in-private, quota, disabled) silently no-ops. */
(function(){
  var LS_KEY_PREFIX = 'product_scope:';
  function _lsGet(k){ try { return localStorage.getItem(k); } catch(_){ return null; } }
  function _lsSet(k, v){ try { localStorage.setItem(k, v); } catch(_){} }

  /* Landscape treemap: swap between .lscape-compact (default) and
     .lscape-expanded (SVG grid). Both live inside the same .lscape-section
     so the swap is a `hidden` attribute flip. Buttons on both sides carry
     data-landscape-toggle. */
  var lscape = document.querySelector('.lscape-section[data-collapsible="landscape"]');
  if (lscape){
    var compact = lscape.querySelector('[data-landscape-view="compact"]');
    var expanded = lscape.querySelector('[data-landscape-view="expanded"]');
    var setLandscapeState = function(open){
      if (compact) compact.hidden = !!open;
      if (expanded) expanded.hidden = !open;
      /* Unified open-state signal (gold left-edge accent via CSS). */
      lscape.classList.toggle('is-open', !!open);
      lscape.querySelectorAll('[data-landscape-toggle]').forEach(function(b){
        b.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    };
    /* Treemap proportion tuning (condense pass 2026-07-26): the treemap is
       the chapter's centerpiece visual, so it renders EXPANDED by default
       (its two smaller kind rows are collapsed server-side instead). The
       compact text summary is the user-chosen collapsed state, remembered
       per machine. */
    var initialOpen = _lsGet(LS_KEY_PREFIX + 'landscape_expanded') !== 'false';
    setLandscapeState(initialOpen);
    lscape.addEventListener('click', function(e){
      var b = e.target.closest && e.target.closest('[data-landscape-toggle]');
      if (!b) return;
      e.preventDefault();
      var currentlyOpen = !expanded || expanded.hidden === false;
      var next = !currentlyOpen;
      setLandscapeState(next);
      _lsSet(LS_KEY_PREFIX + 'landscape_expanded', next ? 'true' : 'false');
      /* When collapsing, scroll the section header back into view so the
         reader isn't stranded at the bottom of the previously-tall SVG. */
      if (!next){
        var h = lscape.querySelector('h2');
        if (h && h.scrollIntoView) h.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      }
    });
    /* Also let a click on any compact kind row open the expanded view - it
       reads as a discovery affordance without needing a second button. */
    var rows = lscape.querySelectorAll('.lscape-compact-row');
    rows.forEach(function(r){
      r.style.cursor = 'pointer';
      r.setAttribute('role', 'button');
      r.setAttribute('tabindex', '0');
      r.addEventListener('click', function(){
        setLandscapeState(true);
        _lsSet(LS_KEY_PREFIX + 'landscape_expanded', 'true');
      });
      r.addEventListener('keydown', function(e){
        if (e.key === 'Enter' || e.key === ' '){
          e.preventDefault();
          setLandscapeState(true);
          _lsSet(LS_KEY_PREFIX + 'landscape_expanded', 'true');
        }
      });
    });
  }

  /* Bureau press feed: swap between .cpress-preview (default) and
     .cpress-full (5-item list). Same hidden-attr flip pattern. */
  var bureau = document.querySelector('.cpress-section[data-collapsible="bureau"]');
  if (bureau){
    var preview = bureau.querySelector('[data-bureau-view="collapsed"]');
    var full = bureau.querySelector('[data-bureau-view="expanded"]');
    var setBureauState = function(open){
      if (preview) preview.hidden = !!open;
      if (full) full.hidden = !open;
      /* Unified open-state signal (gold left-edge accent via CSS). */
      bureau.classList.toggle('is-open', !!open);
      bureau.querySelectorAll('[data-bureau-toggle]').forEach(function(b){
        b.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    };
    var bInitialOpen = _lsGet(LS_KEY_PREFIX + 'bureau_expanded') === 'true';
    setBureauState(bInitialOpen);
    bureau.addEventListener('click', function(e){
      var b = e.target.closest && e.target.closest('[data-bureau-toggle]');
      if (!b) return;
      e.preventDefault();
      var currentlyOpen = !full || full.hidden === false;
      var next = !currentlyOpen;
      setBureauState(next);
      _lsSet(LS_KEY_PREFIX + 'bureau_expanded', next ? 'true' : 'false');
    });
  }

  /* WWL Show-all drawer: <details> element with data-persist-key. Native
     <details> already toggles open/closed with JS off; this restores the
     last state from localStorage and persists changes on 'toggle'. */
  document.querySelectorAll('details[data-persist-key]').forEach(function(el){
    var key = LS_KEY_PREFIX + el.dataset.persistKey;
    if (_lsGet(key) === 'true') el.open = true;
  });
  document.addEventListener('toggle', function(e){
    var el = e.target;
    if (el && el.tagName === 'DETAILS' && el.dataset && el.dataset.persistKey){
      _lsSet(LS_KEY_PREFIX + el.dataset.persistKey, el.open ? 'true' : 'false');
    }
  }, true);
})();
/* --- Condense-home pass 2026-07-26 commit #3. Sticky in-page chapter nav
   wayfinder for Home. Two behaviors:
     1. Click a chip -> smooth-scroll to the corresponding chapter (uses
        scroll-margin-top so the chapter label lands below the sticky bar).
     2. As the reader scrolls, highlight the chip whose chapter is currently
        top-of-viewport (IntersectionObserver watches each .home-chapter and
        picks the last one whose top has crossed the sticky-nav boundary).
   Falls back gracefully with JS off (chips are <a href="#..."> anchors that
   still work). The nav DOM lives inside #panel-home so tab switching handles
   its visibility automatically. */
(function(){
  var nav = document.querySelector('.home-chapternav');
  if (!nav) return;
  var chips = Array.prototype.slice.call(
    nav.querySelectorAll('.home-chapternav-chip'));
  if (!chips.length) return;

  /* Smooth-scroll click handler. Native anchor jumps land under the sticky
     nav because scroll-margin-top is set on .home-chapter; behavior: 'smooth'
     is the only add. Ctrl/Cmd+click and middle-click still work as native
     anchors. */
  chips.forEach(function(chip){
    chip.addEventListener('click', function(e){
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
      var id = chip.getAttribute('href');
      if (!id || id.charAt(0) !== '#') return;
      var target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({behavior: 'smooth', block: 'start'});
      _setActive(chip);
      /* Update the URL hash without triggering another scroll. */
      try { history.replaceState(null, '', id); } catch(_){}
    });
  });

  function _setActive(activeChip){
    chips.forEach(function(c){
      c.classList.toggle('on', c === activeChip);
      c.setAttribute('aria-current', c === activeChip ? 'true' : 'false');
    });
  }

  /* IntersectionObserver: watch every chapter, keep track of which ones are
     currently intersecting near the top of the viewport. The `rootMargin`
     top offset is negative so the "trigger line" sits just below the sticky
     nav rather than at the very top of the viewport. */
  var chapters = Array.prototype.slice.call(
    document.querySelectorAll('.home-chapter[data-chapter]'));
  if (!chapters.length) { _setActive(chips[0]); return; }
  var visibleIds = new Set();
  var observer = new IntersectionObserver(function(entries){
    entries.forEach(function(en){
      var cid = en.target.getAttribute('data-chapter');
      if (en.isIntersecting) visibleIds.add(cid);
      else visibleIds.delete(cid);
    });
    /* Pick the LAST chapter that's currently visible (most-recently-crossed
       becomes the "current" one). Fallback: the first chapter above the
       viewport if none intersect. */
    var pick = null;
    for (var i = chapters.length - 1; i >= 0; i--){
      var cid = chapters[i].getAttribute('data-chapter');
      if (visibleIds.has(cid)) { pick = cid; break; }
    }
    if (!pick){
      /* Nothing intersecting - find the chapter whose top is above the
         trigger line (i.e., we've scrolled past it). */
      for (var j = chapters.length - 1; j >= 0; j--){
        var r = chapters[j].getBoundingClientRect();
        if (r.top < 80){ pick = chapters[j].getAttribute('data-chapter'); break; }
      }
    }
    if (!pick) pick = chapters[0].getAttribute('data-chapter');
    var chip = nav.querySelector('.home-chapternav-chip[data-chapter-target="' + pick + '"]');
    if (chip) _setActive(chip);
  }, {
    root: null,
    rootMargin: '-80px 0px -55% 0px',
    threshold: 0
  });
  chapters.forEach(function(ch){ observer.observe(ch); });
  /* Seed the initial highlight on the first chapter so the nav isn't blank
     before the first scroll event. */
  _setActive(chips[0]);
})();
/* --- Keyboard shortcut: E toggles the focused Quick Look drill-down ---
   Behaviour (Phase 4b #5):
     * Fires only for plain 'e' / 'E'. Modifiers (Ctrl/Alt/Meta/Shift) skip.
     * Never fires while the user is typing in an input, textarea, contenteditable,
       or select - so the sidebar text-search box (Phase 1 #2) and any facet
       checkbox are unaffected.
     * If the currently-focused element is inside a card, toggle that card's
       <details>. Falls back to the topmost <details> visible in the viewport,
       so the user can hit E without first tab-focusing anything.
     * Uses .open = !.open which triggers the native 'toggle' event, which the
       persistence handler above catches - so localStorage stays in sync. */
(function(){
  function _isTypingTarget(el){
    if (!el) return false;
    if (el.isContentEditable) return true;
    var tag = (el.tagName || '').toUpperCase();
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  }
  function _topmostVisibleDetails(){
    var vh = window.innerHeight || document.documentElement.clientHeight;
    var all = document.querySelectorAll('details[data-product-id]');
    var best = null, bestTop = Infinity;
    for (var i = 0; i < all.length; i++){
      var r = all[i].getBoundingClientRect();
      // Any part of the card in the viewport counts as visible. Rank by how
      // close the top edge is to the top of the viewport (positive = below
      // the fold, negative = scrolled past); positive-and-smallest wins,
      // otherwise the one closest to zero from below.
      if (r.bottom < 0 || r.top > vh) continue;
      var score = r.top >= 0 ? r.top : (vh + Math.abs(r.top));
      if (score < bestTop){ bestTop = score; best = all[i]; }
    }
    return best;
  }
  document.addEventListener('keydown', function(e){
    if (e.key !== 'e' && e.key !== 'E') return;
    if (e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
    if (_isTypingTarget(e.target)) return;
    var focused = document.activeElement;
    var target = focused && focused.closest ? focused.closest('details[data-product-id]') : null;
    if (!target) target = _topmostVisibleDetails();
    if (!target) return;
    e.preventDefault();
    target.open = !target.open;
  });
})();
/* --- Landscape viz click-to-drill handler (Phase A ceiling-push #1) ---
   Clicking any program box (SVG <g> in the treemap, or a fallback flex chip
   when a kind degrades) jumps to the Products tab and populates the tab's
   text-filter box with the program name so the reader lands on that slice
   of the catalog. Reuses the existing filter-input listener (._applyFacets)
   so behavior stays in sync with sidebar facet + AM toggle changes.
   Selector accepts both `.lscape-prog[data-landscape-prog]` (SVG group) and
   `.lscape-fallback-chip[data-landscape-prog]` (degraded row). Also fires
   on Enter/Space for keyboard users focused on an SVG group via tabindex. */
(function(){
  function _findBox(target){
    if (!target || !target.closest) return null;
    return target.closest('[data-landscape-prog]');
  }
  function _drill(box){
    var prog = box.getAttribute('data-landscape-prog');
    if (!prog) return;
    /* Ensure the reader can see all matching cards: if reviewer mode is on,
       flip it off so non-AM cards become visible. Default view already shows
       all cards. */
    if (document.body.classList.contains('am-reviewer')){
      var cb = document.querySelector('.am-cb');
      if (cb){ cb.checked = false;
        cb.dispatchEvent(new Event('change', {bubbles: true})); }
    }
    /* Prefer whichever kind panel actually contains this program's cards.
       Kind panels ONLY (bug fix 2026-07-26): #panel-am sits first in the
       DOM but is CSS-hidden outside reviewer mode, and the drill just
       flipped reviewer mode off above - landing there showed nothing.
       Every product has a kind-panel copy, so nothing is unreachable. */
    var panels = document.querySelectorAll('.panel.panel-kind');
    var target = null;
    for (var i = 0; i < panels.length; i++){
      var p = panels[i];
      var any = p.querySelector('.prod[data-family="' + CSS.escape(prog) + '"]');
      if (any){ target = p; break; }
    }
    if (!target) return;
    var pid = target.id;
    var key = pid.replace(/^panel-/, '');
    var tab = document.querySelector('.tab[data-k="' + key + '"]');
    if (tab && !tab.classList.contains('on')) tab.click();
    /* Populate the filter input and fire input event so the sidebar re-applies. */
    var inp = target.querySelector('.filter input');
    if (inp){
      inp.value = prog;
      inp.dispatchEvent(new Event('input', {bubbles: true}));
      /* Scroll the products area into view. */
      setTimeout(function(){
        var y = inp.getBoundingClientRect().top + window.pageYOffset - 60;
        window.scrollTo({top: y, behavior: 'smooth'});
        inp.focus({preventScroll: true});
      }, 30);
    }
  }
  document.addEventListener('click', function(e){
    var box = _findBox(e.target);
    if (!box) return;
    e.preventDefault();
    _drill(box);
  });
  document.addEventListener('keydown', function(e){
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var box = _findBox(e.target);
    if (!box) return;
    /* Only intercept when focus IS on a program box; typing Enter in an
       input somewhere else on the page must not fire the drill. */
    if (!box.matches('[data-landscape-prog]')) return;
    if (box !== document.activeElement && !box.contains(document.activeElement)) return;
    e.preventDefault();
    _drill(box);
  });
})();
/* --- Home -> card jump (bug-fixed 2026-07-26 after Garrett's live test) ---
   Every Home element that names a product (curriculum "Open card", search
   results, Up-next queue, Recently touched, What-we've-learned chips)
   carries data-jump-path="<catalog path>" and shares this ONE code path.

   ROOT CAUSE of the "opens to nothing" bug: actively-managed products render
   TWICE - once in #panel-am (which sits FIRST in the DOM) and once in their
   kind panel. querySelector() therefore returned the #panel-am copy, and the
   handler clicked the hidden AM tab. In the default show-all mode the CSS
   rule `body:not(.am-reviewer) .panel.panel-am{display:none}` kept that
   panel invisible even with .on, so the click hid the Home panel and showed
   nothing at all. Since every curriculum product IS actively managed, every
   curriculum link hit this path.

   The fix: pick the copy whose panel is visible in the CURRENT mode
   (reviewer mode -> #panel-am copy, show-all mode -> kind-panel copy), then
   tab-switch, unfold the card ITSELF (not just its .gsec/.psec ancestors -
   a folded card previously read as "nothing happened"), clear any facet /
   text filter hiding it, scroll, and pulse-highlight. Exposed as
   window.__jumpToCard(path) so future sources can call it directly. */
(function(){
  function _pick(path){
    /* All rendered copies of this product's card, DOM order. */
    var cards = document.querySelectorAll(
      '.prod[data-path="' + CSS.escape(path) + '"]');
    if (!cards.length) return null;
    var reviewer = document.body.classList.contains('am-reviewer');
    var fallback = null;
    for (var i = 0; i < cards.length; i++){
      var p = cards[i].closest('.panel');
      if (!p) continue;
      var inAm = p.classList.contains('panel-am');
      /* Mode-visible copy: AM-panel copy in reviewer mode, kind-panel copy
         in show-all mode. */
      if (reviewer === inAm) return {card: cards[i], panel: p};
      if (!fallback) fallback = {card: cards[i], panel: p};
    }
    return fallback;
  }
  function _unfold(card){
    /* The card itself may be collapsed (server renders non-FOCUS cards
       .folded); open it AND every ancestor .gsec/.psec scaffold. */
    card.classList.remove('folded');
    var el = card.parentElement;
    while (el){
      if (el.classList){
        el.classList.remove('gfold');
        el.classList.remove('pfold');
      }
      el = el.parentElement;
    }
  }
  window.__jumpToCard = function(path){
    var hit = _pick(path);
    if (!hit) return false;
    /* Non-AM product only exists in a kind panel; if reviewer mode is
       hiding kind panels, flip it off (the checkbox change handler does the
       re-filter + tab swap), then re-pick under the new mode. */
    if (document.body.classList.contains('am-reviewer') &&
        !hit.panel.classList.contains('panel-am')){
      var cb = document.querySelector('.am-cb');
      if (cb){ cb.checked = false;
        cb.dispatchEvent(new Event('change', {bubbles: true})); }
      hit = _pick(path) || hit;
    }
    var card = hit.card, panel = hit.panel;
    var key = panel.id.replace(/^panel-/, '');
    var tab = document.querySelector('.tab[data-k="' + CSS.escape(key) + '"]');
    if (tab && !tab.classList.contains('on')) tab.click();
    _unfold(card);
    /* A leftover facet or text filter can hide the card via inline
       display:none (_applyFacets). The reader explicitly asked for THIS
       card, so clear the panel's filters and re-apply. */
    if (card.style.display === 'none'){
      panel.querySelectorAll('.facet input:checked').forEach(
        function(x){ x.checked = false; });
      var inp = panel.querySelector('.filter input');
      if (inp) inp.value = '';
      if (typeof _applyFacets === 'function') _applyFacets(panel);
    }
    /* Scroll after the layout settles (tab switch just toggled display). */
    setTimeout(function(){
      var y = card.getBoundingClientRect().top + window.pageYOffset - 40;
      window.scrollTo({top: y, behavior: 'smooth'});
      card.style.transition = 'background-color .4s ease';
      var prev = card.style.backgroundColor;
      card.style.backgroundColor = '#FBF6E7';
      setTimeout(function(){ card.style.backgroundColor = prev; }, 1600);
    }, 50);
    return true;
  };
  document.addEventListener('click', function(e){
    var a = e.target.closest && e.target.closest('[data-jump-path]');
    if (!a) return;
    e.preventDefault();
    window.__jumpToCard(a.getAttribute('data-jump-path'));
  });
})();
/* --- Phase 5 #6 - Quick Look TL;DR "N more" button opens the sibling
   <details> so the reader can jump into the full insights feed. Delegated
   listener stays trivial: this is the only Phase 5 client-side behaviour
   left after the CLI-helper pivot dropped the inline edit UI. */
(function(){
  document.addEventListener('click', function(e){
    var btn = e.target.closest && e.target.closest('.ql-ins-more');
    if (!btn) return;
    e.preventDefault();
    var qlCard = btn.closest('.bcard');   // the Quick Look bcard
    var details = qlCard ? qlCard.querySelector('details[data-product-id]') : null;
    if (details){
      details.open = true;
      /* Scroll the drill-down into view; leave a bit of headroom. */
      var body = details.querySelector('.ql-details-body');
      if (body && body.scrollIntoView){
        body.scrollIntoView({behavior: 'smooth', block: 'start'});
      }
    }
  });
})();
/* --- Phase A ceiling-push #2: triage-nav keyboard shortcuts + URL hash filter state ---
   Three progressive-enhancement additions to the Products tabs. All degrade
   gracefully if JS is disabled: native anchor scroll, native <details>
   toggle, and localStorage-only filter state still work.

     1. "/" focuses the sidebar text-filter input on the active panel.
        Never fires when the user is already typing in an input; typing "/"
        in the filter box types the literal slash character as expected.

     2. "j" / "k" cycles focus through visible .prod cards on the active
        panel with wrap-around at the ends. Enter on a focused card opens
        that card's Quick Look drill-down. Tab still works normally for
        general keyboard navigation.

     3. Every facet click, text-filter change, or reviewer-mode toggle
        serializes state to location.hash (URLSearchParams format:
        #tab=k0&q=income&f_kind=Aggregate%20tables&am=1). On page load, if
        the hash is non-empty it's parsed FIRST and its keys override
        localStorage defaults for those keys. Absent keys leave localStorage
        alone, so a bookmark that only pins the text query doesn't wipe
        the reader's AM-toggle preference. */
(function(){
  function _isTypingTarget(el){
    if (!el) return false;
    if (el.isContentEditable) return true;
    var tag = (el.tagName || '').toUpperCase();
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  }
  function _activePanel(){
    return document.querySelector('.panel.on');
  }
  function _visibleCards(panel){
    if (!panel) return [];
    return Array.prototype.filter.call(
      panel.querySelectorAll('.prod'),
      function(p){ return p.offsetParent !== null &&
                          getComputedStyle(p).display !== 'none'; });
  }
  /* --- "/" shortcut: focus the sidebar text-filter input --- */
  document.addEventListener('keydown', function(e){
    if (e.key !== '/') return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (_isTypingTarget(e.target)) return;
    var panel = _activePanel();
    if (!panel) return;
    var inp = panel.querySelector('.filter input');
    if (!inp) return;
    e.preventDefault();
    inp.focus({preventScroll: false});
    inp.select();
  });
  /* --- "j" / "k" card nav + "Enter" to toggle Quick Look drill-down --- */
  document.addEventListener('keydown', function(e){
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (_isTypingTarget(e.target)) return;
    var panel = _activePanel();
    if (!panel) return;
    if (e.key === 'j' || e.key === 'k'){
      var cards = _visibleCards(panel);
      if (!cards.length) return;
      var current = document.activeElement && document.activeElement.closest
                    ? document.activeElement.closest('.prod')
                    : null;
      var idx = current ? cards.indexOf(current) : -1;
      var next;
      if (e.key === 'j'){
        next = idx < 0 ? cards[0] : cards[(idx + 1) % cards.length];
      } else {
        next = idx < 0 ? cards[cards.length - 1]
                       : cards[(idx - 1 + cards.length) % cards.length];
      }
      if (!next) return;
      e.preventDefault();
      next.focus({preventScroll: false});
      /* scrollIntoView so the reader doesn't lose the card off-viewport. */
      if (next.scrollIntoView){
        next.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      }
    } else if (e.key === 'Enter'){
      var focused = document.activeElement && document.activeElement.closest
                    ? document.activeElement.closest('.prod')
                    : null;
      if (!focused) return;
      var details = focused.querySelector('details[data-product-id]');
      if (!details) return;
      e.preventDefault();
      details.open = !details.open;
    }
  });
  /* --- URL hash filter state (per-panel: active tab, text query, facets, AM) ---
     Encoding: URLSearchParams with keys 'tab' (data-k of active tab),
     'q' (text filter), 'f_<facet-key>' (comma-separated values), 'am' ('1'
     when reviewer mode is on). Decoded on load; unspecified keys fall back
     to their localStorage / default values. */
  var _restoringHash = false;    /* suppress write while restore is running */
  function _serializeState(){
    var params = new URLSearchParams();
    var activeTab = document.querySelector('.tab.on');
    if (activeTab && activeTab.dataset.k) params.set('tab', activeTab.dataset.k);
    var panel = _activePanel();
    if (panel){
      var inp = panel.querySelector('.filter input');
      if (inp && inp.value) params.set('q', inp.value);
      var facets = {};
      panel.querySelectorAll('.facet input:checked').forEach(function(cb){
        var f = cb.dataset.f;
        (facets[f] = facets[f] || []).push(cb.value);
      });
      for (var f in facets) params.set('f_' + f, facets[f].join(','));
    }
    if (document.body.classList.contains('am-reviewer')) params.set('am', '1');
    /* Home-tab search state (2026-07-26). Preserved across facet toggles so
       a bookmark of the URL captures both goal-directed search + browse
       state; the Home-search JS also fires _writeHash() on its own inputs. */
    try {
      var hsq = document.getElementById('hs-q');
      var hst = document.getElementById('hs-topic');
      var hsg = document.getElementById('hs-geo');
      if (hsq && hsq.value) params.set('search', hsq.value);
      if (hst && hst.value) params.set('topic', hst.value);
      if (hsg && hsg.value) params.set('geo', hsg.value);
    } catch(_) { /* Home-search may not be rendered - no-op */ }
    return params.toString();
  }
  function _writeHash(){
    if (_restoringHash) return;
    try {
      var s = _serializeState();
      var newHash = s ? ('#' + s) : '';
      if ((location.hash || '') !== newHash){
        history.replaceState(null, '',
          location.pathname + location.search + newHash);
      }
    } catch(_) { /* history API disabled - no-op */ }
  }
  function _restoreFromHash(){
    var hash = location.hash || '';
    if (hash.length < 2) return false;
    _restoringHash = true;
    try {
      var params = new URLSearchParams(hash.slice(1));
      /* AM toggle: hash overrides localStorage. Only touched if 'am' present. */
      if (params.has('am')){
        var amOn = params.get('am') === '1';
        document.body.classList.toggle('am-reviewer', amOn);
        document.querySelectorAll('.panel').forEach(function(p){
          if (p.querySelector('.am-cb')) p.classList.toggle('am-reviewer', amOn);
        });
        document.querySelectorAll('.am-cb').forEach(function(cb){
          cb.checked = amOn;
        });
      }
      /* Tab: switch to the specified panel BEFORE reading filters. */
      var t = params.get('tab');
      if (t){
        var tab = document.querySelector('.tab[data-k="' + CSS.escape(t) + '"]');
        if (tab && !tab.classList.contains('on')) tab.click();
      }
      /* Home-tab search inputs (2026-07-26). Restore search / topic / geo
         from the hash and dispatch input+change events so the Home-search
         JS re-renders the ranked results without a page reload. */
      var hsq = document.getElementById('hs-q');
      var hst = document.getElementById('hs-topic');
      var hsg = document.getElementById('hs-geo');
      if (hsq && params.has('search')){
        hsq.value = params.get('search') || '';
        hsq.dispatchEvent(new Event('input', {bubbles: true}));
      }
      if (hst && params.has('topic')){
        hst.value = params.get('topic') || '';
        hst.dispatchEvent(new Event('change', {bubbles: true}));
      }
      if (hsg && params.has('geo')){
        hsg.value = params.get('geo') || '';
        hsg.dispatchEvent(new Event('change', {bubbles: true}));
      }
      var panel = _activePanel();
      if (panel){
        if (params.has('q')){
          var inp = panel.querySelector('.filter input');
          if (inp){ inp.value = params.get('q') || ''; }
        }
        /* Facets: clear any pre-checked defaults, then apply hash's picks. */
        var anyFacetKey = false;
        params.forEach(function(v, k){ if (k.indexOf('f_') === 0) anyFacetKey = true; });
        if (anyFacetKey){
          panel.querySelectorAll('.facet input:checked').forEach(function(cb){
            cb.checked = false;
          });
        }
        params.forEach(function(val, key){
          if (key.indexOf('f_') !== 0) return;
          var f = key.slice(2);
          (val || '').split(',').forEach(function(v){
            if (!v) return;
            var cb = panel.querySelector(
              '.facet[data-f="' + CSS.escape(f) + '"] input[value="' + CSS.escape(v) + '"]');
            if (cb) cb.checked = true;
          });
        });
        if (typeof _applyFacets === 'function') _applyFacets(panel);
      }
    } catch(_) { /* malformed hash - fall through to defaults */ }
    _restoringHash = false;
    return true;
  }
  /* Wire state-writes to every input the reader can change. Uses event
     delegation so cards / facets added later would still fire (though the
     tool renders everything server-side, so all listeners exist at load). */
  document.addEventListener('change', function(e){
    var t = e.target;
    if (!t) return;
    if (t.matches && (t.matches('.facet input') || t.matches('.am-cb'))){
      _writeHash();
    }
    /* Home-search topic + geo dropdowns (2026-07-26). */
    if (t.id === 'hs-topic' || t.id === 'hs-geo') _writeHash();
  });
  document.addEventListener('input', function(e){
    var t = e.target;
    if (t && t.matches && t.matches('.filter input')) _writeHash();
    /* Home-search text input (2026-07-26). */
    if (t && t.id === 'hs-q') _writeHash();
  });
  document.addEventListener('click', function(e){
    var t = e.target;
    if (t && t.closest && t.closest('.tab')){
      /* Defer so the tab-click handler above runs first, flipping .panel.on. */
      setTimeout(_writeHash, 0);
    }
    if (t && t.closest && t.closest('.facet-clear')){
      setTimeout(_writeHash, 0);
    }
  });
  /* Kick off restore on load: hash wins over localStorage for any key it
     specifies. Runs AFTER the existing AM-reviewer restore block so any
     'am' key in the hash properly overrides. */
  _restoreFromHash();
  /* Also react to manual hash edits (back/forward button, or user typing
     into the address bar). */
  window.addEventListener('hashchange', function(){ _restoreFromHash(); });
})();
/* --- Phase A ceiling-push #2: sidebar "/" hint injection -------------
   Added at load time so a JS-disabled reader isn't shown a hint about a
   shortcut that wouldn't work. Sits directly below the filter input on
   every products panel. */
(function(){
  document.querySelectorAll('.filter').forEach(function(f){
    if (f.querySelector('.filter-kbd-hint')) return;
    var hint = document.createElement('span');
    hint.className = 'filter-kbd-hint';
    hint.setAttribute('title', 'Press / anywhere on the page to focus this filter');
    hint.innerHTML = 'Press <kbd>/</kbd> to focus &middot; <kbd>j</kbd>/<kbd>k</kbd> to move between cards &middot; <kbd>Enter</kbd> to open';
    f.appendChild(hint);
  });
})();
/* -------------------------------------------------------------------------
   UX pass 2026-07-26 commit #6 - Guided tour mode.
   Walks a first-time reader through Home in 7 stops (~15s each). Overlay
   dims the page except for a halo around the current step's target; the
   floating callout box carries the copy + next/back/skip controls.
   State: localStorage 'product_scope:tour_seen' remembers completion so the
   launcher hides itself after one full pass (the small "?" re-entry stays).
   No new deps: pure vanilla JS + the fixed-position DOM added above.
   -------------------------------------------------------------------------- */
(function(){
  var TOUR_SEEN_KEY = 'product_scope:tour_seen';
  // Six tour stops in page order. Each: {sel, title, body}. sel is a CSS
  // selector; the FIRST match on the page is highlighted. Home-panel
  // selectors are guaranteed present (the tour runs on Home).
  var STOPS = [
    {sel: '#starthere',
     title: "Start here",
     body:  "This small banner is the shortest way in - three bullets that "
          + "tell you what to do next. Dismiss it when you know your way "
          + "around."},
    {sel: '.home-search',
     title: "Find a product",
     body:  "Already have a question - housing, income, trade? Search the "
          + "full catalog by keyword, topic, or geography level and jump "
          + "straight to the matching product card."},
    {sel: '.curriculum-section',
     title: "5-product curriculum",
     body:  "If you'd rather explore in the tool, walk these five products "
          + "top to bottom. Each one illustrates a single uncertainty "
          + "mechanism with real Census data."},
    {sel: '.wti-section',
     title: "Where the team is",
     body:  "The flow diagram shows how far we are on the research pipeline - "
          + "how many of the 573 products we've probed, sampled, and reviewed. "
          + "Ribbon width is the count that carried forward at each stage."},
    {sel: '.lscape-section',
     title: "The Census data landscape",
     body:  "All 573 product families laid out by type and program. Box size "
          + "is proportional to product count. Click any box to drill into "
          + "that program's cards."},
    {sel: '.wwl-section',
     title: "What we've learned",
     body:  "One feed for every insight the team has recorded: curated head-"
          + "lines, WORKLOG findings, per-product notes, auto-generated "
          + "signals when data drifts. You're ready - open the first "
          + "curriculum product from step 3 and start exploring."}
  ];
  var idx = 0;
  var overlay = document.getElementById('tour-overlay');
  var dims = overlay ? overlay.querySelectorAll('.tour-dim') : null;
  var halo = overlay ? overlay.querySelector('.tour-halo') : null;
  var callout = overlay ? overlay.querySelector('.tour-callout') : null;
  var launch = document.getElementById('tour-launch');
  var relaunch = document.getElementById('tour-relaunch');
  var titleEl = document.getElementById('tour-title');
  var bodyEl = document.getElementById('tour-body');
  var idxEl = document.getElementById('tour-step-idx');
  var prevBtn = document.getElementById('tour-prev');
  var nextBtn = document.getElementById('tour-next');
  var skipBtn = document.getElementById('tour-skip');
  if (!overlay || !launch || !callout || !titleEl) return; /* defensive */

  function _seenAlready(){
    try { return window.localStorage &&
           window.localStorage.getItem(TOUR_SEEN_KEY) === '1'; }
    catch(_){ return false; }
  }
  function _markSeen(){
    try { window.localStorage &&
          window.localStorage.setItem(TOUR_SEEN_KEY, '1'); }
    catch(_){}
    launch.classList.add('hidden');
    relaunch.classList.add('visible');
  }
  if (_seenAlready()){
    launch.classList.add('hidden');
    relaunch.classList.add('visible');
  }
  function _rectOf(sel){
    var el = document.querySelector(sel);
    if (!el) return null;
    /* Ensure element is in view before measuring. Scroll with instant
       behavior so we don't race the transition. */
    var r = el.getBoundingClientRect();
    if (r.top < 60 || r.bottom > window.innerHeight - 40){
      var y = r.top + window.pageYOffset - 100;
      window.scrollTo({top: y, behavior: 'smooth'});
    }
    return el.getBoundingClientRect();
  }
  function _place(rect){
    /* Position the four dim panels so their combined absence is a hole
       around the target rect. */
    var W = window.innerWidth, H = window.innerHeight;
    var pad = 8;
    var rTop = Math.max(0, rect.top - pad);
    var rLeft = Math.max(0, rect.left - pad);
    var rBottom = Math.min(H, rect.bottom + pad);
    var rRight = Math.min(W, rect.right + pad);
    /* top dim */
    dims[0].style.top = 0; dims[0].style.left = 0;
    dims[0].style.width = W + 'px'; dims[0].style.height = rTop + 'px';
    /* right dim */
    dims[1].style.top = rTop + 'px'; dims[1].style.left = rRight + 'px';
    dims[1].style.width = Math.max(0, W - rRight) + 'px';
    dims[1].style.height = Math.max(0, rBottom - rTop) + 'px';
    /* bottom dim */
    dims[2].style.top = rBottom + 'px'; dims[2].style.left = 0;
    dims[2].style.width = W + 'px'; dims[2].style.height = Math.max(0, H - rBottom) + 'px';
    /* left dim */
    dims[3].style.top = rTop + 'px'; dims[3].style.left = 0;
    dims[3].style.width = rLeft + 'px';
    dims[3].style.height = Math.max(0, rBottom - rTop) + 'px';
    /* halo around the target */
    halo.style.top = rTop + 'px'; halo.style.left = rLeft + 'px';
    halo.style.width = Math.max(0, rRight - rLeft) + 'px';
    halo.style.height = Math.max(0, rBottom - rTop) + 'px';
    /* callout: prefer below the target; if that overflows, above it. */
    var cw = 296, ch = callout.offsetHeight || 180;
    var cLeft = Math.min(W - cw - 12, Math.max(12, rect.left + rect.width/2 - cw/2));
    var cTop = rBottom + 14;
    if (cTop + ch > H - 12){
      cTop = Math.max(12, rTop - ch - 14);
    }
    callout.style.left = cLeft + 'px';
    callout.style.top = cTop + 'px';
  }
  function _show(i){
    if (i < 0) i = 0;
    if (i >= STOPS.length){ _end(); return; }
    idx = i;
    var stop = STOPS[idx];
    /* If the current stop's target is missing entirely, skip it forward. */
    if (!document.querySelector(stop.sel)){
      if (idx === STOPS.length - 1) return _end();
      return _show(idx + 1);
    }
    titleEl.textContent = stop.title;
    bodyEl.textContent = stop.body;
    idxEl.textContent = (idx + 1) + ' / ' + STOPS.length;
    prevBtn.disabled = (idx === 0);
    nextBtn.textContent = (idx === STOPS.length - 1) ? 'Finish' : 'Next →';
    /* Measure AFTER text swap so callout height is correct. */
    var rect = _rectOf(stop.sel);
    if (!rect) return _end();
    _place(rect);
  }
  function _start(){
    document.body.classList.add('tour-running');
    overlay.hidden = false;
    /* Home tab must be active - the stops are Home-only. */
    var homeTab = document.querySelector('.tab[data-k="home"]');
    if (homeTab && !homeTab.classList.contains('on')) homeTab.click();
    idx = 0;
    /* Give the layout one frame to settle after the tab click, then show. */
    setTimeout(function(){ _show(0); }, 20);
    nextBtn.focus();
  }
  function _end(){
    document.body.classList.remove('tour-running');
    overlay.hidden = true;
    _markSeen();
    launch.blur();
  }
  launch.addEventListener('click', _start);
  relaunch.addEventListener('click', _start);
  nextBtn.addEventListener('click', function(){ _show(idx + 1); });
  prevBtn.addEventListener('click', function(){ _show(idx - 1); });
  skipBtn.addEventListener('click', _end);
  /* Keyboard nav while the tour is running. */
  document.addEventListener('keydown', function(e){
    if (overlay.hidden) return;
    if (e.key === 'Escape'){ e.preventDefault(); _end(); }
    else if (e.key === 'ArrowRight' || e.key === 'Enter'){ e.preventDefault(); _show(idx + 1); }
    else if (e.key === 'ArrowLeft'){ e.preventDefault(); _show(idx - 1); }
  });
  /* Reflow on resize so the halo tracks the target. */
  window.addEventListener('resize', function(){
    if (!overlay.hidden){
      var r = _rectOf(STOPS[idx].sel);
      if (r) _place(r);
    }
  });
})();
</script>
<footer>product_scope.py &bull; re-run before each biweekly &bull; --online refreshes the catalog &bull;
tabs come from the catalog's own dataset flags; subjects are matched from product titles (SUBJECTS in this file, editable) &bull; stages and uncertainty notes are written only
by the team in product_review.json &bull; work depth and work-log findings are read from the repo.</footer>
</body></html>"""

def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ---- Beginner-UX pass commit #2: inline glossary tooltip helpers ------------
# Small `?` badge decorators for the first visible occurrence of terms a
# non-technical reader wouldn't know. Tracked by a per-render set so we don't
# sprinkle 500 tooltips on the same page - render() clears the set at the top
# of every regen. The tooltip content is a plain-English one-liner; CSS handles
# hover via .gloss::after (see the stylesheet above).
GLOSSARY = {
    "probe":              "Fetch the list of variables and geographies this "
                          "product publishes from the Census API. Doesn't "
                          "download any actual data - just describes what's "
                          "in the product.",
    "sample":             "Peek at actual data rows (default 100) and run a "
                          "quick summary - column types, missing values, top "
                          "values.",
    "cataloged":          "Listed in the Census catalog but the team hasn't "
                          "looked at it yet.",
    "actively managed":   "Products the team has flagged as focus areas "
                          "(currently 5).",
    "vintages":           "Years or time periods this product covers.",
    "kind":               "Type of dataset - aggregate tables, microdata "
                          "(individual records), time series, or "
                          "uncategorized.",
    # UX pass 2026-07-26 commit #2: research pipeline vocabulary. Named-tier
    # rail replaces the old coverage bars; readers see the noun for the first
    # time in that rail's caption and each pipeline label.
    "research pipeline":  "How a product moves from a catalog listing to a "
                          "fully reviewed reliability note: "
                          "cataloged -> probed -> sampled -> reviewed. "
                          "Each stage adds evidence.",
    "reviewed":           "The team has recorded uncertainty notes for this "
                          "product (its uncertainty_metrics field is filled "
                          "in). The deliverable of the research pipeline.",
    # Phase A 2026-07-26 commit #3: uncertainty-methodology vocabulary that
    # shows up in body copy across Home + card drill-downs. Auto-decorated
    # on first occurrence via `_gloss_body()` at render time so the team
    # doesn't have to remember to call gloss() manually every time a term
    # appears in a description. Definitions kept short (~1 sentence) so the
    # tooltip fits on a line without wrapping oddly.
    "moe":                "Margin of error: the range around a Census "
                          "estimate; smaller is more reliable.",
    "cv":                 "Coefficient of variation: MOE as a fraction of "
                          "the estimate; CV > 30% flags low reliability.",
    "dp":                 "Differential privacy: method the Bureau uses to "
                          "protect confidentiality by adding calibrated "
                          "noise to counts.",
    "differential privacy": "Method the Bureau uses to protect "
                          "confidentiality by adding calibrated noise to "
                          "counts. Fixed cost per geography, so small "
                          "places take a bigger relative hit than large ones.",
    "pums":               "Public Use Microdata Sample: individual "
                          "anonymized responses instead of aggregated "
                          "tables. Enables custom cross-tabs the pre-made "
                          "aggregate tables don't cover.",
    "allocation":         "When a respondent left a value blank, the "
                          "Bureau fills it in from statistical models; "
                          "the allocation rate measures how often.",
    "swapping":           "Confidentiality method the Bureau used before "
                          "differential privacy; swaps records between "
                          "similar geographies to prevent re-identification.",
    "imputation":         "Filling in missing values with statistical "
                          "estimates - a form of educated-guess fill-in "
                          "the Bureau does before publishing.",
    "variance replicate": "Set of ~80 alternate weightings the Bureau "
                          "provides so users can compute uncertainty "
                          "around ACS estimates without inside knowledge "
                          "of the survey design.",
}
_GLOSS_SEEN = set()

# Regex used by `_gloss_body()` for auto-tooltip on jargon. Multi-word terms
# match first so 'differential privacy' beats 'dp' when both would apply.
# Ordered by descending length so specific-first matching Just Works.
_GLOSS_BODY_TERMS = sorted(
    ["MOE", "CV", "differential privacy", "DP", "PUMS", "allocation",
     "swapping", "imputation", "variance replicate"],
    key=lambda t: -len(t))

def _gloss_reset():
    """Clear the per-render 'already decorated' set. Called at the top of
    render() so every regen gets a fresh first-occurrence assignment."""
    _GLOSS_SEEN.clear()

def gloss(term):
    """Return an HTML `?` tooltip for `term` on its first occurrence in the
    render, else "". Term lookup is case-insensitive against GLOSSARY."""
    key = (term or "").strip().lower()
    if key not in GLOSSARY: return ""
    if key in _GLOSS_SEEN: return ""
    _GLOSS_SEEN.add(key)
    tip = GLOSSARY[key]
    return (f' <span class="gloss" tabindex="0" role="button" '
            f'aria-label="Glossary: {_esc(term)}" '
            f'data-tip="{_esc(tip)}" title="{_esc(tip)}">?</span>')

# --- Phase A 2026-07-26 commit #3: auto-tooltip on jargon in body copy ------
# The manual `gloss("term")` calls are still the right pattern for a specific
# jargon-adjacent header word (e.g. "kind" in a facet label). But most body
# copy - card descriptions, hero blurbs, drill-down explanations - is written
# in plain sentences with terms like "MOE" or "differential privacy"
# scattered through. Asking every rendering function to remember to sprinkle
# `gloss()` around each such term is fragile.
#
# `_gloss_body(html)` walks a rendered HTML string, decorates the FIRST
# occurrence of each glossary term (from the compact list _GLOSS_BODY_TERMS),
# and leaves later occurrences alone. Sharing the `_GLOSS_SEEN` set with
# gloss() means a term auto-tooltipped in body copy won't get re-tooltipped
# in a header the manual gloss() call also produces.
#
# Rules:
#   * TEXT NODES ONLY. HTML tags, attribute values, and existing .gloss
#     spans are skipped by splitting on <...> and processing only text
#     between tags.
#   * <script>, <style>, and <pre>/<code> blocks are skipped in full - we
#     don't want to tooltip inside a shell command a user is meant to copy.
#   * Case-insensitive match, word-boundary anchored, so "moe" inside "smoe"
#     doesn't match. Uppercase acronyms (MOE, CV, DP, PUMS) require an
#     uppercase match to avoid false positives in ordinary sentences.
#   * First occurrence per glossary term GLOBALLY per render. Once a term
#     is tooltipped anywhere on the page, later occurrences pass through.

def _gloss_body(html):
    """Auto-tooltip the first occurrence of each glossary body term in
    `html`. Idempotent - safe to call on the same HTML twice; the second
    pass sees `_GLOSS_SEEN` already populated and no-ops."""
    if not html: return html
    # Split on <...> so tag pieces stay separate from text nodes. `re.split`
    # with a captured group keeps the tags in the result list.
    pieces = re.split(r"(<[^>]+>)", html)
    # Track skip zones - once we enter a <script>/<style>/<pre>/<code>,
    # skip text pieces until the matching close tag.
    SKIP_STACK_TAGS = {"script", "style", "pre", "code", "textarea"}
    skip_depth = 0
    out = []
    for p in pieces:
        if p.startswith("<") and p.endswith(">"):
            # Tag piece. Update skip-depth if we entered/left a skip zone.
            m = re.match(r"</?([a-zA-Z][a-zA-Z0-9]*)", p)
            if m:
                tag = m.group(1).lower()
                if tag in SKIP_STACK_TAGS:
                    if p.startswith("</"):
                        skip_depth = max(0, skip_depth - 1)
                    elif not p.endswith("/>"):
                        skip_depth += 1
            out.append(p)
            continue
        # Text piece. If we're inside a skip zone, pass through unchanged.
        if skip_depth > 0:
            out.append(p)
            continue
        out.append(_gloss_body_text(p))
    return "".join(out)

def _gloss_body_text(text):
    """Wrap the first occurrence of each glossary body term in `text`
    (a text node with no HTML tags). Case rules per _GLOSS_BODY_TERMS
    docstring above."""
    if not text or "<" in text:
        return text
    for term in _GLOSS_BODY_TERMS:
        key = term.lower()
        if key in _GLOSS_SEEN:
            continue
        # Uppercase-acronym terms (all caps in the term) require an exact
        # uppercase match to avoid false positives ('moe' as a name syllable
        # etc.). Multi-word / lowercase terms are matched case-insensitively.
        if term.isupper() and len(term) <= 5:
            pat = r"\b" + re.escape(term) + r"\b"
            flags = 0
        else:
            pat = r"\b" + re.escape(term) + r"\b"
            flags = re.IGNORECASE
        m = re.search(pat, text, flags)
        if not m:
            continue
        # Consult GLOSSARY via the same key logic gloss() uses.
        tip = GLOSSARY.get(key) or ""
        if not tip:
            continue
        _GLOSS_SEEN.add(key)
        matched = m.group(0)
        wrapped = (
            f'<span class="gloss-inline" tabindex="0" role="button" '
            f'aria-label="Glossary: {_esc(term)}" '
            f'data-tip="{_esc(tip)}" title="{_esc(tip)}">'
            f'{_esc(matched)}<sup class="gloss-mark">?</sup></span>')
        text = text[:m.start()] + wrapped + text[m.end():]
    return text

def _vint(f):
    v = f["vintages"]
    if len(v) > 1: return f"{v[0]}–{v[-1]}"
    return str(v[0]) if v else EMDASH

def _frequency_bucket(f):
    """Vintage-to-release-frequency heuristic. Coarse-grained by design - the
    catalog doesn't carry an explicit frequency field, so we infer:
       time-series flag -> 'time series'
       0-1 vintages     -> 'single vintage'
       spans >=10y with 1-2 vintages -> 'decennial'
       spans <=10y with >=3 vintages -> 'annual (or near-annual)'
       everything else  -> 'multi-year'
    Used for the sidebar Frequency facet. If this proves noisy we can tighten
    the thresholds; if it proves useless, drop the facet and move on.
    """
    if (f.get("flags") or {}).get("ts"):
        return "time series"
    v = sorted(f.get("vintages") or [])
    if len(v) <= 1: return "single vintage"
    span = v[-1] - v[0]
    n = len(v)
    if n >= max(3, int(span * 0.6)): return "annual"
    if span >= 10 and n <= 2:         return "decennial"
    return "multi-year"

# TODO(reframe #4): geography-level facet needs probe data to be trustworthy;
# the catalog's spatial field is usually just "United States". Once probes
# cover more of the catalog, add a "geo_level" derived from probe["levels"]
# to the facet_values dict + FACET_DEFS list. Skipping for now instead of
# fabricating from repo-inferred keyword grepping (which would be misleading).

def product_facet_values(f, review, work, probes, top_families, data_cache=None):
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
        "freq":      _frequency_bucket(f),
        "evidence":  "yes" if ws > 0 else "no",
        "probe":     "yes" if probes.get(f["path"], {}).get("ok") else "no",
        "validated": "yes" if ws >= 4 else "no",
        "role":      role or "(unset)",
    }

# FACET_DEFS entries: (key, label, sortmode, group).
# group='primary'   -> discovery-oriented facets, always visible.
# group='reviewer'  -> review-workflow facets, collapsed behind a details toggle
#                      at the bottom of the sidebar (reframe pass commit #4).
# Phase A #2 (2026-07-26): the "Composite role" facet was removed alongside
# the --role/--note/--author CLI flags. Composite framing is on hold; the
# schema field still exists so the 5 pre-existing FOCUS entries preserve
# their roles on read, but the facet, CLI setters, and role-required-note
# TTY prompt are all gone.
FACET_DEFS = [
    ("fbucket",   "Family",              "count",  "primary"),
    ("agency",    "Agency",              "count",  "primary"),
    ("freq",      "Frequency",           None,     "primary"),
    ("stage",     "Status",              None,     "reviewer"),
    ("evidence",  "Has repo evidence",   None,     "reviewer"),
    # Beginner-UX pass commit #3: rename visible facet label to plain English
    # (was "Has API probe" - jargon; the facet key `probe` stays for
    # backward compat with URL hash state, data-* attributes, and JS).
    ("probe",     "Metadata fetched",    None,     "reviewer"),
    ("validated", "Notebook validated",  None,     "reviewer"),
]
FACET_ORDER = {
    "stage":     ["focus", "candidate", "reviewed", "cataloged", "set-aside"],
    "freq":      ["annual", "decennial", "multi-year",
                  "single vintage", "time series"],
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

def build_diff_banner(diff, eda_diffs=None):
    """Home-tab 'Since last regeneration' banner. Baseline mode on first run.

    eda_diffs: {path: [change_string, ...]} from the last --sample --refresh
    run (Phase 3 #6). Rendered as extra bullets on the same banner so the
    reader sees data drift alongside repo drift in one place.
    """
    if diff.get("is_baseline"):
        base = ('<div class="diff-banner baseline">'
                '<b>Baseline snapshot recorded.</b> Diff will appear on the next regeneration.'
                '</div>')
        if not eda_diffs:
            return base
        # Even on the baseline run we surface EDA diffs if a --refresh
        # produced any (they exist independently of the snapshot mechanism).
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
    # Phase 3 #6 - fold EDA drift into the same banner headline. Kept short:
    # per-product change strings appear in the details list below.
    if eda_diffs:
        n_prods = len(eda_diffs)
        n_changes = sum(len(v) for v in eda_diffs.values())
        parts.append(f"<b>EDA changes on {n_prods} sampled product"
                     + ("s" if n_prods != 1 else "")
                     + f"</b> ({n_changes} change" + ("s" if n_changes != 1 else "") + ")")
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
    # Fold per-product EDA changes into the same details list so all drift
    # (repo + data) is in one place.
    if eda_diffs:
        for path in sorted(eda_diffs):
            for ch in eda_diffs[path]:
                # `ch` already contains backtick-formatted column names from diff_eda;
                # escape for safety but preserve the text.
                detail_rows.append(f'<li><code>{_esc(path)}</code> EDA — {_esc(ch)}</li>')
    details = ""
    if detail_rows:
        details = ('<details class="disc"><summary>Show '
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

def _affordances(f, r, ws, has_probe, git, snapshot, has_eda=False):
    """Return a list of {"tone", "text", "cmd"} banners for one product card.

    Rules (documented in the redesign spec + Phase 3):
      1. No repo evidence                           -> probe command
      2. Candidate without a probe                  -> amber probe command
      3. Candidate without a cached EDA sample      -> amber sample command
      4. FOCUS + snapshot's captured SHA != current HEAD -> regen command
      5. Still cataloged                            -> nudge to edit product_review.json
    """
    path = f["path"]
    stage = r.get("stage", "cataloged")
    out = []
    probe_cmd  = f'python tools/product_scope.py --probe {path}'
    sample_cmd = f'python tools/product_scope.py --sample {path}'
    regen_cmd  = 'python tools/product_scope.py'
    if ws == 0:
        out.append({"tone": "info",
                    "text": "Ask the Census API what's in this product — copy and "
                            "paste into your terminal (open PowerShell in the repo folder first):",
                    "cmd":  probe_cmd})
    if stage == "candidate" and not has_probe:
        out.append({"tone": "amber",
                    "text": "Candidate without a probe. Ask the Census API what's in "
                            "this product — copy and paste into your terminal "
                            "(open PowerShell in the repo folder first):",
                    "cmd":  probe_cmd})
    if stage == "candidate" and not has_eda:
        # Phase 3 #8: candidates need actual data, not just a probe. This is
        # deliberately its own affordance rather than a suffix on the probe
        # one: probing and sampling are separate steps a reviewer takes in
        # order (probe first to understand the shape, sample second to see it).
        out.append({"tone": "amber",
                    "text": "Candidate without a cached EDA sample. Fetch actual "
                            "rows and run canonical EDA:",
                    "cmd":  sample_cmd})
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
        # Beginner-UX pass commit #3: rename "Still cataloged" -> plain
        # English "Team hasn't looked at this product yet".
        out.append({"tone": "nudge",
                    "text": f'Team hasn\'t looked at this product yet. Set a '
                            f'Status by editing product_review.json at key "{path}".',
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

def _eda_header_html(cache_entry):
    """Header line for Quick Look tier 2: freshness pill, shape, source SHA + URL.
    (Formerly shared with the standalone EDA snapshot branch; that branch was
    removed in Phase 4b because it duplicated Quick Look tier 2 verbatim.)"""
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
    return '<div class="eda-head">' + "".join(head_bits) + '</div>'

def _eda_body_html(cache_entry, diff_note=None):
    """Inner EDA tables (columns / numerics / categoricals / geography /
    sparklines) plus optional refresh-diff banner. Returns just the tables
    HTML, no branch/bcard wrapper, no header - now used exclusively by Quick
    Look tier 2 (the standalone EDA snapshot section was removed in Phase 4b,
    and the same helper feeds the More-details drill-down)."""
    if not cache_entry:
        return ""
    parts = []
    if diff_note:
        # Accept either a single string or a list of change strings (Phase 3 #6).
        if isinstance(diff_note, (list, tuple)):
            txt = "; ".join(str(x) for x in diff_note)
        else:
            txt = str(diff_note)
        parts.append(f'<div class="eda-diff"><b>EDA changed on rerun:</b> '
                     f'{_esc(txt)}</div>')

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

    return "".join(parts)

# NOTE: render_eda_card_section() was removed in Phase 4b. Its body was a thin
# wrapper around _eda_header_html() + _eda_body_html(), both of which now live
# inside the Quick Look Tier 2 renderer below. Deleting it here keeps a card
# from showing the same EDA tables twice; the shared helpers survive because
# Quick Look still calls them.

# ============================================================================
# QUICK LOOK (Phase 4 #1)
# ============================================================================
# A persistent summary section at the top of every product card that renders
# the HIGHEST tier of data currently cached. Chip tells the reader at a glance
# which tier they're seeing:
#   Tier 0 (catalog metadata)        - grey    "Cached: catalog"
#   Tier 1 (probe results)           - blue    "Cached: probe"
#   Tier 2 (sample + EDA)            - green   "Cached: sample"
#
# Non-API products (no variables_url in the catalog) never advance past Tier 0
# and render a "not sample-able via API" note where the run-a-probe hint would
# otherwise sit.

def _quick_look_tier(f, probe_entry, cache_entry):
    """Highest tier currently cached for one product. Returns (tier, label,
    class) where class matches the CSS chip variants defined in TEMPLATE.
    Beginner-UX pass commit #3: chip labels renamed from jargon (catalog /
    probe / sample) to plain English (listed / metadata fetched / data
    peeked)."""
    if cache_entry:
        return (2, "Cached: data peek", "tier-sample")
    if probe_entry and probe_entry.get("ok"):
        return (1, "Cached: metadata", "tier-probe")
    return (0, "Cached: listing only", "tier-catalog")

def _ql_what_it_is(f):
    """Line 1 of the reframed TL;DR: 'what it is'. Compact one-liner of
    family, kind, and vintages. Zero API cost - everything comes from the
    catalog record. Replaces the pre-reframe tier-chip-and-desc header as
    the visual anchor for a newcomer's first glance ('this product IS X').

    Post-reframe cut (Phase A #1, 2026-07-26): agency chip removed because
    every one of the 573 catalog entries is 'U.S. Census Bureau' - the chip
    was 573x pure noise. The agency stays in the catalog record and is still
    read via `f["agency"]` where needed; the drill-down / export both still
    surface it when they carry other agency-adjacent context."""
    bits = []
    fam = f.get("group") or ""
    if fam:
        bits.append(f'<span class="ql-k">Family</span> {_esc(fam)}')
    kind = f.get("kind") or ""
    if kind:
        # Beginner-UX pass commit #2: `?` glossary tooltip on first appearance
        # of the term. gloss() is a no-op after first call per render.
        # Beginner-UX pass commit #3: rename visible label "Kind" -> "Dataset
        # type"; the internal `kind` key on the fam dict is unchanged.
        bits.append(f'<span class="ql-k">Dataset type{gloss("kind")}</span> {_esc(kind)}')
    v = f.get("vintages") or []
    if v:
        # Beginner-UX pass commit #3: rename visible label "Vintages" ->
        # "Years published"; the fam dict field name is unchanged.
        bits.append(f'<span class="ql-k">Years published{gloss("vintages")}</span> {_esc(_vint(f))}')
    spatial = sorted(f.get("spatial") or [])
    if spatial:
        # First entry is enough - the catalog usually lists one spatial coverage
        # per product (e.g., "United States"). Any list-y case is exposed in
        # the More-details block.
        bits.append(f'<span class="ql-k">Spatial</span> {_esc(spatial[0])}')
    return ' <span class="ql-sep">&middot;</span> '.join(bits)

def _ql_what_is_inside(f, probe_entry, cache_entry):
    """Line 2 of the reframed TL;DR: 'what's inside'. Answers 'what would I
    find if I opened this product?'. Composition depends on how far the team
    has reached into the product:
      * Always: geography link (verified levels if probed; otherwise a
        placeholder saying we haven't probed yet).
      * If probed: variable + MOE + allocation counts.
      * If sampled: rows x cols shape + missingness flag + top numeric range.
    Falls back gracefully - a non-API product with no probe just says so.
    """
    bits = []
    # Geography: sample counts > declared probe levels > 'not probed' fallback.
    geo = (cache_entry or {}).get("geography") or {}
    if geo:
        entries = sorted(geo.items(),
                         key=lambda kv: -int(kv[1].get("distinct_populated", 0)))
        show = entries[:4]
        parts = [f'{int(v.get("distinct_populated", 0)):,} {_esc(k)}'
                 for k, v in show]
        suffix = " ..." if len(entries) > len(show) else ""
        bits.append('<span class="ql-k">Populated geographies</span> '
                    + ", ".join(parts) + suffix)
    elif probe_entry and probe_entry.get("ok"):
        levels = probe_entry.get("levels") or []
        if levels:
            preview = ", ".join(_esc(x) for x in levels[:6])
            if len(levels) > 6: preview += " ..."
            bits.append(f'<span class="ql-k">Geography levels</span> {preview}')
    elif f.get("variables_url"):
        # We know an API endpoint exists but nobody has fetched metadata yet.
        # Beginner-UX pass commit #3: rename "not yet probed" -> plain English.
        bits.append('<span class="ql-k">Geography</span> '
                    '<span class="ql-muted">metadata not yet fetched</span>')
    else:
        # Non-API product - no way to enumerate levels without a download.
        bits.append('<span class="ql-k">Geography</span> '
                    '<span class="ql-muted">bulk-download product</span>')
    # Probe counts, if we have them.
    if probe_entry and probe_entry.get("ok"):
        if probe_entry.get("variables") is not None:
            bits.append(f'{int(probe_entry["variables"]):,} variables')
        if probe_entry.get("moe_variables"):
            bits.append(f'{int(probe_entry["moe_variables"]):,} MOE vars')
        if probe_entry.get("allocation_group_count"):
            bits.append(f'{int(probe_entry["allocation_group_count"])} alloc groups')
    # Sample shape.
    if cache_entry:
        shape = cache_entry.get("shape") or [0, 0]
        rows = int(shape[0]) if shape else 0
        cols = int(shape[1]) if shape else 0
        bits.append(f'sample: {rows:,} rows &times; {cols:,} cols')
        cols_dict = cache_entry.get("columns", {}) or {}
        over30 = sum(1 for c in cols_dict.values() if c.get("flag_missing_over_30"))
        if over30:
            bits.append(f'{over30} col{"s" if over30 != 1 else ""} &gt; 30% missing')
        top_name, top_num = _ql_top_numeric_col(cache_entry)
        if top_name and top_num:
            bits.append(f'<span class="ql-k">{_esc(top_name)}</span> '
                        f'{_fmt_num(top_num.get("min"))} &ndash; '
                        f'{_fmt_num(top_num.get("max"))}')
    return ' <span class="ql-sep">&middot;</span> '.join(bits)

def _ql_description_line(f):
    """Line 3 of the reframed TL;DR: catalog `description` truncated to fit on
    one visual line. Many products have a Bureau-written description that
    reads well as a one-liner; it was buried in the More-details drill-down
    before the reframe. Returns '' when the catalog carries no description."""
    desc = (f.get("desc") or "").strip()
    if not desc: return ""
    # Truncate at word boundary near 220 chars for one-line readability.
    if len(desc) > 220:
        cut = desc[:217]
        sp = cut.rfind(" ")
        if sp > 160: cut = cut[:sp]
        desc = cut.rstrip(".,;: ") + "..."
    return _esc(desc)

# Kept as a stable back-compat alias - the pre-reframe callers (and any external
# probe of the module) still see _ql_tier0_line. Semantically identical to the
# renamed helper above (still catalog-only, one compact line).
_ql_tier0_line = _ql_what_it_is

def _ql_tier1_line(probe_entry, cache_entry):
    """Tier-1 TL;DR line: probed metadata condensed to one glance.

    If a sample is ALSO cached (tier 2), geography swings from 'declared
    levels' to 'populated counts' - same axis, more informative number.
    Returns "" if the probe didn't succeed (renderer skips the line)."""
    if not (probe_entry and probe_entry.get("ok")):
        return ""
    bits = []
    if probe_entry.get("moe_variables") is not None:
        bits.append(f'{int(probe_entry["moe_variables"]):,} MOE variables')
    if probe_entry.get("allocation_group_count") is not None:
        bits.append(f'{int(probe_entry["allocation_group_count"])} allocation groups')

    # Geography: prefer populated counts from the sample cache when available,
    # otherwise fall back to the flat list of declared level names. Populated
    # counts are strictly more informative (they answer "how many rows per
    # level did we actually see?"), so upgrade whenever the sample exists.
    geo = (cache_entry or {}).get("geography") or {}
    if geo:
        # Sort geographies by populated count descending; cap at 4 to keep
        # the line scannable. The full breakdown lives in the drill-down.
        entries = sorted(geo.items(),
                         key=lambda kv: -int(kv[1].get("distinct_populated", 0)))
        show = entries[:4]
        parts = [f'{int(v.get("distinct_populated", 0)):,} {_esc(k)}'
                 for k, v in show]
        suffix = " ..." if len(entries) > len(show) else ""
        bits.append("Populated geographies: " + ", ".join(parts) + suffix)
    else:
        levels = probe_entry.get("levels") or []
        if levels:
            preview = ", ".join(_esc(x) for x in levels[:6])
            if len(levels) > 6:
                preview += " ..."
            bits.append("Declared levels: " + preview)
    return ' <span class="ql-sep">&middot;</span> '.join(bits)

def _ql_top_numeric_col(cache_entry):
    """Return (name, numeric_dict) of the 'headline' numeric column for the
    Tier-2 TL;DR line, or (None, None) if no numeric column is present.

    Ranking - reuse what the EDA already computes cheaply:
      1. First entry in `sparklines` (already ranked by looks-like-estimate
         then descending variance in compute_eda; see _rank_numeric_for_spark).
      2. Fallback: first column with a `numeric` block.
    """
    cols = (cache_entry or {}).get("columns", {}) or {}
    sparks = (cache_entry or {}).get("sparklines", {}) or {}
    for name in sparks:
        num = (cols.get(name) or {}).get("numeric")
        if num:
            return name, num
    for name, meta in cols.items():
        num = meta.get("numeric")
        if num:
            return name, num
    return None, None

def _ql_tier2_line(cache_entry):
    """Tier-2 TL;DR line: sample shape + missingness flag + one headline
    numeric column's range. One glance, no tables. Full EDA lives in the
    drill-down. Returns "" if no sample is cached."""
    if not cache_entry:
        return ""
    shape = cache_entry.get("shape") or [0, 0]
    rows, cols = int(shape[0]), int(shape[1])
    bits = [f'{rows:,} rows &times; {cols:,} cols']
    cols_dict = cache_entry.get("columns", {}) or {}
    over30 = sum(1 for c in cols_dict.values() if c.get("flag_missing_over_30"))
    if over30:
        bits.append(f'{over30} col{"s" if over30 != 1 else ""} &gt; 30% missing')
    top_name, top_num = _ql_top_numeric_col(cache_entry)
    if top_name and top_num:
        bits.append(f'<span class="ql-k">{_esc(top_name)}</span> '
                    f'{_fmt_num(top_num.get("min"))} &ndash; '
                    f'{_fmt_num(top_num.get("max"))}')
    return ' <span class="ql-sep">&middot;</span> '.join(bits)

def _ql_probe_detail_html(probe_entry):
    """Drill-down for the Tier-1 (probed) portion of a card. Shows the full
    catalog description, the variables.json endpoint, and probe-level lists
    that were hidden from the TL;DR (allocation-group names + queryable-
    without-parent geographies). Returns "" when there's nothing to show."""
    if not (probe_entry and probe_entry.get("ok")):
        return ""
    parts = []
    v = probe_entry.get("variables")
    if v is not None:
        parts.append(f'<div class="ql-d-row"><span class="ql-k">Variables</span> '
                     f'{int(v):,}</div>')
    est = probe_entry.get("estimates")
    if est is not None:
        parts.append(f'<div class="ql-d-row"><span class="ql-k">Estimate variables</span> '
                     f'{int(est):,}</div>')
    ann = probe_entry.get("annotation_variables")
    if ann is not None:
        parts.append(f'<div class="ql-d-row"><span class="ql-k">Annotation variables</span> '
                     f'{int(ann):,}</div>')
    ag = probe_entry.get("allocation_groups") or []
    if ag:
        preview = ", ".join(_esc(x) for x in ag[:20])
        if len(ag) > 20:
            preview += f' <span class="ql-muted">(+{len(ag) - 20} more)</span>'
        parts.append('<div class="ql-d-row"><span class="ql-k">Allocation groups</span> '
                     + preview + '</div>')
    rg = probe_entry.get("replicate_groups") or []
    if rg:
        preview = ", ".join(_esc(x) for x in rg[:12])
        if len(rg) > 12:
            preview += f' <span class="ql-muted">(+{len(rg) - 12} more)</span>'
        parts.append('<div class="ql-d-row"><span class="ql-k">Replicate groups</span> '
                     + preview + '</div>')
    qwp = probe_entry.get("queryable_without_parent") or []
    if qwp:
        parts.append('<div class="ql-d-row"><span class="ql-k">Queryable without parent</span> '
                     + ", ".join(_esc(x) for x in qwp) + '</div>')
    levels = probe_entry.get("levels") or []
    if levels:
        parts.append('<div class="ql-d-row"><span class="ql-k">All declared levels</span> '
                     + ", ".join(_esc(x) for x in levels) + '</div>')
    return "".join(parts)

def _ql_catalog_detail_html(f, non_api, uncertainty_metrics=""):
    """Drill-down for the Tier-0 portion: full catalog description + endpoint
    URL (or the 'non-API' explanatory note) + optional Bureau documentation
    link + the human-written uncertainty_metrics description from the review
    file (folded in from the removed 'Uncertainty surface' card section)."""
    parts = []
    desc = f.get("desc") or ""
    if desc:
        parts.append(f'<div class="ql-d-desc">{_esc(desc)}</div>')
    endpoint = f.get("variables_url") or ""
    if endpoint:
        base = endpoint.replace("/variables.json", "")
        parts.append(f'<div class="ql-d-row"><span class="ql-k">Endpoint</span> '
                     f'<a class="ql-d-link" href="{_esc(endpoint)}" target="_blank" '
                     f'rel="noopener">{_esc(base)}</a></div>')
    elif non_api:
        # Beginner-UX pass commit #3: rename "not sample-able via API" ->
        # plain-English "data not available via the Census API".
        parts.append('<div class="ql-d-row"><span class="ql-k">Endpoint</span> '
                     '<span class="ql-muted">data not available via the '
                     'Census API (bulk-download product)</span></div>')
    doc = f.get("doc") or ""
    if doc:
        parts.append(f'<div class="ql-d-row"><span class="ql-k">Bureau docs</span> '
                     f'<a class="ql-d-link" href="{_esc(doc)}" target="_blank" '
                     f'rel="noopener">{_esc(doc)}</a></div>')
    unc = (uncertainty_metrics or "").strip()
    if unc:
        parts.append(f'<div class="ql-d-row"><span class="ql-k">Uncertainty</span> '
                     f'<span>{_esc(unc)}</span></div>')
    else:
        # UX pass 2026-07-26 commit #5 - teaching-moment empty state.
        # Pre-fills a --review --notes scaffold so a first draft can land in
        # one paste. product_id comes from f["path"] on the parent scope.
        path = f.get("path", "")
        scaffold = (f'python tools/product_scope.py --review {path} '
                    f'--notes "Reliability of {path}: '
                    f'(one paragraph on what could go wrong with numbers '
                    f'from this product)"')
        parts.append(
            '<div class="ql-d-row"><span class="ql-k">Uncertainty</span> '
            '<span class="ql-muted ql-unc-empty">'
            'No one\'s characterized reliability yet. '
            '<span class="copy-cmd light">'
            f'<code>{_esc(scaffold)}</code>'
            f'<button data-copy="{_esc(scaffold)}">Copy scaffold</button>'
            '</span>'
            '</span></div>')
    # Phase-1 findings report cross-link (2026-07-26). Turns the tool into a
    # wayfinder into the report - not a replacement for it. Only rendered when
    # this product's path appears in PHASE1_REPORT_SECTIONS (i.e. the report
    # covers it explicitly).
    p1 = PHASE1_REPORT_SECTIONS.get(f.get("path", ""))
    if p1:
        anchor, section_label = p1
        href = f"{PHASE1_REPORT_PATH}#{anchor}"
        parts.append('<div class="ql-d-p1link">'
                     '<span class="p1-label">&#128214; Phase 1 report</span>'
                     f'<a href="{_esc(href)}" target="_blank" rel="noopener">'
                     f'{_esc(section_label)} &rarr;</a>'
                     '</div>')
    return "".join(parts)

def _ql_empty_state_html(f, tier, non_api):
    """Drill-down affordance shown when the pipeline hasn't been fully run
    for this product (Tier 0 catalog only; Tier 1 probed but not sampled;
    or non-API). One command per state, always the natural next step,
    always in the exact same visual container - so the toggle shape is
    identical regardless of tier and the reader learns 'drill-down is
    always here for a reason' (Phase 4b #6).

    Non-API products get an explanatory note instead of a command so the
    reader doesn't think there's a working invocation they haven't run yet.
    Tier 2 products return "" - the sample IS the deliverable, no next step
    to prompt.
    """
    if non_api:
        # Beginner-UX pass commit #3: rename "Not sample-able via API".
        return ('<div class="ql-d-empty">Data isn\'t available via the Census '
                'API - this is a bulk-download product (e.g. TIGER shapefiles, '
                'DAS demo). The catalog record above is all we have.</div>')
    if tier == 0:
        cmd = f'python tools/product_scope.py --probe {f["path"]}'
        return (
            '<div class="ql-d-empty">Ask the Census API what\'s in this product — '
            'copy and paste into your terminal (open PowerShell in the repo folder '
            'first):'
            f'<div class="ql-d-cmd"><span class="copy-cmd light">'
            f'<code>{_esc(cmd)}</code>'
            f'<button data-copy="{_esc(cmd)}">Copy</button></span></div>'
            '</div>')
    if tier == 1:
        cmd = f'python tools/product_scope.py --sample {f["path"]}'
        return (
            '<div class="ql-d-empty">Peek at the actual data (a small sample '
            'plus a quick summary of column types and missing values) — copy '
            'and paste into your terminal:'
            f'<div class="ql-d-cmd"><span class="copy-cmd light">'
            f'<code>{_esc(cmd)}</code>'
            f'<button data-copy="{_esc(cmd)}">Copy</button></span></div>'
            '</div>')
    return ""

def _ql_learn_more_html(f, non_api):
    """Beginner-UX pass commit #4: a single prominent copy-command button that
    combines the two most common actions (fetch metadata + peek at data) into
    one no-sequencing-confusion invocation. Sits at the top of the drill-down.
    For non-API products the combined command still works cleanly - --probe
    runs, --sample no-ops with the 'data not available via the API' message -
    but we add a subtle note so the reader isn't surprised."""
    path = f["path"]
    combo_cmd = f'python tools/product_scope.py --probe {path} --sample {path} --open'
    probe_only  = f'python tools/product_scope.py --probe {path}'
    sample_only = f'python tools/product_scope.py --sample {path}'
    non_api_note = ('<div class="ql-lm-note">(data peek not available &mdash; '
                    'this product isn\'t available via the Census API)</div>'
                    if non_api else "")
    return ('<div class="ql-lm-wrap">'
            '<div class="ql-lm-row">'
            '<button class="ql-lm-btn" type="button" '
            f'data-copy="{_esc(combo_cmd)}" '
            f'title="Copies: {_esc(combo_cmd)}">'
            'Learn more about this product (1 command)'
            '</button>'
            f'{non_api_note}'
            '</div>'
            '<details class="ql-lm-more disc">'
            '<summary>More options for advanced users</summary>'
            '<div class="ql-lm-more-body">'
            '<div class="ql-lm-sub">Fetch metadata only:</div>'
            '<div class="ql-d-cmd"><span class="copy-cmd light">'
            f'<code>{_esc(probe_only)}</code>'
            f'<button data-copy="{_esc(probe_only)}">Copy</button></span></div>'
            '<div class="ql-lm-sub" style="margin-top:6px">Peek at data only:</div>'
            '<div class="ql-d-cmd"><span class="copy-cmd light">'
            f'<code>{_esc(sample_only)}</code>'
            f'<button data-copy="{_esc(sample_only)}">Copy</button></span></div>'
            '</div>'
            '</details>'
            '</div>')

def _ql_details_html(f, probe_entry, cache_entry, tier, non_api, insights=None,
                     uncertainty_metrics=""):
    """Assemble the expanded (behind-the-toggle) content for one card. Order
    of blocks matches the TL;DR tier order so the reader can follow the
    thread: (NEW commit #4) Learn-more one-command button, Tier 0 context,
    Tier 1 probe detail, Tier 2 full EDA tables, Phase 5 #6 full insights
    feed, empty-state affordance last."""
    parts = []
    # Beginner-UX pass commit #4: single "Learn more" button pinned to top so
    # the reader's default next-step is one click, not a sequence.
    parts.append(_ql_learn_more_html(f, non_api))
    cat = _ql_catalog_detail_html(f, non_api, uncertainty_metrics=uncertainty_metrics)
    if cat:
        parts.append('<div class="ql-d-block ql-d-t0">' + cat + '</div>')
    probe_html = _ql_probe_detail_html(probe_entry)
    if probe_html:
        parts.append('<div class="ql-d-block ql-d-t1">'
                     '<div class="ql-d-cap">Probe detail</div>'
                     + probe_html + '</div>')
    if cache_entry:
        parts.append('<div class="ql-d-block ql-d-t2">'
                     '<div class="ql-d-cap">Sample &amp; EDA</div>'
                     + _eda_header_html(cache_entry)
                     + _eda_body_html(cache_entry) + '</div>')
    # Phase 5 #6 - full insights feed in the drill-down, always rendered so
    # the drill-down is a superset of the TL;DR (spec: "full chronological
    # feed of all insights"). No insights -> a small empty state.
    parts.append(_ql_insights_drill_html(insights or [], f["path"]))
    # Beginner-UX pass commit #4: the pre-#4 empty-state block (which showed
    # separate probe/sample copy commands) is now redundant - the Learn-more
    # button at the top of the drill-down covers both. We still render an
    # empty-state banner for non-API products so the reader knows why the
    # data-peek half of the combined command will no-op; otherwise drop it.
    if non_api:
        empty = _ql_empty_state_html(f, tier, non_api)
        if empty:
            parts.append('<div class="ql-d-block ql-d-empty-wrap">' + empty + '</div>')
    return "".join(parts)

# ---- Phase 5 #6: insights render in Quick Look TL;DR + drill-down -----------
# TL;DR carries the last 2 insights as compact one-liners so a reader scanning
# the page sees the freshest signal without expanding anything. When the feed
# has >2 entries, an `<N more →` button opens the More Details drill-down
# (delegates to the existing <details> element on the same card). The full
# feed lives on the standalone Insights branch below the card, but a
# duplicate copy also appears in the drill-down so the reader gets everything
# in one expansion.

def _ql_insights_tldr_html(insights):
    """Compact top-2 insights list rendered inside the Quick Look TL;DR block.
    Returns "" when the entry has no insights.

    Sort order: newest first (same as the drill-down feed) so the reader's
    first glance is always the freshest signal."""
    if not insights: return ""
    ordered = sorted(insights, key=lambda i: i.get("when") or "", reverse=True)
    rows = [_insight_row_html(i, kind="tldr") for i in ordered[:2]]
    more_link = ""
    if len(ordered) > 2:
        # data-open-details=1 hooks the small JS shim to programmatically open
        # the sibling <details> when clicked. Native button so keyboard nav
        # picks it up.
        more_link = (f'<button type="button" class="ql-ins-more" '
                     f'data-open-details="1">'
                     f'{len(ordered) - 2} more insight'
                     + ('s' if len(ordered) - 2 != 1 else '')
                     + ' &rarr;</button>')
    return ('<ul class="ql-insights">' + "".join(rows) + '</ul>'
            + (f'<div style="margin:2px 0 0">{more_link}</div>' if more_link else ""))

def _ql_curated_findings_html(product_id):
    """Render curated FINDINGS that match this card's family as pinned rows
    at the top of the drill-down insights feed. Phase A #5 (2026-07-26): the
    12 hand-curated headlines used to live only in Home's 'What we've
    learned'; they now also inline on the matching card so a reviewer who
    opens a product's drill-down doesn't have to jump back to Home to see
    what the team has synthesised on it.

    Order: curated findings first (editorial synthesis of the EDA notebooks),
    then human insights (chronological), then auto-insights (recent). Cards
    with no matching curated finding render nothing here - the caller keeps
    the existing empty state / insights feed unchanged in that case.

    Icon: WWL_ICON_CURATED (pinned pushpin) matches the Home feed so a
    reader who has learned 'pushpin = editorial finding' gets the same
    visual on the card."""
    finds = [x for x in FINDINGS if x.get("family") == product_id]
    if not finds:
        return ""
    rows = []
    for x in finds:
        headline = x.get("headline") or ""
        stat = x.get("stat") or ""
        detail = x.get("detail") or ""
        nb = x.get("nb") or ""
        kind_lbl = x.get("kind") or "finding"
        head_html = ((f'<b>{_esc(stat)}</b> &middot; ' if stat else "")
                     + _esc(headline))
        meta_bits = []
        if nb: meta_bits.append(f'EDA nb {_esc(nb)}')
        meta_bits.append(_esc(kind_lbl))
        meta_html = ' &middot; '.join(meta_bits)
        rows.append('<li class="ins-row ins-curated" data-source="curated">'
                    f'<span class="ins-ico" title="curated finding">'
                    f'{WWL_ICON_CURATED}</span>'
                    '<div class="ins-body">'
                    f'<div class="ins-meta"><span class="ins-badge '
                    f'ins-src-curated">curated</span>'
                    f'<span class="ins-who">{meta_html}</span></div>'
                    f'<div class="ins-text">{head_html}'
                    + (f'<div class="wwl-detail" style="margin-top:3px">'
                       f'{_esc(detail)}</div>' if detail else "")
                    + '</div></div></li>')
    return "".join(rows)

def _ql_insights_drill_html(insights, product_id):
    """Full chronological feed of insights for the drill-down, read-only.
    Wrapped inside the tier-flavoured ql-d-block so it fits the drill-down
    visual language. Writes come from either the CLI helper (`python
    tools/product_scope.py --review <id> --insight "..."`) OR - since
    beginner-UX pass commit #5 - the browser "+ Add a note" download flow
    that emits a template file into notes/ for the next regen to ingest.
    The HTML page itself still never mutates JSON directly.

    Post-Phase-A #5: curated FINDINGS matching this product family render as
    pinned rows at the top of the feed. Order within the feed: curated
    findings first, then human insights (newest first), then auto-insights.
    """
    curated_rows = _ql_curated_findings_html(product_id)
    # Split human vs auto so we can order them independently. Human insights
    # get chronological (newest first); auto-insights sort the same way.
    def _split(inss):
        human = [i for i in inss if (i.get("source") or "") == INSIGHT_HUMAN]
        auto  = [i for i in inss if (i.get("source") or "") != INSIGHT_HUMAN]
        return human, auto
    human, auto = _split(insights or [])
    human.sort(key=lambda i: i.get("when") or "", reverse=True)
    auto.sort(key=lambda i: i.get("when") or "", reverse=True)
    rows_html = curated_rows + "".join(
        _insight_row_html(i, kind="drill") for i in (human + auto))
    if not rows_html:
        # UX pass 2026-07-26 commit #5 - empty states become teaching moments.
        # Replaces "No notes yet on this product." with three Notion-style
        # click-to-copy scaffolds. Each is a --review CLI invocation pre-
        # filled with a starter question so the reader learns the shape of
        # an insight while writing one.
        scaffolds = [
            ("What did the team learn?",
             f"What did the team learn about {product_id}? "
             f"(one sentence)"),
            ("What's the reliability caveat?",
             f"Reliability caveat for {product_id}: "
             f"(what should a data user know before trusting a number here?)"),
            ("Where is this used at Census?",
             f"Where {product_id} is used inside Census, and by whom: "
             f"(link a Bureau page if you have one)"),
        ]
        scaffold_rows = []
        for label, prompt in scaffolds:
            cmd = (f'python tools/product_scope.py --review {product_id} '
                   f'--insight "{prompt}"')
            scaffold_rows.append(
                f'<li class="ins-empty-scaffold">'
                f'<span class="ins-empty-scaffold-label">{_esc(label)}</span>'
                f'<span class="copy-cmd light">'
                f'<code>{_esc(cmd)}</code>'
                f'<button data-copy="{_esc(cmd)}">Copy</button></span>'
                f'</li>')
        insights_html = (
            '<div class="ins-empty ins-empty-scaffolds">'
            '<div class="ins-empty-lead">'
            'No notes yet. Pick a prompt to start &mdash; each one copies a '
            'ready-to-run CLI command:'
            '</div>'
            '<ul class="ins-empty-scaffold-list">'
            + "".join(scaffold_rows) +
            '</ul>'
            '<div class="ins-empty-kbd">'
            '<span class="ins-empty-kbd-lbl">Keyboard:</span> '
            'press <kbd>E</kbd> to toggle this drill-down &middot; '
            '<kbd>j</kbd>/<kbd>k</kbd> next / previous card &middot; '
            '<kbd>/</kbd> focus filter'
            '</div>'
            '</div>')
    else:
        insights_html = ('<ul class="scope-insights-feed" style="max-height:none">'
                         + rows_html + '</ul>')
    # Beginner-UX pass commit #5: "+ Add a note" button downloads a small text
    # stub the user edits and drops into notes/ for the next regen to ingest.
    # Delegated JS handler wired in the page script (see makeNoteStub()).
    add_note_btn = (f'<div class="ql-addnote-wrap">'
                    f'<button type="button" class="ql-addnote-btn" '
                    f'data-addnote-path="{_esc(product_id)}">'
                    f'+ Add a note</button>'
                    f'<span class="ql-addnote-hint">Downloads a small text '
                    f'file you edit and drop into <code>notes/</code>. Next '
                    f'regen picks it up. No terminal needed.</span>'
                    f'</div>')
    return ('<div class="ql-d-block ql-d-t2" style="background:#FAFAFC;'
            'border-color:#EDEEF3">'
            '<div class="ql-d-cap">Notes &amp; insights</div>'
            + insights_html + add_note_btn + '</div>')

# ============================================================================
# PHASE 5 #6 - INSIGHT ROW / RELATIVE-TIME HELPERS
# ============================================================================
# Shared by the TL;DR sub-line inside Quick Look AND by the full drill-down
# feed. Server-side rendering only - no client-side JS mutates these once
# generated. Writes to the underlying JSON come from the CLI helper (--review
# <id> --insight "..."), never from the page itself.

def _rel_time_html(iso_when, absolute_title=True):
    """Return an HTML span with relative-time text ('3h ago') plus the absolute
    ISO timestamp in title= for hover reveal. Rendered server-side so the
    insight feed stays readable without any JavaScript on the page."""
    if not iso_when:
        return '<span class="ins-when" title="">just now</span>'
    try:
        ts = iso_when
        if ts.endswith("Z"): ts = ts[:-1] + "+00:00"
        when = datetime.datetime.fromisoformat(ts)
    except Exception:
        return f'<span class="ins-when" title="{_esc(iso_when)}">{_esc(iso_when)}</span>'
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    age = (now - when).total_seconds()
    if age < 0: age = 0
    if   age < 90:     lbl = f"{int(max(1, age))}s ago"
    elif age < 3600:   lbl = f"{int(round(age/60))}m ago"
    elif age < 86400:  lbl = f"{int(round(age/3600))}h ago"
    else:              lbl = f"{int(round(age/86400))}d ago"
    title = _esc(iso_when) if absolute_title else ""
    return f'<span class="ins-when" title="{title}">{_esc(lbl)}</span>'

def _insight_row_html(ins, kind="drill"):
    """Render one insight entry. `kind` is either 'drill' (full detail, in the
    drill-down feed and the standalone Insights section) or 'tldr' (compact,
    used by Quick Look TL;DR - text truncated to 80 chars, no source badge)."""
    source = ins.get("source") or INSIGHT_HUMAN
    icon = INSIGHT_SOURCE_ICON.get(source, "\U0001F4C4")  # page icon fallback
    who = ins.get("who") or ""
    text = ins.get("text") or ""
    when_html = _rel_time_html(ins.get("when"))
    if kind == "tldr":
        # Line 1: icon + relative-time + who + text-truncated. No badge to
        # keep the TL;DR one glance.
        trunc = text if len(text) <= 80 else text[:77].rstrip() + "..."
        return ('<li class="ins-tldr" data-source="' + _esc(source) + '">'
                f'<span class="ins-ico">{icon}</span>'
                f'{when_html}'
                f'<span class="ins-who">{_esc(who)}</span>: '
                f'<span class="ins-text">{_esc(trunc)}</span></li>')
    badge = _esc(INSIGHT_SOURCE_LABEL.get(source, source))
    return ('<li class="ins-row" data-source="' + _esc(source) + '">'
            f'<span class="ins-ico" title="{_esc(source)}">{icon}</span>'
            f'<div class="ins-body">'
            f'<div class="ins-meta">{when_html}'
            f'<span class="ins-who">{_esc(who)}</span>'
            f'<span class="ins-badge ins-src-{_esc(source.replace(":", "-"))}">{badge}</span>'
            f'</div>'
            f'<div class="ins-text">{_esc(text)}</div>'
            f'</div></li>')

def _ql_dcgov_html(f):
    """Prominent 'Explore data' primary CTA (2026-07-26). Sits at the very
    top of every Quick Look block so a reviewer's first-eye path is straight
    to data.census.gov - the Bureau's interactive query tool for filtering,
    previewing, and downloading tables + maps. The URL comes from
    program_dcgov_url(), which cascades path -> program -> keyword-search so
    every product carries a working link even when we don't have a clean
    landing page for it. Non-API products (TIGER shapefiles, DAS demo files)
    override to their Bureau reference pages instead of data.census.gov,
    since the interactive query tool has no view for them."""
    url = program_dcgov_url(f.get("path", ""))
    # Different explanatory text depending on whether we're linking to
    # data.census.gov (the interactive tool) or a Bureau reference page (for
    # non-API products where the interactive tool has nothing to show).
    is_dcgov = url.startswith(DCGOV_BASE)
    if is_dcgov:
        label = "Explore data on data.census.gov"
        tag = ('<b>data.census.gov</b> is the Bureau&rsquo;s interactive query '
               'tool &mdash; filter, preview, download tables and maps.')
    else:
        label = "Open the Bureau reference page"
        tag = ('This product isn&rsquo;t queryable via data.census.gov &mdash; the '
               'link opens the Bureau&rsquo;s reference / download page.')
    return ('<div class="ql-dcgov">'
            f'<a class="ql-dcgov-btn" href="{_esc(url)}" target="_blank" '
            f'rel="noopener">{_esc(label)}'
            f'<span class="arrow" aria-hidden="true">&nbsp;&rarr;</span></a>'
            f'<span class="ql-dcgov-tag">{tag}</span>'
            '</div>')

def render_quick_look(f, probe_entry, cache_entry, insights=None,
                       uncertainty_metrics="", review_entry=None):
    """One card's Quick Look branch. Reframe pass commit #5: TL;DR now leads
    with WHAT the product IS and WHAT'S INSIDE - not the tier / stage /
    composite-role decision chips that dominated pre-reframe.

    Line order:
      1. What it is  - family, agency, kind, vintages (always visible).
      2. What's inside - geography levels + probe/sample counts if available
         (always visible; falls back to 'not yet probed' when we haven't
         reached the product yet). The cache-tier is shown as a small trailing
         marker on this line - readable but not the visual anchor.
      3. Description - one-line catalog description (~200 chars), if present.
         Previously buried in the drill-down.
      4. Insights TL;DR (Phase 5 #6) - unchanged.

    Below the TL;DR sits the native <details>/<summary> toggle. Now also
    carries the demoted Stage + Composite-role chips as a small header row
    at the top of the drill-down, so a reviewer who needs those signals has
    them one click away without their loudness dominating the browse view.

    insights:     list of insight dicts (from review[path]["insights"]).
    review_entry: full review dict for this path; used to pull stage/role
                   into the drill-down header. Optional for back-compat.
    """
    tier, chip_label, chip_class = _quick_look_tier(f, probe_entry, cache_entry)
    non_api = not f.get("variables_url")

    parts = []
    # "Explore data" primary CTA (2026-07-26). Pinned to the very top of the
    # card so the first link a reviewer's eye lands on is a one-click path to
    # actual data on data.census.gov (or the Bureau reference page for
    # non-API products). Everything else (endpoint URL, Bureau docs, probe /
    # sample commands) is secondary.
    parts.append(_ql_dcgov_html(f))
    # Line 1: What it is (catalog facts). Always visible; visual anchor.
    parts.append('<div class="ql-line ql-t0">' + _ql_what_it_is(f) + '</div>')

    # Line 2: What's inside (geography + counts). Always visible. Tier chip
    # rides at the end as a subtle marker - keeps the color-tier signal for
    # readers who've learned it, without leading with it.
    inside = _ql_what_is_inside(f, probe_entry, cache_entry)
    tier_marker = (f'<span class="tier-chip tier-mini {chip_class}" '
                   f'title="{_esc(chip_label)}">'
                   f'{_esc(chip_label.split(":")[-1].strip())}</span>')
    tier_line_class = {0: "ql-t0", 1: "ql-t1", 2: "ql-t2"}[tier]
    parts.append(f'<div class="ql-line {tier_line_class} ql-inside">'
                 f'{inside} <span class="ql-tier-tail">{tier_marker}</span></div>')

    # Line 3: Catalog description (one line, ~200 char cap). Skipped when the
    # catalog carries no description (rare but possible).
    desc = _ql_description_line(f)
    if desc:
        parts.append(f'<div class="ql-desc">{desc}</div>')

    # Non-API products still get a one-line explanatory note so a reader
    # doesn't misread "metadata not yet fetched" as a missed run.
    # Beginner-UX pass commit #3: rename "not sample-able via API" ->
    # plain-English "data isn't available via the API".
    if tier == 0 and non_api:
        parts.append('<div class="ql-nonapi">Bulk-download product - data '
                     'isn\'t available via the Census API (e.g. TIGER '
                     'shapefiles, DAS demo).</div>')

    # Insights TL;DR (Phase 5 #6). Unchanged.
    insights = list(insights or [])
    tldr_ins = _ql_insights_tldr_html(insights)
    if tldr_ins:
        parts.append(tldr_ins)

    # More-details toggle. Native <details>/<summary> - works without JS.
    tier_slug = {0: "ql-d-tier0", 1: "ql-d-tier1", 2: "ql-d-tier2"}[tier]
    # Drill-down carries the demoted reviewer chips as a small header - but
    # only when there's actually a review signal to show. Phase A #4
    # (2026-07-26): the row was rendering for all 573 cards, showing
    # "Review status: Cataloged" 568x times. Skip the row entirely when the
    # product is (still) at stage=cataloged AND has no composite_role - i.e.
    # nobody has touched the review workflow on it yet. Reviewed / Candidate
    # / FOCUS / Set-aside products, or any product carrying a declared role,
    # keep the header so the reviewer signal stays surfaced.
    r = review_entry or {}
    st = r.get("stage", "cataloged")
    role = effective_role(r)
    show_reviewer_header = (st != "cataloged") or bool(role)
    drill_header = ""
    if show_reviewer_header:
        demoted_chips = []
        stage_chip_color = "#F5D77A" if st == "focus" else "#1F2A5C"
        demoted_chips.append(f'<span class="stagechip" '
                             f'style="background:{STAGE_COLORS[st]};'
                             f'color:{stage_chip_color}">'
                             f'{STAGE_LABELS[st]}</span>')
        if role:
            role_lbl = COMPOSITE_ROLE_LABELS.get(role, role)
            note = r.get("composite_role_note", "")
            demoted_chips.append(
                f'<span class="rolechip" title="{_esc(note)}">{_esc(role_lbl)}</span>')
        drill_header = ('<div class="ql-d-reviewer">'
                        '<span class="ql-d-cap" style="margin-right:8px">Review status</span>'
                        + "".join(demoted_chips) + '</div>')
    details_body = drill_header + _ql_details_html(
        f, probe_entry, cache_entry, tier, non_api,
        insights=insights, uncertainty_metrics=uncertainty_metrics)
    parts.append(
        f'<details class="ql-details {tier_slug}" data-product-id="{_esc(f["path"])}">'
        f'<summary class="ql-summary" title="Toggle drill-down (press E when focused)">'
        f'<span class="ql-chevron">&#x25B8;</span>'  # right-pointing triangle
        f'<span class="ql-summary-label">More details</span>'
        f'</summary>'
        f'<div class="ql-details-body">{details_body}</div>'
        f'</details>'
    )

    return ('<div class="branch"><div class="bcard"><div class="blabel">Quick Look</div>'
            + "".join(parts) + '</div></div>')

def _is_actively_managed(f, review_entry):
    """Post-audit UX pass #3. A product is "actively managed" if it's in the
    funnel beyond Reviewed (candidate or focus) OR it has at least one
    auto:divergence insight (something changed and someone should look). The
    default sidebar toggle hides everything else, so the reviewer opens the
    tab looking at the handful of products that matter today, not all 573."""
    entry = review_entry or {}
    st = entry.get("stage", "cataloged")
    if st in ("candidate", "focus"):
        return True
    for ins in (entry.get("insights") or []):
        if ins.get("source") == INSIGHT_AUTO_DIVERGENCE:
            return True
    return False

def product_row(f, review, work, probes, ctx=None):
    ctx = ctx or {}
    top_families = ctx.get("top_families", set())
    git = ctx.get("git") or {}
    snapshot = ctx.get("snapshot")
    facets = product_facet_values(f, review, work, probes, top_families,
                                    ctx.get("data_cache"))
    r = review.get(f["path"], {})
    st = r.get("stage", "cataloged")
    w = work.get(f["product"], {}) if f["product"] else {}
    ws = w.get("status", 0)
    finds = [x for x in FINDINGS if x["family"] == f["path"]]

    # Reframe pass commit #5: pcard mini now carries only the discovery-oriented
    # signals - work depth (how far the team has reached) and any curated
    # insights count. Stage chip + Composite role chip demoted into the Quick
    # Look drill-down where the review workflow lives. The pcard's left border
    # keeps the stage color so a reader who's learned the color still gets
    # peripheral signal without a loud chip.
    mini = f'<span class="workchip w{ws}">{STATUS_LABELS[ws]}</span>'
    if finds:
        plural = "s" if len(finds) > 1 else ""
        mini += f'<span class="fcount">{len(finds)} insight{plural}</span>'
    # Per-card probe checkbox removed in the beginner-UX pass (commit #1). The
    # single-shot copy-command affordance below the card is the one path now.
    node = (f'<div class="pcard" style="border-left-color:{STAGE_COLORS[st]}">'
            f'<div class="path">{_esc(f["path"])}</div>'
            f'<div class="title">{_esc(f["title"][:96])}</div>'
            f'<div class="title" style="opacity:.75">{_esc(f["group"])} &bull; {_vint(f)}</div>'
            f'<div class="mini">{mini}</div></div>')

    branches = []
    # Quick Look (Phase 4 #1) - persistent summary showing the highest tier of
    # cached data. Sits above every other section so the reader's first glimpse
    # of the card is a summary tagged with a tier chip.
    _data_cache = ctx.get("data_cache") or {}
    branches.append(render_quick_look(f, probes.get(f["path"]),
                                       _data_cache.get(f["path"]),
                                       insights=r.get("insights") or [],
                                       uncertainty_metrics=r.get("uncertainty_metrics", ""),
                                       review_entry=r))

    # Contextual affordances: state-driven copyable commands that fill
    # what would otherwise be a blank section. Rules in _affordances().
    has_probe = bool(probes.get(f["path"], {}).get("ok"))
    # Phase 3 #8: cached EDA sample is a separate state signal - a probe alone
    # doesn't satisfy 'candidate with a sample', because a probe reports what
    # the API says it publishes, and a sample reports what the data looks like.
    has_eda = bool(_data_cache.get(f["path"]))
    banners = _affordances(f, r, ws, has_probe, git, snapshot, has_eda)
    aff = _affordance_html(banners)
    if aff: branches.append(aff)
    # NOTE: the "Uncertainty surface" and "From the Census catalog" card
    # sections were removed in audit simplify 3. The uncertainty_metrics text
    # + Bureau doc link + catalog description now live inside Quick Look's
    # "More details" drill-down (via _ql_catalog_detail_html). The other
    # catalog facets (kind chip, family chip, vintages, spatial) already
    # appear on line 1 of Quick Look's TL;DR (_ql_tier0_line).

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
            '<div class="branch"><div class="bcard"><div class="blabel">What the Census API says is in this product</div>'
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

    # Phase 4b: the standalone "EDA snapshot" section was removed here. It
    # rendered the same tables Quick Look Tier 2 already shows via
    # _eda_body_html(), so on any card with a cached sample the reader saw the
    # full EDA twice. Quick Look is now the single home for the sample view;
    # the sampling logic (fetch_sample, compute_eda, scope_data_cache.json) is
    # untouched, and the eda_diffs dump still feeds the Home-tab drift banner.

    if finds:
        cards = "".join(
            '<div class="tk' + (" odd" if x["kind"] == "oddity" else "") + '">'
            f'<div class="tkh"><b>{_esc(x["stat"])}</b>{_esc(x["headline"])}<em>nb {x["nb"]}</em></div>'
            f'<div class="tkd">{_esc(x["detail"])}</div></div>' for x in finds)
        branches.append('<div class="branch"><div class="bcard"><div class="blabel">'
                        f'Curated insights ({len(finds)})</div>{cards}</div></div>')

    # Phase 5 #6 - insights render inside Quick Look (TL;DR + drill-down feed).
    # No standalone Insights branch and no inline edit controls: after the
    # CLI-helper pivot, writes come from `python tools/product_scope.py
    # --review <id> --insight "..."`, not from the browser.

    search = (f["path"] + " " + f["title"] + " " + f["group"] + " " + f["subject"]).lower()
    folded = "" if st == "focus" else " folded"
    facet_attrs = " ".join(f'data-{k}="{_esc(v)}"' for k, v in facets.items())
    # "Actively managed" = a product a reviewer is currently working on: it's
    # either been promoted into the funnel (candidate/focus) OR it has at
    # least one auto:divergence insight (something changed and someone should
    # look). Rendered as a data-* attr so the sidebar toggle (default-on) can
    # hide the ~560 cataloged-but-untouched cards on page load without losing
    # them - the box unchecks to reveal all 573. Post-audit UX pass #3.
    am_attr = ' data-actively-managed="true"' if _is_actively_managed(f, r) else ""
    # id="prod-<path>" is the anchor target used by the Home tab's
    # "Recently touched" links. The path can contain '/' which is valid in
    # HTML5 fragment IDs but breaks some browsers' scrollIntoView; the
    # accompanying JS handler in the page script uses querySelector with the
    # escaped attribute value so both patterns work.
    # tabindex="0" so the Phase-A j/k keyboard-nav script can focus each
    # visible card and Enter can toggle its Quick Look drill-down. Focus
    # outline is subtle (CSS :focus-visible on .prod).
    return (f'<div class="prod{folded}" id="prod-{_esc(f["path"])}" '
            f'data-s="{_esc(search)}" data-path="{_esc(f["path"])}" '
            f'tabindex="0" '
            f'{facet_attrs}{am_attr}><div class="pnode">{node}</div>'
            f'<div class="branches">{"".join(branches)}</div></div>')

def build_facet_sidebar(prods, review, work, probes, top_families, data_cache=None,
                        am_view=False, catalog_total=None):
    """Left-column facet blocks for the Products tabs.

    For each facet we render every value present in this tab's product set, with
    its (current, unfiltered) count. When the user clicks a value the JS filters
    the cards AND rewrites every other facet's counts to reflect the intersection.

    `am_view=True` marks this sidebar as belonging to the combined "Actively
    managed" panel (Phase A #2): the toggle then advertises that ticking will
    reveal the full 4-kind catalog view (not just more cards in this same tab).
    `catalog_total` overrides the total count shown next to the toggle - used
    so the AM panel says "5 of 573" (the whole catalog) instead of "5 of 5".
    """
    # ---- Reviewer-mode toggle (reframe pass commit #4) ----------------------
    # Post-reframe default: SHOW all products (573). Ticking flips to reviewer
    # mode - hides everything but Candidate/FOCUS/newly-changed cards. Same
    # localStorage key as the pre-reframe toggle; the JS handles semantic
    # migration so returning readers keep their last view. On the sidebar this
    # toggle now advertises entry INTO the smaller review workflow, not out
    # of it. Off (default) = 573 cards across 4 kind panels; On = ~5 AM cards.
    n_all = catalog_total if catalog_total is not None else len(prods)
    n_am  = sum(1 for f in prods
                 if _is_actively_managed(f, review.get(f["path"], {})))
    # Beginner-UX pass commit #3: hint text + toggle label renamed from
    # jargon-heavy "actively-managed / reviewer mode" wording to plain English
    # ("products the team is working on"). Semantics unchanged - ticking still
    # hides most cards, revealing the 5 the team is focused on.
    if am_view:
        hint = (f'Currently showing {n_am} product'
                f'{"s" if n_am != 1 else ""} the team is working on '
                f'(Candidate / FOCUS / newly-changed). Untick to browse the '
                f'full catalog ({n_all} products) split by dataset type.')
    else:
        hint = (f'Currently browsing all {n_all} products. Tick to see only '
                f'the {n_am} product'
                f'{"s" if n_am != 1 else ""} the team is working on '
                f'(Candidate / FOCUS / newly-changed).')
    am_toggle = (
        '<div class="am-toggle">'
        '<label><input type="checkbox" class="am-cb"> '
        '<span class="lbl">Filter to only products the team is working on</span> '
        f'<span class="cnt">({n_am} of {n_all})</span></label>'
        f'<div class="am-hint">{hint}</div>'
        '</div>')
    # Collect all facet values across the tab's products.
    rows = [product_facet_values(f, review, work, probes, top_families, data_cache)
            for f in prods]
    def _facet_block(key, label, sortmode):
        vals = {}
        for r in rows:
            v = r.get(key, "")
            vals[v] = vals.get(v, 0) + 1
        if not vals: return ""
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
            # Beginner-UX pass commit #2: gloss() tooltip on first occurrence
            # of glossary-tracked value labels (e.g. "cataloged" in the STAGE
            # facet, which renders as "Listed only" post-#3-rename but keeps
            # the internal enum value for GLOSSARY lookup).
            gloss_html = gloss(v) if key == "stage" else ""
            items.append(
                f'<li data-v="{_esc(v)}"><label>'
                f'<input type="checkbox" data-f="{_esc(key)}" value="{_esc(v)}"> '
                f'<span class="lbl">{_esc(lbl)}{gloss_html}</span>'
                f'<span class="cnt">{n}</span></label></li>')
        note = ""
        if key == "role" and set(vals.keys()) == {"(unset)"}:
            note = '<div class="fhint">Set <code>composite_role</code> on a product to populate this facet.</div>'
        return (f'<div class="facet" data-f="{_esc(key)}">'
                f'<h4>{_esc(label)}</h4>'
                f'<ul>{"".join(items)}</ul>{note}</div>')

    primary_blocks = []
    reviewer_blocks = []
    for key, label, sortmode, group in FACET_DEFS:
        html = _facet_block(key, label, sortmode)
        if not html: continue
        if group == "reviewer":
            reviewer_blocks.append(html)
        else:
            primary_blocks.append(html)
    reviewer_section = ""
    if reviewer_blocks:
        # Reframe pass commit #4: reviewer-workflow facets (Status / Composite
        # role / Has evidence / Has probe / Notebook validated) collapse behind
        # a details toggle so the sidebar reads as discovery-first. Everything
        # still filters exactly as before once expanded.
        # Beginner-UX pass commit #3: rename "Reviewer mode facets" summary
        # to plain-English "More filters" (the internal group name is
        # still 'reviewer' - see FACET_DEFS).
        reviewer_section = (
            '<details class="facet-reviewer-group disc">'
            '<summary>More filters</summary>'
            '<div class="facet-reviewer-body">' + "".join(reviewer_blocks) + '</div>'
            '</details>')
    return ('<aside class="facets"><div class="facets-head">'
            '<h3>Filter</h3><a class="facet-clear" href="#" style="display:none">Clear filters</a>'
            '</div>' + am_toggle + "".join(primary_blocks) + reviewer_section
            + '</aside>')

def build_kind_panel(kind, fams, review, work, probes, git=None, snapshot=None,
                     data_cache=None, eda_diffs=None):
    prods = [f for f in fams.values() if f["kind"] == kind]
    # Compute per-panel "top families" bucket for the Family facet.
    fam_counts = {}
    for f in prods: fam_counts[f["group"]] = fam_counts.get(f["group"], 0) + 1
    top_families = set(sorted(fam_counts, key=lambda g: -fam_counts[g])[:12])
    ctx = {"top_families": top_families, "git": git or {}, "snapshot": snapshot,
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
    sidebar = build_facet_sidebar(prods, review, work, probes, top_families, data_cache)
    body = ('<div class="blurb">' + KIND_BLURB.get(kind, "") + '</div>'
            f'<div class="filter"><input type="text" placeholder="Filter {len(prods)} products '
            f'by path, title, subject or program..."><span class="fcnt">{len(prods)} shown</span></div>'
            '<div class="nohit">Nothing matches that filter.</div>' + "".join(secs))
    return ('<div class="products-shell">' + sidebar
            + f'<div class="products-main">{body}</div></div>')

def build_am_panel(fams, review, work, probes, git=None, snapshot=None,
                   data_cache=None, eda_diffs=None):
    """Phase A #2 - the combined "Actively managed" panel that replaces the
    4 kind panels in default view.

    Only the ~5-10 products a reviewer is currently working on (Candidate /
    FOCUS / carrying an auto:divergence insight) are rendered here, sorted
    by composite role then path. Cards use the same `product_row()` renderer
    the kind panels use, so drill-downs, chips, and Quick Look behave identically.
    No program/subject nesting - it's a flat list, on the theory that at 5-10
    cards you don't need scaffolding to find the one you want.
    """
    am_prods = [f for f in fams.values()
                if _is_actively_managed(f, review.get(f["path"], {}))]
    # Sort by composite role (unset last) then by path. Puts recipe ingredients
    # in a familiar order rather than the alphabetical accident of the paths.
    role_order = {r: i for i, r in enumerate(COMPOSITE_ROLES)}
    def _key(f):
        role = (review.get(f["path"], {}) or {}).get("composite_role") or ""
        return (role_order.get(role, 99), f["path"])
    am_prods.sort(key=_key)

    fam_counts = {}
    for f in am_prods: fam_counts[f["group"]] = fam_counts.get(f["group"], 0) + 1
    top_families = set(sorted(fam_counts, key=lambda g: -fam_counts[g])[:12])
    ctx = {"top_families": top_families, "git": git or {}, "snapshot": snapshot,
           "data_cache": data_cache or {}, "eda_diffs": eda_diffs or {}}

    rows = "".join(product_row(f, review, work, probes, ctx) for f in am_prods)
    # `catalog_total` = the full 573 so the toggle language reads "of 573"
    # rather than the misleading "of 5" (which would be the AM panel's own size).
    sidebar = build_facet_sidebar(am_prods, review, work, probes, top_families,
                                  data_cache, am_view=True,
                                  catalog_total=len(fams))
    n = len(am_prods)
    # Beginner-UX pass commit #3: rename visible blurb + filter placeholder
    # from jargon ("actively-managed") to plain English ("the team is
    # working on"). Same product set, same filter behavior.
    blurb = ('Products the team is currently working on: Candidate stage, '
             'FOCUS stage, or flagged by an auto:divergence insight. '
             'Everything else is one tick away in the sidebar toggle.')
    body = (f'<div class="blurb">{blurb}</div>'
            f'<div class="filter"><input type="text" placeholder="Filter {n} '
            f'product{"s" if n != 1 else ""} the team is working on by path, '
            f'title, subject or program..."><span class="fcnt">{n} shown</span></div>'
            f'<div class="nohit">Nothing matches that filter.</div>{rows}')
    return ('<div class="products-shell">' + sidebar
            + f'<div class="products-main">{body}</div></div>')

# ============================================================================
# HOME TAB "WHERE THE TEAM IS" SECTION (reframe pass commit #1)
# ============================================================================
# Cold-teammate onramp: replaces the funnel + curated-findings-first framing.
# The two questions this section answers before the reader has to click:
#   (a) How much of the ~573-product Census catalog has the team actually
#       reached into (repo evidence, API probes, sampled data)?
#   (b) Which products are we currently working with, and how recently?
# The prior scope-decision framing (funnel, work-depth table, curated
# insights list, WORKLOG headline hero) moves into a collapsed "Reviewer mode
# data" details block at the bottom of the tab. The composite-role machinery
# is untouched in the schema and CLI - a future mode toggle can promote it back.

def _evidence_coverage(fams, work, probes, data_cache):
    """Return three coverage counts + the total, for the top-of-Home stats bars.

    Fields:
      total    - number of catalog paths (all products, ~573 today).
      evidence - # of catalog paths whose family_product() maps to a tracked
                 product with any repo evidence hits. Same signal the
                 data-evidence="yes" card facet uses.
      probed   - # of catalog paths present in product_probes.json with ok=True.
      sampled  - # of catalog paths present in scope_data_cache.json.
    Untouched (no signal at all) = total - max(evidence, probed, sampled)."""
    total = len(fams)
    evidence = 0
    for f in fams.values():
        prod = f.get("product")
        if prod and (work or {}).get(prod, {}).get("status", 0) > 0:
            evidence += 1
    probed  = sum(1 for v in (probes or {}).values()
                  if isinstance(v, dict) and v.get("ok"))
    sampled = sum(1 for _ in (data_cache or {}))
    return {"total": total, "evidence": evidence,
            "probed": probed, "sampled": sampled}

def _coverage_tone(pct):
    """Color the coverage bars by team-reach percentage: green >20%, amber
    5-20%, red <5%. The point is calibration, not alarm - a low percent on a
    fresh clone is expected; the color just says 'don't misread this as high'."""
    if pct >= 20.0: return "green"
    if pct >= 5.0:  return "amber"
    return "red"

# UX pass 2026-07-26 commit #2 (named-tier progress rail) --------------------
# Mutually-exclusive per-product pipeline stage assignment: each catalog path
# sits at exactly one of {cataloged, probed, sampled, reviewed}, chosen by
# the deepest evidence attached to it. Feeds the segmented rail on Home.
#
# 2026-07-26 Phase A counter-consolidation pass:
#   Renamed `_pipeline_counts()` -> `_tier_counts()` and made it the SINGLE
#   SOURCE OF TRUTH for every counter on the Home tab (tier rail, Sankey,
#   landscape treemap legend, landscape box coloring). Prior state had three
#   disagreeing renderers - tier rail said 551/0/0/22, Sankey said
#   573->22->22->22 (cumulative view of the same numbers), and the landscape
#   legend said 567/6/0/0 under a totally different "repo evidence" tier
#   definition. Fixed by:
#     (1) canonical helper: `_tier_counts()` returns {cataloged, probed,
#         sampled, reviewed, total} counted mutually-exclusively per path.
#     (2) landscape legend + `_prog_tier4()` now read those same counts +
#         those same stage priorities, so a program is coloured by the
#         DEEPEST pipeline stage any of its families reached (not by whether
#         a repo scan happened to match its name).
#     (3) `_pipeline_counts()` kept as a thin alias so external callers +
#         old snapshots don't break.
# Reviewed definition matches the docs/spec:
#   stage != "cataloged" OR uncertainty_metrics OR note OR any insights entry.
# Under the current review file this counts 22 products (all backfilled
# uncertainty_metrics entries; the 5 FOCUS entries + 7 insight-carrying paths
# are all a subset of the 22).

PIPELINE_STAGES = ["cataloged", "probed", "sampled", "reviewed"]

def _has_review_signal(r):
    """Single-source predicate for whether a product counts as 'reviewed'.
    Kept as a helper so the tier-counter, the per-program treemap tinting,
    and any future renderer share one definition and can't drift.

    True when the review entry has ANY of:
      (a) stage != "cataloged"     (e.g. FOCUS - team explicitly promoted it)
      (b) non-empty uncertainty_metrics (backfilled reliability sentence)
      (c) non-empty note               (free-text caveat)
      (d) at least one entry in insights (curated finding, WORKLOG line,
          human note, or auto:cache_diff / auto:divergence signal)
    """
    if not isinstance(r, dict):
        return False
    if (r.get("stage") or "cataloged") != "cataloged":
        return True
    if (r.get("uncertainty_metrics") or "").strip():
        return True
    if (r.get("note") or "").strip():
        return True
    if r.get("insights"):
        return True
    return False

def _tier_counts(fams, review, work, probes, data_cache):
    """Canonical mutually-exclusive pipeline-stage counter (Phase A #1).

    Every Home-tab counter reads from THIS helper - no duplicate math. The
    priority order (deepest wins) mirrors the Sankey flow: a product that has
    a review overrides a sampled-only entry, sampled overrides probed,
    probed overrides bare cataloged.

      reviewed  - `_has_review_signal(review[path])` fires
                  (stage!=cataloged / uncertainty_metrics / note / insights)
      sampled   - path present in scope_data_cache
      probed    - path present in product_probes with ok=True
      cataloged - everything else (only the catalog listing exists)

    `work` is accepted for signature symmetry with other tier helpers but not
    used here - repo evidence is a signal on the tracked-product side, not a
    per-path pipeline stage. It's still surfaced separately in the recently-
    touched list and the treemap tooltip.

    Returns dict with the four stage counts + `total`. Sum of stages == total.
    """
    counts = {s: 0 for s in PIPELINE_STAGES}
    probes = probes or {}
    data_cache = data_cache or {}
    review = review or {}
    for path in fams:
        if _has_review_signal(review.get(path) or {}):
            counts["reviewed"] += 1; continue
        if path in data_cache:
            counts["sampled"] += 1; continue
        pe = probes.get(path)
        if isinstance(pe, dict) and pe.get("ok"):
            counts["probed"] += 1; continue
        counts["cataloged"] += 1
    counts["total"] = sum(counts[s] for s in PIPELINE_STAGES)
    return counts

# Back-compat alias so pre-consolidation callers still work.
_pipeline_counts = _tier_counts

def _iso_to_dt(ts):
    """Parse an ISO-8601 timestamp (optionally 'Z'-terminated) to a UTC-aware
    datetime. Returns None on any parse failure - callers treat that as 'no
    timestamp' and skip the relative-time bit rather than crashing."""
    if not ts: return None
    try:
        if isinstance(ts, str) and ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        d = datetime.datetime.fromisoformat(ts) if isinstance(ts, str) else None
        if d and d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return d
    except Exception:
        return None

def _rel_time_str(when, now=None):
    """Compact 'Xs / Xm / Xh / Xd / Xmo ago' from a datetime. Empty on None."""
    if not when: return ""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age = (now - when).total_seconds()
    if age < 0: age = 0
    if age < 90:         return f"{max(1, int(age))}s ago"
    if age < 3600:       return f"{int(round(age/60))}m ago"
    if age < 86400:      return f"{int(round(age/3600))}h ago"
    if age < 30 * 86400: return f"{int(round(age/86400))}d ago"
    return f"{int(round(age/(30*86400)))}mo ago"

def _recency_signals(fams, review, work, probes, data_cache, repo):
    """One dict per catalog path with any team-reach signal.

    Signal priority (highest tier first):
      Tier 2 (sampled) - scope_data_cache.json entry's `sampled_at` timestamp
        plus the sample's rows x cols shape.
      Tier 1 (probed)  - product_probes.json entry's `probed` YYYY-MM-DD date
        plus a compact metadata summary (MOE var count, allocation groups).
      Tier 0+ (repo)   - via family_product() -> work[product]. Uses the
        newest mtime across evidence files (walked via receipts' repo-relative
        paths + repo/<path>.stat().st_mtime). WORKLOG mentions are not folded
        in here because WORKLOG doesn't record catalog paths - guessing the
        product<->entry link is exactly the kind of inference this tool
        deliberately avoids.
    Untouched paths (no signal at all) are excluded.

    Return list sorted by (highest tier first, most-recent-within-tier first,
    then path). Downstream callers slice the first N for the visible list.
    """
    out = []
    now = datetime.datetime.now(datetime.timezone.utc)
    probes = probes or {}
    data_cache = data_cache or {}
    for path, f in fams.items():
        # Tier 2: sample cache is the strongest team-engagement signal.
        ce = data_cache.get(path)
        if isinstance(ce, dict):
            when = _iso_to_dt(ce.get("sampled_at"))
            shape = ce.get("shape") or [0, 0]
            rows = int(shape[0]) if shape else 0
            cols = int(shape[1]) if shape else 0
            rel = _rel_time_str(when, now) if when else ""
            what = (f"sampled {rel}, {rows:,} rows &times; {cols:,} cols"
                    if rel else f"sampled: {rows:,} rows &times; {cols:,} cols")
            out.append({"path": path, "tier": 2, "when": when, "what": what})
            continue
        # Tier 1: probed metadata.
        pe = probes.get(path)
        if isinstance(pe, dict) and pe.get("ok"):
            # `probed` is a YYYY-MM-DD date string; parse as midnight-UTC so
            # ordering still works alongside the ISO-8601-full timestamps.
            when = _iso_to_dt(str(pe.get("probed") or "") + "T00:00:00Z")
            rel = _rel_time_str(when, now) if when else ""
            bits = []
            if pe.get("moe_variables") is not None:
                bits.append(f"{int(pe['moe_variables']):,} MOE vars")
            if pe.get("allocation_group_count") is not None:
                ag = int(pe['allocation_group_count'])
                if ag: bits.append(f"{ag} alloc group{'s' if ag != 1 else ''}")
            detail = ", ".join(bits) if bits else "metadata cached"
            what = f"probed {rel}, {detail}" if rel else f"probed: {detail}"
            out.append({"path": path, "tier": 1, "when": when, "what": what})
            continue
        # Tier 0+: repo evidence via the family_product map.
        prod = f.get("product")
        w = (work or {}).get(prod, {}) if prod else {}
        if w.get("status", 0) > 0:
            newest = None
            files = []
            for rc in (w.get("receipts") or []):
                rel_path = rc.get("path") or ""
                if not rel_path: continue
                abs_p = repo / rel_path if repo else None
                if abs_p and abs_p.exists():
                    try:
                        mt = abs_p.stat().st_mtime
                        d = datetime.datetime.fromtimestamp(
                            mt, tz=datetime.timezone.utc)
                        if newest is None or d > newest: newest = d
                    except OSError:
                        pass
                fname = rc.get("file") or ""
                if fname and fname not in files: files.append(fname)
            rel = _rel_time_str(newest, now) if newest else ""
            hit_count = int(w.get("hit_count", 0))
            preview = ", ".join(files[:3])
            more = f" (+{len(files) - 3} more)" if len(files) > 3 else ""
            what = (f"{hit_count} repo evidence hit"
                    f"{'s' if hit_count != 1 else ''}"
                    + (f" in {_esc(preview)}{more}" if preview else ""))
            if rel: what += f", last touched {rel}"
            out.append({"path": path, "tier": 0, "when": newest, "what": what})
    out.sort(key=lambda r: (-r["tier"],
                             -(r["when"].timestamp() if r["when"] else 0),
                             r["path"]))
    return out

def build_curriculum_card(fams):
    """Start-here 5-product curriculum (UX pass 2026-07-26 commit #4).

    Renders in the right column of the Get-oriented grid on Home (the Phase-1
    hero card that used to sit above it was retired 2026-07-26; the report
    link now lives in the Team Pulse tail). Each of the 5 CURRICULUM
    products becomes a scannable numbered card - large numeral, plain-English
    concept + reasoning, and an 'Open card' CTA that jumps to the matching
    product card on the Products tab. All 5 blurbs are grounded in either the
    phase-1 findings report or the seeded FOCUS product_review entries; the
    source of each blurb is documented in the CURRICULUM constant.

    Products missing from the catalog (defensive - shouldn't happen given
    all 5 are seeded FOCUS) get a muted placeholder so the numbering stays
    intact rather than collapsing.
    """
    parts = [
        '<div class="curriculum-section" role="region" '
        'aria-label="Start here: five-product curriculum">',
        '<h2>Start here &mdash; 5 products to learn Census data reliability</h2>',
        '<div class="curriculum-intro">'
        'Walk this list top to bottom &mdash; each product illustrates one of '
        'the four uncertainty mechanisms: sampling noise, differential '
        'privacy, imputation, and pre-DP baselines. The headline numbers the '
        'team found live in <b>Team pulse</b> at the bottom of this page.'
        '</div>',
        '<div class="curriculum-list">'
    ]
    for i, entry in enumerate(CURRICULUM, start=1):
        path = entry["path"]
        exists = path in fams
        # Jump target on the Products tab (matching #prod-<path> id).
        # data-jump-path hooks the same handler used by "Recently touched".
        cta_html = (
            f'<a class="curriculum-cta" href="#prod-{_esc(path)}" '
            f'data-jump-path="{_esc(path)}" '
            f'aria-label="Open the {_esc(entry["title"])} card">'
            f'Open card <span class="arrow" aria-hidden="true">&rarr;</span>'
            f'</a>'
            if exists else
            '<span class="curriculum-cta" style="background:var(--muted);'
            'cursor:not-allowed" aria-disabled="true">Not in catalog</span>'
        )
        parts.append(
            f'<div class="curriculum-item">'
            f'<div class="curriculum-num" aria-hidden="true">{i}</div>'
            f'<div class="curriculum-body">'
            f'<div class="curriculum-concept">Learn: {_esc(entry["concept"])}</div>'
            f'<div class="curriculum-title-row">'
            f'<span class="curriculum-title">{_esc(entry["title"])}</span>'
            f'<code class="curriculum-path">{_esc(path)}</code>'
            f'</div>'
            f'<div class="curriculum-why">{_esc(entry["why"])}</div>'
            f'</div>'
            f'{cta_html}'
            f'</div>'
        )
    parts.append('</div></div>')
    return "".join(parts)

def build_where_team_is(fams, review, work, probes, data_cache, git, repo):
    """Home-tab top: named-tier research-pipeline rail + 'Recently touched' list.

    UX pass 2026-07-26 commit #2. Replaces the pre-existing 3-bar coverage
    list (Has repo evidence / Probed / Sampled with raw percentages) with a
    single segmented horizontal bar showing mutually-exclusive pipeline
    stages: cataloged -> probed -> sampled -> reviewed. Sub-25% raw
    percentages are gone entirely; segment area IS the percentage, and the
    named counts below the rail carry the exact numbers.
    """
    pc = _tier_counts(fams, review, work, probes, data_cache)
    total = pc["total"] or 1  # avoid div-by-zero if catalog is empty

    # Human-friendly labels for the pipeline vocabulary. Kept alongside the
    # tone/colour map so the label + swatch never drift.
    STAGE_LABEL = {
        "cataloged": "cataloged",
        "probed":    "probed",
        "sampled":   "sampled",
        "reviewed":  "reviewed",
    }

    # Condense pass 2026-07-26: the segmented tier bar was retired in favor
    # of the Sankey flow (they rendered the same four counts as two separate
    # bands). The Sankey is now the section's visual; the swatch + count
    # labels below survive as its legend, so no number was lost.
    # Labels: swatch + count + name. Reads left-to-right in
    # the same order as the Sankey stages.
    lbl_html = []
    for stage in PIPELINE_STAGES:
        n = pc[stage]
        lbl_html.append(
            f'<span class="pipeline-label">'
            f'<span class="pipeline-swatch" data-stage="{stage}"></span>'
            f'<span class="pipeline-label-n">{n:,}</span>'
            f'<span class="pipeline-label-name">{STAGE_LABEL[stage]}</span>'
            f'</span>')

    parts = ['<div class="wti-section">',
             '<h2>Where the team is</h2>',
             '<div class="sub">Every product moves through the '
             f'research pipeline{gloss("research pipeline")} on its way to a '
             'finished uncertainty note. This shows where each of the '
             f'{pc["total"]:,} catalog product families currently sits'
             f'{gloss("reviewed")}. <b>Ribbon width</b> is the number of '
             'products that carried forward to the next stage.</div>',
             # Condense pass 2026-07-26: the Sankey flow IS the section's
             # visual (it and the old segmented tier bar told the same
             # pipeline-state story as two separate bands). Visual first,
             # then the swatch legend, then the plain-English caption.
             build_sankey_pipeline(pc, embedded=True),
             '<div class="pipeline-rail">',
             '<div class="pipeline-labels">',
             "".join(lbl_html),
             '</div>',
             '<div class="pipeline-caption">'
             'Each product moves from '
             '<b>cataloged</b> (listed in the Census catalog) &rarr; '
             '<b>probed</b> (variables + geographies fetched from the API) &rarr; '
             '<b>sampled</b> (a small data slice pulled + summarized) &rarr; '
             '<b>reviewed</b> (uncertainty notes written by the team). '
             'The deliverable is a reviewed uncertainty note; the earlier '
             'stages are just how we get enough evidence to write one.'
             '</div>',
             '</div>']

    signals = _recency_signals(fams, review, work, probes, data_cache, repo)
    parts.append('<div class="wti-recent">')
    parts.append('<h3>Recently touched</h3>')
    if not signals:
        # UX pass 2026-07-26 commit #5 - teaching-moment empty state. Pre-
        # fills the first suggested command so a beginner never has to type.
        first_cmd = 'python tools/product_scope.py --probe acs/acs5'
        parts.append(
            '<div class="wti-empty wti-teach">'
            'No products touched yet. Fetch metadata for the first one:'
            '<div style="margin-top:8px"><span class="copy-cmd light">'
            f'<code>{_esc(first_cmd)}</code>'
            f'<button data-copy="{_esc(first_cmd)}">Copy</button>'
            '</span></div>'
            '<div class="wti-teach-more">Or press <kbd>/</kbd> to focus the '
            'filter on any Products tab, then <kbd>j</kbd>/<kbd>k</kbd> to '
            'walk the catalog card by card.</div>'
            '</div>')
    else:
        parts.append('<ul class="wti-recent-list">')
        # Beginner-UX pass commit #3: chip labels renamed from jargon
        # (sample/probe) to plain English (peek/metadata).
        tier_lbl = {2: "data peek", 1: "metadata", 0: "repo"}
        for s in signals[:10]:
            when_str = _rel_time_str(s["when"]) if s.get("when") else ""
            when_html = (f'<div class="wti-when">{_esc(when_str)}</div>'
                         if when_str else "")
            # data-jump-path hooks the client-side "jump into Products tab"
            # handler wired below the panel HTML - anchor works even without
            # JS thanks to the id="prod-<path>" on the .prod card.
            parts.append(
                f'<li><span class="wti-tier-chip t{s["tier"]}">'
                f'{tier_lbl[s["tier"]]}</span>'
                f'<a class="wti-path" href="#prod-{_esc(s["path"])}" '
                f'data-jump-path="{_esc(s["path"])}">'
                f'{_esc(s["path"])}</a>'
                f'<div class="wti-what">{s["what"]}</div>'
                f'{when_html}</li>')
        parts.append('</ul>')
    parts.append('</div></div>')
    return "".join(parts)

# ============================================================================
# HOME TAB "THIS WEEK FROM CENSUS" MINI-FEED  (Phase A 2026-07-26 commit #2)
# ============================================================================
# Small always-visible slice of the census.gov press-release RSS feed. Adds
# external recency signal to Home - one of the axes the tool scored 5/10 on
# in the census.gov head-to-head audit. Fetched at regen time with graceful
# fallback:
#   (1) fresh cache (< 24h old)                -> use cache silently
#   (2) network fetch (5s timeout, stdlib xml) -> parse, cache, use
#   (3) stale cache (>= 24h old) after fetch fail -> show cache + "may be
#       outdated" tag so a reader knows the numbers aren't live
#   (4) no cache at all + fetch fail           -> render empty state with a
#       direct census.gov/newsroom link
# Zero new dependencies (urllib + xml.etree from stdlib). Cache file is
# gitignored (regenerable on demand).

CENSUS_PRESS_URL      = "https://www.census.gov/newsroom/press-releases.xml"
CENSUS_PRESS_CACHE    = ".census_press_cache.json"
CENSUS_PRESS_TTL_SEC  = 24 * 3600     # 24-hour cache TTL
CENSUS_PRESS_TIMEOUT  = 5             # seconds - hard cap so a slow fetch
                                      # never delays regen more than a beat
CENSUS_PRESS_LIMIT    = 5             # items rendered
CENSUS_PRESS_FALLBACK = "https://www.census.gov/newsroom.html"

def _load_press_cache(cache_path):
    """Return (items, fetched_at_str) tuple or (None, None) on any parse
    failure. Cache format is {"fetched_at": <iso>, "items": [...]}."""
    if not cache_path.exists():
        return None, None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        items = data.get("items") or []
        fetched_at = data.get("fetched_at") or ""
        return items, fetched_at
    except Exception:
        return None, None

def _cache_is_fresh(fetched_at_iso, ttl_sec):
    """True if `fetched_at_iso` is within the TTL window."""
    when = _iso_to_dt(fetched_at_iso)
    if not when:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - when).total_seconds() < ttl_sec

def _parse_press_xml(xml_bytes, limit=CENSUS_PRESS_LIMIT):
    """Parse a Census press-release RSS/ATOM feed with stdlib xml.etree.
    Returns list of dicts: {title, link, date_iso, date_display}. Handles both
    RSS 2.0 (<item>) and Atom (<entry>) shapes since census.gov has been known
    to change the feed engine between refreshes."""
    import xml.etree.ElementTree as ET
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    # RSS 2.0: <rss><channel><item>...
    for el in root.iter():
        # Strip any XML namespace from the tag for a friendlier match.
        tag = el.tag.rsplit("}", 1)[-1] if "}" in el.tag else el.tag
        if tag not in ("item", "entry"):
            continue
        title, link, date_raw = "", "", ""
        for child in el:
            ctag = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
            text = (child.text or "").strip()
            if ctag == "title" and text and not title:
                title = text
            elif ctag == "link":
                # RSS: <link>URL</link>; Atom: <link href="URL"/>
                if text:
                    link = text
                elif child.get("href"):
                    link = child.get("href")
            elif ctag in ("pubDate", "published", "updated", "date") and text:
                date_raw = text
        if not title:
            continue
        # Try to parse the date to an ISO string + a compact display.
        date_iso, date_display = "", date_raw[:16]
        d = _parse_press_date(date_raw)
        if d:
            date_iso = d.isoformat()
            date_display = d.strftime("%b %d")
        items.append({"title": title, "link": link,
                      "date_iso": date_iso, "date_display": date_display})
        if len(items) >= limit:
            break
    return items

def _parse_press_date(raw):
    """Best-effort date parser for RSS/Atom timestamps. Handles the common
    RFC-822 (`Mon, 21 Jul 2026 12:00:00 GMT`) and ISO 8601 (`2026-07-21T...`)
    forms without a 3rd-party dep. Returns tz-aware UTC datetime or None."""
    if not raw: return None
    raw = raw.strip()
    # RFC-822 style (pubDate on RSS 2.0).
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(raw)
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return d.astimezone(datetime.timezone.utc)
    except Exception:
        pass
    # ISO 8601 (Atom published/updated).
    d = _iso_to_dt(raw)
    if d: return d
    return None

def fetch_census_press_releases(cache_path):
    """Return (items, status) tuple.

    status ∈ {"fresh", "cached", "stale", "empty"}:
      fresh  - network fetch just succeeded (cache updated)
      cached - fresh cache hit (< TTL), no network call needed
      stale  - fetch failed but a stale cache is available
      empty  - no cache and fetch failed - caller renders an empty state
    """
    # (1) Fresh cache? Use it, skip network entirely.
    items, fetched_at = _load_press_cache(cache_path)
    if items is not None and _cache_is_fresh(fetched_at, CENSUS_PRESS_TTL_SEC):
        return items, "cached"

    # (2) Try to fetch. 5-second timeout - if census.gov is slow or blocked,
    #     we degrade to the stale-cache path below.
    try:
        req = urllib.request.Request(
            CENSUS_PRESS_URL,
            headers={"Accept": "application/rss+xml, application/xml, "
                               "application/atom+xml, text/xml, */*",
                     "User-Agent": "Census-Uncertainty-Analysis/1.0 "
                                   "(product_scope.py; capstone research tool)"})
        with urllib.request.urlopen(req, timeout=CENSUS_PRESS_TIMEOUT) as r:
            xml_bytes = r.read()
        parsed = _parse_press_xml(xml_bytes, CENSUS_PRESS_LIMIT)
        if parsed:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            payload = {"fetched_at": now_iso, "url": CENSUS_PRESS_URL,
                       "items": parsed}
            try:
                cache_path.write_text(json.dumps(payload, indent=2),
                                       encoding="utf-8")
            except OSError:
                pass   # cache write failed; still return fresh items
            return parsed, "fresh"
        # Fetch worked but parse produced nothing - treat like a failure.
    except Exception:
        pass

    # (3) Stale cache fallback.
    if items:
        return items, "stale"

    # (4) No cache at all + network failed.
    return [], "empty"

# ============================================================================
# "UP NEXT" ACTION QUEUE (mission-statement pass 2026-07-26)
# ============================================================================
# The tool's mission statement is two jobs: (1) a first-timer learns what
# Census data is, fast; (2) the team tracks what to do next. The discovery
# pivot demoted all the decide-next machinery, so job 2 had no surface left.
# This section derives a ranked punch list ENTIRELY from existing state
# (product_review.json stages/insights/metrics, product_probes.json,
# scope_data_cache.json, the CURRICULUM constant) - no new schema, nothing
# hand-maintained. Finish an item, regen, and it disappears on its own.

# One icon per action type (the visual cue the eye keys on before reading).
NEXT_ACTION_ICONS = {
    "probe":   "\U0001F4E1",  # satellite antenna - fetch API metadata
    "sample":  "\U0001F52C",  # microscope - data peek / canonical EDA
    "deepen":  "\U0001F393",  # graduation cap - curriculum depth
    "insight": "\U0001F4DD",  # memo - record a human observation
    "metrics": "\U0001F4CF",  # ruler - document reliability
}

# Verb phrase per action type, composed after the linked product name
# ("American Community Survey 5-year - probe its metadata").
NEXT_ACTION_VERBS = {
    "probe":   "probe its metadata",
    "sample":  "pull a data sample",
    "deepen":  "give it a first probe",
    "insight": "Record the team's first insight (any product)",
    "metrics": "document its reliability",
}

def _derive_next_actions(fams, review, probes, data_cache):
    """Rank-ordered list of next-action dicts, derived purely from existing
    state. Rules, in priority order (rule order IS the ranking):

      1. probe   - FOCUS products never probed: reviewed on paper, but the
                   tool has never fetched their actual API metadata.
      2. sample  - FOCUS products probed but never sampled: no data peek to
                   verify the reliability notes against real values.
      3. deepen  - CURRICULUM products with no team touch at all (no human
                   insight, no successful probe, no sample): in the learning
                   path but nobody has gone deeper than the blurb.
      4. insight - zero human insights anywhere: the feed is all automated,
                   so prompt the first real team note (targets acs/acs5 as
                   the canonical starting product; the command is editable).
      5. metrics - stage != cataloged but uncertainty_metrics empty: flagged
                   as important with reliability undocumented.

    Staleness of the report itself is deliberately NOT a rule here - the
    freshness pill in the header already carries that signal, and duplicating
    it would violate the one-source-per-signal principle from Phase A #1.

    Each product appears AT MOST ONCE, under its highest-priority rule
    (e.g. an unprobed FOCUS product queues its probe, not also its sample -
    probe-then-sample is the pipeline order the Sankey draws). Within rule 1
    the FOCUS products sort in CURRICULUM order first (learning-path order
    is the reading order the Home tab already teaches), then by path.

    Returns [{rule, icon, path (None for rule 4), why, cmd}], full list -
    the renderer decides how many are visible vs. behind the disclosure.
    """
    review = review or {}
    probes = probes or {}
    data_cache = data_cache or {}

    def _probed(p):
        pe = probes.get(p)
        return isinstance(pe, dict) and pe.get("ok")

    def _sampled(p):
        return p in data_cache

    def _has_human_insight(p):
        r = review.get(p) or {}
        return any(i.get("source") == INSIGHT_HUMAN
                   for i in (r.get("insights") or []) if isinstance(i, dict))

    curriculum_rank = {e["path"]: i for i, e in enumerate(CURRICULUM)}
    focus_paths = sorted(
        (p for p, r in review.items()
         if isinstance(r, dict) and r.get("stage") == "focus" and p in fams),
        key=lambda p: (curriculum_rank.get(p, len(CURRICULUM)), p))

    actions, queued = [], set()

    def _add(rule, path, why, cmd):
        if path is not None:
            if path in queued:
                return
            queued.add(path)
        actions.append({"rule": rule, "icon": NEXT_ACTION_ICONS[rule],
                        "path": path, "why": why, "cmd": cmd})

    # Rule 1: FOCUS never probed.
    for p in focus_paths:
        if not _probed(p):
            _add("probe", p,
                 "Focus product - we've reviewed it on paper but never "
                 "fetched its actual metadata.",
                 f"python tools/product_scope.py --probe {p} --open")

    # Rule 2: FOCUS probed but never sampled.
    for p in focus_paths:
        if _probed(p) and not _sampled(p):
            _add("sample", p,
                 "No data peek yet - the EDA would verify our reliability "
                 "notes.",
                 f"python tools/product_scope.py --sample {p} --open")

    # Rule 3: curriculum products with no team touch beyond the blurb.
    for e in CURRICULUM:
        p = e["path"]
        if p not in fams:
            continue
        if not (_probed(p) or _sampled(p) or _has_human_insight(p)):
            _add("deepen", p,
                 "In the learning path but nobody's gone deeper.",
                 f"python tools/product_scope.py --probe {p} --open")

    # Rule 4: zero human insights across the whole review file.
    n_human = sum(1 for r in review.values() if isinstance(r, dict)
                  for i in (r.get("insights") or [])
                  if isinstance(i, dict) and i.get("source") == INSIGHT_HUMAN)
    if n_human == 0:
        _add("insight", None,
             "The insights feed is all automated - no teammate has recorded "
             "an observation yet.",
             'python tools/product_scope.py --review acs/acs5 '
             '--insight "your observation"')

    # Rule 5: promoted past cataloged but reliability undocumented.
    for p in sorted(review):
        r = review.get(p)
        if not isinstance(r, dict) or p not in fams:
            continue
        if ((r.get("stage") or "cataloged") != "cataloged"
                and not (r.get("uncertainty_metrics") or "").strip()):
            _add("metrics", p,
                 "Flagged as important but reliability is undocumented.",
                 f'python tools/product_scope.py --review {p} '
                 f'--notes "reliability: ..."')

    return actions

UPNEXT_VISIBLE_CAP = 5

def build_up_next(fams, review, probes, data_cache):
    """Team Pulse chapter lead: the 'Up next' action-queue card.

    Renders the top-5 derived actions from _derive_next_actions() as a
    10-second punch list - rank chip, action-type icon, linked product name
    + verb phrase, one-line why, and the exact command click-to-copyable on
    the right (the same .copy-cmd control the freshbar and card scaffolds
    use). Product names jump to their card via the existing data-jump-path
    handler. Overflow beyond 5 sits behind the unified details.disc
    disclosure (persisted under product_scope:upnext_more). A fully
    caught-up state renders a green celebration line, not an empty box.
    """
    actions = _derive_next_actions(fams, review, probes, data_cache)
    n = len(actions)
    parts = [
        '<div class="upnext-section" role="region" '
        'aria-label="Up next - suggested team actions">',
        '<div class="upnext-head"><h2>Up next</h2>'
        + (f'<span class="upnext-tag">{n} queued</span>' if n else
           '<span class="upnext-tag" style="background:#D6EDD9;'
           'color:#1F5A2E">all clear</span>')
        + '</div>',
        '<div class="upnext-caption">What the team should do next, ranked - '
        'derived from the tracker\'s current state at regen time, nothing '
        'hand-maintained. Finish an item and it drops off on the next '
        'regen.</div>',
    ]

    if not actions:
        parts.append(
            '<div class="upnext-done">'
            '<span class="una-ico" aria-hidden="true">✅</span>'
            '<span><b>All caught up - nothing queued.</b> Browse the '
            'landscape or add a note to any product.</span>'
            '</div></div>')
        return "".join(parts)

    def _row(a, rank):
        path = a["path"]
        verb = NEXT_ACTION_VERBS[a["rule"]]
        if path:
            name = (fams.get(path) or {}).get("title") or path
            head = (f'<a class="una-name" href="#prod-{_esc(path)}" '
                    f'data-jump-path="{_esc(path)}">{_esc(name)}</a>'
                    f' <span class="una-act">&mdash; {_esc(verb)}</span>')
        else:
            head = f'<span class="una-act">{_esc(verb)}</span>'
        return ('<li>'
                f'<span class="una-rank" aria-hidden="true">{rank}</span>'
                f'<span class="una-ico" aria-hidden="true">{a["icon"]}</span>'
                f'<span class="una-body">'
                f'<span class="una-head">{head}</span>'
                f'<span class="una-why" style="display:block">'
                f'{_esc(a["why"])}</span>'
                f'</span>'
                f'<span class="copy-cmd light"><code>{_esc(a["cmd"])}</code>'
                f'<button data-copy="{_esc(a["cmd"])}">Copy</button></span>'
                '</li>')

    visible = actions[:UPNEXT_VISIBLE_CAP]
    hidden = actions[UPNEXT_VISIBLE_CAP:]
    parts.append('<ul class="upnext-list">')
    parts.extend(_row(a, i) for i, a in enumerate(visible, start=1))
    parts.append('</ul>')

    if hidden:
        # Closed-state preview names the next suggestion, per the unified
        # disclosure grammar (tell the reader what's inside before opening).
        nxt = hidden[0]
        nxt_name = ((fams.get(nxt["path"]) or {}).get("title") or nxt["path"]
                    if nxt["path"] else NEXT_ACTION_VERBS[nxt["rule"]])
        preview = f'next: {nxt["icon"]} {_esc(nxt_name)}'
        parts.append(
            f'<details class="upnext-more disc" data-persist-key="upnext_more">'
            f'<summary>+ {len(hidden)} more suggestion'
            f'{"s" if len(hidden) != 1 else ""}'
            f'<span class="disc-preview">{preview}</span></summary>'
            '<ul class="upnext-list" style="border-top:1px solid #EADFB8">')
        parts.extend(_row(a, i) for i, a in
                     enumerate(hidden, start=len(visible) + 1))
        parts.append('</ul></details>')

    parts.append('</div>')
    return "".join(parts)

def build_census_press_feed(cache_path):
    """Return an HTML fragment for the Bureau press-release mini-feed. Always
    renders SOMETHING - fresh feed, cached feed with a `may be outdated` tag,
    or an empty state with a direct link to census.gov/newsroom - so the
    section never silently disappears. Called from build_home()."""
    items, status = fetch_census_press_releases(cache_path)

    # Empty state - no cache and fetch failed.
    if status == "empty":
        return (
            '<div class="cpress-section" role="region" '
            'aria-label="Bureau press releases feed (unavailable)">'
            '<div class="cpress-head">'
            '<h3>This week from Census</h3>'
            '<span class="cpress-tag miss">unavailable</span>'
            '</div>'
            '<div class="cpress-empty">'
            'Bureau feed unavailable - check '
            f'<a href="{_esc(CENSUS_PRESS_FALLBACK)}" target="_blank" '
            f'rel="noopener">census.gov/newsroom</a> for the latest releases.'
            '</div>'
            '</div>')

    tag_class, tag_text = {
        "fresh":  ("fresh",  "live"),
        "cached": ("fresh",  "cached"),
        "stale":  ("stale",  "may be outdated"),
    }.get(status, ("stale", ""))

    top_items = items[:CENSUS_PRESS_LIMIT]
    lis = []
    for it in top_items:
        title = it.get("title") or "(untitled)"
        link = it.get("link") or CENSUS_PRESS_FALLBACK
        date_display = it.get("date_display") or ""
        lis.append(
            '<li>'
            f'<span class="cpress-date">{_esc(date_display)}</span>'
            f'<a class="cpress-title" href="{_esc(link)}" '
            f'target="_blank" rel="noopener">{_esc(title)}</a>'
            '</li>')

    # Condense-home pass 2026-07-26 commit #2: default-collapse into a
    # single-line preview showing only the most recent headline + a "N more"
    # button. Full head + caption + 5-item list live in the expanded panel,
    # revealed via the toggle. Persists via localStorage
    # `product_scope:bureau_expanded`. Preview line is always rendered so a
    # first-time reader can see today's top Bureau headline without any
    # interaction; the expand button opens the full list when they want more.
    first = top_items[0] if top_items else {}
    first_title = first.get("title") or "(no recent releases)"
    first_link = first.get("link") or CENSUS_PRESS_FALLBACK
    n_more = max(0, len(top_items) - 1)
    return (
        '<div class="cpress-section" role="region" '
        'data-collapsible="bureau" '
        'aria-label="This week from Census - recent Bureau press releases">'
        # Compact preview: shown by default, hidden when expanded.
        '<div class="cpress-preview" data-bureau-view="collapsed">'
        '<span class="cpress-preview-label">This week from Census:</span> '
        f'<a class="cpress-preview-title" href="{_esc(first_link)}" '
        f'target="_blank" rel="noopener">{_esc(first_title)}</a>'
        + (f' <button type="button" class="cpress-expand-btn" '
           f'data-bureau-toggle aria-expanded="false" '
           f'aria-controls="cpress-full-panel">{n_more} more '
           f'<span class="arrow" aria-hidden="true">&rarr;</span>'
           f'</button>' if n_more else '')
        + '</div>'
        # Full panel: hidden by default, shown when expanded.
        '<div class="cpress-full" id="cpress-full-panel" '
        'data-bureau-view="expanded" hidden>'
        '<div class="cpress-head">'
        '<h2>This week from Census</h2>'
        + (f'<span class="cpress-tag {tag_class}">{_esc(tag_text)}</span>'
           if tag_text else "")
        + '<a class="cpress-source" '
          f'href="{_esc(CENSUS_PRESS_FALLBACK)}" '
          'target="_blank" rel="noopener">census.gov/newsroom &rarr;</a>'
        '</div>'
        '<div class="cpress-caption">The Bureau&rsquo;s most recent public '
        'releases &mdash; useful for spotting new products or policy changes '
        'while the team is heads-down on the analysis.</div>'
        '<ul class="cpress-list">'
        + "".join(lis) +
        '</ul>'
        '<button type="button" class="cpress-collapse-btn" '
        'data-bureau-toggle aria-expanded="true" '
        'aria-controls="cpress-full-panel">'
        '<span class="arrow" aria-hidden="true">&larr;</span> Collapse'
        '</button>'
        '</div>'
        '</div>')

# ============================================================================
# HOME TAB "WHAT WE'VE LEARNED" SECTION (reframe pass commit #2)
# ============================================================================
# First place in the tool where every insight source lands in one feed:
#   * Curated findings (FINDINGS constant, mostly from EDA notebooks)
#   * WORKLOG findings (mined from WORKLOG.md's `Findings / decisions:` lines)
#   * Human insights (source="human" from product_review.json)
#   * Auto-insights (source="auto:cache_diff", "auto:divergence")
# Legacy source="auto:repo" entries are skipped here - the audit cut them as
# noisy WORKLOG restatements, and re-surfacing them alongside real WORKLOG
# entries would double-count. Existing entries still render on cards; they
# just don't feed the Home synthesis feed.

# Icon for curated findings in the "What we've learned" feed. Human notes
# reuse INSIGHT_SOURCE_ICON so a reader who learned the icons on a product
# card sees the same ones here. (WWL_ICON_WORKLOG removed 2026-07-26 - mined
# WORKLOG rows no longer render on Home.)
WWL_ICON_CURATED = "\U0001F4CC"   # pushpin - hand-selected headlines

def _worklog_url(git):
    """Same GitHub-blob-or-file-fallback pattern the pre-reframe WORKLOG
    headline used, extracted so both callers stay in sync."""
    gh = (git or {}).get("github_slug") or ""
    branch = (git or {}).get("branch") or "main"
    if gh:
        return f"https://github.com/{gh}/blob/{branch}/WORKLOG.md"
    return "file:///" + str((Path((git or {}).get("repo_abs", ".")) / "WORKLOG.md")
                            ).replace("\\", "/")

def build_what_learned(fams, review, worklog, git):
    """Home-tab 'What we've learned' section - stat-first redesign
    (2026-07-26, after Garrett's live test: the previous every-source feed
    read as 'a massive wall of text and not helpful').

    Layout, top to bottom:
      1. Hero stat cards - the curated findings flagged `hero` in FINDINGS,
         rendered number-first (type-scale step 8/9) with a one-line
         takeaway and a product chip that jumps to the card via
         window.__jumpToCard (the Home->card jump fixed the same day).
      2. Team notes - human insights from product_review.json, newest
         first, capped at 5 visible. Team gold; stays prominent.
      3. More findings - the remaining curated findings as compact
         one-liners (stat + headline + product chip), 5 visible, the rest
         behind the persisted Show-more drawer.
      4. One 'Full team log' link out to WORKLOG.md.

    Deliberately DEMOTED (Garrett's call, live test 2026-07-26):
      * WORKLOG-mined prose rows - not rendered here at all any more. The
        ~40 mined rows were the wall; one WORKLOG.md link replaces them.
        mine_worklog() still runs (the entry count labels the link).
      * auto:cache_diff / auto:divergence insights - bookkeeping signals;
        they still render on each product card's Quick Look drill-down,
        just not on Home.
    """
    wl_url = _worklog_url(git)
    heroes = [x for x in FINDINGS if x.get("hero")]
    rest   = [x for x in FINDINGS if not x.get("hero")]

    # Human insights only (see docstring for what got demoted and why).
    notes = []
    for path, r in (review or {}).items():
        if not isinstance(r, dict): continue
        for ins in (r.get("insights") or []):
            if (ins.get("source") or "") != INSIGHT_HUMAN: continue
            notes.append({"text": ins.get("text") or "",
                          "who":  ins.get("who") or "",
                          "when": ins.get("when") or "",
                          "product": path})
    notes.sort(key=lambda n: (-_iso_to_ord(n["when"]), n["product"]))

    def _chip(family):
        if not family: return ""
        return (f'<a class="wti-path" href="#prod-{_esc(family)}" '
                f'data-jump-path="{_esc(family)}">{_esc(family)}</a>')

    parts = ['<div class="wwl-section">',
             '<h2>What we\'ve learned</h2>',
             '<div class="sub">The headline numbers from the team\'s EDA '
             'notebooks first, then the rest of the curated findings. '
             'Every product chip jumps to that product\'s card.</div>']

    # ---- 1. Hero stat cards ------------------------------------------------
    if heroes:
        parts.append('<div class="wwl-stats">')
        for x in heroes:
            stat = x.get("stat") or ""
            # Long stats (e.g. 'R (approx) 0.67') drop one type-scale step so the
            # card row keeps a shared baseline; short ones get the full hero size.
            size_cls = " long" if len(stat) > 5 else ""
            chip = _chip(x.get("family"))
            nb = (f'<span class="wwl-stat-nb">EDA nb {_esc(x["nb"])}</span>'
                  if x.get("nb") else "")
            sep = " &middot; " if chip and nb else ""
            parts.append(
                f'<div class="wwl-stat" title="{_esc(x.get("detail") or "")}">'
                f'<div class="wwl-stat-num{size_cls}">{_esc(stat)}</div>'
                f'<div class="wwl-stat-take">{_esc(x["headline"])}</div>'
                f'<div class="wwl-stat-meta">{chip}{sep}{nb}</div>'
                '</div>')
        parts.append('</div>')

    # ---- 2. Team notes (human insights, prominent) -------------------------
    NOTES_VISIBLE = 5
    parts.append('<h3 class="wwl-subhead">Team notes</h3>')
    if not notes:
        # Compact one-liner empty state (the old keyboard-cheatsheet teach
        # block was part of the wall; cut in the same de-walling pass).
        parts.append(
            '<div class="wwl-empty-team">No team notes on individual '
            'products yet &mdash; add the first with '
            '<span class="copy-cmd light">'
            '<code>python tools/product_scope.py --review acs/acs5 '
            '--insight "your observation"</code>'
            '<button data-copy=\'python tools/product_scope.py --review '
            'acs/acs5 --insight "your observation"\'>Copy</button></span>'
            '</div>')
    else:
        note_icon = INSIGHT_SOURCE_ICON.get(INSIGHT_HUMAN, "\U0001F464")
        def _note_row(n):
            meta_bits = [_chip(n["product"])]
            if n["when"]:
                when = _iso_to_dt(n["when"])
                rel = _rel_time_str(when) if when else n["when"][:10]
                meta_bits.append(f'<span title="{_esc(n["when"])}">{_esc(rel)}</span>')
            if n["who"]:
                meta_bits.append(_esc(n["who"]))
            meta = " &middot; ".join(b for b in meta_bits if b)
            return ('<li>'
                    f'<div class="wwl-ico">{note_icon}</div>'
                    '<div class="wwl-body">'
                    f'<div class="wwl-head">{_esc(n["text"])}</div>'
                    + (f'<div class="wwl-meta">{meta}</div>' if meta else "")
                    + '</div></li>')
        parts.append('<ul class="wwl-list">')
        parts.extend(_note_row(n) for n in notes[:NOTES_VISIBLE])
        parts.append('</ul>')
        extra_notes = notes[NOTES_VISIBLE:]
        if extra_notes:
            parts.append(
                f'<details class="wwl-more disc" data-persist-key="wwl_notes_all">'
                f'<summary>Show {len(extra_notes)} more note'
                f'{"s" if len(extra_notes) != 1 else ""}</summary>'
                '<ul class="wwl-list" style="border-top:1px solid var(--ice)">')
            parts.extend(_note_row(n) for n in extra_notes)
            parts.append('</ul></details>')

    # ---- 3. More findings (remaining curated, compact one-liners) ----------
    FIND_VISIBLE = 5
    def _find_row(x):
        stat_html = f'<b>{_esc(x["stat"])}</b> ' if x.get("stat") else ""
        meta_bits = [_chip(x.get("family"))]
        if x.get("nb"):
            meta_bits.append(f'EDA nb {_esc(x["nb"])}')
        meta = " &middot; ".join(b for b in meta_bits if b)
        # Full detail sentence rides in the tooltip so the row stays one line.
        return (f'<li title="{_esc(x.get("detail") or "")}">'
                f'<div class="wwl-ico">{WWL_ICON_CURATED}</div>'
                '<div class="wwl-body">'
                f'<div class="wwl-head">{stat_html}{_esc(x["headline"])}</div>'
                + (f'<div class="wwl-meta">{meta}</div>' if meta else "")
                + '</div></li>')
    if rest:
        parts.append('<h3 class="wwl-subhead">More findings</h3>')
        parts.append('<ul class="wwl-list">')
        parts.extend(_find_row(x) for x in rest[:FIND_VISIBLE])
        parts.append('</ul>')
        overflow = rest[FIND_VISIBLE:]
        if overflow:
            parts.append(
                f'<details class="wwl-more disc" data-persist-key="wwl_show_all">'
                f'<summary>Show {len(overflow)} more finding'
                f'{"s" if len(overflow) != 1 else ""}</summary>'
                '<ul class="wwl-list" style="border-top:1px solid var(--ice)">')
            parts.extend(_find_row(x) for x in overflow)
            parts.append('</ul></details>')

    # ---- 4. Full team log link ---------------------------------------------
    n_wl = len(worklog or [])
    entries_note = f', {n_wl} dated entries' if n_wl else ''
    parts.append(
        f'<div class="wwl-tail">Looking for the day-by-day narrative? '
        f'<a href="{_esc(wl_url)}" target="_blank" rel="noopener">'
        f'Full team log &rarr;</a> (WORKLOG.md{entries_note}). '
        'Process notes live there; auto-generated drift signals stay on '
        'the product cards. Prefer the plain-English write-up behind these '
        f'numbers? <a href="{_esc(PHASE1_REPORT_PATH)}" target="_blank" '
        f'rel="noopener">Phase 1 findings report &rarr;</a> '
        f'({_esc(PHASE1_REPORT_MIN_READ)}).</div>')
    parts.append('</div>')
    return "".join(parts)

# ============================================================================
# HOME TAB "CENSUS DATA LANDSCAPE" VIZ (redesign 2026-07-26)
# ============================================================================
# Stacked squarified treemap: one full-width row per kind, program boxes laid
# out inside each row with a minimum-size floor so every box has a visible
# always-on label (no more hover-only slivers). Rows are ordered largest kind
# first and their height is proportional to product-count share.
#
# Layout, per row:
#   * Header strip: kind name (Georgia bold) + product count + "top:" line
#     listing the three largest programs so a reader gets a scannable summary
#     even before scanning the boxes.
#   * Treemap slice: Bruls et al. (2000) squarified layout with a post-layout
#     spill pass - if the smallest program's box falls below the min-legibility
#     floor (MIN_W x MIN_H), pop it, re-squarify with more area for the rest,
#     and repeat until every visible box clears the floor. Spilled programs
#     render below the SVG as a compact "+ N more programs" <details> chip.
#   * Kind-tinted background: a very subtle hue per kind (warm beige /
#     cool blue-grey / soft green / neutral) breaks up the "wall of grey"
#     that reads as an abandoned dashboard when every tier is untouched.
#
# Each program box carries a data-landscape-prog attribute (the delegated JS
# click handler downstream reuses the existing filter-jump logic - unchanged
# from the pre-redesign version). Color = highest team-reach tier reached
# anywhere in the program's products: grey (untouched), blue (repo evidence
# only), teal (metadata fetched), green (data peeked).
#
# Design notes:
#   * Layout computed server-side in Python at render time. Pure SVG per row,
#     plus small HTML disclosures for overflow. No D3, no CDN, no JS-only
#     rendering. Vanilla JS only for the click delegation.
#   * Readable with JS off: SVG geometry + always-on labels convey the whole
#     message; hover tooltips via native <title>; click drills only work
#     with JS.
#   * Squarified algorithm: at each recursion, walk the shorter side of the
#     remaining rectangle, accumulating siblings into a row while the worst
#     aspect ratio of the row improves; when adding the next sibling would
#     make the worst aspect worse, close the row and recurse.

# Total viz width. Height is dynamic - each kind row sizes itself; total
# stacks up between ~700-900 px depending on kind mix.
LSCAPE_SVG_W = 1000

# Per-kind row sizing. Header strip stays fixed; treemap slice height is
# share-proportional between a floor (so singletons still fit at least one
# labeled box) and a cap (so the biggest kinds don't blow the fold entirely).
# The main loop also auto-grows row height (up to the hard cap) when spill
# would exceed LSCAPE_MAX_SPILL programs - see build_landscape_viz().
LSCAPE_HEADER_H  = 44    # kind header strip (name + count + top-3 line)
LSCAPE_ROW_PAD   = 8     # inner padding around the program treemap slice
LSCAPE_ROW_MIN_H = 44    # min treemap-slice height (one MIN_H row + a hair)
LSCAPE_ROW_MAX_H = 280   # hard cap on treemap-slice height (auto-grow ceiling)
                         # (340 -> 280 in the condense pass 2026-07-26 so the
                         # biggest kind row can't dominate the Home fold)
LSCAPE_ROW_BASE  = 640   # share * base = initial target inner height
LSCAPE_MAX_SPILL = 2     # acceptable spilled programs per kind before auto-grow

# Minimum on-screen size for a program box so its label always renders
# legibly. Tuned so 10px font + ellipsis fits comfortably; smaller boxes
# fall into the "+ N more programs" spill drawer below the row.
LSCAPE_MIN_BOX_W = 76
LSCAPE_MIN_BOX_H = 30

# Size-compression exponent applied to product counts before squarify. A
# pure linear layout (exp=1.0) squeezes singletons to unreadable slivers
# when one program dominates (SIPP is 176 of 235 Microdata products); an
# exponent of ~0.65 keeps SIPP visibly the largest but gives small
# programs enough relative area to clear the min-box floor. This is a
# monotonic visual re-weighting only - the true product count still shows
# on every box label and in the tooltip.
LSCAPE_SIZE_EXP  = 0.65

# Padding between adjacent program boxes so they read as distinct tiles.
LSCAPE_PAD_PROG = 5

# 4-tier color palette (Phase A #1 counter-consolidation: now maps 1:1 to
# pipeline stages, sharing vocabulary with the tier rail + Sankey rather than
# defining its own "repo evidence" concept). Grey = cataloged (untouched by
# the pipeline), the three deeper stages were bumped in saturation from the
# prior version so that when a program IS at a deeper stage it pops off the
# row. Fill + stroke chosen so a color-blind reader can still separate tier-1
# (blue) from tier-2 (teal) via lightness + stroke.
LSCAPE_TIER_FILL = {
    0: "#ECEEF5",   # grey  - cataloged (default catalog-only state)
    1: "#B7CDF6",   # blue  - probed (API metadata fetched)
    2: "#8BD3CC",   # teal  - sampled (data slice pulled)
    3: "#8FCD97",   # green - reviewed (uncertainty notes written)
}
LSCAPE_TIER_STROKE = {
    0: "#CBD1E0",
    1: "#5A7ED1",
    2: "#3D9E93",
    3: "#3E9152",
}
LSCAPE_TIER_LABEL = {
    0: "cataloged",
    1: "probed",
    2: "sampled",
    3: "reviewed",
}
# Stage-name index -> pipeline-stage string, so the legend counts pull from
# _tier_counts() with a fixed left-to-right order.
LSCAPE_TIER_STAGE = {0: "cataloged", 1: "probed", 2: "sampled", 3: "reviewed"}

# Subtle per-kind row tint. Each kind gets a distinct low-saturation hue for
# the row background so the four rows read as four distinct bands even when
# every program box is grey (untouched). Border color echoes the tint at a
# slightly darker step.
LSCAPE_KIND_TINT = {
    "Aggregate tables": {"bg": "#FDF7EB", "border": "#EAD9B0", "accent": "#B58A3E"},
    "Microdata":        {"bg": "#F1F5FD", "border": "#C9D8F1", "accent": "#3A5DA3"},
    "Time series":      {"bg": "#EEF7F0", "border": "#C8E1CE", "accent": "#3E7A4E"},
    "Uncategorized":    {"bg": "#F5F5F7", "border": "#DCDEE6", "accent": "#5A6072"},
}

def _prog_tier(fams_in_prog, work, probes, data_cache, review=None):
    """Legacy 3-tier reach summary. Retained for callers that only need
       'has any signal?' semantics. See _prog_tier4() for the treemap-color
       version aligned to pipeline stages."""
    tier = 0
    review = review or {}
    for f in fams_in_prog:
        path = f["path"]
        if _has_review_signal(review.get(path) or {}):
            return 2      # reviewed = deepest, short-circuit
        if (data_cache or {}).get(path):
            tier = max(tier, 2); continue
        pe = (probes or {}).get(path)
        if isinstance(pe, dict) and pe.get("ok"):
            tier = max(tier, 1)
            continue
        prod = f.get("product")
        if prod and (work or {}).get(prod, {}).get("status", 0) > 0:
            tier = max(tier, 1)
    return tier

# Priority index for _prog_tier4() - matches LSCAPE_TIER_LABEL indices so
# fill/stroke lookups stay in sync. Deeper stage index = deeper pipeline
# stage. Sampling and probing bypass "reviewed" ONLY if uncertainty_metrics
# wasn't backfilled, but the priority order below prefers reviewed first
# so a backfilled family in the program lights up as green regardless of
# whether the API paths were probed/sampled.
_PIPELINE_STAGE_INDEX = {"cataloged": 0, "probed": 1, "sampled": 2, "reviewed": 3}

def _prog_tier4(fams_in_prog, work, probes, data_cache, review=None):
    """4-tier reach summary for the SVG treemap color palette (Phase A #1:
    now aligned to pipeline stages, so a program's color reflects the deepest
    _tier_counts() stage any of its families reached):
       0 - cataloged (all families are catalog-listed only)
       1 - probed (at least one family present in product_probes with ok=True)
       2 - sampled (at least one family present in scope_data_cache)
       3 - reviewed (at least one family has _has_review_signal() = True)
    Reviewed beats sampled beats probed beats cataloged. Repo evidence
    (work) is no longer promoted to its own tier - it was a WEAK signal
    (any grep hit anywhere) that conflicted with pipeline vocabulary.
    Repo evidence is still surfaced in the treemap tooltip below."""
    tier = 0
    review = review or {}
    for f in fams_in_prog:
        path = f["path"]
        # Reviewed short-circuits: it's the deepest tier we track.
        if _has_review_signal(review.get(path) or {}):
            return 3
        if (data_cache or {}).get(path):
            tier = max(tier, 2)
            continue
        pe = (probes or {}).get(path)
        if isinstance(pe, dict) and pe.get("ok"):
            tier = max(tier, 1)
    return tier

def _squarify(sizes, x, y, w, h):
    """Bruls et al. (2000) squarified treemap.

    Given a list of positive `sizes` (any units - internally scaled to the
    (w * h) area budget) and a bounding rectangle at (x, y) with width w and
    height h, return a list of (rx, ry, rw, rh) rectangles - one per size,
    order-preserving with respect to the input `sizes`.

    The goal is a layout where the individual rectangles are as close to
    squares as possible (minimising the worst aspect ratio in each row),
    which is easier for the eye to compare than the extreme rectangles that
    a naive row-by-row layout produces.

    Degenerate inputs are handled by returning zero-area rectangles at the
    origin: the caller can detect these and fall back to a simple flex row
    without crashing the whole regen.
    """
    n = len(sizes)
    if n == 0:
        return []
    if w <= 0 or h <= 0:
        return [(x, y, 0.0, 0.0)] * n
    total = sum(s for s in sizes if s > 0)
    if total <= 0:
        return [(x, y, 0.0, 0.0)] * n
    # Scale sizes so they sum to the rectangle's area.
    scale = (w * h) / total
    areas = [max(0.0, s) * scale for s in sizes]
    # Squarified algorithm sorts largest-first for better aspect ratios;
    # remember the original position so we can return an index-aligned list.
    order = sorted(range(n), key=lambda i: -areas[i])
    ordered_areas = [areas[i] for i in order]
    layout = []
    _sq_recurse(ordered_areas, x, y, w, h, layout)
    result = [None] * n
    for slot, orig_i in enumerate(order):
        result[orig_i] = layout[slot]
    return result

def _worst_aspect(row, side):
    """Worst aspect ratio for the row (list of areas) when laid out along
    the shorter side of length `side`. Larger = worse (further from square).
    Infinity for degenerate inputs so a row of zero-area sizes never gets
    picked over a non-degenerate alternative."""
    if not row or side <= 0:
        return float("inf")
    total = sum(row)
    if total <= 0:
        return float("inf")
    max_a = max(row); min_a = min(row)
    s2 = side * side
    return max((s2 * max_a) / (total * total),
               (total * total) / (s2 * min_a))

def _sq_recurse(areas, x, y, w, h, out):
    """Walk the remaining rectangle, closing rows as adding the next area
    would worsen the worst aspect ratio. Places each closed row along the
    shorter side of the current rectangle, then recurses into what's left."""
    if not areas:
        return
    if len(areas) == 1:
        out.append((x, y, w, h))
        return
    side = min(w, h)
    if side <= 0:
        for _ in areas:
            out.append((x, y, 0.0, 0.0))
        return
    row = []
    idx = 0
    while idx < len(areas):
        cand = row + [areas[idx]]
        if not row or _worst_aspect(cand, side) <= _worst_aspect(row, side):
            row = cand
            idx += 1
        else:
            break
    # Place `row` along the shorter side of the current rectangle.
    row_sum = sum(row)
    if w <= h:
        # Row runs horizontally across the full width; height = row_sum / w.
        rh = row_sum / w if w > 0 else 0
        rx = x
        for a in row:
            rw = a / rh if rh > 0 else 0
            out.append((rx, y, rw, rh))
            rx += rw
        _sq_recurse(areas[len(row):], x, y + rh, w, h - rh, out)
    else:
        # Row runs vertically down the full height; width = row_sum / h.
        rw = row_sum / h if h > 0 else 0
        ry = y
        for a in row:
            rh = a / rw if rw > 0 else 0
            out.append((x, ry, rw, rh))
            ry += rh
        _sq_recurse(areas[len(row):], x + rw, y, w - rw, h, out)

def _lscape_prog_text_svg(pname, n, tier, rx, ry, rw, rh):
    """Emit the SVG text label(s) for a program box. Every box is guaranteed
    to render its program name (thanks to the min-box floor + spill pass in
    _squarify_with_floor); this function just picks a font size that fits
    and truncates the name to the box width with ellipsis. Count line renders
    below the name when the box is tall enough (>= 44 px). Font size scales
    12 -> 11 -> 10 -> 9 as the box shrinks; never below 9 so the label stays
    legible at web zoom. Ink color contrasts against the tier fill."""
    # Adaptive font size: prefer 12 for tall/wide boxes, step down for narrow.
    if rw >= 130 and rh >= 34:
        name_fs = 12
    elif rw >= 100 and rh >= 30:
        name_fs = 11
    elif rw >= 80 and rh >= 26:
        name_fs = 10
    else:
        name_fs = 9
    # ~0.52 * font-size per character for a proportional sans-serif at web
    # weights; leave 6 px padding on each side. Guarantee at least 4 chars so
    # even the tightest legible slot shows meaningful truncation.
    char_w = max(4.6, name_fs * 0.52)
    max_chars = max(4, int((rw - 10) / char_w))
    label = pname if len(pname) <= max_chars else pname[:max_chars - 1] + "…"
    # Darker ink on lighter (grey/blue) tiers; navy stays readable on all four
    # because the palette is intentionally low-contrast on the touched tiers.
    font_ink = "#0F1738" if tier == 0 else "#0E1B4A"
    # Vertical layout: name center-y sits at roughly one-third from the top so
    # the count line can sit under it without touching the bottom edge.
    if rh >= 44:
        name_y = ry + rh * 0.42
        cnt_y  = name_y + name_fs + 4
        parts = [
            f'<text x="{rx + rw / 2:.1f}" y="{name_y:.1f}" '
            f'text-anchor="middle" font-size="{name_fs}" font-weight="700" '
            f'fill="{font_ink}" pointer-events="none">{_esc(label)}</text>',
            f'<text x="{rx + rw / 2:.1f}" y="{cnt_y:.1f}" '
            f'text-anchor="middle" font-size="{max(9, name_fs - 2)}" '
            f'font-family="ui-monospace,Consolas,monospace" '
            f'fill="#5A6072" pointer-events="none">{n}</text>',
        ]
    else:
        # Short box: name only, vertically centered.
        name_y = ry + rh / 2 + name_fs * 0.35
        parts = [
            f'<text x="{rx + rw / 2:.1f}" y="{name_y:.1f}" '
            f'text-anchor="middle" font-size="{name_fs}" font-weight="700" '
            f'fill="{font_ink}" pointer-events="none">{_esc(label)}</text>',
        ]
    return "".join(parts)

def _lscape_kind_head_svg(kind, total, n_progs, prog_items_by_size,
                           kx, ky, kw, accent_color):
    """Emit the SVG header strip for a kind row: kind name (left), product
    count (right), and a small "top:" line naming the three largest programs
    inline. The top-3 gives the reader a scannable summary of what's in this
    kind even before their eye reaches the treemap boxes below.

    `prog_items_by_size` is a list of (program_name, product_count) tuples
    already sorted descending by count. `accent_color` is the kind's tint
    accent (used to underline the kind name as a subtle row identifier)."""
    top3 = prog_items_by_size[:3]
    top_line = " · ".join(f"{pn} ({n})" for pn, n in top3)
    top_prefix = "top:" if len(prog_items_by_size) > 3 else "all:"
    # Truncate the top line if it would spill outside the header width.
    max_top_chars = max(24, int((kw - 220) / 6.0))  # 220 px reserved for the count text right side
    if len(top_line) > max_top_chars:
        top_line = top_line[:max_top_chars - 1] + "…"
    return (
        # Kind name (left)
        f'<text x="{kx + 12:.1f}" y="{ky + 22:.1f}" '
        f'font-family="Georgia,serif" font-size="16" font-weight="700" '
        f'fill="#1F2A5C" pointer-events="none">{_esc(kind)}</text>'
        # Subtle underline accent under the kind name in the kind's tint
        f'<rect x="{kx + 12:.1f}" y="{ky + 26:.1f}" '
        f'width="34" height="2" fill="{accent_color}" opacity="0.55" '
        f'pointer-events="none"/>'
        # Product / program count summary (right)
        f'<text x="{kx + kw - 12:.1f}" y="{ky + 22:.1f}" '
        f'text-anchor="end" font-family="ui-monospace,Consolas,monospace" '
        f'font-size="12" font-weight="600" fill="#3A4256" pointer-events="none">'
        f'{total} product{"s" if total != 1 else ""} &#183; {n_progs} program'
        f'{"s" if n_progs != 1 else ""}</text>'
        # "top:" summary line (below name)
        f'<text x="{kx + 12:.1f}" y="{ky + 39:.1f}" '
        f'font-size="11" fill="#5A6072" pointer-events="none">'
        f'<tspan font-weight="700" fill="#3A4256">{top_prefix}</tspan> '
        f'{_esc(top_line)}</text>'
    )

def _squarify_with_floor(sizes, x, y, w, h, min_w, min_h):
    """Squarify with a minimum-box-size floor.

    Runs the normal Bruls et al. layout. If any resulting rectangle falls
    below (min_w, min_h), drops the smallest input from the layout, re-runs
    with more area for the survivors, and repeats until every visible rect
    clears the floor OR the survivor list is empty.

    Returns (rects_for_kept, kept_orig_indices, spilled_orig_indices).
    Both index lists are in original input order; rects_for_kept is aligned
    to kept_orig_indices."""
    n = len(sizes)
    if n == 0 or w <= 0 or h <= 0:
        return [], [], list(range(n))
    # Sort largest-first, remembering original index.
    order = sorted(range(n), key=lambda i: -sizes[i])
    kept = list(order)              # largest-first
    spilled = []                    # in spill-order (smallest first)
    while kept:
        kept_sizes = [sizes[i] for i in kept]
        rects_kept_order = _squarify(kept_sizes, x, y, w, h)
        # Any rect below the floor? If yes, spill the smallest kept and retry.
        bad = any(rw < min_w or rh < min_h
                  for (_rx, _ry, rw, rh) in rects_kept_order)
        if not bad:
            # Reorder rects back to original input order for the kept subset.
            kept_original = sorted(kept)
            # rects_kept_order is aligned to `kept` (largest-first). We want
            # rects aligned to kept sorted by original index for callers.
            pos = {orig_i: rect for orig_i, rect in zip(kept, rects_kept_order)}
            rects_out = [pos[i] for i in kept_original]
            return rects_out, kept_original, sorted(spilled)
        # Spill the smallest kept (which is the last element since
        # `kept` is largest-first).
        spilled.append(kept.pop())
    # Everything spilled - no boxes big enough. Caller falls back to chip row.
    return [], [], sorted(spilled + kept)

def _lscape_prog_fallback_html(kind, progs, prog_names, work, probes,
                                data_cache, warn=True, review=None):
    """Graceful degradation for a kind whose treemap layout failed (e.g.
    every program had zero product count) or whose bounding rect is too
    small to render proportional inner boxes. Renders a plain flex row of
    program chips so the reader still sees the vocabulary even if the
    proportional viz can't. `warn=True` emits a stderr line so a real
    failure is visible in the regen log; pass warn=False for the expected
    tiny-kind case (e.g. Uncategorized with one product)."""
    if warn:
        print(f"  [landscape] squarified layout failed for kind '{kind}' - "
              f"falling back to flex row", file=sys.stderr)
    chips = []
    for pname in prog_names:
        items = progs[pname]
        n = len(items)
        tier = _prog_tier4(items, work, probes, data_cache, review=review)
        chips.append(
            f'<div class="lscape-fallback-chip lscape-tier-{tier}" '
            f'data-landscape-prog="{_esc(pname)}" '
            f'title="{_esc(pname)} - {n} product{"s" if n != 1 else ""}">'
            f'{_esc(pname)} <em>{n}</em></div>')
    return (f'<div class="lscape-fallback"><div class="lscape-fallback-head">'
            f'{_esc(kind)}</div><div class="lscape-fallback-row">'
            + "".join(chips) + '</div></div>')

def _lscape_prog_box_svg(pname, items, work, probes, data_cache, kind,
                          total_in_kind, frx, fry, frw, frh, review=None):
    """Render a single program box as an SVG <g>. Extracted so both the main
    treemap loop and any future reuse (e.g. spill mini-boxes) share one code
    path for tooltip + accessibility metadata."""
    n = len(items)
    tier = _prog_tier4(items, work, probes, data_cache, review=review)
    reached = sum(1 for f in items
                   if (data_cache or {}).get(f["path"]) or
                      ((probes or {}).get(f["path"]) or {}).get("ok") or
                      _has_review_signal((review or {}).get(f["path"]) or {}) or
                      (f.get("product") and
                       (work or {}).get(f.get("product"), {}).get("status", 0) > 0))
    reviewed_n = sum(1 for f in items
                     if _has_review_signal((review or {}).get(f["path"]) or {}))
    sampled = sum(1 for f in items
                  if (data_cache or {}).get(f["path"]))
    share_pct = (100.0 * n / total_in_kind) if total_in_kind else 0.0
    # Tooltip now leads with the pipeline vocabulary matching the top-of-page
    # counters, and calls out reviewed products alongside sampled so the
    # program's deliverable-progress reads at a glance.
    tip = (f"{pname} — {n} product"
           f"{'s' if n != 1 else ''}, {share_pct:.1f}% of {kind}"
           f" · {reviewed_n} reviewed · {sampled} sampled · {reached} touched")
    fill = LSCAPE_TIER_FILL.get(tier, LSCAPE_TIER_FILL[0])
    stroke = LSCAPE_TIER_STROKE.get(tier, LSCAPE_TIER_STROKE[0])
    # Slightly heavier stroke on non-grey tiers so touched programs pop off
    # the row; 0.75 stays on grey to keep untouched programs visually quiet.
    stroke_w = 1.25 if tier > 0 else 0.75
    return (
        f'<g class="lscape-prog lscape-tier-{tier}" '
        f'data-landscape-prog="{_esc(pname)}" '
        f'tabindex="0" role="button" '
        f'aria-label="{_esc(tip)}">'
        f'<title>{_esc(tip)}</title>'
        f'<rect x="{frx:.1f}" y="{fry:.1f}" width="{frw:.1f}" '
        f'height="{frh:.1f}" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{stroke_w}" rx="3" ry="3"/>'
        + _lscape_prog_text_svg(pname, n, tier, frx, fry, frw, frh)
        + '</g>')

def _lscape_spill_details_html(kind, spilled_progs, work, probes, data_cache,
                                review=None):
    """Render the "+ N more programs" disclosure that follows a kind row when
    squarify + min-floor spilled some programs. Uses <details>/<summary> for
    native accessibility - no JS required. Chips reuse the existing
    .lscape-fallback-chip class so the drill click handler picks them up."""
    if not spilled_progs:
        return ""
    n_spill = sum(len(items) for _, items in spilled_progs)
    n_prog = len(spilled_progs)
    # Preview: names of the first 3 spilled programs on the summary line.
    preview_names = [p for p, _ in spilled_progs[:3]]
    preview = " · ".join(preview_names)
    if n_prog > 3:
        preview += " · …"
    chips = []
    for pname, items in spilled_progs:
        n = len(items)
        tier = _prog_tier4(items, work, probes, data_cache, review=review)
        chips.append(
            f'<div class="lscape-fallback-chip lscape-tier-{tier}" '
            f'data-landscape-prog="{_esc(pname)}" tabindex="0" role="button" '
            f'title="{_esc(pname)} - {n} product{"s" if n != 1 else ""}">'
            f'{_esc(pname)} <em>{n}</em></div>')
    return (
        f'<details class="lscape-spill disc">'
        f'<summary><span class="lscape-spill-count">+{n_prog} more '
        f'program{"s" if n_prog != 1 else ""}</span> '
        f'<span class="lscape-spill-preview">{_esc(preview)}</span> '
        f'<span class="lscape-spill-total">({n_spill} product'
        f'{"s" if n_spill != 1 else ""})</span></summary>'
        f'<div class="lscape-fallback-row lscape-spill-chips">'
        + "".join(chips) + '</div></details>')

def _kind_slug(kind):
    """CSS-safe kind slug for per-row class hooks (e.g. 'Aggregate tables'
    -> 'aggregate-tables')."""
    return re.sub(r'[^a-z0-9]+', '-', kind.lower()).strip('-') or "kind"

def _lscape_row_inner_h(share, n_progs):
    """Compute the treemap-slice height for a kind row given its share of
    total product count and how many programs it holds. Floor + cap keep
    singleton kinds from disappearing and the biggest kinds from dominating."""
    # Base target: linear in share.
    target = share * LSCAPE_ROW_BASE
    # Boost floor a bit when there are more programs to give squarify room to
    # place multiple rows of boxes above the floor.
    row_min = LSCAPE_ROW_MIN_H if n_progs <= 1 else max(LSCAPE_ROW_MIN_H, 78)
    return int(max(row_min, min(LSCAPE_ROW_MAX_H, target)))

# ============================================================================
# SANKEY RESEARCH PIPELINE (UX pass 2026-07-26 commit #3)
# ============================================================================
# Compact 4-stage flow diagram: Catalog -> Probed -> Sampled -> Reviewed.
# Renders ABOVE the landscape treemap on Home. Different question from the
# treemap: "where in the pipeline are we?" vs "what's the shape of the space?"
# Pure SVG - Bezier ribbons + node rectangles - no libraries. ~150 LOC.

# Palette matches the pipeline rail from commit #2 so the eye reads the same
# vocabulary in two places. Each node's fill is that stage's swatch colour;
# the ribbon flowing INTO a stage is drawn in that stage's colour at low alpha.
SANKEY_STAGE_ORDER = ["catalog", "probed", "sampled", "reviewed"]
SANKEY_STAGE_LABEL = {
    "catalog":  "Cataloged",
    "probed":   "Probed",
    "sampled":  "Sampled",
    "reviewed": "Reviewed",
}
SANKEY_STAGE_FILL = {
    "catalog":  "#DDE3EE",
    "probed":   "#B7CDF6",
    "sampled":  "#8BD3CC",
    "reviewed": "#8FCD97",
}

def _sankey_cumulative_counts(pc):
    """Turn mutually-exclusive pipeline-stage counts into cumulative
    'reached-at-least' counts for the Sankey flow.

    Model: reviewed => implies sampled + probed; sampled => implies probed;
    probed => reached (obviously). Reviewed products in the current tool
    can bypass sampling and probing (uncertainty_metrics was backfilled from
    the phase-1 findings report, not from an API sample), but for the FLOW
    visual we treat each deeper tier as having conceptually passed through
    the shallower ones - otherwise the diagram would show three disconnected
    puddles rather than a pipeline.

    Returns: dict {stage: n} where n = # products that reached at least
    that stage. catalog is always the total.
    """
    return {
        "catalog":  pc["total"],
        "probed":   pc["probed"] + pc["sampled"] + pc["reviewed"],
        "sampled":  pc["sampled"] + pc["reviewed"],
        "reviewed": pc["reviewed"],
    }

def _sankey_ribbon_path(x1, y1t, y1b, x2, y2t, y2b):
    """Cubic Bezier ribbon path from a source stripe (x1, y1t..y1b) to a
    target stripe (x2, y2t..y2b). Standard sankey ribbon: horizontal control
    points at the midpoint x so the ribbon comes out flat on both ends.
    """
    mx = (x1 + x2) / 2.0
    # Top edge: (x1, y1t) -> curve -> (x2, y2t)
    # Bottom edge: (x2, y2b) -> curve -> (x1, y1b)
    return (
        f"M {x1:.2f} {y1t:.2f} "
        f"C {mx:.2f} {y1t:.2f}, {mx:.2f} {y2t:.2f}, {x2:.2f} {y2t:.2f} "
        f"L {x2:.2f} {y2b:.2f} "
        f"C {mx:.2f} {y2b:.2f}, {mx:.2f} {y1b:.2f}, {x1:.2f} {y1b:.2f} Z"
    )

def build_sankey_pipeline(pc, embedded=False):
    """Emit an inline-SVG Sankey diagram for the four research-pipeline
    stages. `pc` is a _pipeline_counts() dict.

    embedded=False returns a full standalone section fragment (h2 + captions
    + wrap + SVG). embedded=True (the condense-pass default usage: the Sankey
    now lives INSIDE the "Where the team is" section as its lead visual)
    returns only the .sankey-wrap fragment - no section wrapper, no h2 -
    so the host section supplies the header and legend.
    Compact: ~180px SVG height, full-width. Click on any node jumps to the
    Products tab (handler wired in the shared inline <script>).
    """
    # Cumulative flow counts (reviewed implies sampled implies probed).
    cc = _sankey_cumulative_counts(pc)

    # SVG geometry.
    W = 1000                   # viewBox width
    H = 180                    # viewBox height
    top_pad = 30               # room for stage labels
    bot_pad = 40               # room for stage counts + "of N total"
    inner_h = H - top_pad - bot_pad   # 110 - the max node height
    node_w = 22
    total = cc["catalog"] or 1
    # Y-scale: pixels per unit product (max node = catalog = full inner_h).
    ypp = inner_h / total

    # Node x centers evenly spaced across the width.
    n_stages = len(SANKEY_STAGE_ORDER)
    x_left  = 90                       # room for the tallest left label
    x_right = W - 90
    x_step = (x_right - x_left) / (n_stages - 1)
    node_xs = [x_left + i * x_step for i in range(n_stages)]

    # Node rectangles: each centered on its x, height proportional to the
    # cumulative count. Anchor by TOP so all nodes hang from a shared baseline
    # (visually cleaner than centering when nodes span such different sizes).
    node_top_y = top_pad
    node_geoms = []   # per-stage: (x, y_top, y_bot, h, count)
    for i, stage in enumerate(SANKEY_STAGE_ORDER):
        n = cc[stage]
        h = max(2.0, n * ypp)          # 2px floor so a 0-count node stays visible
        cx = node_xs[i]
        node_geoms.append({
            "stage": stage, "n": n,
            "x": cx - node_w / 2, "y_top": node_top_y,
            "y_bot": node_top_y + h, "h": h,
            "cx": cx,
        })

    # Emit SVG.
    svg = [
        f'<svg class="sankey-svg" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet" '
        f'role="img" aria-label="Research pipeline flow: '
        f'{cc["catalog"]:,} cataloged, {cc["probed"]:,} probed, '
        f'{cc["sampled"]:,} sampled, {cc["reviewed"]:,} reviewed.">'
    ]

    # Ribbons: one per adjacent pair of stages, width = destination count
    # (the source count minus the drop = advance = destination count).
    # Ribbon attaches to the FULL height of the destination node and to the
    # TOP portion of the source node equal to that destination count.
    svg.append('<g class="sankey-ribbon-group">')
    for i in range(len(node_geoms) - 1):
        src = node_geoms[i]
        dst = node_geoms[i + 1]
        # Advance flow = destination count. Source stripe = top h_src px of
        # source (same # of units). Destination stripe = full destination.
        if dst["n"] <= 0 or src["n"] <= 0:
            continue
        adv_h = dst["n"] * ypp
        # Source right edge: (x = src.x + node_w, top = src.y_top,
        # bot = src.y_top + adv_h)
        x1 = src["x"] + node_w
        y1t = src["y_top"]
        y1b = src["y_top"] + max(2.0, adv_h)
        # Destination left edge: (x = dst.x, top = dst.y_top,
        # bot = dst.y_bot)
        x2 = dst["x"]
        y2t = dst["y_top"]
        y2b = dst["y_bot"]
        fill = SANKEY_STAGE_FILL[dst["stage"]]
        path = _sankey_ribbon_path(x1, y1t, y1b, x2, y2t, y2b)
        svg.append(
            f'<path class="sankey-ribbon" d="{path}" fill="{fill}" '
            f'stroke="none">'
            f'<title>{dst["n"]:,} advanced from {SANKEY_STAGE_LABEL[src["stage"]]} '
            f'to {SANKEY_STAGE_LABEL[dst["stage"]]}</title>'
            f'</path>')
    svg.append('</g>')

    # Nodes (drawn AFTER ribbons so nodes sit on top of ribbon edges).
    for g in node_geoms:
        stage = g["stage"]
        fill = SANKEY_STAGE_FILL[stage]
        label = SANKEY_STAGE_LABEL[stage]
        # Group: clickable, keyboard-focusable.
        svg.append(
            f'<g class="sankey-node" data-pipeline-stage="{stage}" '
            f'tabindex="0" role="button" '
            f'aria-label="{label}: {g["n"]:,} products. '
            f'Click to jump to the products tab.">'
        )
        svg.append(
            f'<rect class="sankey-node-rect" x="{g["x"]:.2f}" y="{g["y_top"]:.2f}" '
            f'width="{node_w}" height="{g["h"]:.2f}" rx="3" ry="3" '
            f'fill="{fill}"/>'
        )
        # Stage label ABOVE the node.
        svg.append(
            f'<text class="sankey-node-label" x="{g["cx"]:.2f}" '
            f'y="{g["y_top"] - 12:.2f}">{label}</text>'
        )
        # Count BELOW the node.
        svg.append(
            f'<text class="sankey-node-count" x="{g["cx"]:.2f}" '
            f'y="{g["y_bot"] + 18:.2f}">{g["n"]:,}</text>'
        )
        # "products" subtext (kept tiny to preserve the compact height).
        svg.append(
            f'<text class="sankey-node-sub" x="{g["cx"]:.2f}" '
            f'y="{g["y_bot"] + 32:.2f}">products</text>'
        )
        svg.append('</g>')

    svg.append('</svg>')

    wrap = (
        '<div class="sankey-wrap">'
        + "".join(svg) +
        '<div class="sankey-caption-bottom">'
        'Click any stage to jump to the Products tab.'
        '</div>'
        '</div>'
    )
    if embedded:
        return wrap
    return (
        '<div class="sankey-section">'
        '<h2>Research pipeline</h2>'
        '<div class="sankey-caption-top">'
        'How products move from the Census catalog to a fully reviewed '
        'uncertainty note. <b>Ribbon width</b> shows the number of products '
        'that carried forward to the next stage; the shrinking node stacks '
        'show how many dropped off along the way.'
        '</div>'
        + wrap +
        '</div>'
    )

def build_landscape_viz(fams, work, probes, data_cache, review=None):
    """Home-tab landscape: stacked full-width rows, one per dataset kind, each
    with its own squarified treemap of programs. Row height is proportional
    to product-count share (Aggregate biggest, Uncategorized slimmest). Every
    program box carries an always-on label - if squarify would produce a
    slot below the min-legibility floor we spill it into a compact
    "+ N more programs" disclosure at the end of the row. Pure SVG per row
    with an HTML disclosure for spill; delegated JS click handler unchanged.

    Phase A #1 counter-consolidation: `review` is now threaded in so program
    box color reflects the deepest pipeline stage among a program's families,
    matching the tier rail + Sankey vocabulary at the top of Home. The
    per-tier legend counts below the treemap ALSO come from _tier_counts()
    so all three counters agree.
    """
    review = review or {}

    # Group by kind, then by program group. Use catalog `group` (the human
    # program name) as the second level - matches the Products-tab section
    # heads so the reader learns the same vocabulary in two places.
    by_kind = {}
    for f in fams.values():
        by_kind.setdefault(f["kind"], {}).setdefault(f.get("group") or "Other",
                                                      []).append(f)

    kind_order = [k for k in KINDS if k in by_kind]
    total_products = sum(sum(len(v) for v in by_kind[k].values())
                         for k in kind_order)
    if total_products <= 0:
        return _all_flex_fallback(by_kind, kind_order, work, probes, data_cache,
                                   review=review)

    prog_boxes_rendered = 0
    spilled_boxes = 0
    row_html_parts = []
    smallest_box = None    # (pname, w*h) - reported in the caption

    # Treemap proportion tuning (condense pass 2026-07-26): only the two
    # largest kinds (currently Aggregate tables + Microdata, ~84% of all
    # products) render their treemap slice by default. The remaining kinds
    # (Time series, Uncategorized) collapse to slim header-only rows -
    # native <details> in the unified disc grammar, with per-kind
    # localStorage persistence via data-persist-key - so the default
    # visible treemap drops from ~1,150px to ~750px while every program
    # box stays one click away.
    kind_totals = {k: sum(len(v) for v in by_kind[k].values())
                   for k in kind_order}
    always_open_kinds = set(sorted(kind_order,
                                   key=lambda k: -kind_totals[k])[:2])

    for kind in kind_order:
        progs = by_kind[kind]
        total_in_kind = sum(len(v) for v in progs.values())
        # Largest-first ordering matches squarify's internal preference and
        # also drives the "top:" line in the header.
        prog_names = sorted(progs, key=lambda n: (-len(progs[n]), n))
        prog_sizes = [len(progs[p]) for p in prog_names]
        # Compressed sizes for layout only - real counts still surface in
        # labels + tooltips. Keeps SIPP visibly the biggest without
        # squeezing singletons to invisible slivers.
        prog_sizes_layout = [max(1e-6, s) ** LSCAPE_SIZE_EXP for s in prog_sizes]
        share = total_in_kind / total_products if total_products else 0.0
        inner_h = _lscape_row_inner_h(share, len(prog_names))
        inner_x = LSCAPE_ROW_PAD
        inner_y = LSCAPE_HEADER_H + LSCAPE_ROW_PAD
        inner_w = LSCAPE_SVG_W - LSCAPE_ROW_PAD * 2

        # Auto-grow row height to minimize spill. Squarify area-proportional
        # inherently squeezes tiny programs; growing the row gives them more
        # absolute area to clear the min-box floor. Cap at LSCAPE_ROW_MAX_H
        # so a kind with 15 singletons can't push the viz to 3000px tall.
        auto_rects_kept = []
        auto_kept_i = []
        auto_spilled_i = list(range(len(prog_names)))  # worst case: all spill
        if sum(prog_sizes) > 0:
            try_h = inner_h
            for _grow in range(6):
                try:
                    rk, ki, si = _squarify_with_floor(
                        prog_sizes_layout, inner_x, inner_y, inner_w, try_h,
                        LSCAPE_MIN_BOX_W, LSCAPE_MIN_BOX_H)
                except Exception as ex:
                    print(f"  [landscape] squarify failed for kind '{kind}' "
                          f"({ex}); degrading to flex fallback", file=sys.stderr)
                    rk, ki, si = [], [], list(range(len(prog_names)))
                    break
                # Prefer the pass that gave us more visible boxes so we always
                # take a monotonic improvement even if we bail out mid-loop.
                if len(ki) > len(auto_kept_i):
                    auto_rects_kept, auto_kept_i, auto_spilled_i = rk, ki, si
                    inner_h = try_h
                if len(si) <= LSCAPE_MAX_SPILL or try_h >= LSCAPE_ROW_MAX_H:
                    break
                # Grow ~35% and clamp to the hard cap; will re-squarify.
                try_h = min(int(try_h * 1.35) + 1, LSCAPE_ROW_MAX_H)
        row_svg_h = LSCAPE_HEADER_H + LSCAPE_ROW_PAD * 2 + inner_h

        tint = LSCAPE_KIND_TINT.get(kind, LSCAPE_KIND_TINT["Uncategorized"])
        # Row shell: background tint, rounded corners, kind slug for scoping.
        slug = _kind_slug(kind)
        svg_parts = [
            f'<svg class="lscape-kind-svg" xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {LSCAPE_SVG_W} {row_svg_h}" '
            f'width="100%" height="{row_svg_h}" role="img" '
            f'aria-label="{_esc(kind)}: {total_in_kind} products across '
            f'{len(prog_names)} program{"s" if len(prog_names) != 1 else ""}.">',
            # Row background fill (below program boxes)
            f'<rect x="0" y="0" width="{LSCAPE_SVG_W}" height="{row_svg_h}" '
            f'fill="{tint["bg"]}" rx="10" ry="10"/>',
            # Header divider (subtle underline separating header from treemap)
            f'<line x1="12" y1="{LSCAPE_HEADER_H - 1}" '
            f'x2="{LSCAPE_SVG_W - 12}" y2="{LSCAPE_HEADER_H - 1}" '
            f'stroke="{tint["border"]}" stroke-width="1"/>',
        ]
        # Header content (kind name, count summary, top-3 line)
        prog_size_pairs = list(zip(prog_names, prog_sizes))
        svg_parts.append(_lscape_kind_head_svg(
            kind, total_in_kind, len(prog_names), prog_size_pairs,
            0, 0, LSCAPE_SVG_W, tint["accent"]))

        # Guard against pathological data shape (zero total).
        if sum(prog_sizes) <= 0:
            svg_parts.append('</svg>')
            row_html_parts.append(
                f'<div class="lscape-kind-row" data-kind="{_esc(slug)}" '
                f'style="border-color:{tint["border"]}">'
                + "".join(svg_parts)
                + _lscape_prog_fallback_html(kind, progs, prog_names,
                                              work, probes, data_cache,
                                              warn=True, review=review)
                + '</div>')
            continue

        # Use the best pass captured by the auto-grow loop above.
        rects_kept = auto_rects_kept
        kept_orig_i = auto_kept_i
        spilled_orig_i = auto_spilled_i

        # Emit kept program boxes.
        for orig_i, rect in zip(kept_orig_i, rects_kept):
            rx, ry, rw, rh = rect
            pp = LSCAPE_PAD_PROG
            frx = rx + pp / 2
            fry = ry + pp / 2
            frw = max(0.0, rw - pp)
            frh = max(0.0, rh - pp)
            pname = prog_names[orig_i]
            items = progs[pname]
            svg_parts.append(_lscape_prog_box_svg(
                pname, items, work, probes, data_cache, kind,
                total_in_kind, frx, fry, frw, frh, review=review))
            prog_boxes_rendered += 1
            box_area = frw * frh
            if smallest_box is None or box_area < smallest_box[1]:
                smallest_box = (pname, box_area, frw, frh)

        svg_parts.append('</svg>')

        # Spill disclosure below the SVG (if any).
        spilled_pairs = [(prog_names[i], progs[prog_names[i]])
                         for i in spilled_orig_i]
        spilled_boxes += len(spilled_pairs)
        spill_html = _lscape_spill_details_html(
            kind, spilled_pairs, work, probes, data_cache,
            review=review) if spilled_pairs else ""

        # Assemble the row (SVG + optional spill disclosure) inside a
        # per-kind container so CSS can apply the tint border cleanly.
        row_core = (
            f'<div class="lscape-kind-row" data-kind="{_esc(slug)}" '
            f'style="border-color:{tint["border"]}">'
            + "".join(svg_parts)
            + spill_html
            + '</div>')
        if kind in always_open_kinds:
            row_html_parts.append(row_core)
        else:
            # Smaller kind: slim header-only row that expands on click.
            # Summary mirrors the kind header (name + count + top-3 line)
            # so nothing is lost while collapsed; the .disc-preview span
            # hides once the row is open (the SVG header repeats it).
            top3 = sorted(progs.items(),
                          key=lambda kv: (-len(kv[1]), kv[0]))[:3]
            top3_text = " &middot; ".join(
                f'{_esc(pn)} ({len(items)})' for pn, items in top3)
            top_prefix = "top" if len(prog_names) > 3 else "all"
            row_html_parts.append(
                f'<details class="lscape-kind-details disc" '
                f'data-persist-key="lscape_kind_{_esc(slug)}">'
                f'<summary>'
                f'<span class="lscape-kind-sum-name">{_esc(kind)}</span>'
                f'<span class="lscape-kind-sum-count">{total_in_kind}</span>'
                f'<span class="disc-preview">{top_prefix}: {top3_text}</span>'
                f'</summary>'
                + row_core +
                f'</details>')

    # Legend + counts summary. Phase A #1 consolidation: pulls from the same
    # `_tier_counts()` helper the top-of-Home tier rail and Sankey use, so
    # all three counters render identical numbers. Labels also align to the
    # pipeline stage vocabulary now (was "untouched / repo evidence /
    # metadata fetched / data peeked").
    tc = _tier_counts(fams, review, work, probes, data_cache)
    tier_counts = {0: tc["cataloged"], 1: tc["probed"],
                   2: tc["sampled"],   3: tc["reviewed"]}
    sampled_total = tc["sampled"]
    reviewed_total = tc["reviewed"]
    # "Advanced past cataloged" = anything beyond the default catalog listing.
    advanced_total = tc["probed"] + tc["sampled"] + tc["reviewed"]

    legend_bits = []
    for tier in (0, 1, 2, 3):
        legend_bits.append(
            f'<span class="lscape-legend-item"><span class="lscape-swatch '
            f'lscape-tier-{tier}" style="background:{LSCAPE_TIER_FILL[tier]};'
            f'border-color:{LSCAPE_TIER_STROKE[tier]}"></span>'
            f'<b>{LSCAPE_TIER_LABEL[tier]}</b> '
            f'<span class="lscape-legend-cnt">({tier_counts[tier]})</span></span>')

    caption = ('Every Census product family from the API catalog, stacked one '
               'row per dataset type. Box size is weighted by product count '
               '(squarified treemap - Bruls et al. 2000), mildly compressed '
               'so small programs stay legible next to giants like SIPP; the '
               'true product count for each program shows both on its box and '
               'in the hover tooltip. Color shows the deepest pipeline stage '
               'reached by any product in the slice - same vocabulary as the '
               'tier rail and Sankey at the top of Home. '
               '<b>Click any program to jump to the matching products.</b>')

    smallest_note = ""
    if smallest_box:
        _, _, sw, sh = smallest_box
        smallest_note = (f'&middot; smallest box {sw:.0f}&times;{sh:.0f} px')

    # Condense pass 2026-07-26: the treemap renders EXPANDED by default (it
    # is the chapter's centerpiece visual) but its footprint was tamed two
    # ways - the per-row height cap dropped 340 -> 280 and the two smaller
    # kinds collapse to slim header-only rows (see always_open_kinds above),
    # so the default paint is ~750px instead of ~1,150px. The compact text
    # summary below remains as the user-chosen COLLAPSED state ("Collapse
    # landscape" button), remembered per machine via localStorage
    # `product_scope:landscape_expanded`.
    compact_rows = []
    for kind in kind_order:
        progs = by_kind[kind]
        n_kind = sum(len(v) for v in progs.values())
        n_progs_in_kind = len(progs)
        top3 = sorted(progs.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:3]
        top3_text = " &middot; ".join(
            f'{_esc(pn)} <span class="lscape-compact-num">({len(items)})</span>'
            for pn, items in top3)
        top_prefix = "top" if n_progs_in_kind > 3 else "all"
        tint = LSCAPE_KIND_TINT.get(kind, LSCAPE_KIND_TINT["Uncategorized"])
        compact_rows.append(
            f'<div class="lscape-compact-row" data-kind="{_esc(_kind_slug(kind))}" '
            f'style="border-left-color:{tint["accent"]}">'
            f'<div class="lscape-compact-name">{_esc(kind)}</div>'
            f'<div class="lscape-compact-count">{n_kind}</div>'
            f'<div class="lscape-compact-top">'
            f'<span class="lscape-compact-topprefix">{top_prefix}:</span> '
            f'{top3_text}'
            f'</div>'
            f'</div>')

    return ('<div class="lscape-section" data-collapsible="landscape">'
            '<h2>The Census data landscape</h2>'
            # Scope statement (2026-07-26, dataset-count discussion): what
            # this inventory covers and what it deliberately does not, so
            # nobody quotes "~570 products" as the Bureau's total output.
            # Mirrored in tools/README.md; the open mentor question about
            # which other non-API products belong lives in the repo-root
            # README's "Open Questions for Mentors" list.
            '<div class="lscape-scope-note">'
            '~570 product families from the Census Data API catalog. The API '
            'covers ~1,800 dataset-vintages; the Bureau&rsquo;s full '
            'file-level catalog is larger (~6,000+ files counting every '
            'release) &mdash; non-API bulk products like TIGER shapefiles '
            'and DAS demonstration files are hand-added where relevant to '
            'our analysis.'
            '</div>'
            # Default state (condense pass 2026-07-26): treemap EXPANDED -
            # it is the chapter's centerpiece visual. The compact text
            # summary below is the user-chosen collapsed state (persisted
            # via localStorage `product_scope:landscape_expanded`); it ships
            # `hidden` so JS-off readers get the full visual.
            '<div class="lscape-compact" data-landscape-view="compact" hidden>'
            '<div class="lscape-compact-caption">'
            f'{len(fams):,} Census products across {len(kind_order)} dataset '
            'kinds. The treemap below shows each program sized by product '
            'count; expand it to explore. '
            '<b>Click a kind row to expand.</b>'
            '</div>'
            '<div class="lscape-compact-rows">'
            + "".join(compact_rows) +
            '</div>'
            '<button type="button" class="lscape-expand-btn" '
            'data-landscape-toggle aria-expanded="false" '
            'aria-controls="lscape-expanded-panel">'
            '<span class="lscape-expand-label">Expand landscape</span> '
            '<span class="lscape-expand-caret" aria-hidden="true">&#9656;</span>'
            '</button>'
            '</div>'
            '<div class="lscape-expanded" id="lscape-expanded-panel" '
            'data-landscape-view="expanded">'
            f'<div class="lscape-caption">{caption}</div>'
            f'<div class="lscape-viz">'
            + "".join(row_html_parts)
            + '</div>'
            '<div class="lscape-legend">'
            + "".join(legend_bits)
            + f'<span class="lscape-legend-summary">Pipeline reach: '
              f'{reviewed_total} reviewed &middot; {sampled_total} sampled '
              f'&middot; {advanced_total} advanced past cataloged '
              f'({len(fams)} total) &middot; {prog_boxes_rendered} program '
              f'box{"es" if prog_boxes_rendered != 1 else ""} rendered'
              f'{" &middot; " + str(spilled_boxes) + " in spill drawers" if spilled_boxes else ""}'
              f' {smallest_note}</span>'
            '</div>'
            '<button type="button" class="lscape-collapse-btn" '
            'data-landscape-toggle aria-expanded="true" '
            'aria-controls="lscape-expanded-panel">'
            '<span class="lscape-expand-caret" aria-hidden="true">&#9662;</span> '
            'Collapse landscape'
            '</button>'
            '</div>'
            '</div>')

def _all_flex_fallback(by_kind, kind_order, work, probes, data_cache, review=None):
    """Full-viz fallback for the (very unlikely) case where even the outer
    squarified layout blows up. Emits a plain flex row per kind so the reader
    still gets the vocabulary and reach coloring; loses only the areal comparison."""
    parts = ['<div class="lscape-section">',
             '<h2>The Census data landscape</h2>',
             '<div class="lscape-caption">SVG treemap layout unavailable; '
             'showing plain program list per kind.</div>']
    for kind in kind_order:
        progs = by_kind[kind]
        prog_names = sorted(progs, key=lambda n: (-len(progs[n]), n))
        parts.append(_lscape_prog_fallback_html(kind, progs, prog_names,
                                                  work, probes, data_cache,
                                                  review=review))
    parts.append('</div>')
    return "".join(parts)

def _iso_to_ord(when):
    """Turn an ISO-8601 string into a sortable float (POSIX seconds).
    0 on parse failure so unrecognised timestamps sort last with reverse
    sort. Kept tiny because build_what_learned() uses it in a sort key."""
    d = _iso_to_dt(when)
    return d.timestamp() if d else 0.0

# ============================================================================
# HOME-TAB "FIND A PRODUCT" SEARCH  (2026-07-26)
# ============================================================================
# Goal-directed lookup on the Home tab. Addresses the 4/10 gap from the last
# head-to-head audit against census.gov (which scored 9/10 on the same
# dimension). Leads the Get-oriented chapter, beside the 5-item curriculum:
# curriculum is the "no idea where to start" path; search is the "I have a
# question" path.
#
# All logic lives client-side (pure vanilla JS, no dependencies). The Python
# helper below emits three pieces: (1) a small JSON search index baked into
# the panel HTML, (2) the UI (text input + topic dropdown + geography-level
# dropdown + Clear button + results container), (3) an inline <script> block
# that debounces the input, filters + ranks the index, and re-renders the
# results list. Everything is scoped inside `#home-search` to avoid stepping
# on any existing Products-tab selectors.

# Geography-level keyword patterns, extracted from a product's title +
# description at render time because probes are currently empty and the
# catalog's dcat metadata does not carry per-product geography levels.
# First match wins; each product can carry more than one level. Patterns
# are matched case-insensitively via `.lower()` on the search text.
# Order = display order in the dropdown; the "nation" catch-all sits last
# so a description that mentions "national estimate for county totals"
# still picks up county first.
GEO_LEVEL_PATTERNS = [
    ("state",              r"\bstate\b|\bstates\b|state[-\s]?level"),
    ("county",             r"\bcount(y|ies)\b|county[-\s]?level"),
    ("tract",              r"\bcensus tract\b|\btracts?\b|tract[-\s]?level"),
    ("block group",        r"block[-\s]?groups?"),
    ("place",              r"\bplaces?\b|incorporated place|census designated place"),
    ("MSA",                r"metropolitan statistical|\bmsa\b|metropolitan area|"
                           r"micropolitan|\bcbsa\b|core based statistical"),
    ("ZCTA",               r"\bzcta\b|zip code tabulation|\bzip codes?\b"),
    ("congressional district", r"congressional district"),
    ("PUMA",               r"public use microdata area|\bpumas?\b"),
    ("region",             r"census region|\bregions?\b(?!al)"),
    ("division",           r"census division|\bdivisions?\b"),
    ("school district",    r"school district"),
    ("nation",             r"national|nationwide|united states|\bnation\b"),
]

# Plain-English topic tags, extracted from title + description at render
# time. Deliberately NOT the same list as the SUBJECTS regex above: this
# table uses topic names a non-specialist would type into a search box
# (Garrett's example vocabulary from the feature spec), so the Home
# search dropdown reads scannably instead of using Bureau-internal
# category names. The SUBJECTS-based `subject` field remains available
# to the free-text scorer (a user typing "Redistricting" still hits ACS)
# but doesn't populate the dropdown as its own axis - single canonical
# topic vocabulary keeps the UX simple.
#
# Each product can pick up MULTIPLE tags (first-match semantics per
# pattern, not first-match-wins across patterns). A product with the
# subject "Business & Economy" whose description also mentions
# "employment" and "veterans" therefore surfaces under all three axes.
#
# Order = display order in the dropdown; count-based re-sort happens
# client-side so the topic with the most matches floats to the top.
TOPIC_TAG_PATTERNS = [
    ("Housing",                r"\bhousing\b|\bhouseholds?\b|home ?ownership|"
                               r"rent(al|ers?)?|mortgage|vacanc"),
    ("Income & Poverty",       r"\bincome\b|earnings|poverty|\bwages?\b|"
                               r"program participation|food security"),
    ("Employment & Labor",     r"\bemploy|\bjobs?\b|labor force|unemployment|"
                               r"workers?|workforce|occupation"),
    ("Business & Economy",     r"\bbusiness(es)?\b|\becon|manufactur|wholesale|"
                               r"retail|\bindustr|nonemployer|entrepreneur|"
                               r"establishments?|payroll|receipts|\bfinanc"),
    ("Education",              r"\beducation\b|school enrollment|degree|graduate|"
                               r"library"),
    ("Health & Insurance",     r"\bhealth\b|\binsurance\b|disabilit|fertility"),
    ("Race & Ethnicity",       r"\brace\b|hispanic|ethnic|american indian|"
                               r"alaska native|native hawaiian|\basian\b|"
                               r"nativity|foreign born"),
    ("Age & Sex",              r"\bage\b|\bsex\b|\bmale\b|\bfemale\b|gender"),
    ("Migration & Mobility",   r"migration|mobility|residence one year|movers?"),
    ("Veterans",               r"\bveterans?\b"),
    ("Transportation",         r"transportation|commut|\bvehicles?\b|travel time"),
    ("International Trade",    r"international trade|\bimports?\b|\bexports?\b|"
                               r"commodity flow"),
    ("Public Finance & Government", r"public sector|government finance|"
                               r"tax collect|public pension|school system finance|"
                               r"government|\bpublic pension"),
    ("Population & Demographics", r"\bpopulation\b|demographic|redistricting|"
                               r"apportionment|census tract|summary file"),
]

# Human-friendly emoji per topic - keeps result cards visually scannable
# without pulling in an icon library. Neutral chart emoji for anything
# not on the list.
TOPIC_EMOJI = {
    "Housing":                     "\U0001F3E0",   # house
    "Income & Poverty":            "\U0001F4B5",   # dollar
    "Employment & Labor":          "\U0001F477",   # worker
    "Business & Economy":          "\U0001F3E2",   # office building
    "Education":                   "\U0001F393",   # graduation cap
    "Health & Insurance":          "\U0001FA7A",   # stethoscope
    "Race & Ethnicity":            "\U0001F30D",   # earth
    "Age & Sex":                   "\U0001F465",   # people silhouette
    "Migration & Mobility":        "\U0001F6EB",   # airplane
    "Veterans":                    "\U0001F396",   # military medal
    "Transportation":              "\U0001F697",   # car
    "International Trade":         "\U0001F4E6",   # package
    "Public Finance & Government": "\U0001F3DB",   # classical building
    "Population & Demographics":   "\U0001F465",
}

# Path-based topic overrides. The ACS / Decennial / PEP flagship
# descriptions are extremely generic (they say things like "characteristics
# of the U.S. population" rather than naming specific subjects), so
# pattern-matching against the description misses topics these products
# very obviously cover. These overrides ONLY apply to products the Bureau
# itself documents as multi-topic omnibus datasets. Each entry cites the
# authoritative source so we stay inside CLAUDE.md's "never bluff" rule -
# no invented topics, just topics the Bureau explicitly publishes.
#
# Source: https://www.census.gov/programs-surveys/acs/about/subjects.html
# (ACS subject list) + Decennial DHC + SF1 published subject lists +
# PEP + PDB documentation. Reviewed 2026-07-26 for the search-feature
# ship; extend if the mentors flag a missing coverage area.
PATH_TOPIC_OVERRIDES = {
    r"^acs/(acs1|acs5)$":            ["Housing", "Income & Poverty",
                                       "Employment & Labor", "Education",
                                       "Health & Insurance", "Race & Ethnicity",
                                       "Age & Sex", "Migration & Mobility",
                                       "Veterans", "Transportation",
                                       "Population & Demographics"],
    r"^acs/(acs1|acs5)/(subject|profile|cprofile)$":
                                     ["Housing", "Income & Poverty",
                                       "Employment & Labor", "Education",
                                       "Health & Insurance", "Race & Ethnicity",
                                       "Age & Sex", "Migration & Mobility",
                                       "Veterans", "Transportation",
                                       "Population & Demographics"],
    r"^acs/(acs1|acs5)/pums$":       ["Housing", "Income & Poverty",
                                       "Employment & Labor", "Education",
                                       "Race & Ethnicity", "Age & Sex",
                                       "Migration & Mobility", "Veterans",
                                       "Population & Demographics"],
    r"^dec/(dhc|sf1|sf2|pl|dp)$":    ["Housing", "Race & Ethnicity",
                                       "Age & Sex", "Population & Demographics"],
    r"^dec/das-demo$":               ["Housing", "Race & Ethnicity",
                                       "Age & Sex", "Population & Demographics"],
    r"^pep/(population|housing|charage|charagegroups|components)":
                                     ["Housing", "Age & Sex",
                                       "Race & Ethnicity", "Migration & Mobility",
                                       "Population & Demographics"],
    r"^pdb/(tract|blockgroup|state|county)$":
                                     ["Housing", "Income & Poverty",
                                       "Employment & Labor", "Race & Ethnicity",
                                       "Age & Sex", "Population & Demographics"],
    r"^cbp$":                        ["Business & Economy", "Employment & Labor"],
    r"^ecn":                         ["Business & Economy"],
    r"^abs":                         ["Business & Economy", "Race & Ethnicity",
                                       "Veterans"],
    r"^cps":                         ["Employment & Labor", "Income & Poverty",
                                       "Age & Sex", "Population & Demographics"],
    r"^sipp":                        ["Income & Poverty", "Employment & Labor",
                                       "Health & Insurance",
                                       "Population & Demographics"],
    r"^geo/tiger":                   [],   # boundary files, no topic axis
}
_PATH_TOPIC_RE = [(re.compile(p), tags) for p, tags in PATH_TOPIC_OVERRIDES.items()]

def _extract_topic_tags(title, desc, subject, path=""):
    """Return an ordered de-duplicated list of topic tags for a product.
    Combines two signals:
      (1) description-based pattern matching against TOPIC_TAG_PATTERNS
      (2) path-based overrides in PATH_TOPIC_OVERRIDES for flagship
          multi-topic products whose descriptions are too generic for (1)

    The SUBJECTS-derived `subject` field is deliberately excluded from
    the tag list so the Home-search topic dropdown stays a single
    canonical plain-English vocabulary rather than merging two
    overlapping taxonomies. `subject` is still passed as an argument for
    symmetry (and stored separately on the search-index entry so free-
    text scoring can still match it) but doesn't propagate into the tag
    list. Products with no matched pattern AND no path override get an
    empty tag list - text search on the title/description still surfaces
    them via free-text scoring."""
    hay = ((title or "") + " " + (desc or "")).lower()
    tags = []
    for name, pat in TOPIC_TAG_PATTERNS:
        if re.search(pat, hay): tags.append(name)
    # Merge path overrides. Only the FIRST matching regex applies (paths
    # are structured hierarchically so the more specific pattern usually
    # sorts first in the dict), and each override tag is only added if
    # not already present from the description scan.
    for rx, extras in _PATH_TOPIC_RE:
        if rx.search(path or ""):
            for t in extras:
                if t not in tags: tags.append(t)
            break
    return tags

def _extract_geo_levels(title, desc):
    """Return an ordered de-duplicated list of geography levels a product
    mentions in its title + description. Order preserved from
    GEO_LEVEL_PATTERNS so the display list is stable. Empty when the
    description says nothing about geography (many microdata products
    describe only their subject matter, not their granularity)."""
    hay = ((title or "") + " " + (desc or "")).lower()
    levels = []
    for name, pat in GEO_LEVEL_PATTERNS:
        if re.search(pat, hay): levels.append(name)
    return levels

def _search_index_entry(f, review, focus_paths):
    """One dict per product family, JSON-serialized into the page. Kept
    small on purpose - just enough for text search + ranking + a scannable
    result card - so 573 entries add ~120 KB rather than a megabyte."""
    path = f["path"]
    title = f.get("title", "") or path
    desc = (f.get("desc") or "").strip()
    # Truncate desc to a scannable one-liner; the full description lives on
    # the card itself (which the reader jumps to via 'Open card').
    if len(desc) > 220: desc = desc[:217].rstrip() + "…"
    subject = f.get("subject", "") or ""
    program = f.get("group", "") or ""
    topics = _extract_topic_tags(f.get("title", ""), f.get("desc", ""),
                                    subject, path=path)
    geo_levels = _extract_geo_levels(f.get("title", ""), f.get("desc", ""))
    r = review.get(path, {}) or {}
    stage = r.get("stage", "cataloged")
    touched = bool(r.get("uncertainty_metrics") or r.get("note") or r.get("insights"))
    return {
        "p":  path,
        "t":  title,
        "d":  desc,
        "s":  subject,
        "pg": program,
        "k":  f.get("kind", "") or "",
        "tp": topics,
        "gl": geo_levels,
        # Ranking tie-breakers. Kept as short keys so the JSON payload
        # stays compact when serialized into the HTML.
        "fc": 1 if path in focus_paths else 0,
        "tc": 1 if touched else 0,
        "st": stage,
    }

def build_home_search(fams, review):
    """Home-tab "Find a product" search. Ships a client-side text + topic +
    geography-level filter over the full 573-product catalog, ranked by
    match weight + team-touch signal. Directly closes the 4/10 goal-
    directed-lookup gap from the head-to-head audit against census.gov.

    Renders four things:
      1. Section header + one-line explainer.
      2. Row with the text input, two dropdowns, Clear button, keyboard hint.
      3. Results container (populated by the inline JS on first input).
      4. Inline <script> that carries the search index + wiring.

    Design decisions:
      - Placement: left column of the Get-oriented grid, beside the
        curriculum. This is the "I have a question" path complementing the
        "no idea where to start" curriculum. Both are first-order moves.
      - No new deps; pure vanilla JS.
      - Text search matches title, description, program, subject, topic tags.
      - Ranking = title-word match (10) > title substring (6) > program
        substring (4) > desc-word match (3) > desc substring (2). Ties
        break by focus-list -> team-touch -> alphabetical.
      - Top 5 rendered inline; if more matches exist, a "Show all N ->" link
        pre-fills the Products-tab sidebar filter via URL hash.
      - Ctrl+K (or Cmd+K on macOS) focuses the search from anywhere on the
        page; the existing "/" shortcut still owns Products-tab filter focus.
      - URL hash keys `search`, `topic`, `geo` are read on load and re-emitted
        on every input change (integrated with the existing _writeHash so a
        bookmark captures both search + browse state).
    """
    # Focus / curriculum path set - used as a soft ranking tie-breaker so
    # the 5 first-touched products float to the top on ambiguous queries.
    focus_paths = set()
    for entry in CURRICULUM:
        focus_paths.add(entry["path"])
    for path, r in (review or {}).items():
        if (r or {}).get("stage") in ("focus", "candidate"):
            focus_paths.add(path)

    # Build the index. Ordered by path so the JSON payload is diff-friendly.
    idx = [_search_index_entry(fams[p], review, focus_paths)
           for p in sorted(fams)]

    # Topic dropdown: union of (a) the SUBJECTS ordering (Bureau's own topic
    # vocabulary, matched from titles) and (b) the additional plain-English
    # topics extracted from descriptions. De-duplicated, ordered by count.
    topic_counts = {}
    for e in idx:
        for tp in e["tp"]: topic_counts[tp] = topic_counts.get(tp, 0) + 1
    topic_options = sorted(topic_counts.items(),
                            key=lambda kv: (-kv[1], kv[0]))
    topic_options_html = ['<option value="">Topic — any</option>']
    for name, n in topic_options:
        topic_options_html.append(
            f'<option value="{_esc(name)}">{_esc(name)} ({n:,})</option>')

    # Geography dropdown: only levels actually mentioned somewhere in the
    # catalog. Ordered by GEO_LEVEL_PATTERNS (i.e. rough granularity).
    geo_counts = {}
    for e in idx:
        for g in e["gl"]: geo_counts[g] = geo_counts.get(g, 0) + 1
    geo_order = [n for n, _ in GEO_LEVEL_PATTERNS]
    geo_options_html = ['<option value="">Geography level — any</option>']
    for name in geo_order:
        n = geo_counts.get(name, 0)
        if not n: continue
        geo_options_html.append(
            f'<option value="{_esc(name)}">{_esc(name)} ({n:,})</option>')

    # Emoji-per-topic table for the results renderer. JSON-serialize once so
    # the JS side just does emojiOf[topic] || defaultEmoji.
    emoji_json = json.dumps(TOPIC_EMOJI, ensure_ascii=False)
    idx_json = json.dumps(idx, ensure_ascii=False, separators=(",", ":"))

    # Inline the section HTML + JS. The <script> runs synchronously as the
    # browser parses this fragment, so the input / select / results elements
    # (declared above it) are guaranteed to exist by the time the handler
    # binds. Everything is scoped to `#home-search` selectors to avoid
    # colliding with the Products-tab sidebar filter (which owns `.filter`).
    html = [
        '<div class="home-search" id="home-search" role="region" ',
        'aria-label="Find a Census product by keyword, topic, or geography">',
        '<h2><span class="hs-emoji" aria-hidden="true">\U0001F50D</span>'
        'Find a product</h2>',
        '<div class="hs-sub">Search the full ',
        f'{len(idx):,}-product catalog by keyword, topic, or geography level. '
        'Results jump straight to the card in the Products tab. '
        'Try <b>housing</b>, <b>income</b>, or <b>veterans</b>.',
        '</div>',
        '<div class="hs-row">',
        '<input type="search" id="hs-q" autocomplete="off" spellcheck="false" ',
        'placeholder="e.g. housing values, median income, employment" ',
        'aria-label="Search text">',
        f'<select id="hs-topic" aria-label="Filter by topic">{"".join(topic_options_html)}</select>',
        f'<select id="hs-geo" aria-label="Filter by geography level">{"".join(geo_options_html)}</select>',
        '<button type="button" class="hs-clear" id="hs-clear" '
        'title="Reset text, topic, and geography">Clear</button>',
        '<span class="hs-kbd" title="Press Ctrl+K (or Cmd+K on macOS) '
        'anywhere on the page to focus this search">',
        'Press <kbd>Ctrl</kbd>+<kbd>K</kbd> to search',
        '</span>',
        '</div>',
        '<div class="hs-results" id="hs-results" aria-live="polite">',
        # Empty on first render; JS populates on input change or on hash restore.
        '</div>',
        '</div>',
        # -- Inline JS: search index + filter/rank + event bindings ----------
        '<script>',
        '(function(){',
        f'  var IDX = {idx_json};',
        f'  var EMOJI = {emoji_json};',
        '  var DEFAULT_EMOJI = "\U0001F4CA";',
        '  var TOP_N = 5;',
        '  var qEl = document.getElementById("hs-q");',
        '  var tEl = document.getElementById("hs-topic");',
        '  var gEl = document.getElementById("hs-geo");',
        '  var clr = document.getElementById("hs-clear");',
        '  var out = document.getElementById("hs-results");',
        '  if (!qEl || !out) return;',
        # ---- HTML escaping (never trust index text - it comes from catalog) ---
        '  function esc(s){ return String(s || "")',
        '    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")',
        '    .replace(/"/g,"&quot;").replace(/\'/g,"&#39;"); }',
        # ---- Term parsing: split on whitespace, drop tokens < 2 chars ---------
        # Each term expands to an alternates list [term, stem]. Simple English
        # stemming: strip trailing "s" / "es" / "ies" (length >= 4). This turns
        # "financials" -> [financials, financial], "veterans" -> [veterans,
        # veteran], "policies" -> [policies, policy]. Both alternates are
        # tested; any hit counts as a match for scoring purposes.
        '  function stemAlts(t){',
        '    var alts = [t];',
        '    if (t.length >= 5 && t.slice(-3) === "ies") alts.push(t.slice(0, -3) + "y");',
        '    if (t.length >= 4 && t.slice(-2) === "es") alts.push(t.slice(0, -2));',
        '    if (t.length >= 4 && t.slice(-1) === "s")  alts.push(t.slice(0, -1));',
        '    return alts;',
        '  }',
        '  function terms(q){',
        '    return (q || "").toLowerCase().trim().split(/\\s+/)',
        '      .filter(function(t){ return t.length >= 2; })',
        '      .map(function(t){ return {raw: t, alts: stemAlts(t)}; });',
        '  }',
        # ---- Scoring: title-word > title-sub > program > desc-word > desc-sub ---
        '  function reWord(t){',
        '    var esc = t.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");',
        '    return new RegExp("\\\\b" + esc + "\\\\b", "i");',
        '  }',
        '  function score(e, ts){',
        '    if (!ts.length) return 0;',
        '    var titleLC = e.t.toLowerCase();',
        '    var descLC  = e.d.toLowerCase();',
        '    var progLC  = (e.pg || "").toLowerCase();',
        '    var subjLC  = (e.s  || "").toLowerCase();',
        '    var tagsLC  = (e.tp || []).join(" ").toLowerCase();',
        '    var s = 0, matched = 0;',
        '    for (var i = 0; i < ts.length; i++){',
        '      var alts = ts[i].alts;',
        '      var best = 0;',
        # Score each alternate; take the highest (so an exact "veterans" beats
        # its stem "veteran" and doesn't double-count when both match).
        '      for (var j = 0; j < alts.length; j++){',
        '        var term = alts[j]; var rw = reWord(term); var sc = 0;',
        '        if (rw.test(e.t))                  sc = Math.max(sc, 10);',
        '        else if (titleLC.indexOf(term) >= 0) sc = Math.max(sc, 6);',
        '        if (progLC.indexOf(term) >= 0)     sc = Math.max(sc, sc + 4);',
        '        if (subjLC.indexOf(term) >= 0)     sc = Math.max(sc, sc + 4);',
        '        if (tagsLC.indexOf(term) >= 0)     sc = Math.max(sc, sc + 3);',
        '        if (rw.test(e.d))                  sc = Math.max(sc, sc + 3);',
        '        else if (descLC.indexOf(term) >= 0) sc = Math.max(sc, sc + 2);',
        '        if (sc > best) best = sc;',
        '      }',
        '      if (best > 0){ s += best; matched++; }',
        '    }',
        # More distinct query terms matched = higher bonus; a product that
        # matches all N terms beats one that matches only 1 of N.
        '    if (matched > 1) s += (matched - 1) * 2;',
        # Every query term must appear somewhere for the product to survive.
        '    if (matched < ts.length) return 0;',
        # Soft tie-breakers.
        '    if (e.fc) s += 0.6;',
        '    if (e.tc) s += 0.25;',
        '    return s;',
        '  }',
        # ---- Matched-keyword snippet for the result card meta line -----------
        # Reports the RAW query term (what the user typed) rather than its
        # stem, so the "matched: financials" chip echoes the user's word.
        '  function matchedList(e, ts){',
        '    var out = [];',
        '    var hay = (e.t + " " + e.d + " " + e.pg + " " + e.s + " " + ',
        '               (e.tp || []).join(" ")).toLowerCase();',
        '    for (var i = 0; i < ts.length; i++){',
        '      var alts = ts[i].alts;',
        '      for (var j = 0; j < alts.length; j++){',
        '        if (hay.indexOf(alts[j]) >= 0){ out.push(ts[i].raw); break; }',
        '      }',
        '    }',
        '    return out;',
        '  }',
        # ---- One result card ------------------------------------------------
        '  function emojiFor(e){',
        '    if (e.tp && e.tp.length){',
        '      for (var i = 0; i < e.tp.length; i++){',
        '        if (EMOJI[e.tp[i]]) return EMOJI[e.tp[i]];',
        '      }',
        '    }',
        '    return EMOJI[e.s] || DEFAULT_EMOJI;',
        '  }',
        '  function renderItem(e, ts){',
        '    var em = emojiFor(e);',
        '    var geoBits = (e.gl && e.gl.length)',
        '      ? " at " + e.gl.slice(0, 3).map(esc).join(", ") ',
        '      : "";',
        '    var topicLine = (e.tp && e.tp.length)',
        '      ? e.tp.slice(0, 3).map(esc).join(" · ")',
        '      : "";',
        '    var matched = matchedList(e, ts);',
        '    var matchedHTML = matched.length',
        '      ? \'<span class="hs-matched">matched:</span> \' + ',
        '        matched.map(function(m){ return "<mark>" + esc(m) + "</mark>"; }).join(" · ")',
        '      : "";',
        '    return \'<li class="hs-item">\' + ',
        '      \'<div class="hs-emoji-col" aria-hidden="true">\' + em + \'</div>\' + ',
        '      \'<div class="hs-body-col">\' + ',
        '        \'<div class="hs-title">\' + esc(e.t) + ',
        '          \' <code>\' + esc(e.p) + \'</code></div>\' + ',
        '        \'<div class="hs-desc">\' + esc(topicLine) + esc(geoBits) + ',
        '          (topicLine || geoBits ? " — " : "") + esc(e.d) + \'</div>\' + ',
        '        (matchedHTML ? \'<div class="hs-meta">\' + matchedHTML + \'</div>\' : "") + ',
        '      \'</div>\' + ',
        '      \'<a class="hs-open" href="#prod-\' + esc(e.p) + ',
        '        \'" data-jump-path="\' + esc(e.p) + \'">Open card ',
        '        <span class="arrow" aria-hidden="true">→</span></a>\' + ',
        '    \'</li>\';',
        '  }',
        # ---- Empty state helpers --------------------------------------------
        '  function emptyState(hasQuery){',
        '    if (!hasQuery){',
        '      return \'<div class="hs-empty">Type a topic, program name, or ',
        '        variable of interest to start. Try ',
        '        <span class="hs-sugg">',
        '          <a data-hs-sugg="housing">housing</a>·',
        '          <a data-hs-sugg="income">income</a>·',
        '          <a data-hs-sugg="veterans">veterans</a>',
        '        </span>.</div>\';',
        '    }',
        '    return \'<div class="hs-empty"><b>No products match.</b> Try a ',
        '      broader keyword, or clear a filter. Popular topics: ',
        '      <span class="hs-sugg">',
        '        <a data-hs-sugg="housing">housing</a>·',
        '        <a data-hs-sugg="income">income</a>·',
        '        <a data-hs-sugg="population">population</a>',
        '      </span></div>\';',
        '  }',
        # ---- The main render pass -------------------------------------------
        '  function render(){',
        '    var q = qEl.value || "";',
        '    var topic = tEl.value || "";',
        '    var geo = gEl.value || "";',
        '    var ts = terms(q);',
        '    var hasQuery = !!(ts.length || topic || geo);',
        '    if (!hasQuery){ out.innerHTML = emptyState(false); return; }',
        '    var hits = [];',
        '    for (var i = 0; i < IDX.length; i++){',
        '      var e = IDX[i];',
        '      if (topic){',
        '        var okTopic = (e.s === topic) || ',
        '                      ((e.tp || []).indexOf(topic) >= 0);',
        '        if (!okTopic) continue;',
        '      }',
        '      if (geo){',
        '        if ((e.gl || []).indexOf(geo) < 0) continue;',
        '      }',
        '      var sc = ts.length ? score(e, ts) : 1;',
        '      if (sc <= 0) continue;',
        '      hits.push({e: e, s: sc});',
        '    }',
        '    hits.sort(function(a, b){',
        '      if (b.s !== a.s) return b.s - a.s;',
        '      if (b.e.fc !== a.e.fc) return b.e.fc - a.e.fc;',
        '      if (b.e.tc !== a.e.tc) return b.e.tc - a.e.tc;',
        '      return a.e.t.localeCompare(b.e.t);',
        '    });',
        '    if (!hits.length){ out.innerHTML = emptyState(true); return; }',
        '    var top = hits.slice(0, TOP_N);',
        '    var summary = \'<div class="hs-summary">\' + hits.length + ',
        '      " match" + (hits.length !== 1 ? "es" : "") + ',
        '      " — showing top " + top.length + "</div>";',
        '    var list = \'<ul class="hs-list">\' + ',
        '      top.map(function(h){ return renderItem(h.e, ts); }).join("") + ',
        '      "</ul>";',
        '    var showAll = "";',
        '    if (hits.length > TOP_N){',
        # Show-all deep-link: pre-fills the Products-tab filter via existing hash keys.
        '      var params = new URLSearchParams();',
        # Pick a Products tab that is VISIBLE in the current mode (bug fix
        # 2026-07-26): tab-am is CSS-hidden outside reviewer mode, so a
        # deep-link that targeted it landed on an invisible panel.
        '      var tabEl = document.body.classList.contains("am-reviewer")',
        '        ? document.querySelector(".tab.tab-am")',
        '        : document.querySelector(".tab.tab-kind");',
        '      if (!tabEl) tabEl = document.querySelector(".tab.tab-am") || ',
        '                          document.querySelector(".tab.tab-kind");',
        '      var tabKey = tabEl ? tabEl.dataset.k : "";',
        '      if (tabKey) params.set("tab", tabKey);',
        '      if (q) params.set("q", q);',
        # Preserve topic + geo so a bookmark of the show-all URL reads back to
        # the same Home-search state if the reader flips back to Home.
        '      if (topic) params.set("topic", topic);',
        '      if (geo) params.set("geo", geo);',
        '      showAll = \'<a class="hs-showall" href="#\' + params.toString() + ',
        '        \'">Show all \' + hits.length + \' matches →</a>\';',
        '    }',
        '    out.innerHTML = summary + list + showAll;',
        '  }',
        # ---- Debounce --------------------------------------------------------
        '  var _rt = null;',
        '  function schedule(){ if (_rt) clearTimeout(_rt); _rt = setTimeout(render, 150); }',
        '  qEl.addEventListener("input", schedule);',
        '  tEl.addEventListener("change", render);',
        '  gEl.addEventListener("change", render);',
        # Enter jumps to the first result (mirrors GitHub / VS Code search).
        '  qEl.addEventListener("keydown", function(e){',
        '    if (e.key !== "Enter") return;',
        '    var first = out.querySelector(".hs-open");',
        '    if (first){ e.preventDefault(); first.click(); }',
        '  });',
        # Clear resets all three inputs + re-renders.
        '  if (clr) clr.addEventListener("click", function(){',
        '    qEl.value = ""; tEl.value = ""; gEl.value = "";',
        '    render();',
        # Fire input so the shared _writeHash strips search/topic/geo from the URL.
        '    qEl.dispatchEvent(new Event("input", {bubbles: true}));',
        '    qEl.focus();',
        '  });',
        # Clicking a suggestion chip inside the empty state pre-fills the box.
        '  out.addEventListener("click", function(e){',
        '    var a = e.target && e.target.closest && e.target.closest("[data-hs-sugg]");',
        '    if (!a) return;',
        '    e.preventDefault();',
        '    qEl.value = a.getAttribute("data-hs-sugg") || "";',
        '    qEl.focus();',
        '    render();',
        '    qEl.dispatchEvent(new Event("input", {bubbles: true}));',
        '  });',
        # Ctrl+K / Cmd+K focuses the box from anywhere on the page.
        # Deliberately DOESN\'T conflict with existing "/" (Products-tab filter)
        # or "j"/"k" (card cycling).
        '  document.addEventListener("keydown", function(e){',
        '    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")){',
        '      e.preventDefault();',
        # If a non-Home tab is active, switch to Home first so the input is visible.
        '      var homeTab = document.querySelector(\'.tab[data-k="home"]\');',
        '      if (homeTab && !homeTab.classList.contains("on")) homeTab.click();',
        '      qEl.focus(); qEl.select();',
        '      qEl.scrollIntoView({behavior:"smooth", block:"center"});',
        '    }',
        '  });',
        # Initial render: shows the empty-state prompt with 3 suggestion chips.
        # The shared hash-restore code fires an input event once the hash is
        # parsed, which triggers a second render with the restored state.
        '  render();',
        '})();',
        '</script>',
    ]
    return "".join(html)

def build_home(fams, review, work, counts, worklog, notebooks, probes, git=None,
               diff=None, eda_diffs=None, data_cache=None, repo=None):
    """Home tab. Post-reframe structure: diff banner (session-scoped) -> Where
    the team is (coverage + recently touched) -> What we've learned (feed) ->
    Census landscape viz. The pre-Phase-A `Reviewer mode data` <details>
    block (funnel + inventory + work-depth + notebook-health) has been
    removed - the funnel numbers were '568 -> 0 -> 0 -> 5 -> 0' which is
    depressing without being informative, and work-depth / inventory
    duplicated signals already carried elsewhere. `data_cache` and `repo`
    are threaded through for the reach signals; both default to None so any
    external caller keeps working. `notebooks` and `counts` are still
    accepted for signature stability (used downstream in render()) even
    though the Home tab no longer surfaces them directly.
    """
    h = []
    # Condense-home pass 2026-07-26 commit #3: sticky in-page chapter nav.
    # Rendered at the very top of the Home panel (above the diff banner)
    # so it wayfindes the reader through the 3 chapters below. Sticky-
    # positioned inside body scroll, hides gracefully when the reader is
    # on a Products tab (nav lives inside #panel-home which only shows
    # when Home is the active tab). Small chips, muted colors, doesn't
    # compete with content - see .home-chapternav CSS + the inline JS
    # (IntersectionObserver-driven current-chapter highlight).
    h.append(
        '<nav class="home-chapternav" aria-label="Home chapters">'
        '<span class="home-chapternav-lead" aria-hidden="true">Jump to</span>'
        '<a href="#chapter-get-oriented" class="home-chapternav-chip" '
        'data-chapter-target="get-oriented" data-chip-idx="1">'
        '<span class="hcn-idx">1</span> Get oriented</a>'
        '<a href="#chapter-landscape" class="home-chapternav-chip" '
        'data-chapter-target="landscape" data-chip-idx="2">'
        '<span class="hcn-idx">2</span> The landscape</a>'
        '<a href="#chapter-team-pulse" class="home-chapternav-chip" '
        'data-chapter-target="team-pulse" data-chip-idx="3">'
        '<span class="hcn-idx">3</span> Team pulse</a>'
        '</nav>')
    # The diff banner renders as a slim one-line utility strip directly under
    # the sticky nav (styled via .diff-banner) so all the meta-info - the
    # freshness pill + tour launcher in the freshbar, and this regen diff -
    # reads as ONE utility layer instead of three separate content bands.
    if diff is not None:
        h.append(build_diff_banner(diff, eda_diffs))
    # Condense-home pass 2026-07-26 commit #1: wrap the Home sections into 3
    # labeled chapters so a first-time reader sees structure before density.
    # Small helper keeps the wrapping tidy and lets each chapter carry a
    # muted small-caps label + hairline separator (styled via .home-chapter*).
    def _chapter(cid, tag, caption, sections):
        return (f'<section class="home-chapter" id="chapter-{cid}" '
                f'data-chapter="{cid}" aria-labelledby="chapter-label-{cid}">'
                f'<div class="home-chapter-label" id="chapter-label-{cid}">'
                f'<span class="hc-tag">{tag}</span>'
                f'<span class="hc-sep">&middot;</span>'
                f'<span class="hc-caption">{caption}</span>'
                f'</div>'
                + "".join(sections) +
                '</section>')

    # ---- Chapter 1: Get oriented -----------------------------------------
    # Two first-order onboarding paths a first-time reader picks between:
    # "Find a product" search (I have a question) in the LEFT column and the
    # 5-item curriculum (no idea where to start) in the RIGHT column of a
    # two-column grid (collapsing to one column under ~960px). The Phase-1
    # findings hero card that used to lead this chapter was retired
    # 2026-07-26 (Garrett's live test: the stat cards in Team Pulse carry
    # the findings more clearly); the report link survives in the Team
    # Pulse tail and in each product card's "Related in the Phase 1 report"
    # footer.
    ch1 = [
        '<div class="onboard-grid">'
        '<div class="onboard-col">'
        + build_home_search(fams, review)
        + '</div>'
        '<div class="onboard-col">'
        + build_curriculum_card(fams)
        + '</div>'
        '</div>'
    ]
    h.append(_chapter("get-oriented", "Get oriented",
                      "search &middot; curriculum", ch1))

    # ---- Chapter 2: The landscape ----------------------------------------
    # One pipeline moment (Sankey flow as the visual, tier counts as its
    # legend, "Recently touched" as the drill-in) followed by the landscape
    # treemap - the shape-of-the-space centerpiece. The Sankey + tier rail
    # were merged into build_where_team_is() in the condense pass: they told
    # the same story (pipeline state) as two separate bands.
    ch2 = [
        build_where_team_is(fams, review, work, probes, data_cache or {},
                             git, repo),
        build_landscape_viz(fams, work, probes, data_cache or {},
                             review=review),
    ]
    h.append(_chapter("landscape", "The landscape",
                      "pipeline &middot; treemap", ch2))

    # ---- Chapter 3: Team pulse -------------------------------------------
    # Action first, then signals. The "Up next" queue (mission-statement
    # pass 2026-07-26) leads the chapter: pulse implies action, and this is
    # the one place on the page that answers "what should the team do next"
    # (job 2 of the tool's mission statement). Below it, the external
    # (Bureau press releases) + internal (WWL synthesis feed) activity
    # signals, visually clustered so the reader sees "what's new this week"
    # as one section rather than two scattered feeds.
    ch3 = [build_up_next(fams, review, probes, data_cache or {})]
    if repo is not None:
        ch3.append(build_census_press_feed(repo / CENSUS_PRESS_CACHE))
    ch3.append(build_what_learned(fams, review, worklog, git))
    h.append(_chapter("team-pulse", "Team pulse",
                      "up next &middot; Bureau feed &middot; team findings",
                      ch3))
    # Phase A 2026-07-26 commit #3: auto-tooltip jargon in the Home body copy
    # (MOE, CV, DP, PUMS, allocation, swapping, imputation, variance replicate,
    # differential privacy). Handled as a post-render pass so descriptions and
    # blurbs don't have to remember to call gloss() manually. First-occurrence
    # per glossary term shared with the rest of the render via _GLOSS_SEEN.
    return _gloss_body("".join(h))

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
           snapshot=None, diff=None, data_cache=None, eda_diffs=None):
    eda_diffs = eda_diffs or {}
    # Beginner-UX pass commit #2: reset the glossary first-occurrence tracker
    # so every regen decorates the same first appearance of each term.
    _gloss_reset()
    counts = {s: 0 for s in STAGES}
    for path in fams:
        counts[review.get(path, {}).get("stage", "cataloged")] += 1

    kinds_present = [k for k in KINDS if any(f["kind"] == k for f in fams.values())]
    tabs = ['<button class="tab on" data-k="home">Home</button>']
    # Repo path is threaded down so the "Recently touched" list can stat the
    # evidence files on disk to compute a last-touched timestamp per product.
    # Falls back gracefully to no timestamps if repo is unresolvable.
    _repo_for_home = None
    try:
        _repo_for_home = Path(git.get("repo_abs")) if git and git.get("repo_abs") else None
    except Exception:
        _repo_for_home = None
    # build_home() already runs its own _gloss_body() pass on its output
    # (see the end of build_home()), so tooltips land on the Home body copy
    # first. Kind/AM panels are still passed through _gloss_body() below so
    # a term that wasn't mentioned on Home (unlikely, but possible on a
    # tool state with no reviewed products) still gets tooltipped on its
    # first mention in a card description.
    panels = ['<div class="panel on" id="panel-home">'
              + build_home(fams, review, work, counts, worklog, notebooks, probes, git, diff, eda_diffs,
                           data_cache=data_cache, repo=_repo_for_home) + '</div>']

    # Phase A #2 - "Actively managed" tab + panel replaces the 4 kind tabs in
    # the default view (see the body:not(.am-showall) CSS above). Only emitted
    # when there IS at least one AM product; otherwise the kind tabs stay as
    # the sole Products entrypoint so an empty state doesn't dead-end the
    # reviewer on a blank tab.
    n_am = sum(1 for f in fams.values()
               if _is_actively_managed(f, review.get(f["path"], {})))
    if n_am:
        # Beginner-UX pass commit #2 + #3: gloss() tooltip on the first mention;
        # rename visible tab label from "Actively managed" (jargon) to "Team is
        # working on" (plain English). Internal data-k="am" and CSS classes
        # tab-am / panel-am are unchanged so URL hash + CSS visibility rules
        # keep working.
        tabs.append(f'<button class="tab tab-am" data-k="am">Team is working on'
                    f'{gloss("actively managed")}'
                    f'<span class="n">{n_am}</span></button>')
        panels.append('<div class="panel panel-am" id="panel-am">'
                      + _gloss_body(
                          build_am_panel(fams, review, work, probes, git, snapshot,
                                          data_cache, eda_diffs))
                      + '</div>')
    for i, k in enumerate(kinds_present):
        n = sum(1 for f in fams.values() if f["kind"] == k)
        tabs.append(f'<button class="tab tab-kind" data-k="k{i}">{_esc(k)}<span class="n">{n}</span></button>')
        panels.append(f'<div class="panel panel-kind" id="panel-k{i}">'
                      + _gloss_body(
                          build_kind_panel(k, fams, review, work, probes, git, snapshot,
                                            data_cache, eda_diffs))
                      + '</div>')

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
    ap.add_argument("--repo", default=None,
                    help="repo root. Default: auto-detect by walking up from "
                         "the current directory until a .git file/dir is found; "
                         "falls back to '.' if none. Pass an explicit path (or "
                         "'.') to skip auto-detect.")
    ap.add_argument("--out", default=None,
                    help="default: <repo>/product_report.html (or product_review.<ext> with --export)")
    ap.add_argument("--online", action="store_true")
    ap.add_argument("--probe", metavar="PATH", action="append",
                    help="probe a single catalog path, e.g. --probe acs/acs5 (repeatable)")
    ap.add_argument("--export", choices=("csv", "xlsx"), default=None,
                    help="write a per-product review table instead of the HTML report. "
                         "Default output file is product_review.csv or product_review.xlsx "
                         "at the repo root; override with --out.")
    # ---- Phase 3: sample / EDA mode (see SAMPLE / EDA MODE section above) --
    # --sample takes an optional positional product id: `--sample acs/acs5`
    # samples one product; `--sample` alone batch-samples every Candidate.
    ap.add_argument("--sample", nargs="?", const="__BATCH__", default=None, metavar="PRODUCT_ID",
                    help="fetch actual data slices and run a canonical EDA. "
                         "With a product id (e.g. --sample acs/acs5), samples that one "
                         "product; alone, batch-samples every product currently marked "
                         "'candidate' in product_review.json. Skips fresh cache entries "
                         "(< 7 days) unless --refresh is given.")
    ap.add_argument("--sample-size", type=int, default=SAMPLE_SIZE_DEFAULT, metavar="N",
                    help=f"row count per sample (default: {SAMPLE_SIZE_DEFAULT}). "
                         "The Census data API truncates automatically; smaller = faster.")
    ap.add_argument("--refresh", action="store_true",
                    help="force re-sampling even if a fresh cache entry exists (used "
                         "with --sample). Diff against the previous sample is surfaced "
                         "in the report.")
    # ---- Phase 5 (CLI helper): --review + action flags ----------------------
    # Additive, atomic write to product_review.json. Preserves the schema +
    # auto-insight pieces from earlier Phase 5 commits; replaces the (dropped)
    # --serve HTTP path. See cli_review_action() for the full validation flow.
    rvw = ap.add_argument_group("review helper (--review + action flags)")
    rvw.add_argument("--review", metavar="PRODUCT_ID", default=None,
                    help="target product id (e.g. acs/acs5). Requires at least "
                         "one of --insight / --status / --notes. All actions "
                         "apply atomically.")
    rvw.add_argument("--insight", metavar="TEXT", default=None,
                    help="append a human insight (source='human'). Non-empty "
                         "text required; who defaults to git config user.name.")
    rvw.add_argument("--status", metavar="VALUE", default=None,
                    help="set stage; one of " + "/".join(STAGES) + " "
                         "(case-insensitive on input).")
    rvw.add_argument("--notes", metavar="TEXT", default=None,
                    help="set free-text notes (the review file's `note` field).")
    rvw.add_argument("--no-regen", dest="no_regen", action="store_true",
                    help="after --review, skip the automatic HTML regen. Use "
                         "when batching multiple review writes from a shell "
                         "loop, so the report only regenerates on the last one.")
    ap.add_argument("--open", dest="open_report", action="store_true",
                    help="open product_report.html in the default browser "
                         "after any regen (or standalone, if paired with "
                         "--no-regen). Uses stdlib webbrowser, which delegates "
                         "to start / open / xdg-open on the host OS.")
    args = ap.parse_args()
    if args.repo is None:
        cwd = Path.cwd().resolve()
        detected = _find_repo_root(cwd)
        if detected is None:
            print(f"warning: no .git found from {cwd}; using . as repo root",
                  file=sys.stderr)
            repo = cwd
        else:
            repo = detected
            if repo != cwd:
                print(f"resolved repo root: {repo} (walked up from cwd)")
    else:
        repo = Path(args.repo).resolve()
    if not (repo / "ingestion").exists():
        sys.exit(f"error: {repo} doesn't look like the project repo")
    if args.export:
        default_name = f"product_review.{args.export}"
        out = Path(args.out).resolve() if args.out else repo / default_name
    else:
        out = Path(args.out).resolve() if args.out else repo / "product_report.html"

    # Phase 5 pivot - --review runs cli_review_action() first (atomic write to
    # product_review.json under the shared lock; validation errors exit 2 with
    # no state change). Post-audit UX pass: on a successful review write we
    # now also regenerate product_report.html so the reviewer sees their edit
    # reflected immediately, unless --no-regen was passed (for scripts that
    # batch several writes and want a single regen at the end).
    if args.review is not None:
        code = cli_review_action(repo, args)
        if code == 0 and not args.no_regen:
            print("regenerating product_report.html...")
            t0 = time.perf_counter()
            _run_report_pipeline(repo, args, out)
            print(f"regenerated in {time.perf_counter() - t0:.2f}s -> {out.name}")
        if code == 0 and args.open_report:
            _open_report_in_browser(out)
        sys.exit(code)

    # Standalone (no --review) path. --no-regen here means "just open what's
    # already on disk" - useful when paired with --open to re-launch the
    # existing report without rebuilding it.
    if not args.no_regen:
        _run_report_pipeline(repo, args, out)
    if args.open_report and not args.export:
        _open_report_in_browser(out)

def _find_repo_root(start):
    """Walk up from `start` looking for a directory (or file, for git worktrees)
    called '.git'. Returns the first hit as an absolute Path, or None if we
    reach the filesystem root without finding one. Post-audit UX pass #4:
    lets a teammate run `python tools/product_scope.py` from any subdirectory
    (notebooks/, analysis/, etc.) and have the tool find the real repo root
    on its own, instead of erroring confusingly about a missing ingestion/."""
    cur = Path(start).resolve()
    while True:
        if (cur / ".git").exists():
            return cur
        parent = cur.parent
        if parent == cur:            # reached filesystem root
            return None
        cur = parent

def _open_report_in_browser(out_path):
    """Open the report file in the default browser via stdlib webbrowser.
    Prints a one-line status. `--open` opens whatever is currently on disk -
    if paired with --no-regen and the file is missing, we say so instead of
    silently failing. Cross-platform: webbrowser.open() dispatches to start
    (Windows) / open (macOS) / xdg-open (Linux) under the hood, so the caller
    doesn't have to fork by OS."""
    p = Path(out_path)
    if not p.exists():
        print(f"warning: cannot open {p.name} - file does not exist "
              f"(regen it first, or drop --no-regen)", file=sys.stderr)
        return
    try:
        webbrowser.open(p.resolve().as_uri())
        print(f"opened {p.name} in default browser")
    except Exception as ex:
        print(f"warning: could not open browser ({ex!r}); "
              f"the report is at {p.resolve()}", file=sys.stderr)

def _run_report_pipeline(repo, args, out):
    """Full report-render pipeline: scan repo, load catalog, run any queued
    probes / samples, emit auto-insights, and write product_report.html to
    `out`. Extracted from main() so the --review auto-regen path (post-audit
    UX pass) can invoke exactly the same pipeline after a successful review
    write. The --export short-circuit inside this helper still writes a CSV/
    XLSX instead of HTML and returns early; that mirrors main()'s old flow."""
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
    # args.sample values (nargs='?' with const='__BATCH__'):
    #   None          -> flag not passed; skip sampling
    #   '__BATCH__'   -> `--sample` alone; batch every Candidate
    #   any other str -> `--sample <product_id>`; single-product mode
    if args.sample is not None:
        sample_target = None if args.sample == "__BATCH__" else args.sample
        sample_products(repo, fams, review, probes, sample_target,
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

    # Phase 5 #2 - auto-insight collection. Two sources (cache-diff drift,
    # role-state transitions) share _append_insight() which handles dedup +
    # file locking. Runs BEFORE render so the freshly appended insights land
    # on the cards in the same regen. (auto:repo dropped in audit cut 2;
    # JL_Work_Tree cross-check dropped in audit simplify 1.)
    ai_div = collect_auto_divergence_insights(fams, review, snapshot_prev)
    if diff.get("is_baseline"):
        print(f"  snapshot: baseline recorded to {SNAPSHOT_FILE} (diff will appear on next run)")
    else:
        t = diff["totals"]
        newev = sum(t.get("new_evidence_by_family", {}).values())
        print(f"  snapshot: {newev:+d} evidence hits, {t['status_changes']} status change(s), "
              f"{t['new_probes']} new probe(s)")
    # Phase 3: load the sample cache after sample_products() has (possibly)
    # updated it, so the HTML render sees the latest EDA slice on every card.
    # eda_diffs come from the last --sample run's diff dump (Phase 3 #6).
    data_cache = load_data_cache(repo)
    eda_diffs  = load_eda_diffs(repo)

    # Phase 5 #2 - emit auto:cache_diff insights alongside divergence ones.
    # Do a single batched save so the review file only takes one lock cycle
    # per regen, no matter how many products drifted.
    ai_cache_diff = collect_auto_cache_diff_insights(eda_diffs)
    emit_auto_insights(repo, review, ai_div + ai_cache_diff,
                       log_prefix="auto-insight/regen")
    # Beginner-UX pass commit #5: ingest any notes/*.txt files a teammate has
    # dropped from the browser "+ Add a note" flow. Runs before render() so
    # freshly ingested notes appear on the same regen's cards. Under the same
    # review lock as auto-insights so a concurrent --review CLI write can't
    # clobber them (via _append_insight inside with_review_locked).
    def _ingest_and_save(disk_review):
        for path, entry in review.items():
            if path not in disk_review:
                disk_review[path] = entry
        return ingest_notes(repo, disk_review, fams)
    _ingested = with_review_locked(repo, _ingest_and_save) or []
    if _ingested:
        # Post-ingest: refresh in-memory review from disk so render() sees the
        # freshly appended notes. Read outside the lock is fine here - we've
        # already committed the writes.
        try:
            _rpath = repo / "product_review.json"
            review = json.loads(_rpath.read_text(encoding="utf-8"))
        except Exception:
            pass
        _pids_ingested = sorted({pid for pid, _ in _ingested})
        preview = ", ".join(_pids_ingested[:5])
        more = f" (+{len(_pids_ingested) - 5} more)" if len(_pids_ingested) > 5 else ""
        print(f"  [notes] ingested {len(_ingested)} note(s) from notes/ "
              f"({preview}{more})")
    counts = render(fams, review, work, worklog, notebooks, probes, repo.name, catnote, out, git,
                    snapshot_prev, diff, data_cache, eda_diffs)
    print("  funnel: " + " -> ".join(f"{STAGE_LABELS[s]} {counts.get(s, 0)}" for s in STAGES))
    print(f"Report written to {out}")

if __name__ == "__main__":
    main()
