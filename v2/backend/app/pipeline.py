"""Audit orchestration: crawl → measure → audit → score → prioritise → AI → persist."""

import asyncio
import logging
from datetime import UTC, datetime

from app.ai.recommender import generate_ai_report
from app.audits import ai_search, competitor, content, linking, onpage, performance, structured_data, technical
from app.audits.base import AuditContext, Finding
from app.audits.scoring import BUCKET_LABELS, category_scores, grade, overall_score, prioritise
from app.core.config import Settings, get_settings
from app.core.security import normalize_input_url
from app.crawler.engine import crawl_site
from app.crawler.pagespeed import run_pagespeed
from app.db import Action, Audit, Page, SessionLocal

log = logging.getLogger(__name__)

MODULES = [technical, onpage, content, linking, performance, structured_data, ai_search, competitor]
_audit_slots: asyncio.Semaphore | None = None
_running: set[asyncio.Task] = set()


def run_modules(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    for module in MODULES:
        try:
            findings.extend(module.run(ctx))
        except Exception:  # one broken module must not sink the audit
            log.exception("Audit module %s failed", module.__name__)
    for i, f in enumerate(findings, 1):
        f.id = f"F{i:03d}"
    return findings


def build_result(ctx: AuditContext, findings: list[Finding]) -> dict:
    total = len(ctx.indexable_pages) or len(ctx.html_pages) or 1
    cats = category_scores(findings, total, include_competitor=bool([c for c in ctx.competitors if not c.get("error")]))
    score = overall_score(cats)
    items = []
    for f in findings:
        d = f.model_dump(mode="json")
        d["priority"] = prioritise(f, total)
        items.append(d)
    items.sort(key=lambda d: (-d["priority"]["priority_score"], d["id"]))
    meta = ctx.meta
    summary = {
        "url": meta.start_url,
        "overall_score": score,
        "grade": grade(score),
        "pages_crawled": len(ctx.pages),
        "pages_audited": total,
        "html_pages": len(ctx.html_pages),
        "https": meta.https,
        "robots_txt": bool(meta.robots and meta.robots.exists),
        "sitemaps": meta.sitemap.found if meta.sitemap else [],
        "sitemap_urls": len(meta.sitemap.urls) if meta.sitemap else 0,
        "llms_txt": meta.llms_txt,
        "ai_crawler_access": meta.robots.ai_access(meta.start_url) if meta.robots and meta.robots.exists else None,
        "blocked_by_robots": len(meta.blocked_by_robots),
        "skipped_over_limit": meta.skipped_over_limit,
        "sample_titles": [p.title for p in ctx.indexable_pages[:25] if p.title],
    }
    return {
        "summary": summary,
        "categories": cats,
        "findings": items,
        "buckets": {k: {"label": v, "count": sum(1 for i in items if i["priority"]["bucket"] == k)} for k, v in BUCKET_LABELS.items()},
        "performance": ctx.performance,
        "competitors": {"self": ctx.self_profile, "others": ctx.competitors} if ctx.competitors else None,
    }


async def _update(audit_id: str, **fields) -> None:
    async with SessionLocal() as s:
        audit = await s.get(Audit, audit_id)
        if audit:
            for k, v in fields.items():
                setattr(audit, k, v)
            await s.commit()


async def execute_audit(audit_id: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    async with SessionLocal() as s:
        audit = await s.get(Audit, audit_id)
        url, opts = audit.url, audit.options or {}

    last = {"t": 0.0}

    async def progress(stage: str, frac: float, msg: str):
        now = asyncio.get_running_loop().time()
        if now - last["t"] > 0.5 or frac >= 1:
            last["t"] = now
            await _update(audit_id, stage=stage, progress=round(min(frac, 0.99), 3), message=msg[:500])

    try:
        await _update(audit_id, status="running", stage="crawl", progress=0.01, message="Starting crawl")
        max_pages = min(int(opts.get("max_pages") or settings.default_max_pages), settings.hard_max_pages)
        max_depth = min(int(opts.get("max_depth") or settings.default_max_depth), 10)
        comp_urls = [normalize_input_url(u) for u in (opts.get("competitors") or [])][:3]

        psi_task = None
        if settings.pagespeed_enabled and opts.get("pagespeed", True):
            psi_task = asyncio.create_task(run_pagespeed(url, settings))

        crawl = await crawl_site(url, settings, max_pages, max_depth, progress, progress_range=(0.02, 0.6))

        comp_profiles = []
        if comp_urls:
            await progress("competitors", 0.62, f"Benchmarking {len(comp_urls)} competitor(s)")

            async def comp(u):
                try:
                    c = await crawl_site(u, settings, max_pages=15, max_depth=2, check_external_links=False)
                    return competitor.site_profile(c)
                except Exception as exc:
                    return {"url": u, "error": f"{type(exc).__name__}: {exc}"[:200]}

            comp_profiles = await asyncio.gather(*(comp(u) for u in comp_urls))

        await progress("performance", 0.72, "Collecting PageSpeed Insights data")
        psi = await psi_task if psi_task else {"available": False, "error": "PageSpeed disabled"}

        await progress("analysis", 0.78, "Running audit modules")
        ctx = AuditContext(meta=crawl.meta, pages=crawl.pages, competitors=comp_profiles, performance=psi)
        if comp_profiles:
            ctx.self_profile = competitor.site_profile(crawl)
        findings = run_modules(ctx)
        result = build_result(ctx, findings)

        await progress("ai", 0.85, "Generating AI recommendations")
        result["ai"] = await generate_ai_report(result["summary"], result["findings"], settings)

        await progress("saving", 0.97, "Saving results")
        inbound = linking.inbound_counts(ctx)
        async with SessionLocal() as s:
            audit = await s.get(Audit, audit_id)
            for p in crawl.pages:
                d = p.model_dump(mode="json", exclude={"shingles", "text_sample"})
                d["inbound_internal_links"] = inbound.get(p.url, 0)
                s.add(Page(audit_id=audit_id, url=p.url, status=p.status, data=d))
            for f in result["findings"]:
                s.add(Action(audit_id=audit_id, finding_id=f["id"], title=f["title"][:300], bucket=f["priority"]["bucket"]))
            audit.result = result
            audit.overall_score = result["summary"]["overall_score"]
            audit.status = "completed"
            audit.stage = "done"
            audit.progress = 1.0
            audit.message = f"Audit complete: {len(findings)} findings across {len(crawl.pages)} pages"
            audit.completed_at = datetime.now(UTC)
            await s.commit()
    except Exception as exc:
        log.exception("Audit %s failed", audit_id)
        await _update(audit_id, status="failed", stage="failed", error=f"{type(exc).__name__}: {exc}"[:1000], completed_at=datetime.now(UTC))


def schedule_audit(audit_id: str) -> None:
    """Run in-process with a concurrency cap. For multi-instance deployments swap this
    for a queue worker (arq/Celery on Redis); execute_audit() is already self-contained."""
    global _audit_slots
    if _audit_slots is None:
        _audit_slots = asyncio.Semaphore(get_settings().max_concurrent_audits)

    async def runner():
        async with _audit_slots:
            await execute_audit(audit_id)

    task = asyncio.create_task(runner())
    _running.add(task)
    task.add_done_callback(_running.discard)
