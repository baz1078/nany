"""Run log + password-protected /admin page for Nani.

Stores one row per report run in SQLite: time, address, finding count, seconds, ok/failed, the
inspector's name/email/phone (from the report's signature, for feedback outreach), an optional ?src=
tag, short labels of what was flagged, and a short error for failed runs.
Never stores report text or client names. Logging is best-effort: any failure here is swallowed
so it can never affect a review.

Settings (env):
    ADMIN_PASSWORD  required to enable /admin (unset = page returns 404)
    NANI_DATA_DIR   where the database lives (default: ./data; on Render point it at the disk mount)
    ADMIN_TZ        timezone for "today" and the daily bars (default America/Chicago)
"""

import hmac
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

COST_PER_REPORT = 0.093  # measured average on Sonnet, 2026-10

_DATA_DIR = os.environ.get("NANI_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _db():
    os.makedirs(_DATA_DIR, exist_ok=True)
    con = sqlite3.connect(os.path.join(_DATA_DIR, "runs.db"), timeout=10)
    con.execute(
        "CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
        "address TEXT, findings INTEGER, seconds REAL, ok INTEGER NOT NULL)"
    )
    have = {r[1] for r in con.execute("PRAGMA table_info(runs)")}
    for col in ("inspector_name", "inspector_email", "inspector_phone", "source", "items", "error", "url", "how", "fp"):
        if col not in have:
            con.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")
    return con


def clean_src(src):
    return re.sub(r"[^a-z0-9_-]", "", (src or "").lower())[:30] or None


def finding_labels(findings):
    """Short 'area | tag | section' labels - what was flagged, without any report wording."""
    return [" | ".join(str(f.get(k) or "")[:60] for k in ("area", "tag", "section")) for f in (findings or [])]


def clean_url(url):
    url = (url or "").strip()
    return url[:300] if url.lower().startswith(("http://", "https://")) else None


def log_run(address, findings, seconds, ok, inspector=None, src=None, items=None, error=None, url=None, fp=None):
    """Record one run. Best-effort - never raises."""
    try:
        insp = inspector or {}
        with _db() as con:
            con.execute(
                "INSERT INTO runs (ts, address, findings, seconds, ok, inspector_name, inspector_email, "
                "inspector_phone, source, items, error, url, how, fp) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), (address or "")[:200],
                 findings, round(seconds, 1), 1 if ok else 0,
                 (insp.get("name") or "")[:80] or None, (insp.get("email") or "")[:120] or None,
                 (insp.get("phone") or "")[:20] or None, clean_src(src),
                 json.dumps(items or [], ensure_ascii=False) if items else None, (error or "")[:160] or None,
                 clean_url(url), (insp.get("how") or ("none" if ok else None)), (fp or "")[:16] or None),
            )
    except Exception:
        pass


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(os.environ.get("ADMIN_TZ", "America/Chicago"))
    except Exception:
        return timezone.utc


def check_password(supplied):
    expected = os.environ.get("ADMIN_PASSWORD", "")
    return bool(expected) and hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def _norm(addr):
    """Address key for matching runs of the same report: lowercase letters and digits only."""
    key = re.sub(r"[^a-z0-9]", "", (addr or "").lower())
    return key if len(key) >= 8 else None


def _load(tz):
    """Every run, newest first, with two things worked out: who an unnamed run most likely belongs to
    (same address as a run whose report named the inspector) and whether the report text changed since
    the previous run of that report."""
    with _db() as con:
        rows = con.execute(
            "SELECT ts, address, findings, seconds, ok, inspector_name, inspector_email, inspector_phone, "
            "source, items, error, url, how, fp FROM runs ORDER BY id DESC").fetchall()
    parsed = []
    for ts, address, findings, seconds, ok, iname, iemail, iphone, source, items, error, url, how, fp in rows:
        local = datetime.fromisoformat(ts).astimezone(tz)
        try:
            labels = json.loads(items) if items else []
        except Exception:
            labels = []
        parsed.append({"local": local, "address": address, "findings": findings, "seconds": seconds, "ok": bool(ok),
                       "name": iname, "email": iemail, "phone": iphone, "source": source, "items": labels, "error": error,
                       "url": url, "how": how, "fp": fp, "inferred": False, "text": None})
    known = {}  # address key -> the most recent identity the report itself gave
    for r in parsed:
        k = _norm(r["address"])
        if r["ok"] and k and (r["name"] or r["email"]) and k not in known:
            known[k] = (r["name"], r["email"], r["phone"])
    for r in parsed:
        k = _norm(r["address"])
        if r["ok"] and k and not (r["name"] or r["email"]) and k in known:
            r["name"], r["email"], r["phone"] = known[k]
            r["inferred"] = True
    last_fp = {}  # compare each run's report text with the previous run of the same report
    for r in reversed(parsed):
        key = r["url"] or _norm(r["address"])
        if not (r["ok"] and r["fp"] and key):
            continue
        if key in last_fp:
            r["text"] = "same" if last_fp[key] == r["fp"] else "edited"
        last_fp[key] = r["fp"]
    return parsed


