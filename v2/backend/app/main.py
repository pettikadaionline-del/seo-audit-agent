import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import update

from app.api.routes import router
from app.core.config import get_settings
from app.db import Audit, SessionLocal, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Audits run in-process; any left running by a previous process are dead.
    async with SessionLocal() as s:
        await s.execute(
            update(Audit).where(Audit.status.in_(["queued", "running"]))
            .values(status="failed", stage="failed", error="Interrupted by server restart; please re-run.")
        )
        await s.commit()
    yield


app = FastAPI(title="SEO Audit Agent", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def access_gate(request: Request, call_next):
    code = get_settings().access_code
    path = request.url.path
    if code and path.startswith("/api/") and path != "/api/health" and request.method != "OPTIONS":
        # Header for fetch() calls; ?code= for plain download links (exports).
        given = request.headers.get("x-access-code") or request.query_params.get("code") or ""
        if not hmac.compare_digest(given.encode(), code.encode()):
            return JSONResponse({"detail": "access_code_required"}, status_code=401)
    return await call_next(request)


app.include_router(router)

_static = Path(get_settings().static_dir)
if _static.is_dir():
    app.mount("/", StaticFiles(directory=_static, html=True), name="dashboard")
