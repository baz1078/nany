"""Nani demo web app — paste a report URL, watch Nani review it live.

Built for recording a demo video: a thin Flask front-end over the same
review_report() used by the CLI tool, so what you record is the real
pipeline, not a mockup.

Run:
    python nanny/app.py
Then open http://127.0.0.1:5057
"""

import os
import sys
import time

from flask import Flask, Response, jsonify, make_response, render_template, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools.review_report import review_report
import admin_stats

app = Flask(__name__)


@app.route("/")
def index():
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-store"  # every visit gets the latest page, even in in-app browsers
    return resp


@app.route("/api/review", methods=["POST"])
def api_review():
    url = (request.get_json(silent=True) or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "Paste a report URL first."}), 400
    started = time.time()
    try:
        result = review_report(url)
    except Exception as exc:
        admin_stats.log_run(None, None, time.time() - started, False)
        return jsonify({"error": f"Nani couldn't finish that review: {exc}"}), 502
    result["source_url"] = url
    admin_stats.log_run(result.get("property_address"), len(result.get("findings") or []), time.time() - started, True)
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


if __name__ == "__main__":
    # use_reloader=False: the reloader's watcher subprocess proved unreliable
    # for long-running requests during dev/testing (requests would silently
    # hang) - not worth it for a demo app that isn't being actively edited.
    app.run(debug=True, use_reloader=False, port=5057)
