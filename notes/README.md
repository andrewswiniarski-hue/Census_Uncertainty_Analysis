# notes/ — browser-only insight recording

Drop a `.txt` note file into this folder to record an insight about a Census
product without opening a terminal or editing `product_review.json` by hand.
The next `python tools/product_scope.py` regen picks it up, appends it as a
human insight, and moves the file into `notes/ingested/` so it doesn't
re-ingest on subsequent runs.

## The fastest way to get a note file

1. Open `product_report.html` in your browser.
2. Find the card for the product you want to note (search / filter / click
   into any panel).
3. Expand the card's **"More details ▸"** drill-down.
4. Scroll to the bottom of the drill-down and click **"+ Add a note"**.
5. Your browser downloads a file like `note_acs_acs5_2026-07-26_14-05-12.txt`.
6. Move that file into this `notes/` folder in the repo.
7. Open it in a text editor, replace `Your Name` with your actual name and
   the `(Write your thought here …)` prompt with your observation.
8. Save the file.
9. Run `python tools/product_scope.py` from the repo root. The tool prints a
   line like `[notes] ingested 1 note(s) from notes/ (acs/acs5)` and moves
   your file into `notes/ingested/`. Your note is now on that product's card.

## File format

Plain text. Case-insensitive header keys, comments start with `#`, first
blank line separates the header block from the body:

```
# Any line starting with # is a comment.
# Save this file into notes/ in the repo. Next regen picks it up.

product_id: acs/acs5
who: Katie Doe

The MOE column looks huge on the smaller counties in New Jersey — 30% CV
in Salem, 22% in Cape May. Might explain why we didn't get a stable
signal on the initial cut.
```

**Required keys:** `product_id` (must match a Census catalog path exactly —
e.g. `acs/acs5`, not `ACS 5-year`) and `who` (your name; defaults to
`unknown` if you leave it blank). Everything after the blank line becomes the
insight text; multi-line is fine.

The tool skips files whose `product_id` isn't in the catalog and prints why —
usually a typo. Fix and re-run.

## Dedup

If a note with the same text from the same author already exists on that
product (e.g. you re-drop the same file after regen already ate it), the tool
notices, moves the file into `notes/ingested/` anyway, and doesn't create a
duplicate entry. If two teammates want to say the same thing that's fine —
different `who:` values land as two separate insights.

## What's committed

- `notes/*.txt` — while it's here, it hasn't been ingested yet. If you're
  reviewing a PR and see a note file at the top level of `notes/`, next
  regen ingests it.
- `notes/ingested/*.txt` — the paper trail of every note that got ingested
  since the folder was set up. Committed so `git log notes/ingested/` shows
  contribution history.

Both are tracked by git — this is meant to be a shared, per-teammate
contribution record.

## When to use CLI vs. this flow

- **CLI (`python tools/product_scope.py --review <id> --insight "..."`):**
  fastest when you're already in a terminal, and it auto-attributes to
  `git config user.name`.
- **This flow:** best when you're browsing the report in your browser and
  don't want to context-switch to a terminal — click, edit, drop, next
  regen. Same insight, same feed.
