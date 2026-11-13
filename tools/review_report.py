"""Nani: review a new inspector's Inspectagram report and flag what was left unfinished.

Usage:
    python review_report.py <report_url> [--out-dir .tmp]

Requires ANTHROPIC_API_KEY in the environment (loaded from the repo root .env).
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import anthropic
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.fetch_report import fetch_report_text
from tools.identity import extract_inspector

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))

MODEL = "claude-sonnet-4-6"

AREA_VALUES = ["cover", "agreement", "roof", "exterior", "attic", "interior", "kitchen",
               "laundry", "bathroom", "mechanical", "insurance", "summary", "other"]

SYSTEM_PROMPT = """You are Nani, a completeness checker for home inspection reports generated on the Inspectagram \
platform. You review a new/trainee inspector's finished report and point out what was left unfinished, left over, or \
incomplete before it goes to a client. You are NOT judging tone, wording, spelling, or professional opinions.

The report text below was scraped from the live HTML report. Format notes:
- Text in [brackets] is scraper metadata, not report content: [ANCHOR:page-NN] and [ANCHOR:cell_<hash>] mark the \
nearest element id (use these for the "anchor" field); [some icon] is an <img> alt attribute — severity is often \
conveyed this way (e.g. "[attention icon]", "[immediate attention icon]").
- [PHOTO] marks an image that is one of the inspector's own photos. [STOCK-IMAGE] marks a graphic from the \
platform's stock library — legend icons, chapter/"Baseline" intro pages, educational pages ("Framing 101", \
advisories), and generic "example" pictures. A stock image is NOT the inspector's photo.

THE CHECKLIST. Check every item below, on every report, and report everything that applies — be complete and \
consistent, do not pick favorites or skip items you consider minor. Report each distinct problem once.
1. Leftover/placeholder text (tag "Placeholder text"): a page or block reading "DELETE ME"/"DELETE THIS" or similar \
removal instructions; a leftover sample/template contract or disclaimer (e.g. "this document is provided as a sample \
template only"); unfilled placeholders ("####", "[INSERT ...]", "TBD", "TODO", Lorem ipsum); internal authoring notes \
or AI-prompt instructions meant for the inspector, not the client.
2. Incomplete Insurance section (tag "Missing info"): every field in "The Insurance" checklist must have a \
checkbox-style prefix (◻️ or ⚠️) followed by a real value. A bare "n/a" or a blank field with no prefix/value is \
incomplete — flag it. Report ALL blank or bare-"n/a" Insurance fields together in ONE "Missing info" finding that \
names every one of those fields (do not split them by page or section, and never one finding per field). \
Contradictions and "####" placeholders stay separate findings.
3. Photos (tag "Missing photos"): only a literal admission such as "forgot photo" or "no photo". You cannot see \
the pictures, so a [STOCK-IMAGE] sitting on a component is NOT a finding — it may be an informative diagram that \
belongs there. If a [STOCK-IMAGE] sits on a specific component or observation (e.g. "Toilet", "Kitchen Outlet(s)") \
with no [PHOTO] of its own, mention it only in "also_noticed", worded as a suggestion: "This looks like a stock \
image — if it isn't meant as an explanatory diagram, replace it with your own photo." Never mention stock images on \
legend, cover, chapter/Baseline, educational or advisory pages, or captioned how-to diagrams. Never claim a photo is \
missing when a [PHOTO] is present.
4. Empty content: an observation cell with a label but no issue, action, notes, and no [PHOTO] (tag "Missing info"). \
Empty "+" scaffold pages are found by code — never report them.
5. Summary gaps (tag "Missing info"): a serious safety or liability item in the body that is absent from the \
Summary. Do NOT flag routine maintenance items that simply aren't repeated in the Summary. Also flag a Summary \
entry that carries a severity icon but has no descriptive content at all (just an icon and a name). An entry is NOT \
blank if it describes the problem in any form — "Issue:"/"Action:" labels, or a plain sentence under the name. If \
several blank entries share the same name (for example "Additional Observations" under many chapters), report them \
as ONE finding that lists the chapters. Different names stay separate findings. Only \
flag one when there is genuinely nothing there.
6. Cover basics (tag "Missing info"): property address, inspector name, or inspection date missing, blank, or a \
template default. A blank client/customer name is fine — never flag it.
7. Icon vs. note disagree (tag "Mismatch"): an item whose severity icon says one level but its own note says another \
(e.g. [attention icon] with a note reading "Immediate Attention").
8. Contradictions between sections (tag "Mismatch"): two places in the report that cannot both be true. Go through \
the Insurance answers one by one: for every field marked ◻️ (normal) or "Present" (e.g. GFCI's, Smoke & CO, Heating \
Equipment, Cooling, Egress Windows, Garage fire separation), search the body and Summary for that same item — if they \
document it as missing, absent, damaged, or a risk (e.g. Insurance says GFCI's present but a body/Summary entry says \
"No GFCI protection"), that is a contradiction. Also flag two different inspection dates on the cover (tag \
"Mismatch", not "Missing info").
Missing locations in the Interior and Exterior Summary are found by code — never report them.

