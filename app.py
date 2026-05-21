"""
app.py — Flask web server.

Routes
------
  GET  /              → serves the webapp (index.html)
  POST /api/audit     → accepts JSON {"urls": [...]} and returns audit results
"""

from flask import Flask, jsonify, render_template, request

from checker import check_headings, SEVERITY_ERROR, SEVERITY_WARNING
from crawler import crawl_many

app = Flask(__name__)


def _truncate(text: str, n: int = 80) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


def _build_payload(urls: list[str]) -> list[dict]:
    results = []
    for cr in crawl_many(urls):
        entry: dict = {"url": cr.url}

        if not cr.ok:
            entry["fetch_error"] = cr.error
            entry["pass"] = False
            results.append(entry)
            continue

        check = check_headings(cr.headings)

        tree = [
            {
                "level":      h.level,
                "tag":        h.tag,
                "text":       _truncate(h.text) if h.text else None,
                "is_image":   h.is_image,
                "image_alts": h.image_alts,
            }
            for h in cr.headings
        ]

        issues = [
            {
                "rule":     i.rule,
                "severity": i.severity,
                "message":  i.message,
            }
            for i in check.all_issues
        ]

        entry.update({
            "pass":            check.overall_pass,
            "h1_pass":         check.h1_pass,
            "h1_count":        check.h1_count,
            "h1_is_image":     any(h.level == 1 and h.is_image for h in cr.headings),
            "hierarchy_pass":  check.hierarchy_pass,
            "heading_count":   len(cr.headings),
            "warning_count":   sum(1 for i in check.all_issues if i.severity == SEVERITY_WARNING),
            "tree":            tree,
            "issues":          issues,
        })
        results.append(entry)

    return results


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/audit")
def audit():
    body = request.get_json(silent=True) or {}
    raw_urls: list[str] = body.get("urls", [])

    urls = []
    for u in raw_urls:
        u = u.strip()
        if not u:
            continue
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        urls.append(u)

    if not urls:
        return jsonify({"error": "No valid URLs provided."}), 400

    try:
        payload = _build_payload(urls)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500

    return jsonify({"results": payload})


if __name__ == "__main__":
    app.run(debug=True, port=5000)