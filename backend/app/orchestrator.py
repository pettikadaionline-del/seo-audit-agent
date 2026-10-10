"""Audit pipeline: crawl -> specialised agents -> scoring -> AI insights -> persist."""
from __future__ import annotations

import asyncio
import logging
import statistics
from collections import Counter
from datetime import datetime, timezone

from app.agents import CompetitorAgent, default_agents, profile_site
from app.ai.advisor import generate_insights
from app.config import Settings
from app.crawler.crawler import Crawler
from app.crawler.fetcher import Fetcher
from app.integrations.pagespeed import fetch_pagespeed
from app.models import AuditRequest, AuditResult, AuditStatus, Category, PageData, PageSummary
from app.scoring import grade, prioritise, score
from app.store import AuditStore

log = logging.getLogger(__name__)
COMPETITOR_MAX_PAGES = 15


class AuditRunner:
    def __init__(self, settings: Settings, store: AuditStore, fetcher_factory=None):
        self.settings = settings
        self.store = store
        self.fetcher_factory = fetcher_factory or (lambda: Fetcher(settings))

    async def run(self, result: AuditResult, req: AuditRequest) -> AuditResult:
        s = self.settings
        max_pages = min(req.max_pages or s.default_max_pages, s.max_pages_limit)
        max_depth = min(req.max_depth if req.max_depth is not None else 3, s.max_depth_limit)

        async def progress(n: int, url: str) -> None:
            result.progress = min(70, 5 + int(65 * n / max_pages))
            result.message = f"Crawled {n} page(s): {url}"
            if n % 5 == 0 or n == 1:
                self.store.save(result)

        try:
            result.status = AuditStatus.crawling
            result.message = "Checking robots.txt and sitemaps"
            self.store.save(result)

            fetcher = self.fetcher_factory()
            try:
                crawler = Crawler(s, str(req.url), max_pages, max_depth, req.respect_robots, fetcher=fetcher, progress=progress)
                psi_task = (
                    asyncio.create_task(fetch_pagespeed(str(req.url), s.pagespeed_api_key)) if s.pagespeed_api_key else None
                )
                pages, site = await crawler.run()
                if psi_task:
                    site.pagespeed = await psi_task

                competitor_profiles = []
                for comp_url in req.competitors[:3]:
                    result.message = f"Crawling competitor {comp_url}"
                    self.store.save(result)
                    try:
                        cp, cs = await Crawler(s, str(comp_url), COMPETITOR_MAX_PAGES, 2, True, fetcher=fetcher).run()
                        competitor_profiles.append(profile_site(cp, cs))
                    except Exception as exc:
                        log.warning("competitor crawl failed for %s: %s", comp_url, exc)
                        competitor_profiles.append({"url": str(comp_url), "error": str(exc)})
            finally:
                await fetcher.aclose()

            if not pages or all(p.error for p in pages):
                first_error = pages[0].error if pages else "No pages fetched"
                raise RuntimeError(f"Could not crawl the site: {first_error}")

            result.status = AuditStatus.analyzing
            result.progress = 75
            result.message = "Running audit agents"
            self.store.save(result)

            agents = default_agents()
            categories = [a.category for a in agents]
            if competitor_profiles:
                agents.append(CompetitorAgent(competitor_profiles))
                categories.append(Category.competitor)
            issues = []
            agent_stats = {}
            for agent in agents:
                try:
                    issues.extend(agent.run(pages, site))
                    if getattr(agent, "stats", None):
                        agent_stats[agent.category.value] = agent.stats
                except Exception:
                    log.exception("agent %s failed", agent.name)

            indexable = sum(1 for p in pages if 200 <= p.status_code < 300 and "html" in p.content_type) or len(pages)
            result.issues = prioritise(issues, indexable)
            result.overall_score, result.category_scores = score(result.issues, indexable, categories)
            result.grade = grade(result.overall_score)
            result.site = site
            result.competitors = competitor_profiles
            result.pages = _page_summaries(pages, result)
            result.stats = _stats(pages, site, result) | {"agents": agent_stats}

            if req.use_ai:
                result.status = AuditStatus.ai
                result.progress = 85
                result.message = "Generating AI recommendations"
                self.store.save(result)
            result.ai = await generate_insights(result, s) if req.use_ai else None

            result.status = AuditStatus.completed
            result.progress = 100
            result.message = "Audit complete"
        except Exception as exc:
            log.exception("audit %s failed", result.id)
            result.status = AuditStatus.failed
            result.error = str(exc)
            result.message = "Audit failed"
        result.completed_at = datetime.now(timezone.utc)
        self.store.save(result)
        return result


def _page_summaries(pages: list[PageData], result: AuditResult) -> list[PageSummary]:
    counts = Counter(u for i in result.issues for u in i.affected_urls)
    return [
        PageSummary(
            url=p.url, status_code=p.status_code, title=p.title, word_count=p.word_count,
            response_time_ms=p.response_time_ms, issues=counts.get(p.url, 0), depth=p.depth,
        )
        for p in pages
    ]


def _stats(pages: list[PageData], site, result: AuditResult) -> dict:
    ok = [p for p in pages if 200 <= p.status_code < 300]
    return {
        "pages_crawled": len(pages),
        "pages_ok": len(ok),
        "pages_error": sum(1 for p in pages if p.status_code >= 400 or (p.error and not p.blocked_by_robots)),
        "pages_redirected": sum(1 for p in pages if p.redirect_chain),
        "median_response_ms": round(statistics.median([p.response_time_ms for p in ok])) if ok else None,
        "avg_word_count": round(statistics.mean([p.word_count for p in ok])) if ok else 0,
        "sitemap_urls": len(site.sitemap_urls),
        "crawl_truncated": site.crawl_truncated,
        "issues_by_severity": dict(Counter(i.severity.value for i in result.issues)),
    }
