import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
app.include_router(router)
