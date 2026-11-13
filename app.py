"""Nani demo web app — paste a report URL, watch Nani review it live.

Built for recording a demo video: a thin Flask front-end over the same
review_report() used by the CLI tool, so what you record is the real
pipeline, not a mockup.

Run:
    python nanny/app.py
Then open http://127.0.0.1:5057
"""

import os
import re
import sys
import time

from flask import Flask, Response, jsonify, make_response, render_template, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools.review_report import review_report
from tools.fetch_report import BadLink
import admin_stats

app = Flask(__name__)

_LINK_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def clean_link(raw):
    """People paste the whole share message ("Your report is ready: https://..."); keep only the link."""
    raw = raw if isinstance(raw, str) else ""
    m = _LINK_RE.search(raw)
    return m.group(0).rstrip(".,;:!?)]") if m else raw.strip()


@app.route("/")
def index():
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-store"  # every visit gets the latest page, even in in-app browsers
    return resp


@app.route("/api/review", methods=["POST"])
def api_review():
    body = request.get_json(silent=True) or {}
    url = clean_link(body.get("url", ""))
    src = body.get("src")
    if not url:
        return jsonify({"error": "Paste a report URL first."}), 400
    started = time.time()
    try:
        result = review_report(url)
    except BadLink as exc:  # a link problem, not a Nani problem: say what to do instead
        admin_stats.log_run(None, None, time.time() - started, False, src=src, error="bad link: " + str(exc)[:90], url=url)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        admin_stats.log_run(None, None, time.time() - started, False, src=src, error=str(exc), url=url)
        return jsonify({"error": f"Nani couldn't finish that review: {exc}"}), 502
    result["source_url"] = url
    inspector = result.pop("inspector", None)  # contact details go to the admin log only, never to the browser
    admin_stats.log_run(result.get("property_address"), len(result.get("findings") or []), time.time() - started, True,
                        inspector=inspector, src=src, items=admin_stats.finding_labels(result.get("findings")), url=url,
                        fp=result.get("report_hash"))
    return jsonify(result)


@app.route("/admin")
def admin():
    if not os.environ.get("ADMIN_PASSWORD"):
        return "Not found", 404
    auth = request.authorization
    if not auth or not admin_stats.check_password(auth.password or ""):
        return Response("Sign in with the admin password.", 401, {"WWW-Authenticate": 'Basic realm="Nani admin"'})
    resp = make_response(render_template("admin.html", s=admin_stats.stats()))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/admin.csv")
def admin_csv():
    if not os.environ.get("ADMIN_PASSWORD"):
        return "Not found", 404
    auth = request.authorization
    if not auth or not admin_stats.check_password(auth.password or ""):
        return Response("Sign in with the admin password.", 401, {"WWW-Authenticate": 'Basic realm="Nani admin"'})
    return Response(admin_stats.csv_text(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=nani-runs.csv", "Cache-Control": "no-store"})


if __name__ == "__main__":
    # use_reloader=False: the reloader's watcher subprocess proved unreliable
    # for long-running requests during dev/testing (requests would silently
    # hang) - not worth it for a demo app that isn't being actively edited.
    app.run(debug=True, use_reloader=False, port=5057)
