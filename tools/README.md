# /tools — Product Scope Tracker

Our inventory of every Census statistical product, what each one publishes, and how far our own work has gotten on it. Re-run it before each biweekly; the output is a single self-contained HTML page.

**Two files, both required.** `product_scope.py` is the tool. `scope_evidence.py` is the evidence engine it uses to read the repo. They must sit in the same folder — if `scope_evidence.py` goes missing the tool still runs but downgrades to a shallow text scan and says so. Watch for `deep forensics` in the output; `regex fallback` means something is wrong.

---

## Running it

From the **repo root**, with the venv active:

```powershell
.venv\Scripts\activate
python tools\product_scope.py --repo .
start product_report.html
```

That's the routine run — it uses the cached catalog, so it takes a couple of seconds.

**To refresh the catalog** (new products get published; do this occasionally and before a milestone):

```powershell
python tools\product_scope.py --repo . --online
```

Crawls `api.census.gov/data.json` — about 1,800 dataset-vintages collapsing to roughly 570 product families — and rewrites `scope_field_cache.json`.

If the crawl fails, the tool says so loudly and lists only the non-API products. **Don't commit a `product_review.json` written from that state** — delete it and re-run once you're online.

**To export a per-product review table** (one row per product family, for spreadsheet review workflows outside the browser):

```powershell
python tools\product_scope.py --repo . --export csv    # writes product_review.csv
python tools\product_scope.py --repo . --export xlsx   # writes product_review.xlsx
```

Skips the HTML report and writes only the export. Same catalog + review + evidence + probe sources the report uses, so the export cannot drift from what the tabs show. Columns: `Product ID, Name, Family, Agency, Status, Repo Evidence, MOE Var Count, Allocation Groups, Geography Levels, Notes, Last Reviewed By, Last Reviewed Date`. Override the default path with `--out`. Both files are gitignored — treat them as script output, not committed state.

---

## How the report is organised

**Tabs** come from the Bureau's own dataset flags: **Aggregate tables** (published estimate tables — where margins of error live), **Microdata** (record-level files with replicate weights and no published per-estimate uncertainty), **Time series**, **Unflagged**. This split is not our opinion; it is `c_isAggregate` / `c_isMicrodata` / `c_isTimeseries` straight from the catalog, and it is the single most important distinction for this project.

Inside a tab: **program → subject → products**. The subject level only appears where a program spans more than one topic — Decennial opens as a flat list, ACS splits four ways. The filter box searches path, title, subject and program, and reaches through every level.

---

## The two axes, and which one is ours

**Stage** — `Cataloged → Reviewed → Candidate → FOCUS`, plus `Set aside`. **Our scope decision.** The tool never sets it. Every product is created as `cataloged` and stays there until a human moves it.

**Work depth** — `Not started → Identified → Pulled → Analyzed → Validated`. **Computed from the repo** on every run, never hand-set. `Validated` means a notebook's execution counts run in order, it stored no error outputs, and its code contains at least three real `assert` statements (counted by parsing the syntax tree). Every claim carries receipts naming the file and cell or line.

A product can be `Cataloged + Validated` — work done, not yet formally scoped. That's the two axes disagreeing, which is often the interesting case.

---

## Probing a product — asking the API what it publishes

Every catalog record carries `variables.json` and `geography.json` endpoints. A **probe** fetches them and reports what the product actually publishes:

```
acs/acs5  36,144 variables; 12,048 carry an _M margin of error; 3 allocation groups;
          24,096 annotation variables; geography: us, region, division, state,
          county, tract, block group
```

**To probe:** tick the `probe` box on any number of product cards. A bar appears bottom-right with a count. Click **Download queue** — it saves `probe_queue.json` to your Downloads. Then:

```powershell
python tools\product_scope.py --repo . --probe-queue "$env:USERPROFILE\Downloads\probe_queue.json"
python tools\product_scope.py --repo .        # rebuild the report to see the results
```

