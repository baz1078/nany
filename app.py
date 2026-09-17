"""Nany demo web app — paste a report URL, watch Nany review it live.

Built for recording a demo video: a thin Flask front-end over the same
review_report() used by the CLI tool, so what you record is the real
pipeline, not a mockup.

Run:
    python nanny/app.py
Then open http://127.0.0.1:5057
"""

import os
import sys

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools.review_report import review_report

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/review", methods=["POST"])
def api_review():
    url = (request.get_json(silent=True) or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "Paste a report URL first."}), 400
    try:
        result = review_report(url)
    except Exception as exc:
        return jsonify({"error": f"Nany couldn't finish that review: {exc}"}), 502
    result["source_url"] = url
    return jsonify(result)


if __name__ == "__main__":
    # use_reloader=False: the reloader's watcher subprocess proved unreliable
    # for long-running requests during dev/testing (requests would silently
    # hang) - not worth it for a demo app that isn't being actively edited.
    app.run(debug=True, use_reloader=False, port=5057)