def _csv_cell(value):
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text  # keep spreadsheets from running cell text


def csv_text():
    """All runs as CSV for outreach or sharing, newest first."""
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["time", "inspector", "email", "phone", "matched_by_address", "source", "address", "report_link",
                "findings", "seconds", "status", "note", "report_text_vs_previous_run"])
    for r in _load(_tz()):
        w.writerow([_csv_cell(v) for v in (
            r["local"].strftime("%Y-%m-%d %H:%M"), r["name"], r["email"], r["phone"], "yes" if r["inferred"] else "",
            r["source"], r["address"], r["url"], r["findings"], r["seconds"], "ok" if r["ok"] else "failed",
            r["error"] or ("no inspector found" if r["ok"] and not (r["name"] or r["email"]) and r["how"] == "none" else ""),
            r["text"])])
    return out.getvalue()


def stats():
    """Everything the admin page shows."""
    tz = _tz()
    now = datetime.now(tz)
    today = now.date()
    parsed = _load(tz)
    good = [r for r in parsed if r["ok"]]
    week_start = today - timedelta(days=today.weekday())
    counts = {}
    for r in good:
        counts[r["local"].date()] = counts.get(r["local"].date(), 0) + 1
    days = [today - timedelta(days=i) for i in range(13, -1, -1)]
    tiles = {
        "today": counts.get(today, 0),
        "week": sum(n for d, n in counts.items() if d >= week_start),
        "month": sum(n for d, n in counts.items() if (d.year, d.month) == (today.year, today.month)),
        "all": len(good),
    }
    people = {}
    for r in parsed:  # newest first, so the first row seen per person is their latest run
        if not r["ok"] or not (r["email"] or r["name"]):
            continue
        key = (r["email"] or r["name"]).lower()
        p = people.setdefault(key, {"name": r["name"], "email": r["email"], "phone": r["phone"], "source": r["source"],
                                    "runs": 0, "addresses": set(), "last": r["local"], "last_findings": r["findings"],
                                    "byaddr": {}, "how": r["how"], "inferred": 0})
        p["runs"] += 1
        p["inferred"] += 1 if r["inferred"] else 0
        p["addresses"].add((r["address"] or "").strip().lower())
        g = p["byaddr"].setdefault((r["address"] or "").strip().lower(),
                                   {"address": r["address"] or "—", "url": None, "runs": 0, "counts": [], "last": r["local"]})
        g["runs"] += 1
        g["counts"].append(r["findings"])
        g["url"] = g["url"] or r["url"]  # newest run that kept a link
        p["source"] = p["source"] or r["source"]
    top = sorted(people.values(), key=lambda p: (-p["runs"], -p["last"].timestamp()))[:15]
    for p in top:
        p["reports"] = len({a for a in p.pop("addresses") if a})
        groups = sorted(p.pop("byaddr").values(), key=lambda g: -g["last"].timestamp())
        for g in groups:
            g["counts"] = list(reversed(g["counts"]))[-10:]  # oldest to newest
            g["last"] = g["last"].strftime("%b %d").replace(" 0", " ")
        p["reports_list"] = groups
        p["last"] = p["last"].strftime("%b %d").replace(" 0", " ")
    unknown = sum(1 for r in parsed if r["ok"] and not (r["email"] or r["name"]))
    return {
        "people": top,
        "unknown_runs": unknown,
        "tiles": tiles,
        "cost": {k: round(v * COST_PER_REPORT, 2) for k, v in tiles.items()},
        "days": [{"label": str(d.day), "count": counts.get(d, 0)} for d in days],
        "recent": [
            {"when": r["local"].strftime("%b %d, %I:%M %p").replace(" 0", " "), "address": r["address"] or "—",
             "findings": r["findings"], "seconds": r["seconds"], "ok": r["ok"], "name": r["name"], "email": r["email"],
             "source": r["source"], "labels": r["items"], "error": r["error"], "url": r["url"], "how": r["how"],
             "inferred": r["inferred"], "text": r["text"]}
            for r in parsed[:30]
        ],
        "tz": getattr(tz, "key", "UTC"),
    }