Or probe one directly, no clicking:

```powershell
python tools\product_scope.py --repo . --probe acs/acs5 --probe dec/dhc
```

Results land in **`product_probes.json` at the repo root, which IS committed** — probe once, the whole team sees it. Probed products show a gold `probe` chip so you can tell at a glance what's been checked.

**A probe reports counts and levels. It never writes an uncertainty description.** Reading the probe and writing that sentence is the review, and only a person does it.

---

## Sampling a product — asking the API for actual data

A **probe** tells you what a product publishes. A **sample** fetches an actual data slice and runs a canonical EDA on it — dtype, missingness, numeric summaries, categorical top-5, geography breakdown, unicode sparklines. Same principle as the probe: it reports what the data looks like, it never writes a verdict.

There are two ways to sample: **on-demand** (one product, right now) and **bulk** (`--warm-cache`, whole catalog, thread-pooled). They are separate entry points and have deliberately different rules — pick the one that matches what you're doing.

**On-demand: sample one product directly.**

```powershell
python tools\product_scope.py --repo . --sample --product acs/acs5
```

Always hits the API. **Freshness is NOT checked** — the reviewer asked for that product, so we fetch it, regardless of what's in the cache. This is the difference from `--warm-cache`.

**On-demand: batch-sample every Candidate.**

```powershell
python tools\product_scope.py --repo . --sample
```

Batch mode picks up every product currently `stage: "candidate"` in `product_review.json`, skips ones with a fresh cache (< 7 days), and skips non-API products (DAS demo, TIGER, anything without a queryable `variables.json`) with a clear message. Sequential requests with a 500 ms delay to be polite to the Census API.

**Force a re-sample** even if the cache is fresh:

```powershell
python tools\product_scope.py --repo . --sample --refresh
```

`--refresh` also runs a **diff** against the previous cached sample and surfaces material changes (new/removed columns, dtype changes, missingness deltas > 10 percentage points, row-count deltas > 10 %) both on the affected card and in the Home tab's "Since last regeneration" banner.

**Sample size** defaults to 100 rows; override with `--sample-size N`. The Census data API truncates automatically, so smaller = faster.

**API key:** if a `CENSUS_API_KEY` line is present in `.env`, it's appended to every request (higher rate limits). Public endpoints work without one, subject to the usual 500-requests-per-day cap.

Results land in **`scope_data_cache.json` at the repo root, which is GITIGNORED** — a sample is a moment-in-time slice against a rate-limited endpoint, not shareable factual state (unlike probes, which describe what an endpoint publishes and ARE committed). If two teammates need the same slice, each runs their own sample.

**Where the EDA appears in the report:** every product with a cached sample gets an "EDA snapshot" section on its card (below "Our progress"), showing the freshness pill, the source URL, the four EDA tables, and — if `--refresh` produced any drift — a per-card amber banner listing what changed. Products marked Candidate without a cached sample get a copyable `--sample` command in the "Suggested next step" panel instead. Every card also carries a **Quick Look** section near the top — see the next section.

---

## Warming the cache — bulk pass with `--warm-cache`

`--warm-cache` walks the whole catalog and, for every product, runs a probe (into `product_probes.json`) then a sample (into `scope_data_cache.json`). It's the "everything at once" path — after one warm-cache run, every card in the report has the deepest tier of cached data the product supports, without a reviewer clicking through 573 products.

```powershell
python tools\product_scope.py --repo . --warm-cache
```

**What it skips** (and how the summary tags each case):

- **Non-API products** (no `variables.json` endpoint — TIGER shapefiles, DAS demo, etc.) → `skipped_non_api`. These land in the Quick Look with a "not sample-able via API" note instead of the generic empty state.
- **Fresh cache** — a probe cache < 7 days old AND a sample cache < 7 days old both count as fresh → `skipped_fresh`. `--refresh` overrides.
- **`sample_config: "skip"`** in `product_review.json` (see below) → `skipped_config`. Never sampled by warm-cache, no matter how stale.

