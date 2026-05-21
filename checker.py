"""
checker.py — Validates heading structure against two rules:

  1. Single H1  — the page must have exactly one <h1>.
                  An image-only <h1> counts as a valid <h1> but gets
                  an IMAGE_H1 advisory flag (not a failure).

  2. Hierarchy  — headings must not skip levels downward
                  (e.g. h1 → h3 is invalid; h1 → h2 → h3 is valid).
                  Going back up (h3 → h2) is perfectly fine.
"""

from dataclasses import dataclass, field
from crawler import Heading


# ── issue severity ────────────────────────────────────────────────────────────

SEVERITY_ERROR   = "error"    # rule failure
SEVERITY_WARNING = "warning"  # advisory — doesn't fail the overall check


@dataclass
class Issue:
    rule: str           # "single_h1" | "hierarchy" | "image_h1"
    severity: str       # SEVERITY_ERROR | SEVERITY_WARNING
    message: str
    heading: Heading | None = None


@dataclass
class CheckResult:
    h1_count: int  = 0
    h1_pass:  bool = False

    hierarchy_pass:   bool        = False
    hierarchy_issues: list[Issue] = field(default_factory=list)

    # advisory: image-only h1 flags (warnings, not errors)
    image_h1_flags: list[Issue] = field(default_factory=list)

    @property
    def overall_pass(self) -> bool:
        """True when all *error-level* rules pass (warnings are informational)."""
        return self.h1_pass and self.hierarchy_pass

    @property
    def all_issues(self) -> list[Issue]:
        issues: list[Issue] = []
        if not self.h1_pass:
            count_str = "none" if self.h1_count == 0 else str(self.h1_count)
            issues.append(Issue(
                rule="single_h1",
                severity=SEVERITY_ERROR,
                message=f"Expected exactly 1 <h1>, found {count_str}.",
            ))
        issues.extend(self.hierarchy_issues)
        issues.extend(self.image_h1_flags)   # warnings last
        return issues


# ── helpers ───────────────────────────────────────────────────────────────────

def _truncate(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


# ── rule implementations ──────────────────────────────────────────────────────

def _check_single_h1(headings: list[Heading]) -> tuple[int, bool]:
    """
    Count ALL h1 tags — text or image-only — and pass only when there's exactly 1.
    """
    count = sum(1 for h in headings if h.level == 1)
    return count, count == 1


def _check_hierarchy(headings: list[Heading]) -> tuple[bool, list[Issue]]:
    issues: list[Issue] = []
    prev_level: int | None = None

    for heading in headings:
        if prev_level is not None:
            jump = heading.level - prev_level
            if jump > 1:
                issues.append(Issue(
                    rule="hierarchy",
                    severity=SEVERITY_ERROR,
                    message=(
                        f"<h{heading.level}> follows <h{prev_level}> — "
                        f"skips {jump - 1} level(s). "
                        f'(text: "{_truncate(heading.text or "[image]")}")'
                    ),
                    heading=heading,
                ))
        prev_level = heading.level

    return len(issues) == 0, issues


def _check_image_h1s(headings: list[Heading]) -> list[Issue]:
    """
    Return a WARNING issue for every image-only <h1>, noting whether
    the image has alt text (accessible) or not (potentially problematic).
    """
    flags: list[Issue] = []
    for h in headings:
        if h.level == 1 and h.is_image:
            alts = [a for a in h.image_alts if a]  # non-empty alts
            if alts:
                alt_preview = _truncate(alts[0])
                detail = f'Image has alt text: "{alt_preview}" — readable by screen readers & search engines.'
            else:
                detail = "Image has no alt text — invisible to screen readers and search engines."

            flags.append(Issue(
                rule="image_h1",
                severity=SEVERITY_WARNING,
                message=f"<h1> is an image, not text. {detail}",
                heading=h,
            ))
    return flags


# ── public API ────────────────────────────────────────────────────────────────

def check_headings(headings: list[Heading]) -> CheckResult:
    result = CheckResult()
    result.h1_count, result.h1_pass = _check_single_h1(headings)
    result.hierarchy_pass, result.hierarchy_issues = _check_hierarchy(headings)
    result.image_h1_flags = _check_image_h1s(headings)
    return result