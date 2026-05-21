"""
crawler.py — Fetches pages and extracts heading tags in document order.

Modes
-----
  crawl(url)                        — single page
  crawl_many(urls)                  — list of individual pages
  crawl_paginated(listing_url, ...) — listing page → pagination → item cards → headings
"""

from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from bs4 import BeautifulSoup
import re


HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

NON_HTML_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".avif",
    ".zip", ".rar", ".gz", ".tar",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv",
    ".css", ".js", ".json", ".xml", ".rss",
}


# ── data classes ──────────────────────────────────────────────────────────────

@dataclass
class Heading:
    level: int
    text: str
    tag: str
    is_image: bool = False
    image_alts: list[str] = field(default_factory=list)


@dataclass
class CrawlResult:
    url: str
    headings: list[Heading]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class PaginatedCrawlResult:
    listing_url: str       # which listing URL this item came from
    listing_page: int      # which pagination page the card appeared on
    item_url: str          # the individual article/event URL
    crawl: CrawlResult     # heading audit result for the item page


# ── heading extraction ────────────────────────────────────────────────────────

def _extract_heading(tag) -> Heading:
    level      = int(tag.name[1])
    text       = tag.get_text(separator=" ", strip=True)
    imgs       = tag.find_all("img")
    svgs       = tag.find_all("svg")
    is_image   = bool(imgs or svgs)
    image_alts = [img.get("alt", "").strip() for img in imgs]
    return Heading(level=level, text=text, tag=tag.name,
                   is_image=is_image, image_alts=image_alts)


def _html_to_headings(html: str) -> list[Heading]:
    soup = BeautifulSoup(html, "html.parser")
    return [_extract_heading(tag) for tag in soup.find_all(HEADING_TAGS)]


# ── Playwright fetch (keeps a single browser open per call) ──────────────────

class _Browser:
    """Thin wrapper around a Playwright browser kept alive for a crawl session."""

    def __init__(self):
        from playwright.sync_api import sync_playwright
        self._pw      = sync_playwright().start()
        self._browser = self._pw.chromium.launch(args=["--no-sandbox"])
        self._ctx     = self._browser.new_context(
            user_agent="Mozilla/5.0 (compatible; HeadingAuditor/2.0)"
        )

    def fetch(self, url: str, timeout: int = 15) -> Optional[str]:
        from playwright.sync_api import TimeoutError as PWTimeout
        page = self._ctx.new_page()
        try:
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except PWTimeout:
                pass
            html = page.content()
            return html if html and len(html) > 200 else None
        except Exception:
            return None
        finally:
            page.close()

    def close(self):
        try: self._ctx.close()
        except Exception: pass
        try: self._browser.close()
        except Exception: pass
        try: self._pw.stop()
        except Exception: pass


def _fetch_html_simple(url: str, timeout: int = 15) -> Optional[str]:
    """Single-shot fetch — opens/closes browser each time. Used for one-off crawl()."""
    try:
        browser = _Browser()
        try:
            return browser.fetch(url, timeout=timeout)
        finally:
            browser.close()
    except ImportError:
        import requests as _req
        try:
            r = _req.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; HeadingAuditor/2.0)"},
                         timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception:
            return None


# ── pagination detection ──────────────────────────────────────────────────────