Failures (HTTP timeouts, 4xx, bad JSON) are counted as `failed` and printed at the end with the reason; the run continues past every failure so one broken endpoint can't tank the whole batch.

**Concurrency:** the batch runs in a `ThreadPoolExecutor` with 6 workers by default. Override with `--concurrency N`. Set `--concurrency 1` for a sequential run (no thread pool), which is much cleaner for debugging a specific failure.

**Rate limiting:** outbound requests are held under **10 req/sec globally** via a sliding-window limiter shared across all workers. If any response returns a `Retry-After` header, the limiter honors it and every worker slows down accordingly. Rate limit responses (HTTP 429) are retried once.

**Incremental persistence:** every successful probe/sample is written to its cache file immediately, under a `threading.Lock`. A mid-run crash — power loss, Ctrl-C, exception — keeps all completed work. Restart and it picks up where it left off (with `--refresh` if you want to re-do the freshly-cached ones).

**Wall time is honest:** it depends on catalog size and Census API responsiveness. Rough guide on the current ~570-product catalog: a first pass without a `CENSUS_API_KEY` takes several minutes because the public rate limit throttles you; with a key it's typically under 2 minutes end-to-end. A steady-state re-run (`--warm-cache` with no `--refresh`) is a few seconds because most products are fresh-cache skipped.

**Force a full re-warm:**

```powershell
python tools\product_scope.py --repo . --warm-cache --refresh
```

Ignores every freshness check and re-does the whole catalog. `--refresh` also triggers the EDA diff logic from `--sample`, so per-card drift banners appear.

**Summary artifact:** `.warm_cache_last_run.json` at the repo root (gitignored) records counts, path lists, and the finish timestamp. The report reads it to fill in the "Last warm-cache: Xh ago" line under the freshness bar.

### Per-product opt-outs and opt-ins: `sample_config`

The review file supports an optional `sample_config` field per product:

```json
"dec/dhc": {
  "stage": "focus",
  "sample_config": "always"
},
"some/huge/product": {
  "stage": "set-aside",
  "sample_config": "skip"
}
```

Values:

- `"default"` (or missing) — respect `--warm-cache` freshness + non-API skip logic.
- `"always"` — re-sample on every `--warm-cache` run even if the cache is fresh. Useful for FOCUS products where drift matters.
- `"skip"` — never sample during warm-cache runs. Useful for Set-aside, huge, or API-problematic products.

Unknown values (typos) fall back to `"default"` and log a warning to stderr so the reviewer notices.

`--sample --product X` ignores `sample_config` entirely — an explicit ask from a reviewer always runs.

---

## The Quick Look card section

Every product card carries a **Quick Look** section near the top. It renders the highest tier of data currently cached for that product and tags it with a colored chip so you can see the state at a glance without expanding the card:

| Chip                    | Meaning                                                                 |
|-------------------------|-------------------------------------------------------------------------|
| **Cached: catalog** (grey)  | Tier 0 — only catalog metadata (family, agency, vintages, endpoint URL). |
| **Cached: probe** (blue)    | Tier 1 — probe results cached: MOE variable count, allocation groups, geography levels. |
| **Cached: sample** (green)  | Tier 2 — a data sample has been fetched: full EDA (dtypes, missingness, numeric summaries, top-5 categoricals, sparklines). |

The Home tab's freshness bar carries a **cache coverage line** below it:

```
Cache coverage: 342/570 sampled (60%), 145/570 non-API, 83/570 unfetched · Last warm-cache: 4h ago
```

Green pill above 80% sampled, amber 40–80%, red below 40%. The denominator ignores non-API products (TIGER, DAS demo) because they can never contribute to that fraction. The Products tab's sidebar has a matching **Cache tier** facet (`sample / probe / catalog / not sample-able`) so you can filter to "candidates that haven't been sampled yet" in one click.

---

