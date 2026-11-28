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
- 2026-11-27: Removed the orange Attention poster from the bottom of the page (the image file stays in static/, unused). The disclaimer now sits on the gray background as the last thing on the page, same text, bold "DISCLAIMER:". The poster can come back when the owner sends good/bad example photos and demo report links.
- 2026-11-27: New look (page only, backend untouched). Every finding is red (#FF003C, Inspectagram's brand red);
  the Attention / Immediate split and its count buttons are gone (`level()` always returns 'high'). A red "Fix it!"
  label (not a button) sits in the address card, which shows the street only (`streetOf`) plus "Correct almost
  EVERYTHING directly from the Summary."; no client line; the label and line hide when nothing is found. First card =
  Lucas's photo + the one report comment in quotes. Missed opportunities is slate (#43566A). Page background #EAEAEA so
  the white cards stand out. Section headings, address and quote use Lato. DISCLAIMER: is a bold run-in label. The
  Take snapshot picture uses the same colours. No grade / A+ (owner dropped it; no agreed meaning for grades).
- 2026-11-27: Round 1 of the owner's "Report Corrections" list, all in code, prompt untouched. Icon vs note:
  flag ONLY an Immediate icon with an Observation note (`find_icon_note_findings`); the model's own icon/note
  findings are dropped (`_icon_note_dupe`). Insurance: a bare n/a is an answer (blanks and #### still count).
  Blackbox is back in corrections: a stock-placeholder Blackbox photo = "Missing photo", and a chapter whose
  Blackbox has entries needs ONE Summary line ("Roof Blackbox"; `_blackbox_summary_gaps`, silent when the Summary
  has no Blackbox lines at all). Missing locations apply to Interior, Bathroom AND Exterior again (only entries
  with an Attention/Immediate icon); "general/various/throughout/areas" entries are exempt. Method and Icons &
  Legends moved to Missed opportunities. Known: Lucas's own report (R11) now shows "Roof Blackbox: Missing from
  Summary" (his Roof Blackbox is not in his Summary); kept on purpose. Not built: "every photo needs a title"
  (the scraper flattens table rows, so photos and titles cannot be paired).
- 2026-11-24: Owner's round after Lucas's own report (9c7b4fdf) came back with 19 flags, 13 of them false.
  (1) "Missing observation note" on photo-and-name tiles (thermal tiles, appliance row) and on a "Not Inspected"
  item with a reason: those rows use another invisible blank (U+200E) than the one the Nov 19 rule knew.
  New rule `_empty_row_without_icon`: the model's "a row with a label and nothing written" finding is kept only
  when the row carries an Attention or Immediate attention icon (`_attention_entry_names`). (2) A Summary entry
  that says "throughout", "multiple", "various" or "several" needs no location (`_EVERYWHERE_RE`); Lucas's
  Door Hinges was one, his "at the windows" / "in the flooring" entries still ask for one (owner to decide).
  (3) "Contract: Missing page" now reads "Contract: Not present." (left out on purpose sometimes; a heads-up).
  (4) New last section "Missed opportunities" (orange, `#f87700`, bullets, no counts, hidden by the red/yellow
  buttons): Conduct page (the realtor chapter, "The Business of People"), 72 Seconds page, and chapters whose
  Blackbox photo is still the stock placeholder. 72 Seconds and Blackbox moved out of "Missing items". Built in
  code (`find_missed_opportunities`), returned as `result["opportunities"]`, kept out of `findings` so they never
  change counts, the report comment or the admin log. Not built: a Lot7 line (owner: back burner, maybe "L7 URL");
  a check that the 72 Seconds logo is a link (the report's page source shows the logo as a plain image even on
  Lucas's own report, so a link check from the text is not possible; only the page's presence is checked);
  "no Blackbox block at all" in a chapter (older reports say "General Notes").
- 2026-11-23: 8 of 250 live runs failed with "Expecting value: line 1 column 1" (the review model's reply was not
  readable JSON; three in a row on one report that morning). `_read_reply` now takes the text blocks only, drops
  code fences, and reads from the first "{" to the last "}"; if it still can't read it, the review is asked once
  more (a second ~9 cents, only on a bad reply). Still bad: the student sees "Nani got tangled on that one. Tap
  Run it again." and the admin log keeps "unreadable reply: stop=..., N chars, starts: ..." (first 40 characters
  of the reply, also printed to the Render log). A "stop=max_tokens" there would mean the reply was cut off, which
  retrying will not fix (raise max_tokens or shorten the output instead). Prompt and input untouched. Also noted:
  the admin page groups runs by address, so one student's different drafts look like one wobbling report.
- 2026-11-19: Two more rules in code. (1) A row that is only a photo with no text ("Roof Observation - (2)",
  "Additional Vent(s)") is fine: `_photo_only_names` finds them from the report text (a label followed by
  blank/braille padding, with a [PHOTO] just before) and `_drop_out_of_scope` drops the model's "empty cell"
  finding about them. (2) A chapter whose Blackbox photo is still the "Walk & Talk" stock placeholder
  ([STOCK-IMAGE] right before the "Blackbox" label) is flagged, one line per chapter, in "Missing items"
  (`_blackbox_placeholders`). Older reports use "General Notes" instead of a "Blackbox" label and are not
  affected. Not built: the gray "+" empty slot (`<td class="cell-search">`, shows as a lone "+" line) because it
  also appears on fine rows; waiting on the owner's rule. Not yet seen: a filled Blackbox photo in a live run.
- 2026-11-18: Owner's round after Lucas's feedback. Rules in code on the review's output: an item missing
  from the Summary is never flagged (leaving one out takes a deliberate click), Insurance is only checked
  for blank fields and "####", two dates on the cover are fine. New code-made "Missing items" finding
  (`find_missing_pages`, kept out of the review's input): standard pages missing from the report's menu
  (Elements, Method, Disclaimer, Icons & Legends, 72 Seconds, Agreement/Contract), a weather line with no
  temperature on the Elements page, a leftover "sample contract". Icon/note mismatches read "Icon says
  Attention, note says Observation." Page: report links off (they sent people out of Nani and back into a
  full re-run), page numbers show on phone too, "Beta" tag, round Instagram photo in the card corner,
  Take snapshot button (canvas picture of all items, share sheet on phones), Run it matches the level
  buttons. Watch on live runs: "Contract: Missing page" shows on most reports that have no Agreement page.
- 2026-11-13 (night): Lucas: "if something is missing from the Summary it's probably supposed to be."
  Code rule `_minor_summary_gap` drops model-made yellow "in the report but missing from the Summary"
  findings; red ones (safety items) and code-found blank entries stay. None of the 5 saved reports had a
  yellow one, so the effect is only seen on live runs. Also: one comment for the whole report under the
  buttons (`report_comment`, picked in code), heading font Roboto Condensed, phone shows a "›" in place of
  the page number, fine print bold. Check a live run for a yellow gap that should have stayed.
- 2026-11-13 (later): Owner's new layout, from a picture of Lucas's: each finding is a numbered short
  line, "Item: what's wrong." (about five words), red and yellow bands only (high = Immediate attention,
  everything else = Attention), a green Run button, the page number at the right of each tappable line,
  and one comment per section under the list. The voice step now returns `lines` per finding; code-made
  findings build their own. Section comments come from `SECTION_COMMENTS` in code, never from the model
  (starter lines, the owner and Lucas supply the real list). The small model now and then returns a
  broken or partial reply, so the voice step asks twice and falls back per finding, not all-or-nothing.
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
