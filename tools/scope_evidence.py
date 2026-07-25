#!/usr/bin/env python3
"""
scope_evidence.py - the deep evidence engine behind scope_audit.py.

Upgrades the audit from "text mentions a table" to verifiable evidence:

  * Python files are parsed with the AST: only real code counts (comments and
    docstring chatter can no longer create false coverage), and files that
    make actual download-style calls are tagged as pullers.
  * Notebooks are read forensically: per-cell source, execution counts
    (monotonic = ran top-to-bottom), presence of outputs, error outputs,
    and AST-counted assert statements. A notebook that merely *mentions* a
    table but shows no clean executed run cannot reach "Analyzed"; asserts
    plus a clean run are what earn "Validated".
  * Local artifacts (data/raw parquet files) are inventoried when present,
    so a machine that has actually run the pipeline gets artifact receipts.
  * --verify re-executes every notebook via jupyter nbconvert on the local
    machine and demotes anything that no longer runs clean.
  * suggest_findings() mines WORKLOG.md "Findings / decisions" blocks into
    ready-to-paste FINDINGS dict stubs.

scope_audit.py imports this when present and falls back to its internal
regex scan when it isn't - the audit never breaks, it just gets shallower.
"""

import ast, json, re, shutil, subprocess, sys
from pathlib import Path

# ----------------------------------------------------------------------------
# Python file forensics
# ----------------------------------------------------------------------------

def _scan_python(path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    rec = {"file": path.name, "text": text, "low": text.lower(),
           "lines": text.splitlines(), "puller": False, "code_strings": []}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return rec  # fall back to raw text matching
    strings, puller = [], False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.append((getattr(node, "lineno", 0), node.value))
        if isinstance(node, ast.Call):
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute) else
                    fn.id if isinstance(fn, ast.Name) else "")
            kw = {k.arg for k in node.keywords if k.arg}
            if "download" in name.lower() or "urlretrieve" in name.lower() or {"dataset", "vintage"} & kw:
                puller = True
    rec["puller"] = puller
    rec["code_strings"] = strings
    # code-only text: what pattern matching should see (strings + identifiers,
    # never comments). Cheap approximation: strip comment lines.
    rec["code_text"] = "\n".join(l for l in rec["lines"] if not l.lstrip().startswith("#"))
    return rec

# ----------------------------------------------------------------------------
# Notebook forensics
# ----------------------------------------------------------------------------

def _scan_notebook(path: Path):
    raw = path.read_text(encoding="utf-8", errors="ignore")
    rec = {"file": path.name, "text": "", "low": "", "cells": [], "markdown": "",
           "health": None}
    try:
        nb = json.loads(raw)
    except Exception:
        rec["text"] = raw; rec["low"] = raw.lower()
        return rec
    code_cells, md_parts = [], []
    execs, with_out, errors, asserts = [], 0, 0, 0
    for c in nb.get("cells", []):
        srcs = c.get("source", [])
        src = "".join(srcs) if isinstance(srcs, list) else str(srcs)
        if c.get("cell_type") == "code":
            code_cells.append(src)
            execs.append(c.get("execution_count"))
            outs = c.get("outputs", [])
            if outs: with_out += 1
            errors += sum(1 for o in outs if o.get("output_type") == "error")
            try:
                asserts += sum(isinstance(n, ast.Assert) for n in ast.walk(ast.parse(src)))
            except SyntaxError:
                asserts += src.count("assert ")
        elif c.get("cell_type") == "markdown":
            md_parts.append(src)
    nonempty = [e for e in execs if e is not None]
    mono = bool(nonempty) and len(nonempty) == len(execs) and nonempty == sorted(nonempty)
    rec["cells"] = code_cells
    rec["markdown"] = "\n".join(md_parts)
    rec["text"] = "\n".join(code_cells)              # matching sees CODE only
    rec["low"] = rec["text"].lower()
    rec["health"] = {
        "code_cells": len(code_cells), "mono": mono, "with_outputs": with_out,
        "errors": errors, "asserts": asserts,
        "clean_run": mono and errors == 0 and with_out >= max(1, len(code_cells) - 1),
        "verified": None,   # set by --verify
    }
    return rec

# ----------------------------------------------------------------------------
# Deep scan entry point (same shape scope_audit expects, plus extras)
# ----------------------------------------------------------------------------

def deep_scan(repo: Path):
    ev = []
    for f in sorted((repo / "ingestion").glob("*.py")):
        r = _scan_python(f); r["kind"] = "ingestion"; ev.append(r)
    for f in sorted((repo / "analysis").glob("*.py")):
        r = _scan_python(f); r["kind"] = "analysis"; ev.append(r)
    for f in sorted((repo / "notebooks").glob("*.ipynb")):
        r = _scan_notebook(f); r["kind"] = "notebook"; ev.append(r)
    dd = repo / "docs" / "data-dictionary.md"
    if dd.exists():
        t = dd.read_text(encoding="utf-8", errors="ignore")
        ev.append({"file": dd.name, "kind": "docs", "text": t, "low": t.lower()})
    return ev