def _detect_total_pages(html: str) -> int:
    """
    Detect how many pagination pages a listing has.

    Tries multiple strategies and returns the highest number found:
      1. Any element whose stripped text is a plain integer (anchors, spans,
         list items, buttons — pagination widgets use all of these)
      2. rel="last" / rel="next" link href with page= or /page/ patterns
      3. aria-label="Page N" or aria-label="N" on pager elements
      4. Common data attributes: data-page, data-total-pages
      5. URL patterns in hrefs: ?page=N, /page/N, /p/N, ?pg=N, ?p=N
    Falls back to 1 if nothing found.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[int] = []

    # Strategy 1 — any element with purely numeric text (covers <a>, <span>,
    # <li>, <button> — pagination widgets use all of these)
    for el in soup.find_all(["a", "span", "li", "button"]):
        txt = el.get_text(strip=True)
        if re.fullmatch(r"\d{1,5}", txt):
            try:
                candidates.append(int(txt))
            except ValueError:
                pass

    # Strategy 2 — rel="last" or rel="next" href
    for rel_val in ("last", "next"):
        link = soup.find("a", rel=lambda r: r and rel_val in r)
        if link:
            href = link.get("href", "")
            m = re.search(r"[?&/](?:page|pg|p)[=/](\d+)", href, re.IGNORECASE)
            if m:
                candidates.append(int(m.group(1)))

    # Strategy 3 — aria-label patterns
    for el in soup.find_all(attrs={"aria-label": True}):
        m = re.search(r"\b(\d+)\b", el["aria-label"])
        if m:
            try:
                candidates.append(int(m.group(1)))
            except ValueError:
                pass

    # Strategy 4 — data-page / data-total-pages attributes
    for attr in ("data-total-pages", "data-page-count", "data-pages"):
        el = soup.find(attrs={attr: True})
        if el:
            try:
                candidates.append(int(el[attr]))
            except (ValueError, TypeError):
                pass

    # Strategy 5 — page numbers inside hrefs on the page
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"[?&/](?:page|pg|p)[=/](\d+)", href, re.IGNORECASE)
        if m:
            try:
                candidates.append(int(m.group(1)))
            except ValueError:
                pass

    # Filter out obviously-wrong values (years, IDs > 9999, 0)
    valid = [n for n in candidates if 1 < n <= 9999]
    return max(valid) if valid else 1


def _build_page_url(base_url: str, page_num: int) -> str:
    """Inject/replace the ?page= query parameter."""
    parsed = urlparse(base_url)
    qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    qs["page"] = str(page_num)
    return urlunparse(parsed._replace(query=urlencode(qs)))


# ── item-link extraction ──────────────────────────────────────────────────────

def _extract_item_links(listing_url: str, html: str) -> list[str]:
    """
    Extract links to individual item pages from a listing page.

    Strategy (mirrors the orchestrator's parsers.extract_listing_item_links):
      1. Collect links that are inside recognised card/item containers
         (article, [class*=card], [class*=item], [class*=news], [class*=event], etc.)
      2. A link qualifies when it:
           - is on the same domain as the listing URL
           - has a path that is a sub-path of the listing OR is different enough
             (we do NOT require it to be strictly under the listing path, because
             many sites have /news/ listing but cards link to /noticias/slug)
           - is NOT a pagination link (?page=N, /page/N, /p/N …)
           - is NOT a non-HTML asset
           - is NOT the listing page itself
      3. We deduplicate preserving first-seen order.
    """
    parsed_base = urlparse(listing_url)
    domain      = parsed_base.netloc
    base_path   = parsed_base.path.rstrip("/")

    soup = BeautifulSoup(html, "html.parser")

    PAGINATION_RE = re.compile(
        r"[?&/](?:page|pg|p)[=/]\d+", re.IGNORECASE
    )

    def _normalise(href: str) -> Optional[str]:
        href = href.strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return None
        # resolve relative
        if href.startswith("//"):
            href = parsed_base.scheme + ":" + href
        elif href.startswith("/"):
            href = f"{parsed_base.scheme}://{domain}{href}"
        elif not href.startswith("http"):
            # relative path — resolve against base
            base_dir = base_path.rsplit("/", 1)[0]
            href = f"{parsed_base.scheme}://{domain}{base_dir}/{href}"

        p = urlparse(href)
        # same domain only
        if p.netloc != domain:
            return None
        # not a pagination URL
        if PAGINATION_RE.search(href):
            return None
        # not the listing page itself (with or without query string)
        clean_path = p.path.rstrip("/")
        if clean_path == base_path and not p.query:
            return None
        # not a non-HTML asset
        suffix = "." + p.path.rsplit(".", 1)[-1].lower() if "." in p.path.rsplit("/", 1)[-1] else ""
        if suffix in NON_HTML_EXTENSIONS:
            return None
        # normalise: strip fragment, trailing slash
        return urlunparse(p._replace(fragment="")).rstrip("/") or href

    # --- collect from card containers first (higher confidence) ---
    CARD_SELECTORS = [
        "article",
        "[class*='card']",
        "[class*='item']",
        "[class*='news']",
        "[class*='event']",
        "[class*='post']",
        "[class*='article']",
        "[class*='entry']",
        "[class*='noticia']",
        "[class*='evento']",
        "li.news", "li.event", "li.article", "li.post",
    ]

    seen:    set[str]  = set()
    results: list[str] = []

    def _add(href: str):
        url = _normalise(href)
        if url and url not in seen:
            seen.add(url)
            results.append(url)

    for sel in CARD_SELECTORS:
        try:
            for container in soup.select(sel):
                for a in container.find_all("a", href=True):
                    _add(a["href"])
        except Exception:
            pass

    # --- if card containers found nothing, fall back to ALL links on the page
    # filtered to only those that look like content paths (have a slug-like segment)
    if not results:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            url  = _normalise(href)
            if not url:
                continue
            p = urlparse(url)
            # heuristic: path must be deeper than the listing base
            # (at least one extra path segment)
            path_parts = [x for x in p.path.split("/") if x]
            base_parts = [x for x in base_path.split("/") if x]
            if len(path_parts) > len(base_parts):
                _add(href)

    return results


# ── public API ────────────────────────────────────────────────────────────────

def crawl(url: str, timeout: int = 15) -> CrawlResult:
    html = _fetch_html_simple(url, timeout=timeout)
    if html is None:
        return CrawlResult(url=url, headings=[], error=f"Failed to fetch {url!r}")
    return CrawlResult(url=url, headings=_html_to_headings(html))


def crawl_many(urls: list[str], timeout: int = 15) -> list[CrawlResult]:
    return [crawl(url, timeout=timeout) for url in urls]


def crawl_paginated(
    listing_url:       str,
    max_pages:         int = 20,
    max_items:         int = 200,
    timeout:           int = 15,
    progress_callback  = None,   # callable(dict)
) -> list[PaginatedCrawlResult]:
    """
    Two-phase crawl mirroring the orchestrator pattern:

    Phase 1 — collect ALL item links
        a. Fetch listing page 1 → detect total_pages
        b. Fetch listing pages 2…N → harvest item links from each

    Phase 2 — audit each item page
        Fetch every collected item URL and run the heading check.

    progress_callback receives:
        {"phase": "listing", "page": N, "total_pages": T, "found_so_far": K}
        {"phase": "items",   "index": N, "total": T, "url": url}
    """
    results:    list[PaginatedCrawlResult] = []
    item_seen:  set[str]                   = set()
    item_links: list[tuple[str, int]]      = []   # (url, listing_page_number)

    # Keep one browser open for the whole crawl — much faster than
    # opening/closing per page.
    try:
        browser = _Browser()
    except ImportError:
        browser = None  # will fall back to requests inside _fetch

    def _fetch(url: str) -> Optional[str]:
        if browser is not None:
            return browser.fetch(url, timeout=timeout)
        return _fetch_html_simple(url, timeout=timeout)

    def _harvest(html: str, page_num: int):
        for link in _extract_item_links(listing_url, html):
            if link not in item_seen and len(item_links) < max_items:
                item_seen.add(link)
                item_links.append((link, page_num))

    try:
        # ── Phase 1a: first listing page ──────────────────────────────────
        first_html = _fetch(listing_url)
        if first_html is None:
            return results

        total_pages = _detect_total_pages(first_html)
        total_pages = min(total_pages, max(1, max_pages))

        if progress_callback:
            progress_callback({
                "phase": "listing", "page": 1,
                "total_pages": total_pages, "found_so_far": 0,
            })

        _harvest(first_html, 1)

        # ── Phase 1b: remaining listing pages ─────────────────────────────
        for page_num in range(2, total_pages + 1):
            page_url = _build_page_url(listing_url, page_num)
            if progress_callback:
                progress_callback({
                    "phase": "listing", "page": page_num,
                    "total_pages": total_pages,
                    "found_so_far": len(item_links),
                })
            html = _fetch(page_url)
            if html:
                _harvest(html, page_num)
            # keep going even if one page fails

        # ── Phase 2: audit each item page ─────────────────────────────────
        total_items = len(item_links)
        for idx, (item_url, lpage) in enumerate(item_links, start=1):
            if progress_callback:
                progress_callback({
                    "phase": "items", "index": idx,
                    "total": total_items, "url": item_url,
                })
            html = _fetch(item_url)
            if html is None:
                cr = CrawlResult(url=item_url, headings=[],
                                 error=f"Failed to fetch {item_url!r}")
            else:
                cr = CrawlResult(url=item_url, headings=_html_to_headings(html))

            results.append(PaginatedCrawlResult(
                listing_url=listing_url,
                listing_page=lpage,
                item_url=item_url,
                crawl=cr,
            ))

    finally:
        if browser is not None:
            browser.close()

    return results