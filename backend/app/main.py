"""FastAPI application: REST API for submitting and retrieving audits."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from app.ai.advisor import generate_insights
from app.config import Settings, get_settings
from app.models import AIInsights, AuditRequest, AuditResult, AuditStatus
from app.orchestrator import AuditRunner
from app.reports import exporters
from app.security.url_guard import UnsafeURLError, validate_url
from app.store import AuditStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, fetcher_factory=None) -> FastAPI:
    settings = settings or get_settings()
    store = AuditStore(settings.database_path)
    runner = AuditRunner(settings, store, fetcher_factory)
    tasks: set[asyncio.Task] = set()
    hits: dict[str, deque] = defaultdict(deque)

    app = FastAPI(title="AI SEO Audit Agent", version="1.0.0")
    app.state.store = store
    app.state.tasks = tasks
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    def require_key(x_api_key: str | None = Header(default=None)) -> None:
        if settings.api_key and x_api_key != settings.api_key:
            raise HTTPException(401, "Invalid or missing API key")

    def rate_limit(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        q = hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= settings.rate_limit_per_minute:
            raise HTTPException(429, "Too many audits requested; try again in a minute")
        q.append(now)

    def get_or_404(audit_id: str) -> AuditResult:
        r = store.get(audit_id)
        if not r:
            raise HTTPException(404, "Audit not found")
        return r

    def completed(audit_id: str) -> AuditResult:
        r = get_or_404(audit_id)
        if r.status != AuditStatus.completed:
            raise HTTPException(409, f"Audit is {r.status.value}")
        return r

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "running_audits": len(tasks)}

    @app.post("/api/audits", status_code=202, dependencies=[Depends(require_key), Depends(rate_limit)])
    async def create_audit(req: AuditRequest) -> dict:
        for u in [req.url, *req.competitors]:
            try:
                await validate_url(str(u), settings.allow_private_networks)
            except UnsafeURLError as exc:
                raise HTTPException(422, f"URL rejected: {exc}") from exc
        result = AuditResult(id=uuid.uuid4().hex[:16], url=str(req.url), status=AuditStatus.queued, message="Queued")
        store.save(result)
        task = asyncio.create_task(runner.run(result, req))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"id": result.id, "status": result.status}

    @app.get("/api/audits", dependencies=[Depends(require_key)])
    def list_audits(limit: int = 50) -> list[dict]:
        return store.list(min(limit, 200))

    @app.get("/api/audits/{audit_id}", dependencies=[Depends(require_key)])
    def get_audit(audit_id: str) -> AuditResult:
        return get_or_404(audit_id)

    @app.get("/api/audits/{audit_id}/status", dependencies=[Depends(require_key)])
    def get_status(audit_id: str) -> dict:
        r = get_or_404(audit_id)
        return {"id": r.id, "status": r.status, "progress": r.progress, "message": r.message, "error": r.error}

    @app.delete("/api/audits/{audit_id}", status_code=204, dependencies=[Depends(require_key)])
    def delete_audit(audit_id: str) -> Response:
        if not store.delete(audit_id):
            raise HTTPException(404, "Audit not found")
        return Response(status_code=204)

    @app.get("/api/audits/{audit_id}/report.{fmt}", dependencies=[Depends(require_key)])
    def report(audit_id: str, fmt: str, kind: str = "issues") -> Response:
        return _render_report(completed(audit_id), fmt, kind)

    # ---- Stateless API (serverless hosting, e.g. Vercel) -------------------
    # Each call does one bounded unit of work and returns everything the client
    # needs; the client keeps the result and sends it back for AI / exports.

    @app.post("/api/audit/run", dependencies=[Depends(require_key), Depends(rate_limit)])
    async def run_audit_sync(req: AuditRequest) -> AuditResult:
        """Crawl + analyse + score, synchronously, within SEO_CRAWL_TIME_BUDGET_S. No AI."""
        for u in [req.url, *req.competitors]:
            try:
                await validate_url(str(u), settings.allow_private_networks)
            except UnsafeURLError as exc:
                raise HTTPException(422, f"URL rejected: {exc}") from exc
        result = AuditResult(id=uuid.uuid4().hex[:16], url=str(req.url), status=AuditStatus.queued)
        result = await runner.run(result, req.model_copy(update={"use_ai": False}))
        if result.status == AuditStatus.failed:
            raise HTTPException(502, result.error or "Audit failed")
        return result

    @app.post("/api/insights", dependencies=[Depends(require_key), Depends(rate_limit)])
    async def insights(result: AuditResult) -> AIInsights:
        """AI recommendations for an audit result produced by /api/audit/run."""
        return await generate_insights(result, settings)

    @app.post("/api/report.{fmt}", dependencies=[Depends(require_key)])
    def report_stateless(fmt: str, result: AuditResult, kind: str = "issues") -> Response:
        return _render_report(result, fmt, kind)

    return app


def _render_report(r: AuditResult, fmt: str, kind: str) -> Response:
    name = f"seo-audit-{r.id}"
    if fmt == "json":
        return Response(exporters.to_json(r), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    if fmt == "csv":
        body = exporters.pages_csv(r) if kind == "pages" else exporters.issues_csv(r)
        return PlainTextResponse(body, media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{name}-{kind}.csv"'})
    if fmt == "html":
        return HTMLResponse(exporters.to_html(r))
    if fmt == "pdf":
        return Response(exporters.to_pdf(r), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    raise HTTPException(400, "Format must be json, csv, html or pdf")


app = create_app()
