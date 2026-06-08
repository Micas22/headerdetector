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
    if tag.name in HEADING_TAGS:
        level = int(tag.name[1])
        tag_name = tag.name
    else:
        level_str = tag.get("aria-level", "2")
        try:
            level = int(level_str)
        except ValueError:
            level = 2
        tag_name = tag.name

    text       = tag.get_text(separator=" ", strip=True)
    imgs       = tag.find_all("img")
    svgs       = tag.find_all("svg")
    is_image   = bool(imgs or svgs)
    image_alts = [img.get("alt", "").strip() for img in imgs]
    return Heading(level=level, text=text, tag=tag_name,
                   is_image=is_image, image_alts=image_alts)


def _html_to_headings(html: str) -> list[Heading]:
    soup = BeautifulSoup(html, "html.parser")
    
    def is_heading(tag):
        if tag.name in HEADING_TAGS:
            return True
        if tag.get("role") == "heading":
            return True
        return False

    return [_extract_heading(tag) for tag in soup.find_all(is_heading)]


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
            try:
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            except PWTimeout:
                pass
            
            try:
                # wait for h1 to appear, giving SPAs time to render
                page.wait_for_selector("h1, [role='heading'][aria-level='1']", timeout=2000, state="attached")
            except Exception:
                pass

            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except PWTimeout:
                pass
                
            page.wait_for_timeout(500)
            
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
    except Exception:
        import requests as _req
        try:
            r = _req.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; HeadingAuditor/2.0)"},
                         timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception:
            return None


# ── pagination detection ──────────────────────────────────────────────────────