NEVER FLAG: tone, alarmist or unprofessional wording, boilerplate phrasing, negotiation advice, spelling, typos, or \
grammar, a blank client name, labeled reference/how-to diagrams. These are out of scope, even when obvious.

For every finding, classify it:
- "area": exactly one of: cover, agreement, roof, exterior, attic, interior, kitchen, laundry, bathroom, mechanical, \
insurance, summary, other ("other" only if truly nothing fits). Any finding about a field inside The Insurance \
pages (including "####" ages, blank fields, n/a answers) is always area "insurance", even when the field describes \
another system such as heating or the roof.
- "tag": exactly one of the tags named above — "Missing info", "Missing photos", "Mismatch", "Placeholder text". \
Never invent another.
- "severity": use this fixed rule so results are consistent — "high": leftover sample contract/disclaimer, "DELETE \
ME" pages, unfilled placeholders, safety items missing from the Summary; "medium": incomplete Insurance fields, \
photo problems, blank Summary entries, icon/note or cross-section mismatches, missing cover info; "low": empty \
minor cells, unused pages, and missing locations.

CODE-DETECTED MATCHES: the user message may list literal matches found by a text scan (e.g. "DELETE ME", "####"). \
Each one is confirmed present — include every one in your findings (matches of the same kind on the same page may \
be grouped into one finding).

ALSO NOTICED: after the checklist, add up to 5 items to "also_noticed": something else that looks unfinished, left \
over, or incomplete — or that a client would clearly question — that none of the checklist items cover. Same \
out-of-scope rules apply (no tone, opinions, spelling). Do not repeat a checklist finding. If there is nothing, \
return an empty list; never pad it.

Also return "sections_reviewed": the areas (same list as above) this report actually contains — skip "laundry" if \
it has no laundry section. This drives an explicit clean checkmark for sections with no findings.

Return ONLY valid JSON, no markdown fencing:
{
  "property_address": "..." or null,
  "client_name": "..." or null,
  "overall_assessment": "one sentence, plain and direct",
  "sections_reviewed": ["cover", "roof", "exterior", "..."],
  "findings": [
    {
      "section": "e.g. The Insurance, The Summary, Cover Page, Kitchen",
      "area": "one of the fixed area values",
      "tag": "one of the fixed tags",
      "severity": "high|medium|low",
      "issue": "what's wrong, specifically — this is the evidence, keep full detail/quotes here",
      "anchor": "the nearest [ANCHOR:...] value if one appeared near this issue, else null",
      "why_it_matters": "a short phrase, under 8 words, not a sentence (e.g. 'Erodes trust, creates liability if disputed')",
      "fix": "a short phrase, under 8 words, not a sentence (e.g. 'Pick the correct date, remove the other')"
    }
  ],
  "also_noticed": [
    {
      "section": "...",
      "area": "one of the fixed area values",
      "issue": "what looks unfinished or questionable, specifically",
      "anchor": "nearest [ANCHOR:...] value, else null",
      "fix": "a short phrase, under 8 words"
    }
  ],
  "coaching_summary": "a short, encouraging paragraph (120-200 words) written directly to the inspector — \
group the recurring patterns, not just a repeat of every line item, and end on what they did well if anything \
stood out as solid"
}"""

# SYSTEM_PROMPT above is deliberately left alone. Every edit to it, even one extra rule, moved unrelated
# findings around (tested 2026-11-12 on 5 reports: findings merged, dropped, shifted to "Also noticed",
# and new ones invented). So new rules are enforced in code on the review's output (_drop_out_of_scope),
# and Nani's voice is a separate second pass: a small model rewords the finished findings afterwards.
# It only ever sees the findings, never the report.
VOICE_MODEL = "claude-haiku-5-5"

VOICE_PROMPT = """You reword quality-check findings about a home inspection report. Another reviewer already \
decided what is wrong; you change only how it is said. Never add, drop, merge, split or reorder findings, and never \
change a fact or a name.

The voice: a firm, experienced mentor talking straight to a trainee inspector. Short, clean, direct. Never rude.

