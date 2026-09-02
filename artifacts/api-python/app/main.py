from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import SessionLocal, init_db
from app.routers import (
    analytics,
    audio,
    dashboard,
    dqa,
    health,
    insights,
    projects,
    prompts,
    reports,
    settings,
    studies,
    submissions,
    usage,
)
from app.services.daily_report import maybe_send_scheduled_report
from app.services.dqa_daily_email import maybe_send_scheduled_dqa_daily
from app.services.transcription_job import drain_pending_transcriptions

logger = logging.getLogger(__name__)

# artifacts/api-python/app/main.py → repo root is parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND_DIST = _REPO_ROOT / "artifacts" / "infosutra" / "dist" / "public"


async def _scheduler_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            db = SessionLocal()
            try:
                maybe_send_scheduled_report(db)
                maybe_send_scheduled_dqa_daily(db)
            finally:
                db.close()
            drain_pending_transcriptions()
        except Exception:
            logger.exception("Daily report scheduler tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    init_db()
    db = SessionLocal()
    try:
        from app.services.settings import clear_undecryptable_secrets
        from app.services import dqa_engine
        from app.services import studies as studies_service

        if clear_undecryptable_secrets(db):
            logger.warning(
                "Cleared stored credentials that could not be decrypted with the "
                "current encryption key. Re-enter them in study Kobo settings.",
            )
        study = studies_service.seed_default_study(db)
        logger.info("Study ready: %s (%s)", study.name, study.id)
        seeded = dqa_engine.seed_rule_packs(db, overwrite=False)
        if seeded:
            logger.info("Seeded %s DQA rule pack(s)", seeded)
        assigned = studies_service.apply_all_study_form_maps(db)
        if assigned:
            logger.info("Assigned %s project(s) to studies from seed tool links", assigned)
    finally:
        db.close()
    stop_event = asyncio.Event()
    task = asyncio.create_task(_scheduler_loop(stop_event))
    logger.info("Infosutra API started")
    try:
        yield
    finally:
        stop_event.set()
        await task
        logger.info("Infosutra API stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Infosutra API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Accept-Ranges", "Content-Range", "Content-Length", "Content-Type"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception):
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

    prefix = "/api"
    app.include_router(health.router, prefix=prefix)
    app.include_router(dashboard.router, prefix=prefix)
    app.include_router(studies.router, prefix=prefix)
    app.include_router(projects.router, prefix=prefix)
    app.include_router(submissions.router, prefix=prefix)
    app.include_router(analytics.router, prefix=prefix)
    app.include_router(insights.router, prefix=prefix)
    app.include_router(prompts.router, prefix=prefix)
    app.include_router(reports.router, prefix=prefix)
    app.include_router(settings.router, prefix=prefix)
    app.include_router(dqa.router, prefix=prefix)
    app.include_router(dqa.projects_router, prefix=prefix)
    app.include_router(audio.router, prefix=prefix)
    app.include_router(usage.router, prefix=prefix)

    # Production UI only (Pi/systemd). Local start-local uses Vite on :5173.
    serve_frontend = os.environ.get("SERVE_FRONTEND", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if (
        serve_frontend
        and _FRONTEND_DIST.is_dir()
        and (_FRONTEND_DIST / "index.html").is_file()
    ):
        assets_dir = _FRONTEND_DIST / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/")
        async def spa_index():
            return FileResponse(_FRONTEND_DIST / "index.html")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            # Never shadow API routes (mounted above); this only catches non-API GETs.
            if full_path == "api" or full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"error": "Not found"})
            candidate = (_FRONTEND_DIST / full_path).resolve()
            try:
                candidate.relative_to(_FRONTEND_DIST.resolve())
            except ValueError:
                return FileResponse(_FRONTEND_DIST / "index.html")
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(_FRONTEND_DIST / "index.html")

        logger.info("Serving frontend from %s", _FRONTEND_DIST)
    elif serve_frontend:
        logger.warning(
            "SERVE_FRONTEND is set but build not found at %s — API only. "
            "Run scripts/build-frontend.sh.",
            _FRONTEND_DIST,
        )

    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
    )