def _detect_total_pages(html: str) -> Optional[int]:
    """
    Detect how many pagination pages a listing has.
    Returns None if no pagination is detected (caller should treat as 1 page).

    Passes are ordered from most-specific to most-generic to avoid false
    positives from unrelated numbers on the page.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Pass 1 — ".pagination--select__label" with "de N" text
    for label in soup.select(".pagination--select__label"):
        text = label.get_text(" ", strip=True)
        m = re.search(r"de\s+(\d+)", text, re.IGNORECASE)
        if m:
            return int(m.group(1))

    # Pass 2 — any pagination__item <a> that is just a digit
    page_numbers = [
        int(a.get_text(strip=True))
        for a in soup.select("li.pagination__item a")
        if a.get_text(strip=True).isdigit()
    ]
    if page_numbers:
        return max(page_numbers)

    # Pass 3 — rel="last" link  <a rel="last" href="?page=N">
    last_link = soup.find("a", rel=lambda v: v and "last" in v)
    if last_link:
        href = last_link.get("href", "")
        m = re.search(r"[?&]page=(\d+)", href, re.IGNORECASE)
        if m:
            return int(m.group(1))

    # Pass 4 — aria-label="Page N" / aria-label="Go to page N"
    aria_pages = []
    for tag in soup.find_all(attrs={"aria-label": True}):
        m = re.search(r"\bpage\s+(\d+)\b", tag["aria-label"], re.IGNORECASE)
        if m:
            aria_pages.append(int(m.group(1)))
    if aria_pages:
        return max(aria_pages)

    # Pass 5 — digits inside common pagination containers
    for sel in [
        "nav[aria-label*='agina' i]",
        "nav[aria-label*='pagin' i]",
        ".pagination", ".pager", ".paginator",
        "[class*='pagination']", "[class*='pager']",
        "ul.pages", "ol.pages",
    ]:
        container = soup.select_one(sel)
        if not container:
            continue
        nums = [
            int(t)
            for tag in container.find_all(["a", "span", "button", "li"])
            for t in [tag.get_text(strip=True)]
            if t.isdigit() and int(t) > 0
        ]
        if nums:
            return max(nums)

    # Pass 6 — "?page=N" / "/page/N" in any href on the page
    all_page_nums = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"[?&]page=(\d+)", href, re.IGNORECASE)
        if m:
            all_page_nums.append(int(m.group(1)))
            continue
        m = re.search(r"/p(?:age)?/(\d+)", href, re.IGNORECASE)
        if m:
            all_page_nums.append(int(m.group(1)))
    if all_page_nums:
        return max(all_page_nums)

    # Pass 7 — plain text patterns like "Page 1 of 38" / "1 de 38"
    full_text = soup.get_text(" ", strip=True)
    for pattern in [
        r"\bof\s+(\d+)\b",
        r"\bde\s+(\d+)\b",
        r"\bvan\s+(\d+)\b",
        r"\bvon\s+(\d+)\b",
        r"\bdi\s+(\d+)\b",
        r"/\s*(\d+)\s*pages?",
    ]:
        matches = re.findall(pattern, full_text, re.IGNORECASE)
        if matches:
            total = max(int(v) for v in matches)
            if total > 1:
                return total

    return None


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

    from urllib.parse import urljoin

    def _strip_www(netloc: str) -> str:
        return netloc[4:] if netloc.startswith("www.") else netloc

    def _normalise(href: str) -> Optional[str]:
        href = href.strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return None
        
        # resolve relative
        href = urljoin(listing_url, href)

        p = urlparse(href)
        # same domain only (allowing www. variations)
        if _strip_www(p.netloc) != _strip_www(domain):
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
        p = p._replace(netloc=_strip_www(p.netloc), fragment="")
        return urlunparse(p).rstrip("/") or href

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
            # heuristic: path must be deeper or at the same level as the listing base
            path_parts = [x for x in p.path.split("/") if x]
            base_parts = [x for x in base_path.split("/") if x]
            if len(path_parts) >= len(base_parts):
                _add(href)

    return results


# ── public API ────────────────────────────────────────────────────────────────

def crawl(url: str, timeout: int = 15) -> CrawlResult:
    html = _fetch_html_simple(url, timeout=timeout)
    if html is None:
        return CrawlResult(url=url, headings=[], error=f"Failed to fetch {url!r}")
    return CrawlResult(url=url, headings=_html_to_headings(html))


@dataclass
class SiteCrawlResult:
    """One audited page from a whole-site crawl."""
    site_root: str       # the seed URL that started the crawl
    crawl: CrawlResult   # heading audit result


def _extract_same_domain_links(page_url: str, html: str) -> list[str]:
    """
    Return all unique, same-domain, HTML links found on *html*.
    Strips fragments; normalises trailing slashes.
    """
    from urllib.parse import urljoin
    from pathlib import Path

    parsed_base = urlparse(page_url)
    domain = parsed_base.netloc
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    results: list[str] = []

    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        full = urljoin(page_url, href)
        p = urlparse(full)

        if p.scheme not in ("http", "https"):
            continue

        def _strip_www(netloc: str) -> str:
            return netloc[4:] if netloc.startswith("www.") else netloc

        if _strip_www(p.netloc) != _strip_www(domain):
            continue

        # skip non-HTML assets by extension
        ext = Path(p.path).suffix.lower()
        if ext and ext in NON_HTML_EXTENSIONS:
            continue

        # normalise: strip fragment, strip trailing slash (unless root)
        path = p.path or "/"
        if path != "/":
            path = path.rstrip("/")
        normalised = f"{p.scheme}://{_strip_www(p.netloc)}{path}"
        if p.query:
            normalised += f"?{p.query}"

        if normalised not in seen:
            seen.add(normalised)
            results.append(normalised)
    return results


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en,pt;q=0.9",
}

# Statuses that are worth retrying (rate-limit, server hiccup, gateway errors)
_RETRY_STATUSES = {429, 500, 502, 503, 504}


def _make_session() -> "requests.Session":
    import requests as _req
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = _req.Session()
    retry = Retry(
        total=5,
        backoff_factor=2.0,           # waits 2s, 4s, 8s, 16s, 32s between retries
        status_forcelist=_RETRY_STATUSES,
        allowed_methods={"GET"},
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(_HEADERS)
    return session


def _fetch_with_session(
    session,
    url: str,
    timeout: int = 20,
) -> Optional[str]:
    """Fetch a single URL using an existing requests.Session."""
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            return None
        ct = r.headers.get("Content-Type", "")
        if ct and "text/html" not in ct:
            return None
        return r.text
    except Exception:
        return None


def crawl_site(
    seed_url:          str,
    max_pages:         int  = 500,
    timeout:           int  = 20,
    progress_callback        = None,
    result_callback          = None,
    request_delay:     float = 0.5,  # seconds between requests
) -> list[SiteCrawlResult]:
    """
    BFS whole-site crawl — follows all same-domain HTML links starting from
    *seed_url*, up to *max_pages* pages.

    Keeps one requests.Session open for connection pooling and reuse.
    Uses request_delay to throttle requests and avoid overwhelming the server.
    """
    import time
    
    parsed_seed = urlparse(seed_url)
    seed_netloc = parsed_seed.netloc[4:] if parsed_seed.netloc.startswith("www.") else parsed_seed.netloc
    seed_normalised = urlunparse(parsed_seed._replace(netloc=seed_netloc, fragment="")).rstrip("/") or seed_url

    visited: set[str]              = set()
    queue_:  list[str]             = [seed_normalised]
    results: list[SiteCrawlResult] = []

    _site_session = _make_session()
    last_request_time = 0

    try:
        browser = _Browser()
    except Exception:
        browser = None

    def _fetch(url: str) -> Optional[str]:
        nonlocal last_request_time
        
        # Throttle requests to avoid overwhelming the server
        elapsed = time.time() - last_request_time
        if elapsed < request_delay:
            time.sleep(request_delay - elapsed)
        last_request_time = time.time()
        
        if browser is not None:
            try:
                html = browser.fetch(url, timeout=timeout)
                if html is not None:
                    return html
            except Exception:
                pass
            # browser fetch failed for this URL — fall back to requests
        return _fetch_with_session(_site_session, url, timeout=timeout)

    try:
        idx = 0
        while queue_ and len(results) < max_pages:
            url = queue_.pop(0)
            if url in visited:
                continue
            visited.add(url)
            idx += 1

            if progress_callback:
                progress_callback({
                    "phase":  "crawling",
                    "index":  idx,
                    "queued": len(queue_),
                    "url":    url,
                })

            html = _fetch(url)
            if html is None:
                cr = CrawlResult(url=url, headings=[],
                                 error=f"Failed to fetch {url!r}")
            else:
                cr = CrawlResult(url=url, headings=_html_to_headings(html))
                for link in _extract_same_domain_links(url, html):
                    if link not in visited and link not in queue_:
                        queue_.append(link)

            sr = SiteCrawlResult(site_root=seed_url, crawl=cr)
            results.append(sr)
            if result_callback:
                result_callback(sr)

    finally:
        if browser is not None:
            browser.close()
        _site_session.close()

    if progress_callback:
        progress_callback({"phase": "done", "total": len(results)})

    return results


def crawl_many(urls: list[str], timeout: int = 15) -> list[CrawlResult]:
    return [crawl(url, timeout=timeout) for url in urls]


def crawl_paginated(
    listing_url:       str,
    max_pages:         int = 500,
    max_items:         int = 200,
    timeout:           int = 15,
    progress_callback  = None,   # callable(dict)
    request_delay:     float = 0.3,  # seconds between requests
) -> list[PaginatedCrawlResult]:
    """
    Two-phase crawl mirroring the orchestrator pattern:

    Phase 1 — collect ALL item links
        a. Fetch listing page 1 → detect total_pages
        b. Fetch listing pages 2…N → harvest item links from each

    Phase 2 — audit each item page
        Fetch every collected item URL and run the heading check.

    Includes request throttling to avoid overwhelming the server.

    progress_callback receives:
        {"phase": "listing", "page": N, "total_pages": T, "found_so_far": K}
        {"phase": "items",   "index": N, "total": T, "url": url}
    """
    import time
    
    parsed_listing = urlparse(listing_url)
    listing_netloc = parsed_listing.netloc[4:] if parsed_listing.netloc.startswith("www.") else parsed_listing.netloc
    listing_url = urlunparse(parsed_listing._replace(netloc=listing_netloc, fragment="")).rstrip("/") or listing_url

    results:    list[PaginatedCrawlResult] = []
    item_seen:  set[str]                   = set()
    item_links: list[tuple[str, int]]      = []   # (url, listing_page_number)
    last_request_time = 0

    # Keep one browser open for the whole crawl — much faster than
    # opening/closing per page.
    try:
        browser = _Browser()
    except ImportError:
        browser = None  # will fall back to requests inside _fetch

    _site_session = _make_session()

    def _fetch(url: str) -> Optional[str]:
        nonlocal last_request_time
        
        # Throttle requests to avoid overwhelming the server
        elapsed = time.time() - last_request_time
        if elapsed < request_delay:
            time.sleep(request_delay - elapsed)
        last_request_time = time.time()
        
        if browser is not None:
            try:
                return browser.fetch(url, timeout=timeout)
            except Exception:
                pass
        return _fetch_with_session(_site_session, url, timeout=timeout)

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

        total_pages = _detect_total_pages(first_html) or 1

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
        _site_session.close()

    return results