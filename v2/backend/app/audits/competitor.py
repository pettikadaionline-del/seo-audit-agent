"""Competitor benchmark built from a light crawl of each competitor.

Compares observable on-site signals only. We do not have rankings, traffic or
backlink data (those need paid third-party data sources), so no claims about
them are made."""

from statistics import median

from app.audits.base import AuditContext, Category, Finding, Severity, finding
from app.crawler.engine import CrawlResult

C = Category.competitor


def _types(item: dict) -> list[str]:
    t = item.get("@type", [])
    return [x for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]


def site_profile(crawl: CrawlResult) -> dict:
    pages = [p for p in crawl.pages if p.status == 200 and "html" in p.content_type and p.indexable]
    n = max(1, len(pages))
    schema_types = sorted({t for p in pages for i in p.json_ld for t in _types(i)} | {t for p in pages for t in p.microdata_types})
    ai = crawl.meta.robots.ai_access(crawl.meta.start_url) if crawl.meta.robots and crawl.meta.robots.exists else {}
    ttfbs = [p.ttfb_ms for p in pages if p.ttfb_ms]
    return {
        "url": crawl.meta.start_url,
        "pages_crawled": len(pages),
        "sitemap_urls": len(crawl.meta.sitemap.urls) if crawl.meta.sitemap else 0,
        "median_word_count": int(median([p.word_count for p in pages])) if pages else 0,
        "pct_with_schema": round(100 * sum(1 for p in pages if p.json_ld or p.microdata_types) / n),
        "schema_types": schema_types,
        "pct_with_meta_description": round(100 * sum(1 for p in pages if p.meta_description) / n),
        "pct_with_single_h1": round(100 * sum(1 for p in pages if len(p.h1) == 1) / n),
        "pct_with_question_headings": round(100 * sum(1 for p in pages if p.question_headings) / n),
        "pct_images_with_alt": round(100 * sum(1 for p in pages for i in p.images if i.alt is not None) / max(1, sum(len(p.images) for p in pages))),
        "median_ttfb_ms": round(median(ttfbs)) if ttfbs else None,
        "https": crawl.meta.https,
        "llms_txt": crawl.meta.llms_txt,
        "ai_search_bots_allowed": all(ai.get(b, True) for b in ("OAI-SearchBot", "PerplexityBot", "Claude-SearchBot")) if ai else True,
        "has_faq_schema": any("FAQPage" in _types(i) for p in pages for i in p.json_ld),
        "error": None if pages else "No indexable HTML pages could be crawled",
    }


def run(ctx: AuditContext) -> list[Finding]:
    out: list[Finding] = []
    comps = [c for c in ctx.competitors if not c.get("error")]
    if not comps:
        return out
    you = ctx.self_profile
    if not you:
        return out

    def med(key):
        vals = [c[key] for c in comps if c.get(key) is not None]
        return median(vals) if vals else None

    ev = lambda key: [(c["url"], {key: c[key]}) for c in comps] + [(you["url"], {key: you[key], "you": True})]  # noqa: E731

    m = med("median_word_count")
    if m and you["median_word_count"] < 0.6 * m:
        out.append(finding("comp.content_depth", C, "Competitors publish more content per page", Severity.medium,
                           f"Your median page has {you['median_word_count']} words vs a competitor median of {int(m)}. Depth isn't a ranking factor in itself, but it often reflects more complete answers to buyer questions.",
                           "Expand key product/category pages with the details competitors cover (usage, ingredients, origin, shipping, FAQs), without padding.",
                           ev("median_word_count"), site_level=True, effort=3, confidence="medium"))

    their_types = {t for c in comps for t in c["schema_types"]}
    missing = sorted(their_types - set(you["schema_types"]))
    if missing:
        out.append(finding("comp.schema_gap", C, "Competitors use schema types you don't", Severity.medium,
                           f"Types used by competitors but not on your crawled pages: {', '.join(missing)}.",
                           "Add the types that match real content on your site (e.g. Product, FAQPage, BreadcrumbList, Review). Never mark up content that isn't visible.",
                           [(c["url"], {"schema_types": c["schema_types"]}) for c in comps] + [(you["url"], {"schema_types": you["schema_types"], "you": True})],
                           site_level=True, effort=2))

    m = med("pct_with_meta_description")
    if m is not None and you["pct_with_meta_description"] + 20 < m:
        out.append(finding("comp.meta_coverage", C, "Lower meta description coverage than competitors", Severity.low,
                           f"{you['pct_with_meta_description']}% of your pages have descriptions vs a competitor median of {int(m)}%.",
                           "Write descriptions for all key pages, starting with top sellers.", ev("pct_with_meta_description"), site_level=True, effort=1))

    if any(c["has_faq_schema"] or c["pct_with_question_headings"] > 20 for c in comps) and not you["has_faq_schema"] and you["pct_with_question_headings"] <= 20:
        out.append(finding("comp.faq_gap", C, "Competitors answer customer questions on-page; you don't", Severity.medium,
                           "At least one competitor uses FAQ markup or question-style headings on 20%+ of pages. Such content can win 'People also ask' and AI answer placements.",
                           "Add FAQ blocks built from real customer questions (WhatsApp/email queries are a goldmine).",
                           ev("pct_with_question_headings"), site_level=True, effort=2, confidence="medium"))

    m = med("median_ttfb_ms")
    if m and you["median_ttfb_ms"] and you["median_ttfb_ms"] > 1.5 * m and you["median_ttfb_ms"] > 600:
        out.append(finding("comp.slower", C, "Your server responds slower than competitors", Severity.medium,
                           f"Median TTFB {you['median_ttfb_ms']} ms vs competitor median {int(m)} ms (measured from the same audit server, same run).",
                           "Look at caching/CDN and hosting; see the performance findings.", ev("median_ttfb_ms"), site_level=True, effort=3, confidence="medium"))

    m = med("sitemap_urls")
    if m and you["sitemap_urls"] and you["sitemap_urls"] < 0.3 * m and m > 50:
        out.append(finding("comp.site_size", C, "Competitors have a much larger indexable footprint", Severity.info,
                           f"Your sitemap lists {you['sitemap_urls']} URLs vs a competitor median of {int(m)}. More pages = more queries you can rank for, if each page is useful.",
                           "Plan content that targets real search demand: recipe/usage guides, gifting guides, regional specialities, comparison pages.",
                           ev("sitemap_urls"), site_level=True, effort=5, confidence="medium"))
    return out
