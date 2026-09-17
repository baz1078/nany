# Nanny: New Inspector Report Review

## Objective
Review a new inspector's finished Inspectagram report and flag everything they need to
fix before it goes to a client — the way a mentor inspector would red-pen a draft.
Working name only ("Nanny" / "training wheels") — not final branding.

## Required Input
- A report URL. Works with either:
  - The admin report URL (`admin.inspectagram.io/v3/reports/<id>`) — no login required to
    read the rendered HTML, confirmed 2026-08-21.
  - Any other hosted report URL that serves the report as a normal HTML page.

## Tools Used
- `tools/fetch_report.py` — `fetch_report_text(url)`. Self-contained HTML scraper
  (stdlib only), deliberately NOT imported from the Lot7 backend
  (`inspection-ai-backend/utils.py`) so this project has no cross-repo dependency.
  If Inspectagram changes its markup and the upstream scraper gets fixed there, port the
  fix over manually.
- `tools/review_report.py` — `review_report(url)`. Fetches the text, sends it to Claude
  (`claude-sonnet-4-6`) with the calibrated rubric, returns structured findings + a
  coaching summary. Run directly:
  ```
  python nanny/tools/review_report.py <report_url>
  ```
  Requires `ANTHROPIC_API_KEY` in the repo-root `.env`.

## What Gets Checked
Calibrated against one real "bad" report and one real "good" report from Assure
Inspections (2026-08-21):
1. **The Insurance section** — every field must have a checkbox prefix (◻️ normal /
   ⚠️ flagged) plus a real value. A bare `n/a` with no prefix is a completion gap.
   Confirmed real example: bad report left Site Limitations, Cooling Type(s), Barriers &
   Walls, Fire Separation, and Safety Auto Reverse as bare `n/a`; the good report had a
   real value on every single field.
2. **The Summary section** — should reflect every attention/immediate-attention item
   raised in the body. Missing, too-short, or omitting a body finding = flag.
3. **Cover page basics** — property address, client name, inspector name, inspection
   date present and not template defaults.
4. **Leftover draft artifacts** — instructional/placeholder text, "delete this",
   Lorem ipsum, TBD/TODO markers, empty scaffold pages.
5. **Missing photos** — a defect description with no photo evidence nearby, or repeated
   generic placeholder images.
6. **Severity/icon consistency** — an "immediate attention" icon should match genuinely
   urgent text; flag mismatches.

Not yet implemented: the "blackbox" check (deferred — definition still TBD as of
2026-08-21, revisit later).

## Output
Two outputs from one run, written to `nanny/.tmp/`:
- `nanny_review_<timestamp>.json` — structured findings (section, severity, issue,
  anchor, why it matters, fix) for admin review.
- `nanny_review_<timestamp>.txt` — the same, formatted as plain text, findings sorted
  high→low severity, each with a `{url}#{anchor}` deep link back to the exact spot in
  the report, plus the coaching summary at the end.

`nanny/.tmp/` is disposable — regenerate by re-running the script. Nothing here goes to
a cloud deliverable yet; that's a later step once the rubric is validated on more
reports.

## Known Gaps / Edge Cases
- Anchors: Inspectagram uses `#page-XX` on page containers and `#cell_<hash>` on
  individual findings. The scraper prefers `data-page-anchor` when present, else falls
  back to `id`. Not yet verified whether every finding actually has a precise
  `data-page-anchor` — if deep links keep landing on the wrong page, check whether we're
  only getting the coarse `page-XX` anchor and need a better precision strategy.
- Only tested against 2 reports total (1 good, 1 bad), both from the same company
  (Assure Inspections) and same report template. Rubric may need adjustment once tested
  against reports from other companies/templates.
- "Blackbox" check is a placeholder — nothing implemented for it yet.
- The admin report URL works without login for reading — this may not hold for every
  company/account on Inspectagram; verify if a report from another company 403s.

## Self-Improvement Log
- 2026-08-21: Built v1. Discovered the Insurance-section `n/a` pattern is a strong,
  reliable signal by diffing a real good/bad report pair — this is the most concrete
  rubric item so far. `admin.inspectagram.io/v3/reports/<id>` (no `.json` suffix, no
  auth) turned out to be readable HTML despite living under `/admin/`.