For each finding write "issue": what is wrong, in plain everyday words, straight to the point.
- One or two short sentences, 25 words at most. Where it fits, close with a short pointed question ("Why isn't it \
in the Summary?", "Which is it?", "Where is it?").
- Say "you" and "your". Aim at the report, never at the person. No insults, no profanity, no ALL CAPS, no \
exclamation marks.
- Say only what is wrong. Never say why it matters, what the client will think, how it makes anyone look, or how \
to fix it. Never write "Fix it." because the page adds that.
- Say it in your own plain words; do not copy text out of the report.
- A finding tagged "Not filled in" means the inspector never put the real thing in. Write one sentence that \
starts with "You didn't put" and says what is missing and where: "You didn't put the age of the AC unit in the \
Insurance section." Nothing else: no question, and no word about what is sitting there in its place.
- No symbols or markup: no dashes, colons, semicolons, brackets, parentheses, slashes, emoji or icon characters. \
Write "an attention icon", never "[attention icon]".
- No page numbers. The page shows those separately.
- Never write "checkbox", "prefix", "prefixed", "placeholder", "filler", "template" or "body". Say "the report" \
or name the section ("the Bathroom section").
- Name an entry only when the inspector needs it to know which one, and then always put its name in single \
quotes, exactly as the finding gives it: 'Furnace', 'Hot Water Unit(s)'. A name in quotes may keep its own \
punctuation. If the finding lists several entries, keep every name, even if that runs past 25 words.
- Each finding stands alone. Use only what that finding's own text says.
- Do not take sides. When two things disagree, say that they disagree and leave the choice to the inspector.

Also write "overall": exactly two short sentences, under 35 words, in the same voice and under the same rules. \
The verdict first, then the main things to fix. No questions. If there are no findings, say the report is ready \
to send.

Examples of the voice:
"You found a missing GFCI in the bathroom. Why isn't it in the Summary?"
"Insurance says the bathroom GFCI is present. The Bathroom section says there isn't one. Which is it?"
"You didn't put the age of the AC unit in the Insurance section."
"'Furnace' has an attention icon, but its note says Observation. Which is it?"
"The water heater has no photo."
overall "Close, but not ready to send. One safety item is missing from the Summary and the Insurance section has gaps."

Return ONLY valid JSON, no markdown fencing, one entry per input finding with the same "i":
{"overall": "...", "findings": [{"i": 0, "issue": "..."}]}"""


_NUMBER_WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven",
                 "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen", "Twenty"]


def _insurance_list(findings, blanks):
    """The blank Insurance fields as a list for the page to show, taken from the code scan and limited to
    the fields the review's own Insurance finding names. Returns (finding, items) or (None, None)."""
    for f in findings:
        if f.get("area") != "insurance" or f.get("tag") != "Missing info":
            continue
        issue = (f.get("issue") or "").lower()
        items = []
        for b in blanks or []:
            label = b.split(" (")[0]
            if label.lower() in issue:
                items.append({"name": label, "note": "says n/a" if "n/a" in b[len(label):] else None})
        if len(items) >= 3:
            return f, items
    return None, None


_FILLER_RE = re.compile(r"(?:the\s+)?(?:placeholder\s+)?['\"]?(?:[A-Za-z]+:\s*)?#{3,}['\"]?", re.IGNORECASE)


def _no_questions(s):
    """The verdict states things; drop any closing question the model adds."""
    parts = re.split(r"(?<=[.?!])\s+", s.strip())
    while len(parts) > 1 and parts[-1].endswith("?"):
        parts.pop()
    return " ".join(parts)


def _only_whats_missing(s):
    """A 'not filled in' finding says what is missing and nothing about what was left in its place."""
    parts = re.split(r"(?<=[.?!])\s+", s.strip())
    lead = [p for p in parts if p.startswith("You didn't put")]
    if lead:
        return lead[0]
    return " ".join(p for p in parts if not re.search(r"placeholder|#{3,}", p, re.IGNORECASE)) or s


