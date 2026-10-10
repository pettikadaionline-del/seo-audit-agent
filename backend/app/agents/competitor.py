"""Agent H: competitor gap analysis.

Competitor sites are crawled shallowly by the orchestrator; this agent compares
measurable profiles (not rankings - that needs a paid SERP/keyword API).
"""
from __future__ import annotations

import statistics
from typing import Any

from app.agents.base import AuditAgent, html_pages, is_noindex
from app.agents.structured_data import iter_entities, types_of
from app.models import Category, Effort, Issue, PageData, Severity, SiteContext


def profile_site(pages: list[PageData], site: SiteContext) -> dict[str, Any]:
    ok = [p for p in html_pages(pages) if not is_noindex(p)]
    schema = sorted({t for p in ok for e in iter_entities(p.json_ld) for t in types_of(e)})
    return {
        "url": site.start_url,
        "pages_crawled": len(pages),
        "indexable_pages": len(ok),
        "avg_word_count": round(statistics.mean([p.word_count for p in ok])) if ok else 0,
        "median_response_ms": round(statistics.median([p.response_time_ms for p in ok])) if ok else None,
        "schema_types": schema,
        "has_blog": any(s in p.url for p in ok for s in ("/blog", "/article", "/guide", "/news", "/recipe")),
        "faq_pages": sum(1 for p in ok if p.has_faq_pattern),
        "pages_with_og": sum(1 for p in ok if p.og.get("og:image")),
        "sitemap_urls": len(site.sitemap_urls),
        "https": site.https,
        "llms_txt": site.llms_txt_found,
        "title_sample": [p.title for p in ok[:5] if p.title],
    }


class CompetitorAgent(AuditAgent):
    category = Category.competitor
    name = "Competitor Gaps"

    def __init__(self, competitor_profiles: list[dict[str, Any]] | None = None):
        self.competitors = competitor_profiles or []

    def run(self, pages: list[PageData], site: SiteContext) -> list[Issue]:
        if not self.competitors:
            return []
        out: list[Issue] = []
        me = profile_site(pages, site)
        comps = [c for c in self.competitors if c.get("indexable_pages")]
        if not comps:
            return out

        avg_comp_words = statistics.mean(c["avg_word_count"] for c in comps)
        if me["avg_word_count"] < 0.7 * avg_comp_words:
            out.append(self.issue("content_depth", Severity.medium, "Less content depth than competitors",
                f"Your average page has {me['avg_word_count']} words vs ~{round(avg_comp_words)} for competitors.",
                "Expand key category and product pages with useful detail; build out guides where competitors rank.",
                [site.start_url], impact=6, effort=Effort.high, you=me["avg_word_count"], competitors=round(avg_comp_words)))

        comp_schema = {t for c in comps for t in c["schema_types"]}
        gap = sorted(comp_schema - set(me["schema_types"]))
        if gap:
            out.append(self.issue("schema_gap", Severity.medium, "Structured data competitors use that you don't",
                f"Competitors mark up: {', '.join(gap[:10])}.", "Implement the relevant types to compete for the same rich results.",
                [site.start_url], impact=5, effort=Effort.low, missing_types=gap))

        if not me["has_blog"] and any(c["has_blog"] for c in comps):
            names = [c["url"] for c in comps if c["has_blog"]]
            out.append(self.issue("content_hub_gap", Severity.medium, "Competitors run a blog/content hub - you don't",
                f"{len(names)} competitor(s) publish editorial content capturing informational searches and AI citations.",
                "Start a focused content hub (2-4 quality posts/month) around your product category.",
                [site.start_url], impact=6, effort=Effort.high, competitors_with_blog=names))

        comp_speed = [c["median_response_ms"] for c in comps if c.get("median_response_ms")]
        if me["median_response_ms"] and comp_speed and me["median_response_ms"] > 1.5 * statistics.median(comp_speed):
            out.append(self.issue("speed_gap", Severity.medium, "Slower server response than competitors",
                f"Your median response is {me['median_response_ms']} ms vs {round(statistics.median(comp_speed))} ms for competitors.",
                "Add CDN/caching; review hosting tier.", [site.start_url], impact=4, effort=Effort.medium))
        if me["faq_pages"] == 0 and any(c["faq_pages"] for c in comps):
            out.append(self.issue("faq_gap", Severity.low, "Competitors use FAQ content - you don't",
                "FAQ sections capture long-tail questions and are frequently quoted by AI answers.",
                "Add FAQ blocks to product/category pages answering real customer questions (shipping, shelf life, ingredients).",
                [site.start_url], impact=4, effort=Effort.low))
        return out
