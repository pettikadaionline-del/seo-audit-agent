"""End-to-end: crawl the fake shop, run all agents, score, export."""
import pytest

from app.models import AuditRequest, AuditResult, AuditStatus
from app.orchestrator import AuditRunner
from app.reports import exporters
from app.store import AuditStore


@pytest.fixture
async def audit(settings, fetcher_factory) -> AuditResult:
    store = AuditStore(settings.database_path)
    runner = AuditRunner(settings, store, fetcher_factory)
    result = AuditResult(id="t1", url="https://shop.example.com/", status=AuditStatus.queued)
    return await runner.run(result, AuditRequest(url="https://shop.example.com/", max_pages=20))


def ids(r: AuditResult) -> set[str]:
    return {i.id for i in r.issues}


async def test_audit_completes(audit):
    assert audit.status == AuditStatus.completed, audit.error
    assert 0 <= audit.overall_score <= 100
    assert audit.grade in "ABCDF"
    assert audit.stats["pages_crawled"] >= 6
    assert audit.ai and audit.ai.generated_by == "heuristic"


async def test_external_links_not_crawled(audit):
    assert all("other.example.org" not in p.url for p in audit.pages)


async def test_expected_findings(audit):
    found = ids(audit)
    expected = {
        "technical.status.4xx",            # /missing-page
        "technical.redirect.chain",        # /old-url -> /old-url-2 -> product
        "technical.canonical.missing",     # product pages
        "onpage.title.duplicate",          # two "Murukku" titles
        "onpage.meta_description.missing",
        "onpage.images.alt_missing",
        "content.thin.severe",             # product pages
        "links.orphans",                   # /orphan only in sitemap
        "links.anchor.generic",            # "click here"
        "links.broken",
        "structured_data.invalid_json",    # broken JSON-LD on blog
        "ai_readiness.crawlers.search_blocked",  # PerplexityBot disallowed
    }
    missing = expected - found
    assert not missing, f"missing findings: {missing}; got {sorted(found)}"


async def test_no_false_positives_for_good_basics(audit):
    found = ids(audit)
    assert "technical.https.missing" not in found
    assert "technical.https.no_redirect" not in found  # fake server redirects http->https
    assert "technical.robots.missing" not in found
    assert "technical.sitemap.missing" not in found
    assert "technical.mobile.viewport" not in found
    assert "technical.host.inconsistent" not in found  # www host 404s, it doesn't serve a duplicate


async def test_issues_sorted_by_priority(audit):
    scores = [i.priority_score for i in audit.issues]
    assert scores == sorted(scores, reverse=True)


async def test_exports(audit):
    assert '"overall_score"' in exporters.to_json(audit)
    assert exporters.issues_csv(audit).startswith("priority,severity")
    assert "shop.example.com" in exporters.pages_csv(audit)
    html = exporters.to_html(audit)
    assert "<table>" in html and "Executive summary" in html
    assert exporters.to_pdf(audit)[:4] == b"%PDF"
