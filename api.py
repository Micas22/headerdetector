"""
api.py — FastAPI server for the header detector.

Endpoints
---------
  POST /api/audit           → {"urls": [...]}       → single audit response
  POST /api/audit-paginated → {"listing_urls": [...]} → SSE stream of progress + results
  GET  /docs               → interactive API documentation
"""

import json
import queue
import threading
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from checker import check_headings, SEVERITY_WARNING
from crawler import crawl_many, crawl_paginated, crawl_site


app = FastAPI(title="Header Detector API", version="1.0.0")


class AuditRequest(BaseModel):
    urls: list[str]


class AuditPaginatedRequest(BaseModel):
    listing_urls: list[str]


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


def _normalize_urls(raw_urls: list[str]) -> list[str]:
    urls = []
    for u in raw_urls:
        u = u.strip()
        if not u:
            continue
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        urls.append(u)
    return urls


# ── routes ────────────────────────────────────────────────────────────────────

@app.post("/api/audit")
async def audit(request: AuditRequest):
    """Audit a list of URLs and return results."""
    urls = _normalize_urls(request.urls)

    if not urls:
        raise HTTPException(status_code=400, detail="No valid URLs provided.")

    try:
        payload = _build_payload(urls)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"results": payload}


@app.post("/api/audit-paginated")
async def audit_paginated(request: AuditPaginatedRequest):
    """Audit listing URLs with pagination, streaming results via SSE."""
    listing_urls = _normalize_urls(request.listing_urls)

    if not listing_urls:
        raise HTTPException(status_code=400, detail="No valid listing URLs provided.")

    def event_stream():
        try:
            for i, (listing_url, results) in enumerate(crawl_paginated(listing_urls)):
                payload = [_build_result_entry(cr) for cr in results]
                event_data = {
                    "progress": i + 1,
                    "total": len(listing_urls),
                    "listing_url": listing_url,
                    "results": payload,
                }
                yield f"data: {json.dumps(event_data)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
