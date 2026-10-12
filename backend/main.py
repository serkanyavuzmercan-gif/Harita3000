"""Harita3000 ASGI application."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import init_db
from backend.routers import auth, backup, company, entities, fleet, logistics, reports, visits
from backend.routers import map as map_router
from services.scheduler import run_scheduler

logger = logging.getLogger("harita3000")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
UPLOADS = settings.upload_path
UPLOADS.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO)
    try:
        await init_db()
    except Exception:
        logger.exception("Veritabanı başlatılamadı")
        raise
    stop = asyncio.Event()
    scheduler = asyncio.create_task(run_scheduler(stop)) if settings.telematics_poller_enabled else None
    try:
        yield
    finally:
        stop.set()
        if scheduler is not None:
            scheduler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scheduler


app = FastAPI(title=settings.app_name, version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["Kimlik"])
app.include_router(company.router, prefix="/api/company", tags=["Firma"])
app.include_router(entities.router, prefix="/api/entities", tags=["Cariler"])
app.include_router(logistics.router, prefix="/api/logistics", tags=["Lojistik"])
app.include_router(visits.router, prefix="/api/visits", tags=["Ziyaretler"])
app.include_router(fleet.router, prefix="/api/fleet", tags=["Filo takip"])
app.include_router(reports.router, prefix="/api/reports", tags=["Raporlar"])
app.include_router(backup.router, prefix="/api/backup", tags=["Yedekleme"])
app.include_router(map_router.router, prefix="/api", tags=["Harita"])

app.mount("/js", StaticFiles(directory=FRONTEND / "js"), name="js")
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "auth_required": settings.auth_required}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")
