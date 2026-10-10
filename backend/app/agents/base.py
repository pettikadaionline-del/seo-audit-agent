"""Base class for specialised audit agents.

Each agent is deterministic and rule-based: it inspects crawl data and emits
`Issue`s with evidence. The AI layer *interprets* these findings; it never
invents them. That keeps the audit reproducible and the AI hallucination-proof
on facts.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.models import Category, Effort, Issue, PageData, Severity, SiteContext

MAX_URLS_PER_ISSUE = 200


class AuditAgent(ABC):
    category: Category
    name: str = ""

    @abstractmethod
    def run(self, pages: list[PageData], site: SiteContext) -> list[Issue]: ...

    def issue(
        self,
        rule: str,
        severity: Severity,
        title: str,
        description: str,
        recommendation: str,
        urls: list[str] | None = None,
        impact: int = 5,
        effort: Effort = Effort.medium,
        **evidence: Any,
    ) -> Issue:
        urls = list(dict.fromkeys(urls or []))
        if len(urls) > MAX_URLS_PER_ISSUE:
            evidence["total_affected"] = len(urls)
            urls = urls[:MAX_URLS_PER_ISSUE]
        return Issue(
            id=f"{self.category.value}.{rule}",
            category=self.category,
            severity=severity,
            title=title,
            description=description,
            recommendation=recommendation,
            affected_urls=urls,
            impact=impact,
            effort=effort,
            evidence=evidence,
        )


def html_pages(pages: list[PageData]) -> list[PageData]:
    """Successfully fetched, indexable-candidate HTML pages."""
    return [p for p in pages if not p.error and 200 <= p.status_code < 300 and "html" in p.content_type]


def is_noindex(p: PageData) -> bool:
    x_robots = p.headers.get("x-robots-tag", "").lower()
    return "noindex" in (p.meta_robots or "") or "noindex" in x_robots