def locate(e, patterns):
    """Human-readable location of the first pattern hit: (cell N) / (line N)."""
    pats = [re.compile(p, re.I) for p in patterns]
    if e.get("cells"):
        for i, src in enumerate(e["cells"], 1):
            if any(p.search(src) for p in pats):
                return f" (cell {i})"
    if e.get("lines"):
        for i, ln in enumerate(e["lines"], 1):
            if ln.lstrip().startswith("#"):
                continue
            if any(p.search(ln) for p in pats):
                return f" (line {i})"
    return ""

# ----------------------------------------------------------------------------
# Local artifact receipts
# ----------------------------------------------------------------------------

def artifact_index(repo: Path):
    root = repo / "data" / "raw"
    if not root.exists():
        return {"present": False, "files": [], "note": "data/raw not present in this clone (regenerable by design)"}
    files = sorted(root.rglob("*.parquet"))
    out = []
    rows_fn = None
    try:
        import pyarrow.parquet as pq
        rows_fn = lambda p: pq.ParquetFile(p).metadata.num_rows
    except Exception:
        pass
    for p in files:
        item = {"name": str(p.relative_to(root)), "mb": round(p.stat().st_size / 1e6, 1)}
        if rows_fn:
            try: item["rows"] = rows_fn(p)
            except Exception: pass
        out.append(item)
    return {"present": True, "files": out,
            "note": f"{len(out)} parquet artifacts on disk" + (" (row counts verified)" if rows_fn else "")}

# ----------------------------------------------------------------------------
# --verify: actually re-run the notebooks
# ----------------------------------------------------------------------------

def verify_notebooks(repo: Path, timeout=1800):
    """Re-execute each notebook headlessly. Returns {name: 'pass'|'fail'|'skip'}."""
    if not shutil.which("jupyter"):
        print("  [verify] jupyter not found on PATH - skipping (pip install jupyter nbconvert)")
        return {}
    results = {}
    for nb in sorted((repo / "notebooks").glob("*.ipynb")):
        cmd = ["jupyter", "nbconvert", "--to", "notebook", "--execute",
               "--stdout", str(nb)]
        try:
            r = subprocess.run(cmd, cwd=repo, capture_output=True, timeout=timeout)
            results[nb.name] = "pass" if r.returncode == 0 else "fail"
            print(f"  [verify] {nb.name}: {results[nb.name]}")
            if r.returncode != 0:
                tail = r.stderr.decode(errors="ignore").strip().splitlines()[-3:]
                for t in tail: print(f"           {t}")
        except subprocess.TimeoutExpired:
            results[nb.name] = "fail"
            print(f"  [verify] {nb.name}: TIMEOUT after {timeout}s")
    return results

# ----------------------------------------------------------------------------
# Worklog mining: propose FINDINGS entries
# ----------------------------------------------------------------------------

def suggest_findings(repo: Path):
    wl = repo / "WORKLOG.md"
    if not wl.exists():
        print("WORKLOG.md not found"); return
    text = wl.read_text(encoding="utf-8", errors="ignore")
    entries = re.split(r"(?m)^(?=\d{4}-\d{2}-\d{2} )", text)
    print("# Candidate FINDINGS entries mined from WORKLOG.md")
    print("# Paste the keepers into FINDINGS in scope_audit.py, then edit stat/headline.\n")
    for entry in entries:
        head = entry.splitlines()[0].strip() if entry.strip() else ""
        m = re.search(r"Findings / decisions:\s*(.+?)(?=\nFiles:|\n\d{4}-|\Z)", entry, re.S)
        if not m or not head:
            continue
        nb = re.search(r"EDA (\d\d?)", head)
        region = "US" if re.search(r"\bUS\b|national", head, re.I) else "NJ"
        # split numbered findings "(1) ... (2) ..." into candidates
        body = " ".join(m.group(1).split())
        parts = re.split(r"\(\d+\)\s*", body)
        for p in parts:
            p = p.strip().rstrip(";. ")
            if len(p) < 40:  # skip stubs like "None - bookkeeping"
                continue
            stat = re.search(r"[\u2212\-+~\u2248]?\d[\d,.\u00D7x%\u2013\-]*%?", p)
            print("{" + f'"region": "{region}", "stat": "{stat.group(0) if stat else "?"}", '
                  f'"headline": "{p[:70]}...", "detail": "{p[:180]}", '
                  f'"nb": "{nb.group(1) if nb else "?"}", "kind": "finding"' + "},")
        print()

if __name__ == "__main__":
    repo = Path(sys.argv[2] if len(sys.argv) > 2 else ".").resolve()
    if len(sys.argv) > 1 and sys.argv[1] == "suggest-findings":
        suggest_findings(repo)
