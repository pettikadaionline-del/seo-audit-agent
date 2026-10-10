"""Stateless (Vercel) flow: run -> insights -> report, plus serverless limits."""
import asyncio
import time

import httpx

from app.config import Settings
from app.crawler.crawler import Crawler
from app.crawler.fetcher import Fetcher
from app.main import create_app
from tests.conftest import handler


async def test_stateless_flow(settings, fetcher_factory):
    app = create_app(settings, fetcher_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/audit/run", json={"url": "https://shop.example.com/", "max_pages": 10})
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["status"] == "completed" and result["issues"] and result["ai"] is None

        ins = await c.post("/api/insights", json=result)
        assert ins.status_code == 200 and ins.json()["generated_by"] == "heuristic"
        result["ai"] = ins.json()

        for fmt, ctype in (("pdf", "application/pdf"), ("csv", "text/csv"), ("html", "text/html"), ("json", "application/json")):
            rr = await c.post(f"/api/report.{fmt}", json=result)
            assert rr.status_code == 200 and rr.headers["content-type"].startswith(ctype), fmt
        assert b"Executive summary" in (await c.post("/api/report.html", json=result)).content


async def test_stateless_run_rejects_private(settings, fetcher_factory):
    settings.allow_private_networks = False
    app = create_app(settings, fetcher_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/audit/run", json={"url": "http://169.254.169.254/"})
        assert r.status_code == 422


def test_serverless_defaults_and_env_override(monkeypatch):
    s = Settings(serverless=True)
    assert s.max_pages_limit == 30 and s.crawl_time_budget_s == 40 and s.database_path.startswith("/tmp")
    monkeypatch.setenv("SEO_MAX_PAGES_LIMIT", "80")
    assert Settings(serverless=True).max_pages_limit == 80  # explicit env wins
    assert Settings(serverless=False).crawl_time_budget_s == 0


async def test_crawl_stops_at_deadline(settings):
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.3)
        return handler(request)

    fetcher = Fetcher(settings, transport=httpx.MockTransport(slow))
    start = time.monotonic()
    crawler = Crawler(settings, "https://shop.example.com/", 50, 5, fetcher=fetcher, deadline=start + 1.0)
    pages, site = await crawler.run()
    await fetcher.aclose()
    assert time.monotonic() - start < 3.5
    assert site.crawl_truncated and crawler.timed_out
    assert len(pages) < 7  # not everything was crawled
