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
- 2026-11-13: Owner wants each finding as ONE plain sentence plus "Fix it." No why/fix lines, no tag pills,
  no "####", dashes, symbols or page numbers in the sentence. The voice step now writes only `issue`.
  A small model ignores "never mention the placeholder" about one time in three, so that part is done in
  code: the filler is stripped from what the voice model sees, the tag is sent as "Not filled in", and
  only the "You didn't put ..." sentence is kept (`_FILLER_RE`, `_only_whats_missing`, `_tidy`).
- 2026-11-13: Exterior Summary entries no longer need a location (Interior still does). The Exterior
  finding is still built so the review's input stays identical; it is only left out of the result.
  "Also noticed" is no longer shown. The link box keeps only the https link from whatever is pasted.
- 2026-11-13: Old wording inside the new layout means a saved result: the page re-shows the last result
  from the browser. Re-run the report before assuming the voice step failed.
- 2026-11-12: **Do not edit the review prompt (`SYSTEM_PROMPT`) to add rules or change wording.**
  Tested on 5 reports: every edit, even one added rule, moved unrelated findings around (merged,
  dropped, shifted to "Also noticed", new false alarms). New rules go in code on the review's output
  (`_drop_out_of_scope`), and wording is a separate second pass (`apply_voice`, `claude-haiku-5-5`)
  that only sees the finished findings. Voice step: thinking off + low effort = about 5s; with thinking
  it took 12-22s. If it fails, the original wording is kept and a `[nani] voice step skipped` line is
  logged. `NANI_VOICE=off` turns it off.
- 2026-11-12: "Blackbox" is now defined: the block that closes a chapter, headed
  "⚠️ <Chapter> General Notes" (or "General Observations"). Rules from the owner: BlackBOX items never
  need their own Summary entry; a photo with no text is fine; a missing location only matters in
  Interior and Exterior. The blank Insurance fields show as one finding with a bulleted list.
- 2026-11-12: Known and still open: two runs on the same unchanged report can differ by a finding or
  two (19 vs 21 on one test report). That is the review model itself, not the rules above.
- 2026-08-21: Built v1. Discovered the Insurance-section `n/a` pattern is a strong,
  reliable signal by diffing a real good/bad report pair — this is the most concrete
  rubric item so far. `admin.inspectagram.io/v3/reports/<id>` (no `.json` suffix, no
  auth) turned out to be readable HTML despite living under `/admin/`.
