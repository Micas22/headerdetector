"""
crawler.py — Fetches pages and extracts heading tags in document order.
"""

from dataclasses import dataclass, field
from typing import Optional
import requests
from bs4 import BeautifulSoup


HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; HeadingCrawler/1.0)"
    )
}


@dataclass
class Heading:
    level: int              # 1–6
    text: str               # visible text (empty string if image-only)
    tag: str                # e.g. "h2"
    is_image: bool = False  # True when the heading contains only <img> / SVG, no text
    image_alts: list[str] = field(default_factory=list)  # alt texts of those images


@dataclass
class CrawlResult:
    url: str
    headings: list[Heading]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _extract_heading(tag) -> Heading:
    """
    Build a Heading from a BeautifulSoup tag.

    A heading is considered "image-only" when:
      - its stripped visible text is empty, AND
      - it contains at least one <img> or inline <svg> element.

    We also collect alt text from every <img> inside the heading,
    since that's what screen readers and search engines use as the
    heading's effective text.
    """
    level = int(tag.name[1])
    text  = tag.get_text(separator=" ", strip=True)

    imgs     = tag.find_all("img")
    svgs     = tag.find_all("svg")
    has_media = bool(imgs or svgs)

    # A heading is "image-only" when there's no meaningful visible text
    # but there IS an image/SVG present.
    is_image = (not text) and has_media

    # Collect alt text (skip empty / missing alts — we'll flag those separately)
    image_alts = [img.get("alt", "").strip() for img in imgs]

    return Heading(
        level=level,
        text=text,
        tag=tag.name,
        is_image=is_image,
        image_alts=image_alts,
    )


def crawl(url: str, timeout: int = 10) -> CrawlResult:
    """
    Fetch *url* and return every heading element found, in DOM order.
    On network / HTTP errors the result's .error field is populated instead.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.MissingSchema:
        return CrawlResult(url=url, headings=[], error=f"Invalid URL (missing schema): {url!r}")
    except requests.exceptions.ConnectionError:
        return CrawlResult(url=url, headings=[], error=f"Could not connect to {url!r}")
    except requests.exceptions.Timeout:
        return CrawlResult(url=url, headings=[], error=f"Request timed out after {timeout}s")
    except requests.exceptions.HTTPError as exc:
        return CrawlResult(url=url, headings=[], error=f"HTTP {exc.response.status_code} for {url!r}")
    except Exception as exc:  # noqa: BLE001
        return CrawlResult(url=url, headings=[], error=str(exc))

    soup = BeautifulSoup(resp.text, "html.parser")
    headings = [_extract_heading(tag) for tag in soup.find_all(HEADING_TAGS)]
    return CrawlResult(url=url, headings=headings)


def crawl_many(urls: list[str], timeout: int = 10) -> list[CrawlResult]:
    """Crawl multiple URLs sequentially and return one result per URL."""
    return [crawl(url, timeout=timeout) for url in urls]