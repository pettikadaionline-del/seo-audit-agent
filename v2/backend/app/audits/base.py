"""Shared types for audit modules.

Every finding is deterministic and evidence-backed: it names the check, the
affected URLs and the concrete observed values. The AI layer only explains and
prioritises findings; it never creates them.
"""

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field

from app.crawler.engine import SiteMeta
from app.crawler.parser import PageData


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class Category(str, Enum):
    technical = "technical"
    onpage = "onpage"
    content = "content"
    linking = "linking"
    performance = "performance"
    structured_data = "structured_data"
    ai_search = "ai_search"
    competitor = "competitor"


CATEGORY_LABELS = {
    Category.technical: "Technical SEO",
    Category.onpage: "On-Page SEO",
    Category.content: "Content Quality",
    Category.linking: "Internal & External Links",
    Category.performance: "Performance & Core Web Vitals",
    Category.structured_data: "Structured Data",
    Category.ai_search: "AI Search Readiness",
    Category.competitor: "Competitive Benchmark",
}


class Finding(BaseModel):
    id: str = ""  # assigned after collection
    check_id: str
    category: Category
    title: str
    severity: Severity
    description: str
    recommendation: str
    affected_urls: list[str] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)  # per-URL observed values, capped
    site_level: bool = False
    effort: int = 2  # 1 (minutes) .. 5 (multi-week project)
    confidence: str = "high"  # high | medium — medium when based on heuristics
    reference: str | None = None


@dataclass
class AuditContext:
    meta: SiteMeta
    pages: list[PageData]
    competitors: list[dict] = field(default_factory=list)  # site_profile() of each competitor
    self_profile: dict = field(default_factory=dict)  # site_profile() of the audited site
    performance: dict = field(default_factory=dict)

    @property
    def html_pages(self) -> list[PageData]:
        return [p for p in self.pages if p.status == 200 and "html" in p.content_type]

    @property
    def indexable_pages(self) -> list[PageData]:
        return [p for p in self.html_pages if p.indexable and not p.redirect_chain]

    @property
    def page_by_url(self) -> dict[str, PageData]:
        out = {}
        for p in self.pages:
            out[p.url] = p
            out.setdefault(p.final_url, p)
        return out


MAX_EVIDENCE = 25


def finding(
    check_id: str,
    category: Category,
    title: str,
    severity: Severity,
    description: str,
    recommendation: str,
    items: list[tuple[str, dict]] | None = None,
    **kwargs,
) -> Finding:
    """Build a finding from (url, evidence) pairs."""
    items = items or []
    return Finding(
        check_id=check_id,
        category=category,
        title=title,
        severity=severity,
        description=description,
        recommendation=recommendation,
        affected_urls=list(dict.fromkeys(u for u, _ in items)),
        evidence=[{"url": u, **e} for u, e in items[:MAX_EVIDENCE]],
        **kwargs,
    )
