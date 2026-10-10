"""Domain models shared by the crawler, audit agents, scoring, AI and reports."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


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
    links = "links"
    performance = "performance"
    structured_data = "structured_data"
    ai_readiness = "ai_readiness"
    competitor = "competitor"


class Effort(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class AuditStatus(str, Enum):
    queued = "queued"
    crawling = "crawling"
    analyzing = "analyzing"
    ai = "ai"
    completed = "completed"
    failed = "failed"


# ---------------------------------------------------------------- crawl data
class LinkRef(BaseModel):
    url: str
    anchor: str = ""
    nofollow: bool = False
    internal: bool = True


class ImageRef(BaseModel):
    src: str
    alt: str | None = None
    loading: str | None = None
    width: str | None = None
    height: str | None = None


class PageData(BaseModel):
    url: str
    final_url: str
    status_code: int
    depth: int = 0
    redirect_chain: list[str] = Field(default_factory=list)
    content_type: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    response_time_ms: float = 0
    html_bytes: int = 0
    error: str | None = None
    blocked_by_robots: bool = False

    # Parsed (HTML only)
    title: str | None = None
    meta_description: str | None = None
    meta_robots: str | None = None
    canonical: str | None = None
    lang: str | None = None
    viewport: str | None = None
    charset: str | None = None
    h1: list[str] = Field(default_factory=list)
    headings: list[tuple[int, str]] = Field(default_factory=list)
    word_count: int = 0
    text_sample: str = ""
    content_hash: str | None = None
    links: list[LinkRef] = Field(default_factory=list)
    images: list[ImageRef] = Field(default_factory=list)
    hreflang: list[dict[str, str]] = Field(default_factory=list)
    og: dict[str, str] = Field(default_factory=dict)
    twitter: dict[str, str] = Field(default_factory=dict)
    json_ld: list[Any] = Field(default_factory=list)
    json_ld_errors: list[str] = Field(default_factory=list)
    microdata_types: list[str] = Field(default_factory=list)
    scripts_blocking: int = 0
    scripts_total: int = 0
    stylesheets: int = 0
    inline_style_bytes: int = 0
    inline_script_bytes: int = 0
    has_faq_pattern: bool = False
    question_headings: int = 0
    lists_count: int = 0
    tables_count: int = 0
    has_author: bool = False
    has_date: bool = False
    mixed_content: list[str] = Field(default_factory=list)


class SiteContext(BaseModel):
    """Site-level facts gathered once per audit."""
    start_url: str
    origin: str
    https: bool
    robots_txt_found: bool = False
    robots_txt: str | None = None
    robots_disallow_all: bool = False
    sitemaps_declared: list[str] = Field(default_factory=list)
    sitemap_urls: list[str] = Field(default_factory=list)
    sitemap_errors: list[str] = Field(default_factory=list)
    http_redirects_to_https: bool | None = None
    www_consistent: bool | None = None
    llms_txt_found: bool = False
    pagespeed: dict[str, Any] | None = None
    crawl_truncated: bool = False


# ------------------------------------------------------------------- results
class Issue(BaseModel):
    id: str  # stable rule id, e.g. "onpage.title.missing"
    category: Category
    severity: Severity
    title: str
    description: str
    recommendation: str
    affected_urls: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    impact: int = Field(5, ge=1, le=10)  # expected ranking / traffic impact
    effort: Effort = Effort.medium
    priority_score: float = 0.0  # computed: impact x severity / effort

    @property
    def affected_count(self) -> int:
        return len(self.affected_urls)


class CategoryScore(BaseModel):
    category: Category
    score: int
    issues: int
    weight: float


class AIInsights(BaseModel):
    executive_summary: str = ""
    top_priorities: list[str] = Field(default_factory=list)
    quick_wins: list[str] = Field(default_factory=list)
    content_opportunities: list[str] = Field(default_factory=list)
    ai_search_recommendations: list[str] = Field(default_factory=list)
    roadmap_30_60_90: dict[str, list[str]] = Field(default_factory=dict)
    generated_by: str = "heuristic"  # "heuristic" or model id


class AuditRequest(BaseModel):
    url: HttpUrl
    max_pages: int | None = Field(None, ge=1)
    max_depth: int | None = Field(None, ge=0)
    competitors: list[HttpUrl] = Field(default_factory=list, max_length=3)
    respect_robots: bool = True
    use_ai: bool = True


class PageSummary(BaseModel):
    url: str
    status_code: int
    title: str | None
    word_count: int
    response_time_ms: float
    issues: int
    depth: int


class AuditResult(BaseModel):
    id: str
    url: str
    status: AuditStatus
    progress: int = 0
    message: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    overall_score: int | None = None
    grade: str | None = None
    category_scores: list[CategoryScore] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    pages: list[PageSummary] = Field(default_factory=list)
    site: SiteContext | None = None
    competitors: list[dict[str, Any]] = Field(default_factory=list)
    ai: AIInsights | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
