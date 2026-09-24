"""Nany: review a new inspector's Inspectagram report and flag what was left unfinished.

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

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))

MODEL = "claude-sonnet-4-6"

AREA_VALUES = ["cover", "agreement", "roof", "exterior", "attic", "interior", "kitchen",
               "laundry", "bathroom", "mechanical", "insurance", "summary", "other"]

SYSTEM_PROMPT = """You are Nany, a completeness checker for home inspection reports generated on the Inspectagram \
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
incomplete — flag it (fields on the same Insurance page may be grouped into one finding that names them).
3. Photos (tag "Missing photos"): (a) a [STOCK-IMAGE] sitting on a specific component or observation (e.g. "Toilet", \
"Kitchen Outlet(s)") with no [PHOTO] belonging to that same component — an example picture left where the inspector's \
own photo belongs; (b) a literal admission such as "forgot photo" or "no photo". Do NOT flag stock images on legend, \
cover, chapter/Baseline, educational or advisory pages, or captioned how-to diagrams. A component with a [PHOTO] near \
it has its photo — never claim a photo is missing when a [PHOTO] is present.
4. Empty content: a page with no content at all, only scaffolding such as a lone "+" (tag "Unused pages"); an \
observation cell with a label but no issue, action, notes, and no [PHOTO] (tag "Missing info").
5. Summary gaps (tag "Missing info"): a Summary entry that carries an icon but has no issue/action/notes; a serious \
safety or liability item in the body that is absent from the Summary. Do NOT flag routine maintenance items that \
simply aren't repeated in the Summary.
6. Cover basics (tag "Missing info"): property address, inspector name, or inspection date missing, blank, or a \
template default. A blank client/customer name is fine — never flag it.
7. Icon vs. note disagree (tag "Mismatch"): an item whose severity icon says one level but its own note says another \
(e.g. [attention icon] with a note reading "Immediate Attention").
8. Contradictions between sections (tag "Mismatch"): two places in the report that cannot both be true (e.g. \
Insurance says a system is "not present" or a safety item is fine, but the body documents a defect there; two \
different inspection dates on the cover).

NEVER FLAG: tone, alarmist or unprofessional wording, boilerplate phrasing, negotiation advice, spelling, typos, or \
grammar, a blank client name, labeled reference/how-to diagrams. These are out of scope, even when obvious.

For every finding, classify it:
- "area": exactly one of: cover, agreement, roof, exterior, attic, interior, kitchen, laundry, bathroom, mechanical, \
insurance, summary, other ("other" only if truly nothing fits).
- "tag": exactly one of the tags named above — "Missing info", "Missing photos", "Mismatch", "Unused pages", \
"Placeholder text". Never invent another.
- "severity": use this fixed rule so results are consistent — "high": leftover sample contract/disclaimer, "DELETE \
ME" pages, unfilled placeholders, safety items missing from the Summary; "medium": incomplete Insurance fields, \
photo problems, blank Summary entries, icon/note or cross-section mismatches, missing cover info; "low": empty \
minor cells and unused pages.

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


def find_insurance_blanks(text):
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
        hits_block += ("INSURANCE FIELDS WITH NO VALUE (found by code; group headings such as 'Roof System' or "
                       "'Garage Systems' may appear here - ignore those, they have no value of their own; every "
                       "real field listed is blank and must be named in your Insurance finding(s)):" + "\n" +
                       "\n".join(f"- {b}" for b in blanks) + "\n" + "\n")
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
    result["report_hash"] = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    result["anchor_hashes"] = anchor_hashes(text)
    return result


def format_admin_report(url, result):
    lines = []
    lines.append(f"NANY REVIEW — {result.get('property_address') or 'address not found'}")
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
    parser = argparse.ArgumentParser(description="Nany: review an Inspectagram report")
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
