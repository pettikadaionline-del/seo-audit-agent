"""End-to-end: real HTTP crawl of the local fixture site through the public API."""

import asyncio

import httpx
import pytest

from app.db import init_db
from app.main import app


@pytest.fixture
async def client():
    await init_db()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def wait_done(client, audit_id, timeout=90):
    for _ in range(timeout * 4):
        r = await client.get(f"/api/audits/{audit_id}/status")
        if r.json()["status"] in ("completed", "failed"):
            return r.json()
        await asyncio.sleep(0.25)
    raise AssertionError("audit did not finish")


async def test_full_audit_flow(client, fixture_site):
    r = await client.post("/api/audits", json={"url": fixture_site, "max_pages": 30, "pagespeed": False})
    assert r.status_code == 202, r.text
    audit_id = r.json()["id"]

    status = await wait_done(client, audit_id)
    assert status["status"] == "completed", status
    assert status["progress"] == 1.0

    result = (await client.get(f"/api/audits/{audit_id}")).json()["result"]
    checks = {f["check_id"]: f for f in result["findings"]}

    # Issues deliberately planted in tests/fixture_site
    assert "tech.no_https" in checks
    assert set(checks["links.broken_internal"]["affected_urls"]) == {fixture_site, fixture_site + "blog/"}
    assert fixture_site + "orphan.html" in checks["links.orphan_pages"]["affected_urls"]
    assert checks["ai.search_bots_blocked"]["evidence"][0]["blocked_user_agents"] == ["PerplexityBot"]
    assert fixture_site + "about.html" in checks["tech.noindex"]["affected_urls"]
    assert fixture_site + "gone.html" in checks["tech.sitemap_non_indexable"]["affected_urls"]
    assert "sd.missing_required" in checks and "onpage.heading_hierarchy" in checks

    # Every finding is evidence-backed
    for f in result["findings"]:
        assert f["affected_urls"] and f["evidence"], f["check_id"]
        assert f["priority"]["bucket"] in ("critical", "quick_win", "strategic", "long_term")

    assert 0 <= result["summary"]["overall_score"] <= 100
    assert result["ai"]["source"] == "rules"  # no API key in tests

    pages = (await client.get(f"/api/audits/{audit_id}/pages")).json()
    assert pages["total"] >= 8
    home = next(p for p in pages["items"] if p["url"] == fixture_site)
    assert home["inbound_internal_links"] >= 1 and home["word_count"] > 100

    actions = (await client.get(f"/api/audits/{audit_id}/actions")).json()
    assert len(actions) == len(result["findings"])
    upd = await client.patch(f"/api/audits/{audit_id}/actions/{actions[0]['id']}", json={"status": "done", "owner": "Ops"})
    assert upd.json()["status"] == "done"

    csv_ = await client.get(f"/api/audits/{audit_id}/export?format=csv")
    assert csv_.status_code == 200 and "bucket,severity" in csv_.text and ",done,Ops," in csv_.text
    html = await client.get(f"/api/audits/{audit_id}/export?format=html")
    assert "SEO Audit Report" in html.text and "Executive summary" in html.text
    js = await client.get(f"/api/audits/{audit_id}/export?format=json")
    assert js.json()["result"]["summary"]["url"] == fixture_site

    assert (await client.delete(f"/api/audits/{audit_id}")).status_code == 204
    assert (await client.get(f"/api/audits/{audit_id}")).status_code == 404


async def test_rejects_invalid_url(client):
    r = await client.post("/api/audits", json={"url": "ftp://nope"})
    assert r.status_code == 422


async def test_access_code_gate(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "access_code", "s3cret")
    assert (await client.get("/api/health")).json()["access_code_required"] is True
    assert (await client.get("/api/audits")).status_code == 401
    assert (await client.get("/api/audits", headers={"x-access-code": "wrong"})).status_code == 401
    assert (await client.get("/api/audits", headers={"x-access-code": "s3cret"})).status_code == 200
    assert (await client.get("/api/audits?code=s3cret")).status_code == 200  # export links use the query form


def test_postgres_url_gets_async_driver():
    from app.core.config import Settings

    assert Settings(database_url="postgres://u:p@h/db").database_url == "postgresql+asyncpg://u:p@h/db"
    assert Settings(database_url="postgresql://u:p@h/db").database_url == "postgresql+asyncpg://u:p@h/db"
    assert Settings(database_url="sqlite+aiosqlite:///x.db").database_url == "sqlite+aiosqlite:///x.db"
