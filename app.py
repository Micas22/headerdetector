"""
app.py — Flask web server.

Routes
------
  GET  /                    → serves the webapp (index.html)
  POST /api/audit           → {"urls": [...]}       → single-page audit
  POST /api/audit-paginated → {"listing_urls": [...]} → SSE stream of progress + results
"""

import json
import queue
import threading
import time

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from checker import check_headings, SEVERITY_WARNING
from crawler import crawl_many, crawl_paginated, crawl_site

app = Flask(__name__)


def _truncate(text: str, n: int = 80) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


def _build_result_entry(cr) -> dict:
    entry: dict = {"url": cr.url}
    if not cr.ok:
        entry["fetch_error"] = cr.error
        entry["pass"] = False
        return entry

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
        {"rule": i.rule, "severity": i.severity, "message": i.message}
        for i in check.all_issues
    ]

    entry.update({
        "pass":           check.overall_pass,
        "h1_pass":        check.h1_pass,
        "h1_count":       check.h1_count,
        "h1_is_image":    any(h.level == 1 and h.is_image for h in cr.headings),
        "hierarchy_pass": check.hierarchy_pass,
        "heading_count":  len(cr.headings),
        "warning_count":  sum(1 for i in check.all_issues if i.severity == SEVERITY_WARNING),
        "tree":           tree,
        "issues":         issues,
    })
    return entry


def _build_payload(urls: list[str]) -> list[dict]:
    return [_build_result_entry(cr) for cr in crawl_many(urls)]


# ── routes ────────────────────────────────────────────────────────────────────

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
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"results": payload})


@app.post("/api/audit-paginated")
def audit_paginated():
    """
    Streams Server-Sent Events for live progress.

    Event types sent to client:
      heartbeat — ": keep-alive" comment line  (every ~20 s, prevents idle timeout)
      progress  — {"phase":"listing","page":N,"total_pages":T,"found_so_far":K}
                  {"phase":"items","index":N,"total":T,"url":"..."}
      result    — {"listing_url":...,"listing_page":N,"entry":{...}}
      done      — {"total": N}
      error     — {"message": "..."}
    """
    body = request.get_json(silent=True) or {}
    raw_listing_urls: list[str] = body.get("listing_urls", [])

    listing_urls = []
    for u in raw_listing_urls:
        u = u.strip()
        if not u:
            continue
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        listing_urls.append(u)

    if not listing_urls:
        return jsonify({"error": "No valid listing URLs provided."}), 400

    # Queue shared between crawl thread and SSE generator.
    # Items are ("event_name", payload_dict) or _HEARTBEAT or _DONE.
    event_queue: queue.Queue = queue.Queue()
    _DONE      = object()
    _HEARTBEAT = object()

    # ── heartbeat thread: sends a ping every 20 s so the browser/proxy
    #    doesn't close an idle connection while pages are being fetched.
    def _heartbeat():
        while True:
            time.sleep(20)
            event_queue.put(_HEARTBEAT)

    hb_thread = threading.Thread(target=_heartbeat, daemon=True)
    hb_thread.start()

    def _run():
        try:
            for listing_url in listing_urls:
                def _progress(info: dict, _lu=listing_url):
                    event_queue.put(("progress", {**info, "listing_url": _lu}))

                paginated_results = crawl_paginated(
                    listing_url=listing_url,
                    progress_callback=_progress,
                )

                for pr in paginated_results:
                    entry = _build_result_entry(pr.crawl)
                    event_queue.put(("result", {
                        "listing_url":  pr.listing_url,
                        "listing_page": pr.listing_page,
                        "entry":        entry,
                    }))
        except Exception as exc:
            event_queue.put(("error", {"message": str(exc)}))
        finally:
            event_queue.put(_DONE)

    threading.Thread(target=_run, daemon=True).start()

    def _generate():
        total_results = 0
        while True:
            item = event_queue.get()
            if item is _DONE:
                yield f"event: done\ndata: {json.dumps({'total': total_results})}\n\n"
                break
            if item is _HEARTBEAT:
                # SSE comment — keeps the connection alive, ignored by the client
                yield ": keep-alive\n\n"
                continue
            event_name, payload = item
            if event_name == "result":
                total_results += 1
            yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


@app.post("/api/audit-site")
def audit_site():
    """
    Streams Server-Sent Events for a whole-site BFS crawl.

    Event types:
      heartbeat — ": keep-alive" comment
      progress  — {"phase":"crawling","index":N,"queued":Q,"url":"..."}
                  {"phase":"done","total":N}
      result    — {"site_root":"...","entry":{...}}
      error     — {"message":"..."}
      done      — {"total":N}
    """
    body = request.get_json(silent=True) or {}
    raw_url: str = (body.get("url") or "").strip()
    max_pages: int = int(body.get("max_pages") or 200)

    if not raw_url:
        return jsonify({"error": "No URL provided."}), 400
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url

    max_pages = max(1, min(max_pages, 2000))

    event_queue: queue.Queue = queue.Queue()
    _DONE      = object()
    _HEARTBEAT = object()

    def _heartbeat():
        while True:
            time.sleep(20)
            event_queue.put(_HEARTBEAT)

    threading.Thread(target=_heartbeat, daemon=True).start()

    def _run():
        try:
            def _progress(info: dict):
                event_queue.put(("progress", info))

            def _on_result(sr):
                entry = _build_result_entry(sr.crawl)
                event_queue.put(("result", {
                    "site_root": sr.site_root,
                    "entry":     entry,
                }))

            crawl_site(
                seed_url=raw_url,
                max_pages=max_pages,
                progress_callback=_progress,
                result_callback=_on_result,
            )
        except Exception as exc:
            event_queue.put(("error", {"message": str(exc)}))
        finally:
            event_queue.put(_DONE)

    threading.Thread(target=_run, daemon=True).start()

    def _generate():
        total_results = 0
        while True:
            item = event_queue.get()
            if item is _DONE:
                yield f"event: done\ndata: {json.dumps({'total': total_results})}\n\n"
                break
            if item is _HEARTBEAT:
                yield ": keep-alive\n\n"
                continue
            event_name, payload = item
            if event_name == "result":
                total_results += 1
            yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


if __name__ == "__main__":
    # threaded=True is required so the SSE generator and the crawl thread
    # can run concurrently under Flask's dev server.
    app.run(debug=True, port=5000, threaded=True)