from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select

from app.api.exports import to_csv, to_html
from app.core.config import get_settings
from app.core.security import UnsafeURLError, assert_public_url, normalize_input_url
from app.db import Action, Audit, Page, SessionLocal
from app.pipeline import schedule_audit

router = APIRouter(prefix="/api")


class AuditCreate(BaseModel):
    url: str
    max_pages: int = Field(default=50, ge=1, le=500)
    max_depth: int = Field(default=4, ge=0, le=10)
    competitors: list[str] = Field(default_factory=list, max_length=3)
    pagespeed: bool = True

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        try:
            return normalize_input_url(v)
        except UnsafeURLError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("competitors")
    @classmethod
    def _comps(cls, v):
        out = []
        for u in v:
            if u.strip():
                try:
                    out.append(normalize_input_url(u))
                except UnsafeURLError as exc:
                    raise ValueError(f"{u}: {exc}") from exc
        return out


class ActionUpdate(BaseModel):
    status: Literal["todo", "in_progress", "done", "wont_fix"] | None = None
    owner: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=5000)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()  # SQLite drops tzinfo; values are stored in UTC


def _audit_brief(a: Audit) -> dict:
    return {
        "id": a.id, "url": a.url, "status": a.status, "stage": a.stage, "progress": a.progress,
        "message": a.message, "overall_score": a.overall_score, "error": a.error, "options": a.options,
        "created_at": _iso(a.created_at),
        "completed_at": _iso(a.completed_at),
    }


def _action_dict(a: Action) -> dict:
    return {"id": a.id, "finding_id": a.finding_id, "title": a.title, "bucket": a.bucket, "status": a.status,
            "owner": a.owner, "notes": a.notes, "updated_at": _iso(a.updated_at)}


@router.get("/health")
async def health():
    s = get_settings()
    return {"status": "ok", "ai_configured": bool(s.anthropic_api_key), "pagespeed_key": bool(s.pagespeed_api_key)}


@router.post("/audits", status_code=202)
async def create_audit(body: AuditCreate):
    settings = get_settings()
    for u in [body.url, *body.competitors]:
        try:
            await assert_public_url(u, settings.allow_private_targets)
        except UnsafeURLError as exc:
            raise HTTPException(422, f"{u}: {exc}") from exc
    async with SessionLocal() as s:
        audit = Audit(url=body.url, options=body.model_dump(exclude={"url"}))
        s.add(audit)
        await s.commit()
        audit_id = audit.id
        brief = _audit_brief(audit)
    schedule_audit(audit_id)
    return brief


@router.get("/audits")
async def list_audits(limit: int = Query(20, le=100)):
    async with SessionLocal() as s:
        rows = (await s.execute(select(Audit).order_by(Audit.created_at.desc()).limit(limit))).scalars().all()
        return [_audit_brief(a) for a in rows]


async def _get(audit_id: str) -> Audit:
    async with SessionLocal() as s:
        audit = await s.get(Audit, audit_id)
        if not audit:
            raise HTTPException(404, "Audit not found")
        return audit


@router.get("/audits/{audit_id}")
async def get_audit(audit_id: str):
    audit = await _get(audit_id)
    return {**_audit_brief(audit), "result": audit.result}


@router.get("/audits/{audit_id}/status")
async def audit_status(audit_id: str):
    return _audit_brief(await _get(audit_id))


@router.get("/audits/{audit_id}/pages")
async def audit_pages(audit_id: str, q: str | None = None, status: int | None = None, offset: int = 0, limit: int = Query(100, le=500)):
    async with SessionLocal() as s:
        stmt = select(Page).where(Page.audit_id == audit_id)
        if q:
            stmt = stmt.where(Page.url.contains(q))
        if status is not None:
            stmt = stmt.where(Page.status == status)
        total = (await s.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await s.execute(stmt.order_by(Page.id).offset(offset).limit(limit))).scalars().all()
        items = []
        for p in rows:
            d = p.data
            items.append({
                "url": p.url, "status": p.status, "depth": d.get("depth"), "title": d.get("title"),
                "meta_description": d.get("meta_description"), "h1": d.get("h1"), "word_count": d.get("word_count"),
                "ttfb_ms": d.get("ttfb_ms"), "html_bytes": d.get("html_bytes"), "indexable": d.get("status") == 200 and "noindex" not in f"{d.get('meta_robots') or ''}{d.get('x_robots_tag') or ''}",
                "canonical": d.get("canonical"), "schema_types": sorted({str(i.get("@type")) for i in d.get("json_ld", [])}),
                "internal_links_out": sum(1 for l in d.get("links", []) if l["internal"]),
                "inbound_internal_links": d.get("inbound_internal_links"), "images": len(d.get("images", [])),
                "redirects": len(d.get("redirect_chain", [])), "error": d.get("error"), "in_sitemap": d.get("in_sitemap"),
            })
        return {"total": total, "items": items}


@router.get("/audits/{audit_id}/pages/detail")
async def page_detail(audit_id: str, url: str):
    async with SessionLocal() as s:
        row = (await s.execute(select(Page).where(Page.audit_id == audit_id, Page.url == url))).scalars().first()
        if not row:
            raise HTTPException(404, "Page not found")
        return row.data


@router.get("/audits/{audit_id}/actions")
async def list_actions(audit_id: str):
    async with SessionLocal() as s:
        rows = (await s.execute(select(Action).where(Action.audit_id == audit_id).order_by(Action.id))).scalars().all()
        return [_action_dict(a) for a in rows]


@router.patch("/audits/{audit_id}/actions/{action_id}")
async def update_action(audit_id: str, action_id: int, body: ActionUpdate):
    async with SessionLocal() as s:
        a = await s.get(Action, action_id)
        if not a or a.audit_id != audit_id:
            raise HTTPException(404, "Action not found")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(a, k, v)
        await s.commit()
        await s.refresh(a)
        return _action_dict(a)


@router.get("/audits/{audit_id}/export")
async def export(audit_id: str, format: Literal["json", "csv", "html"] = "json"):
    audit = await _get(audit_id)
    if audit.status != "completed":
        raise HTTPException(409, "Audit is not complete yet")
    async with SessionLocal() as s:
        rows = (await s.execute(select(Action).where(Action.audit_id == audit_id))).scalars().all()
    actions = {a.finding_id: a for a in rows}
    host = audit.url.split("//", 1)[-1].split("/")[0].replace(":", "_")
    fname = f"seo-audit-{host}-{audit.completed_at:%Y%m%d}"
    if format == "csv":
        return PlainTextResponse(to_csv(audit, actions), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{fname}-actions.csv"'})
    if format == "html":
        return HTMLResponse(to_html(audit, actions), headers={"Content-Disposition": f'inline; filename="{fname}.html"'})
    payload = {**_audit_brief(audit), "result": audit.result, "actions": [_action_dict(a) for a in rows]}
    return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{fname}.json"'})


@router.delete("/audits/{audit_id}", status_code=204)
async def delete_audit(audit_id: str):
    async with SessionLocal() as s:
        audit = await s.get(Audit, audit_id)
        if not audit:
            raise HTTPException(404, "Audit not found")
        if audit.status in ("queued", "running"):
            raise HTTPException(409, "Audit is still running")
        await s.execute(delete(Page).where(Page.audit_id == audit_id))
        await s.execute(delete(Action).where(Action.audit_id == audit_id))
        await s.delete(audit)
        await s.commit()