## Reviewing a product — the actual work

Everything starts blank on purpose. **The tool has no built-in knowledge of what uncertainty any product publishes**, and that is deliberate: a catalog path identifies a *program*, not a *methodology*. `acs/acs5` and `acs/acs5/pums` share a prefix and have completely different uncertainty surfaces — one publishes a 90% margin of error on every estimate, the other hands you replicate weights and expects you to compute your own standard errors. Any rule that guesses from the path will be confidently wrong somewhere, so we don't guess.

To review a product, edit its entry in `product_review.json`:

```json
"acs/acs5": {
  "stage": "focus",
  "uncertainty_metrics": "90% MOE on every estimate; B98/B99 allocation tables; variance replicate tables",
  "note": "our primary product"
}
```

- `uncertainty_metrics` — what this product *actually publishes*, verified. Probe it first, then write what you concluded and where you checked. Filling this in **is** the review.
- `stage` — `cataloged`, `reviewed`, `candidate`, `focus`, or `set-aside`. If you set `set-aside`, say why in `note`.

`product_review.json` **is committed** and is **append-only**: a fresh crawl adds newly published products as `cataloged` and never overwrites an entry you have edited.

---

## Recording insights and reviews — the `--review` CLI helper

Hand-editing `product_review.json` with a text editor works fine for one-off changes. When you're logging what you found on a card, moving a product through the funnel, or dictating a role, use the `--review` subcommand — it validates the input, stamps `last_reviewed_by` + `last_reviewed_date`, and appends insights with a UTC timestamp and author. Every write is atomic (single lock cycle, no half-applied entries) and produces a minimal git diff.

```powershell
# Append a human insight (source='human'); who = your git config user.name
python tools\product_scope.py --repo . --review acs/acs5 --insight "Confirmed replicate weights ship with the microdata extract"

# Set stage; case-insensitive input, canonical lowercase on disk
python tools\product_scope.py --repo . --review acs/acs5 --status FOCUS

# Declare a composite role — REQUIRES --note on the same command
python tools\product_scope.py --repo . --review acs/acs5 --role cv_source --note "primary CV source across every geography"

# Multiple actions atomically in one write
python tools\product_scope.py --repo . --review dec/dhc --status Candidate --sample-config always --insight "Set as Candidate; will sample every warm-cache pass to catch DP noise drift"

# Override the git-derived attribution (e.g. logging insight from a mentor)
python tools\product_scope.py --repo . --review acs/acs5 --author "Andrew" --insight "Mentor confirmed the B98/B99 allocation tables ship separately from the estimate MOEs"
```

**Available action flags** (at least one required per invocation):

| Flag | Effect | Validation |
|---|---|---|
| `--insight TEXT` | Append a human insight to the entry's `insights` list. `source="human"`, `when` = current UTC ISO, `who` = `--author` or `git config user.name`. | Text must be non-empty. |
| `--status VALUE` | Set the entry's `stage`. | One of `cataloged / reviewed / candidate / focus / set-aside`; case-insensitive on input, stored lowercase. |
| `--role VALUE` | Set the entry's `composite_role`. | One of `cv_source / allocation_source / privacy_noise / geometry / benchmark / unused`. Also requires `--note` on the same invocation UNLESS the entry already carries a non-empty `composite_role_note`. |
| `--note TEXT` | Set the entry's `composite_role_note`. | Standalone `--note` (no `--role`) is only accepted if the entry already declares a role to justify. |
| `--sample-config VALUE` | Set the entry's `sample_config`. | One of `default / always / skip`. |
| `--notes TEXT` | Set the entry's free-text `note` field. | No validation. |
| `--author NAME` | Override the git-derived attribution. Applies to both `last_reviewed_by` AND any `--insight`'s `who`. | Optional. |

