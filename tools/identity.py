"""Who wrote the report: the inspector's name, email and phone from the report text.

Inspectagram reports carry the inspector's signature block ("Kind Regards," then the name, phone and
email) on the cover letter. Used only by the admin run log so the owner can reach out for feedback.
Pure text parsing - never changes a review. Returns None when nothing usable is found.
"""

import re

_REGARDS_RE = re.compile(r"^(kind|best|warm|sincere)?\s*(regards|sincerely),?$", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,20}$")


def extract_inspector(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    info = {"name": None, "email": None, "phone": None}
    for i, l in enumerate(lines):
        if not _REGARDS_RE.match(l):
            continue
        for nxt in lines[i + 1:i + 7]:
            if nxt.startswith("[ANCHOR"):
                break
            m = _EMAIL_RE.search(nxt)
            if m and not info["email"]:
                info["email"] = m.group(0).lower()
            elif _PHONE_RE.match(nxt) and not info["phone"]:
                info["phone"] = re.sub(r"\D", "", nxt)
            elif not info["name"] and len(nxt) <= 60:
                alt = re.match(r"^\[PHOTO\]\s*\[(.+)\]$", nxt)
                if alt:
                    info["name"] = alt.group(1).strip()
                elif not nxt.startswith("["):
                    info["name"] = nxt
        break
    return info if (info["name"] or info["email"]) else None
