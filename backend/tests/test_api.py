import asyncio

import httpx

from app.main import create_app


async def _client(settings, fetcher_factory):
    app = create_app(settings, fetcher_factory)
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_full_api_flow(settings, fetcher_factory):
    app, client = await _client(settings, fetcher_factory)
    async with client:
        r = await client.post("/api/audits", json={"url": "https://shop.example.com/", "max_pages": 10})
        assert r.status_code == 202
        audit_id = r.json()["id"]
        await asyncio.gather(*app.state.tasks)

        status = (await client.get(f"/api/audits/{audit_id}/status")).json()
        assert status["status"] == "completed", status
        full = (await client.get(f"/api/audits/{audit_id}")).json()
        assert full["overall_score"] is not None and full["issues"]

        for fmt, ctype in (("json", "application/json"), ("csv", "text/csv"), ("html", "text/html"), ("pdf", "application/pdf")):
            rr = await client.get(f"/api/audits/{audit_id}/report.{fmt}")
            assert rr.status_code == 200 and rr.headers["content-type"].startswith(ctype)
        assert (await client.get(f"/api/audits/{audit_id}/report.xml")).status_code == 400
        assert any(a["id"] == audit_id for a in (await client.get("/api/audits")).json())
        assert (await client.delete(f"/api/audits/{audit_id}")).status_code == 204
        assert (await client.get(f"/api/audits/{audit_id}")).status_code == 404


async def test_rejects_private_targets(settings, fetcher_factory):
    settings.allow_private_networks = False
    _, client = await _client(settings, fetcher_factory)
    async with client:
        for url in ("http://127.0.0.1/", "http://169.254.169.254/", "http://localhost:8000/"):
            r = await client.post("/api/audits", json={"url": url})
            assert r.status_code == 422, url
        r = await client.post("/api/audits", json={"url": "javascript:alert(1)"})
        assert r.status_code == 422


async def test_rate_limit_and_api_key(settings, fetcher_factory):
    settings.rate_limit_per_minute = 1
    settings.api_key = "secret"
    app, client = await _client(settings, fetcher_factory)
    async with client:
        assert (await client.get("/api/audits")).status_code == 401
        h = {"X-API-Key": "secret"}
        assert (await client.post("/api/audits", json={"url": "https://shop.example.com/", "max_pages": 2}, headers=h)).status_code == 202
        assert (await client.post("/api/audits", json={"url": "https://shop.example.com/"}, headers=h)).status_code == 429
        await asyncio.gather(*app.state.tasks)