**How attribution works.** If you pass `--author "Name"`, that name lands on `last_reviewed_by` and on any insight's `who`. If you don't, the tool runs `git config user.name` in the repo and uses that. If git isn't configured either, the tool falls back to `"unknown"`. On a Windows machine with the standard project setup, this means: with `user.name` set to `Garrett Spangler` in `~/.gitconfig`, running `--review acs/acs5 --insight "..."` will attribute the insight to `Garrett Spangler` automatically — no need to type your name every time.

**Exit codes.** `0` = success, `2` = usage / validation error (e.g. bad `--status` value, `--role` without `--note`), `1` = other error (unknown product id, JSON parse failure, file write failure). Failed writes make **no changes** — the tool validates every flag before touching disk, so a mid-invocation reject leaves the file exactly as it was.

**How writes appear in git diffs.** The review file is serialized with `sort_keys=True`, so a single `--review` write shows up as just the added insight lines + the two `last_reviewed_*` fields. Every other entry stays byte-identical. The first `--review` (or regen) after upgrading to this version does a one-time key-order normalization — expect a big diff that pass, then clean diffs from then on.

---

## Findings

**From the work log** — the Home tab reads `WORKLOG.md` directly and shows every finding, newest first, quoted exactly as the teammate wrote it. Nothing is summarised or scored. Add a WORKLOG entry in the normal format and it appears on the next run; no registration needed.

**Curated insights** — the hand-written headline cards. Append a dict to `FINDINGS` near the top of `product_scope.py`, tagged with the product family:

```python
{"family": "acs/acs5", "stat": "22.8%", "headline": "The CV-only blind spot",
 "detail": "481 of 2,109 tracts look fine by the error bar but carry heavily imputed income.",
 "nb": "06", "kind": "finding"},
```

Use `"kind": "oddity"` for unexplained results — they render with a gold rule, matching how we flag open mentor questions elsewhere.

---

## Editable tables at the top of product_scope.py

Four lookup tables are meant to be edited by us, and nothing else depends on them:

| Table | Controls |
|---|---|
| `SUBJECTS` | which subject a product is filed under, matched on its title. First match wins, so specific rules sit above broad ones. |
| `PROGRAM_NAMES` / `PROGRAM_PREFIXES` | plain-English program names, including for single-segment paths like `ecncashadv` → Economic Census. |
| `TIMESERIES_PROGRAMS` | the real program behind a `timeseries/*` path. |
| `PRODUCT_MATCH` | which repo code counts as evidence for which tracked product. |

Subject and program affect **display order only**. They say nothing about a product's uncertainty, its priority, or how far our work has gone.

---

## What's committed and what isn't

| File | Committed? | Why |
|---|---|---|
| `tools/product_scope.py`, `tools/scope_evidence.py` | **yes** | the tool |
| `product_review.json` | **yes** | our scope decisions and review notes |
| `product_probes.json` | **yes** | what the API told us; probe once, share with the team |
| `product_report.html` | no | regenerated every run |
| `scope_field_cache.json` | no | ~4 MB API catalog cache, regenerable with `--online` |
| `scope_data_cache.json` | no | Phase 3 sample cache: EDA on actual API-fetched rows, regenerable with `--sample`. Local-only because it's a moment-in-time slice against a rate-limited endpoint — probes report facts about an endpoint, samples report facts about one download. |

---

## Known limits — read before quoting this to a mentor

- **The geography grid is inferred, not verified.** The five level boxes come from searching our files for the words "state", "county", "tract", "block". It is a rough indicator of where *we* have worked, not a record. **A probe is the verified version** — it reports the levels the Bureau says the product supports. Where the two disagree, trust the probe.
- **`2020 DHC` can't register progress.** Its evidence matcher looks for the string `dec/dhc`, which appears nowhere in our code, so it reads `Not started` regardless. Fix the matcher in `PRODUCT_MATCH` when we start on DHC.
- **Work depth can't see a missing import.** A notebook committed with clean outputs reads as `Validated` even if it won't run in a fresh clone.
- **Requires Python 3.11+.** Developed on 3.12.
