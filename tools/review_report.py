"""Nany: review a new inspector's Inspectagram report and flag what needs fixing.

Usage:
    python review_report.py <report_url> [--out-dir .tmp]

Requires ANTHROPIC_API_KEY in the environment (loaded from the repo root .env).
"""

import argparse
import json
import os
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

SYSTEM_PROMPT = """You are Nany, a QA reviewer for home inspection reports generated on the Inspectagram platform. \
You review a new/trainee inspector's finished report and flag everything they need to fix before it goes to a client, \
the same way a mentor inspector would red-pen a draft.

The report text below was scraped from the live HTML report. Some things to know about the format:
- Text in [brackets] is metadata injected by the scraper, not report content: [ANCHOR:page-NN] and \
[ANCHOR:cell_<hash>] mark the nearest element id (use these to build a deep link back to the exact spot); \
[some icon] is an <img> alt attribute — severity is often conveyed this way (e.g. "[attention icon]", \
"[immediate attention icon]"), not in body text.
- "The Insurance" section is a structured checklist near the end of the report. Every field in it should be \
answered with a checkbox-style prefix (◻️ = normal / not flagged, ⚠️ = flagged) followed by a real, specific value \
(e.g. "⚠️ Unit: A/C - Age: 2025 (Incomplete)"). A field left as a bare "n/a" or blank with NO checkbox prefix and \
no real value is a completion gap, not a legitimate answer — flag every one of these individually.
- "The Summary" section should reflect genuinely important attention/immediate-attention items raised in the body — \
safety hazards, life-safety concerns, or anything with real liability weight. Flag a missing summary entirely, or a \
summary that omits a specific high-severity/safety item. Do NOT flag every routine body observation (a dirty vent, \
a loose railing, ordinary maintenance items) just because it isn't individually repeated in the summary — that's \
normal, not an omission. Use this check sparingly; it should catch a handful of real gaps, not audit every line.
- The cover/disclaimer pages near the start should have the property address, inspector name, and inspection date. \
Flag if any of these are missing, blank, or clearly a template default (e.g. "123 Main St"). Do NOT flag a missing \
or blank client/customer name — that field is expected to be blank on some reports and is not something to raise.
- Watch for leftover draft/template artifacts the inspector forgot to remove — treat each of these as its own \
finding, don't lump them together: instructional/internal-authoring text meant for the inspector, not the client \
(e.g. AI-prompt instructions, "paste the following into..."); unfilled placeholder fields (e.g. "[INSERT ...]", \
"####", bracketed instructions); a leftover sample/template contract or disclaimer block (e.g. "this document is \
provided as a sample template only"); any page whose content is literally "DELETE ME", "DELETE THIS", or similar \
explicit removal instructions left in a client-facing page; Lorem ipsum; TBD/TODO markers; pages that are just \
empty scaffolding.
- Watch for missing photos, but only on explicit textual evidence — the scraper does not reliably capture whether \
a photo is present (it only captures an <img> alt attribute when one happens to exist, so a real, unlabeled photo \
sitting right next to a finding is invisible to you; absence of an image mention in the text is NOT proof a photo \
is missing). Only flag a missing photo when the text itself says so directly: a literal admission ("forgot photo", \
"no photo"), or a cell/finding that is completely blank with zero content of any kind (no notes, no label, nothing \
at all). Never flag "no photo" just because you don't see an image mentioned near a finding that otherwise has \
real notes — that finding likely has a photo you simply can't see. Do NOT flag a cell whose only content is a \
generic supplementary-photo caption/label (e.g. "Support Photo", "Additional Photo") even if nothing else appears \
near it — that caption alone is not evidence either way, since it's used both for real defect photos and for \
reference illustrations, and you cannot tell which from text.
- Check severity consistency: an item marked with the "immediate attention" icon should read as genuinely urgent in \
its description — flag any mismatch between the icon severity and what the text actually says.

Do not invent issues that aren't supported by the text. If a section looks genuinely complete, don't flag it just to \
have something to say.

Be selective, not exhaustive. Flag what would genuinely embarrass the inspector, create liability, or confuse the \
client — not every minor inconsistency you can technically justify. A report with 15 well-chosen findings is more \
useful than one with 40 granular ones; over-flagging makes Nany alarmist and trains inspectors to tune it out. When \
you're on the fence about whether something really matters, leave it out.

For every finding, also classify it:
- "area": which part of the report it belongs to. Pick exactly one from this fixed list — use "other" only if truly \
nothing else fits: cover, agreement, roof, exterior, attic, interior, kitchen, laundry, bathroom, mechanical, \
insurance, summary, other.
- "tag": a short label for what kind of problem this is. Pick exactly one from this fixed list — inspectors scan \
this on a phone and need to recognize it instantly, so never invent a variant wording:
  - "Missing info" — a blank/incomplete field, an empty finding with no issue/action/notes, missing cover info.
  - "Missing photos" — meets the strict photo-evidence bar above.
  - "Mismatched severity" — icon vs. text disagree, or this finding contradicts another section (e.g. Insurance \
says "not present" but the body documents a defect there).
  - "Wording" — content exists but is worded badly: typos, unprofessional or alarmist language, generic \
boilerplate left in place of a real description. Covers everything from a simple typo to overstated language — \
keep the label itself neutral either way, the severity field is what signals how serious it is.
  - "Unused pages" — an empty scaffold page with no content at all.
  - "Placeholder text" — unfilled brackets/####, "DELETE ME"/"DELETE THIS", a leftover sample contract or \
disclaimer, or an internal authoring note that leaked into a client-facing page.

Also return "sections_reviewed": the list of areas (from the same fixed list above) that this specific report \
actually contains — e.g. skip "laundry" if the property/report has no laundry section. This is used to show an \
explicit clean checkmark for any section that has zero findings, so only include areas that are genuinely present \
in this report.

Return ONLY valid JSON, no markdown fencing:
{
  "property_address": "..." or null,
  "client_name": "..." or null,
  "overall_assessment": "one sentence, plain and direct",
  "sections_reviewed": ["cover", "roof", "exterior", "..."],
  "findings": [
    {
      "section": "e.g. The Insurance, The Summary, Cover Page, Kitchen",
      "area": "one of the fixed area values above",
      "tag": "one of the fixed tag values above",
      "severity": "high|medium|low",
      "issue": "what's wrong, specifically",
      "anchor": "the nearest [ANCHOR:...] value if one appeared near this issue, else null",
      "why_it_matters": "why a new inspector should care (client trust, liability, completeness)",
      "fix": "the concrete action to take"
    }
  ],
  "coaching_summary": "a short, encouraging paragraph (120-200 words) written directly to the inspector — \
group the recurring patterns, not just a repeat of every line item, and end on what they did well if anything \
stood out as solid"
}"""


def review_report(url):
    text = fetch_report_text(url)
    client = anthropic.Anthropic(timeout=300.0, max_retries=1)
    # Streamed rather than a single blocking create() call — a non-streamed request
    # that runs long risks a client-side read timeout even while the server is still
    # generating normally (see https://docs.anthropic.com/en/api/errors#long-requests).
    with client.messages.stream(
        model=MODEL,
        max_tokens=12000,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Report URL: {url}\n\nReport text:\n\n{text}"}],
    ) as stream:
        message = stream.get_final_message()
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw.strip())


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
