"""Run log + password-protected /admin page for Nani.

Stores one row per report run (time, address, finding count, seconds, ok/failed) in SQLite.
Never stores report text or client names. Logging is best-effort: any failure here is swallowed
so it can never affect a review.

Settings (env):
    ADMIN_PASSWORD  required to enable /admin (unset = page returns 404)
    NANI_DATA_DIR   where the database lives (default: ./data; on Render point it at the disk mount)
    ADMIN_TZ        timezone for "today" and the daily bars (default America/Chicago)
"""

import hmac
import os
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
    return con


def log_run(address, findings, seconds, ok):
    """Record one run. Best-effort - never raises."""
    try:
        with _db() as con:
            con.execute(
                "INSERT INTO runs (ts, address, findings, seconds, ok) VALUES (?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), (address or "")[:200],
                 findings, round(seconds, 1), 1 if ok else 0),
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


def stats():
    """Everything the admin page shows."""
    tz = _tz()
    now = datetime.now(tz)
    today = now.date()
    with _db() as con:
        rows = con.execute("SELECT ts, address, findings, seconds, ok FROM runs ORDER BY id DESC").fetchall()
    parsed = []
    for ts, address, findings, seconds, ok in rows:
        local = datetime.fromisoformat(ts).astimezone(tz)
        parsed.append({"local": local, "address": address, "findings": findings, "seconds": seconds, "ok": bool(ok)})
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
    return {
        "tiles": tiles,
        "cost": {k: round(v * COST_PER_REPORT, 2) for k, v in tiles.items()},
        "days": [{"label": str(d.day), "count": counts.get(d, 0)} for d in days],
        "recent": [
            {"when": r["local"].strftime("%b %d, %I:%M %p").replace(" 0", " "), "address": r["address"] or "—",
             "findings": r["findings"], "seconds": r["seconds"], "ok": r["ok"]}
            for r in parsed[:30]
        ],
        "tz": getattr(tz, "key", "UTC"),
    }