def _tidy(s):
    """Last pass on a reworded sentence: no page references, dashes, icon characters or trailing 'Fix it.'."""
    s = re.sub(r"\s*\((?:see\s+)?(?:pages?|pp?\.)[\s-]*\d+(?:\s*(?:,|and|&|-)\s*\d+)*\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+[—–]\s+|\s+-\s+", ", ", s)
    s = re.sub(r"[⚠◻◼⬜✅️⠀]", "", s)
    s = re.sub(r"\b([Tt])he body(?: of the report)?\b", r"\1he report", s)
    s = re.sub(r"\s*\bFix it\.?\s*$", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", s).strip()


def apply_voice(result, client=None, insurance_blanks=None):
    """Reword each model-written finding into one plain sentence, plus the one-line verdict. Wording only:
    which findings exist, their order, tags, severity, sections and links are never touched, and code-made
    findings already carry the voice. Any failure leaves the original wording in place."""
    if os.environ.get("NANI_VOICE", "").lower() == "off":
        return result
    items = [f for f in result.get("findings") or [] if f.get("source") != "code"]
    listed, names = _insurance_list(items, insurance_blanks)
    payload = {"overall": result.get("overall_assessment") or "",
               "total_findings": len(result.get("findings") or []),
               "findings": [{"i": i, "tag": f.get("tag"), "severity": f.get("severity"), "section": f.get("section"),
                             "issue": f.get("issue"), "why": f.get("why_it_matters"), "fix": f.get("fix")}
                            for i, f in enumerate(items)]}
    for entry, f in zip(payload["findings"], items):
        if f is listed:  # this one gets fixed wording below; the voice model only needs the gist for its verdict
            entry["issue"] = f"{len(names)} fields in The Insurance section are blank or say only 'n/a'."
        if entry["tag"] == "Placeholder text":  # the inspector should hear what is missing, not what was left there
            entry["tag"] = "Not filled in"
            for k in ("issue", "why", "fix"):
                entry[k] = _FILLER_RE.sub("(nothing filled in)", entry[k] or "")
    try:
        client = client or anthropic.Anthropic(timeout=90.0, max_retries=1)
        message = client.messages.create(
            model=VOICE_MODEL, max_tokens=12000, system=VOICE_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            # A rewording job: no thinking, low effort. Measured 2026-11-12: about 5s this way, against
            # 12-22s whenever the model chose to think. Effort goes via extra_body because the pinned SDK
            # (0.75.0) predates the output_config argument.
            thinking={"type": "disabled"},
            extra_body={"output_config": {"effort": "low"}})
        raw = "".join(b.text for b in message.content if b.type == "text").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        out = json.loads(raw.strip())
        by_i = {int(o["i"]): o for o in out.get("findings", [])}
        if set(by_i) != set(range(len(items))) or not all(
                isinstance(o.get("issue"), str) and o["issue"].strip() for o in by_i.values()):
            print("[nani] voice step skipped: incomplete rewrite", file=sys.stderr, flush=True)
            return result  # keep the original wording rather than mix two voices
        for i, f in enumerate(items):
            f["issue"] = _tidy(by_i[i]["issue"])
            if f.get("tag") == "Placeholder text":
                f["issue"] = _only_whats_missing(f["issue"])
        if listed is not None:  # the page lists the names, so this finding gets fixed wording that never repeats them
            count = _NUMBER_WORDS[len(names)] if len(names) < len(_NUMBER_WORDS) else str(len(names))
            listed["issue"] = f"{count} Insurance fields have no answer."
            listed["items"] = names
        if isinstance(out.get("overall"), str) and out["overall"].strip():
            result["overall_assessment"] = _no_questions(_tidy(out["overall"]))
    except Exception as exc:  # never let the wording step break a review; say so in the server log
        print(f"[nani] voice step skipped: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr, flush=True)
    return result


# Literal leftovers a text scan can find with certainty. Found in code (not left
# to the model) so they're reported the same way on every run.
LITERAL_PATTERNS = [
    ("DELETE ME / DELETE THIS text", r"delete\s+(?:me|this)\b"),
    ("'####' placeholder", r"####"),
    ("[INSERT ...] placeholder", r"\[\s*insert[^\]]{0,60}\]"),
    ("sample/template disclaimer", r"(?:provided as a )?sample template|sample only"),
    ("Lorem ipsum", r"lorem ipsum"),
    ("'forgot photo' note", r"forgot photo"),
    ("TBD/TODO marker", r"\b(?:TBD|TODO)\b"),
    ("AI-prompt instruction", r"paste the following"),
]
_ANCHOR_RE = re.compile(r"\[ANCHOR:([^\]]+)\]")


def find_literal_hits(text, cap=25):
    hits, seen = [], set()
    anchors = [(m.start(), m.group(1)) for m in _ANCHOR_RE.finditer(text)]
    for label, pat in LITERAL_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            anchor = None
            for pos, a in anchors:
                if pos > m.start():
                    break
                anchor = a
            key = (label, anchor)
            if key in seen:
                continue
            seen.add(key)
            snippet = _ANCHOR_RE.sub("", text[max(0, m.start() - 70): m.end() + 70])
            hits.append({"kind": label, "anchor": anchor, "snippet": " ".join(snippet.split())})
    return hits[:cap]


def anchor_hashes(text):
    """Short hash of the text behind each anchor (a whole page for page anchors), so a
    re-run can tell whether the text an item points at actually changed."""
    marks = [(m.start(), m.end(), m.group(1)) for m in _ANCHOR_RE.finditer(text)]
    out = {}
    for i, (_, end, a) in enumerate(marks):
        stop = len(text)
        for nxt_start, _, nxt in marks[i + 1:]:
            if not a.startswith("page-") or nxt.startswith("page-"):
                stop = nxt_start
                break
        out[a] = hashlib.md5(text[end:stop].encode("utf-8")).hexdigest()[:8]
    return out


def _clean_lines(text):
    return [l.strip() for l in text.splitlines() if l.strip()]


_ICON_LEVEL = {"observation": 1, "attention": 2, "immediate": 3}


def _level(word):
    w = word.lower()
    return 3 if "immediate" in w else 2 if "attention" in w else 1 if "observation" in w else None


def find_icon_note_mismatches(text):
    """Summary entries look like: [icon] / 'Name: Issue: ...' / 'Action: ...' /
    'Notes: <Observation|Attention|Immediate Attention> - ...'. The icon and the note's
    own opening label must agree; comparing them is mechanical, so it's done here."""
    lines, out, anchor, icon = _clean_lines(text), [], None, None
    for i, l in enumerate(lines):
        m = _ANCHOR_RE.search(l)
        if m:
            anchor = m.group(1)
        im = re.fullmatch(r"\[([^\]]*icon)\]", l, re.IGNORECASE)
        if im:
            icon = (im.group(1), _level(im.group(1)), i)
            continue
        nm = re.match(r"Notes:\s*(Immediate Attention|Attention|Observation)", l)
        if nm and icon and i - icon[2] <= 6 and icon[1]:
            note_level = _level(nm.group(1))
            if note_level != icon[1]:
                name = lines[icon[2] + 1].split(":")[0] if icon[2] + 1 < len(lines) else "?"
                out.append({"name": name, "icon": icon[0], "note": nm.group(1), "anchor": anchor})
            icon = None
    return out


def _find_insurance_blanks_raw(text):
    """Insurance fields are 'Label' followed by a value starting with a checkbox mark. A label
    followed directly by another label (or a bare 'n/a') has no value. Only the Insurance
    pages are scanned (each starts with 'the' / 'insurance')."""
    lines = _clean_lines(text)
    seq, in_ins = [], False
    for i, l in enumerate(lines):
        if re.fullmatch(r"\[ANCHOR:page-[^\]]+\]", l):
            head = [x.lower() for x in lines[i + 1:i + 3]]
            in_ins = head == ["the", "insurance"]
            continue
        if in_ins and l.startswith("[Inspectagram]"):
            break
        if not in_ins or _ANCHOR_RE.fullmatch(l) or l.lower() in ("the", "insurance") or l.isdigit():
            continue
        seq.append(l)
    blanks = []
    for i, l in enumerate(seq):
        if l.startswith(("◻", "⚠")) or l.lower() == "n/a":
            continue
        nxt = seq[i + 1] if i + 1 < len(seq) else ""
        is_heading = bool(re.search(r"(Overview|System|Systems)$", l)) or l == "Kitchen & Bathroom"
        if nxt.lower() == "n/a":
            blanks.append(f"{l} (bare 'n/a')")
        elif not nxt.startswith(("◻", "⚠")) and not is_heading:
            blanks.append(l)
    return blanks


def page_map(text):
    """anchor -> report page number, using the nearest page-N anchor at or before it."""
    out, page = {}, None
    for m in _ANCHOR_RE.finditer(text):
        a = m.group(1)
        pm = re.fullmatch(r"page-(\d+)", a)
        if pm:
            page = int(pm.group(1))
        out[a] = page
    return out


_MEDIA_LINE_RE = re.compile(r"(?:\[ANCHOR:[^\]]+\]\s*)+(?:\[(?:PHOTO|STOCK-IMAGE)\]\s*)*")
_PAGE_ANCHOR_RE = re.compile(r"\[ANCHOR:(page-\d+)\]")
_SEV_ICON_RE = re.compile(r"\[([^\]]*(?:attention|observation)[^\]]*icon)\]", re.IGNORECASE)
_AREA_WORDS = {"roof": "roof", "exterior": "exterior", "attic": "attic", "interior": "interior",
               "kitchen": "kitchen", "laundromat": "laundry", "laundry": "laundry",
               "bathroom": "bathroom", "mechanical": "mechanical"}


def _anchor_or_media(line):
    return bool(_MEDIA_LINE_RE.fullmatch(line))


def _first_anchor(line):
    m = _ANCHOR_RE.search(line)
    return m.group(1) if m else None


def _code_finding(area, tag, severity, section, issue, anchor, why, fix):
    return {"section": section, "area": area, "tag": tag, "severity": severity, "issue": issue,
            "anchor": anchor, "why_it_matters": why, "fix": fix, "source": "code"}


_INS_HEADING_RE = re.compile(r"(Overview|System|Systems|Q&A)$|^Kitchen & Bathroom$")


def find_insurance_blanks(text):
    """Insurance fields with no value, for the model to write up. Guarded so an unfamiliar report
    layout can't flood the prompt: group headings are dropped, and an implausibly long list is
    ignored entirely (the model then judges the Insurance page on its own)."""
    out = []
    for b in _find_insurance_blanks_raw(text):
        label = b.split(" (")[0]
        if len(label) > 50 or _INS_HEADING_RE.search(label):
            continue
        out.append(b)
    return out if len(out) <= 25 else []


def find_blank_summary_entries(text):
    """Summary entries with an icon and nothing under them (or an Issue but no Action). Only the
    exact 'empty' shapes count - an entry written as a plain sentence is never flagged, so
    report templates that don't use Issue:/Action: labels can't cause false alarms."""
    lines, found = _clean_lines(text), []
    for i, l in enumerate(lines):
        icon_m = _SEV_ICON_RE.fullmatch(l)
        if not icon_m or i + 1 >= len(lines):
            continue
        name_line = lines[i + 1]
        if ":" not in name_line or "Click Here" in name_line or name_line.startswith(("⚠", "◻", "Notes:", "Action:")):
            continue
        name = re.split(r"\s*:", name_line, maxsplit=1)[0].replace("⠀", "").strip()
        after_name = name_line.split(":", 1)[1].strip(" ⠀")
        j, action, notes = i + 2, False, False
        while j < len(lines) and lines[j].startswith(("Action:", "Notes:")):
            val = lines[j].split(":", 1)[1].strip(" ⠀")
            action = action or (lines[j].startswith("Action:") and bool(val))
            notes = notes or (lines[j].startswith("Notes:") and bool(val))
            j += 1
        nxt = lines[j] if j < len(lines) else ""
        sentence_follows = bool(nxt) and not _anchor_or_media(nxt) and not _SEV_ICON_RE.fullmatch(nxt) and not _chapter_of(nxt)
        if not after_name and j == i + 2 and not sentence_follows:
            kind = "nothing"
        elif "Issue:" in name_line and after_name != "Issue:" and not action and not notes and not sentence_follows:
            kind = "no Action"
        else:
            continue
        anchor = _first_anchor(nxt) if _anchor_or_media(nxt) else None
        found.append((name, icon_m.group(1), kind, anchor))
    out, by_name = [], {}
    for item in found:
        by_name.setdefault((item[0], item[2]), []).append(item)
    for (name, kind), items in by_name.items():
        anchor = next((a for _, _, _, a in items if a), None)
        if len(items) > 1:
            issue = f"{len(items)} Summary entries named '{name}' are flagged, with nothing written under them."
            fix = "Fill them in, or remove the empty entries."
        elif kind == "nothing":
            issue = f"'{name}' is flagged in the Summary, with nothing written under it. What's wrong with it?"
            fix = "Add the issue and action, or remove the entry."
        else:
            issue = f"'{name}' in the Summary says what's wrong, but not what to do about it."
            fix = "Add the action, or remove the entry."
        out.append(_code_finding("summary", "Missing info", "medium", f"The Summary — {name}", issue, anchor,
                                 "A flagged item has to give the client something to act on.", fix))
    return out


def find_empty_pages(text):
    """A page whose only content is its header, page number and a lone '+' is an unused scaffold."""
    lines, out = _clean_lines(text), []
    starts = [i for i, l in enumerate(lines) if _PAGE_ANCHOR_RE.fullmatch(l)]
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[s + 1:e]
        scaffold = [b for b in block if b == "+" or re.fullmatch(r".{1,40} \+", b)]
        rest = [b for b in block if b not in scaffold and not b.isdigit() and not _anchor_or_media(b)]
        has_media = any(_anchor_or_media(b) and ("[PHOTO]" in b or "[STOCK-IMAGE]" in b) for b in block)
        if scaffold and not rest and not has_media:
            page = _PAGE_ANCHOR_RE.fullmatch(lines[s]).group(1)
            header = next((b for b in scaffold if b != "+"), "")
            area = next((v for k, v in _AREA_WORDS.items() if k in header.lower()), "other")
            num = page.split("-")[1]
            out.append(_code_finding(
                area, "Unused pages", "low", f"{header.rstrip(' +') or 'Report'} — page {num}",
                f"Page {num} is empty.",
                page, "An empty page looks unfinished to the client.", "Delete the empty page."))
    return out


_CHAPTER_NAMES = {"roof": "Roof", "exterior": "Exterior", "attic": "Attic", "interior": "Interior",
                  "kitchen": "Kitchen", "laundromat": "Laundry", "laundry": "Laundry", "bathroom": "Bathroom",
                  "mechanical": "Mechanical", "garage": "Garage"}
_LOC_RE = re.compile(r"\bL:\s*(?!Click Here)\S")


def _chapter_of(line):
    """Summary chapter headings are short standalone lines such as 'Interior' or 'Exterior System'."""
    if len(line) > 28:
        return None
    key = re.sub(r"\s*\+$", "", line).lower()
    key = re.sub(r"\s*\((?:cont|continued)[^)]*\)\s*$", "", key)
    key = re.sub(r"\s+system$", "", key)
    return _CHAPTER_NAMES.get(key)


def find_missing_locations(text):
    """Interior and Exterior Summary entries should say where the problem is ('L: Office, Kitchen').
    One grouped finding per chapter, listing the entries with no location."""
    lines, chapter, missing = _clean_lines(text), None, {}
    for i, l in enumerate(lines):
        chapter = _chapter_of(l) or chapter
        if not _SEV_ICON_RE.fullmatch(l) or i + 1 >= len(lines):
            continue
        name_line = lines[i + 1]
        if ":" not in name_line or "Click Here" in name_line or name_line.startswith(("⚠", "◻", "Notes:", "Action:")):
            continue
        j, body = i + 2, [name_line]
        while j < len(lines) and not _SEV_ICON_RE.fullmatch(lines[j]) and not _anchor_or_media(lines[j]) and not _chapter_of(lines[j]):
            body.append(lines[j])
            j += 1
        if chapter in ("Interior", "Exterior") and not _LOC_RE.search(" ".join(body)):
            name = re.split(r"\s*:", name_line, maxsplit=1)[0].replace("⠀", "").strip()
            anchor = _first_anchor(lines[j]) if j < len(lines) and _anchor_or_media(lines[j]) else None
            missing.setdefault(chapter, []).append((name, anchor))
    out = []
    for chapter, items in missing.items():
        names = [f"'{n}'" for n, _ in items[:8]] + ([f"and {len(items) - 8} more"] if len(items) > 8 else [])
        out.append(_code_finding(
            chapter.lower(), "Missing location", "low", f"{chapter} — Summary",
            f"{len(items)} {chapter} Summary {'entry does not' if len(items) == 1 else 'entries do not'} say where: "
            + ", ".join(names) + ". Where?",
            next((a for _, a in items if a), None),
            "If the client can't find it, they can't fix it.", "Add an 'L:' location to each entry."))
    return out


def find_code_findings(text):
    """Findings that are pure pattern matches: built in code with fixed wording so they come out
    identical on every run and cost no model output tokens."""
    return find_blank_summary_entries(text) + find_empty_pages(text) + find_missing_locations(text)


def _drop_code_duplicates(claude_items, code_items):
    """Empty pages, missing locations and empty Summary entries are reported by code; drop any copy the model adds."""
    def norm(s):
        return re.sub(r"\W+", "", s).lower()
    names = {norm(m) for c in code_items if c["area"] == "summary" for m in re.findall(r"'([^']{2,60})'", c["issue"])}
    kept = []
    for it in claude_items:
        if it.get("tag") in ("Unused pages", "Missing location"):
            continue
        quoted = {norm(q) for q in re.findall(r"'([^']{2,60})'", it.get("issue", ""))}
        if it.get("area") == "summary" and it.get("tag") == "Missing info" and quoted & names:
            continue
        kept.append(it)
    return kept


_PHOTO_ONLY_RE = re.compile(
    r"\b(?:has|have|contains?|shows?|with)\s+(?:only\s+)?(?:an?\s+|its\s+own\s+)?\[PHOTO\][^.]{0,60}\b(?:but|and|with)\s+no\b",
    re.IGNORECASE)
_NO_LOCATION_RE = re.compile(
    r"\b(?:no|missing|without)\s+(?:(?:an?|the)\s+)?(?:'T:'[^.]{0,25})?(?:'L:'|\(L:\)|L:|location\b)", re.IGNORECASE)


_BLACKBOX_HEAD_RE = re.compile(r"^(?:⚠️?\s*)?[A-Za-z][A-Za-z /&]{1,30}\bGeneral (?:Notes|Observations)\b", re.IGNORECASE)
_BLACKBOX_WORD_RE = re.compile(r"\bGeneral (?:Notes|Observations)\b|\bBlackBOX\b", re.IGNORECASE)
_QUOTED_RE = re.compile(r"'([^']{15,240})'|\"([^\"]{15,240})\"|“([^”]{15,240})”")


def _norm_text(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def blackbox_texts(text):
    """The BlackBOX is the block that closes a chapter: '⚠️ <Chapter> General Notes' (or 'General
    Observations'), usually a numbered list and an End Statement. Returns (inside, outside): the text
    of every BlackBOX block, and the rest of the report, both lower-cased with single spaces."""
    inside, outside, in_box = [], [], False
    for line in _clean_lines(text):
        if "[ANCHOR:" in line or _SEV_ICON_RE.fullmatch(line):
            in_box = False
        elif _BLACKBOX_HEAD_RE.match(line) and "Click" not in line:
            in_box = True
            continue
        (inside if in_box else outside).append(line)
    return _norm_text(" ".join(inside)), _norm_text(" ".join(outside))


def _about_blackbox(item, inside, outside):
    """True when an item says something is missing from the Summary and that something lives in a BlackBOX:
    it names the General Notes block, or quotes text that appears only inside one."""
    issue = item.get("issue") or ""
    if item.get("tag") in ("Mismatch", "Placeholder text"):
        return False
    if item.get("area") != "summary" and "summary" not in issue.lower():
        return False
    if _BLACKBOX_WORD_RE.search(issue + " " + (item.get("section") or "")):
        return True
    for m in _QUOTED_RE.finditer(issue):
        for piece in re.split(r"\.\.\.|…", next(g for g in m.groups() if g)):
            piece = _norm_text(piece).strip(" .,;:")
            if len(piece) >= 15 and piece in inside and piece not in outside:
                return True
    return False


def _drop_out_of_scope(items, text=""):
    """Rules enforced on the review's output, so the review prompt itself never has to change:
    - a BlackBOX item does not need its own Summary entry (the General Notes pointer covers it);
    - a photo with no text is fine;
    - an entry with no location is only a problem in Interior and Exterior, and code checks those."""
    inside, outside = blackbox_texts(text) if text else ("", "")
    return [it for it in items
            if not _PHOTO_ONLY_RE.search(it.get("issue", "")) and not _NO_LOCATION_RE.search(it.get("issue", ""))
            and not _about_blackbox(it, inside, outside)]


def review_report(url):
    text = fetch_report_text(url)
    hits = find_literal_hits(text)
    hits_block = ""
    if hits:
        hits_block = "CODE-DETECTED MATCHES (each must be reported):\n" + "\n".join(
            f"- {h['kind']} near [ANCHOR:{h['anchor']}]: \"{h['snippet']}\"" for h in hits) + "\n\n"
    mism = find_icon_note_mismatches(text)
    if mism:
        hits_block += ("SUMMARY ICON/NOTE MISMATCHES (found by code, each is confirmed - report every one):" + "\n" +
                       "\n".join(f"- {m['name']}: shows [{m['icon']}] but its note starts with \"{m['note']}\"" for m in mism)
                       + "\n" + "\n")
    blanks = find_insurance_blanks(text)
    if blanks:
        hits_block += ("INSURANCE FIELDS WITH NO VALUE (found by code; if an item is clearly not a checklist field, "
                       "such as a heading or an address, ignore it; every real field listed is blank and must be named "
                       "in your ONE Insurance 'Missing info' finding):" + "\n" +
                       "\n".join(f"- {b}" for b in blanks) + "\n" + "\n")
    code_items = find_code_findings(text)
    if code_items:
        hits_block += ("ALREADY REPORTED BY CODE (do NOT report these again anywhere, including Also noticed):\n"
                       + "\n".join(f"- {c['section']}" for c in code_items) + "\n\n")
    client = anthropic.Anthropic(timeout=300.0, max_retries=1)
    # Streamed rather than a single blocking create() call — a non-streamed request
    # that runs long risks a client-side read timeout even while the server is still
    # generating normally (see https://docs.anthropic.com/en/api/errors#long-requests).
    with client.messages.stream(
        model=MODEL,
        max_tokens=12000,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Report URL: {url}\n\n{hits_block}Report text:\n\n{text}"}],
    ) as stream:
        message = stream.get_final_message()
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    result = json.loads(raw.strip())
    result.setdefault("also_noticed", [])
    # Exterior entries no longer need a location (owner, 2026-11-13). The finding is still built above so
    # the review's input stays exactly as it was; it is only left out of the result.
    shown_code = [c for c in code_items if not (c["tag"] == "Missing location" and c["area"] == "exterior")]
    result["findings"] = _drop_out_of_scope(_drop_code_duplicates(result.get("findings", []), code_items), text) + shown_code
    result["also_noticed"] = _drop_out_of_scope(_drop_code_duplicates(result["also_noticed"], code_items), text)
    apply_voice(result, client, insurance_blanks=blanks)
    result["report_hash"] = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    result["anchor_hashes"] = anchor_hashes(text)
    result["inspector"] = extract_inspector(text)  # for the admin run log only; app.py strips it from the response
    pages = page_map(text)
    for item in result.get("findings", []) + result.get("also_noticed", []):
        item["page"] = pages.get(item.get("anchor"))
    return result


def format_admin_report(url, result):
    lines = []
    lines.append(f"NANI REVIEW — {result.get('property_address') or 'address not found'}")
    lines.append(f"Client: {result.get('client_name') or 'not found'}")
    lines.append(f"Source: {url}")
    lines.append("")
    lines.append(f"Overall: {result.get('overall_assessment', '')}")
    lines.append("")

    findings = result.get("findings", [])
    order = {"high": 0, "medium": 1, "low": 2}
    severity_label = {"high": "LIABILITY", "medium": "CREDIBILITY", "low": "POLISH"}
    findings = sorted(findings, key=lambda f: order.get(f.get("severity", "low"), 3))

    lines.append(f"FINDINGS ({len(findings)})")
    lines.append("-" * 60)
    for f in findings:
        sev = severity_label.get(f.get("severity", "low"), "POLISH")
        section = f.get("section", "")
        lines.append(f"[{sev}] {section}: {f.get('issue', '')}")
        if f.get("why_it_matters"):
            lines.append(f"    Why: {f['why_it_matters']}")
        if f.get("fix"):
            lines.append(f"    Fix: {f['fix']}")
        anchor = f.get("anchor")
        if anchor:
            lines.append(f"    Link: {url}#{anchor}")
        lines.append("")

    lines.append("-" * 60)
    lines.append("COACHING SUMMARY (for the inspector)")
    lines.append(result.get("coaching_summary", ""))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Nani: review an Inspectagram report")
    parser.add_argument("url", help="Public/admin URL to the Inspectagram report")
    parser.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tmp"))
    args = parser.parse_args()

    result = review_report(args.url)
    report_text = format_admin_report(args.url, result)

    os.makedirs(args.out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = os.path.join(args.out_dir, f"nanny_review_{stamp}.json")
    txt_path = os.path.join(args.out_dir, f"nanny_review_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(report_text)

    print(report_text)
    print(f"\nSaved: {json_path}")
    print(f"Saved: {txt_path}")


if __name__ == "__main__":
    main()
