from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
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
    jobs,
    projects,
    prompts,
    report_conversations,
    report_templates,
    reports,
    settings,
    studies,
    submissions,
    usage,
)
from app.services.kobo_auto_sync import maybe_run_scheduled_kobo_sync
from app.services.jobs import worker as jobs_worker
from app.services.reporting.schedule_email import maybe_send_scheduled_reports
from app.services.transcription_job import drain_pending_transcriptions

logger = structlog.stdlib.get_logger(__name__)

# artifacts/api-python/app/main.py → repo root is parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND_DIST = _REPO_ROOT / "artifacts" / "infosutra" / "dist" / "public"


def _serve_frontend_enabled() -> bool:
    return os.environ.get("SERVE_FRONTEND", "").strip().lower() in {"1", "true", "yes"}


def _scheduler_tick() -> None:
    db = SessionLocal()
    try:
        maybe_run_scheduled_kobo_sync(db)
        maybe_send_scheduled_reports(db)
        # Small budget so long execute jobs do not starve Kobo/email ticks.
        jobs_worker.run_claimed(db, limit=2)
    finally:
        db.close()
    drain_pending_transcriptions()


async def _scheduler_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(_scheduler_tick)
        except Exception:
            logger.exception("scheduler_tick_failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        from app.services.settings import clear_undecryptable_secrets
        from app.services import dqa_engine
        from app.services import studies as studies_service

        if clear_undecryptable_secrets(db):
            logger.warning("cleared_undecryptable_secrets")
        study = studies_service.seed_default_study(db)
        logger.info("study_ready", study_id=study.id, study_name=study.name)
        seeded = dqa_engine.seed_rule_packs(db, overwrite=False)
        if seeded:
            logger.info("seeded_dqa_rule_packs", count=seeded)
        from app.services.dqa_compile_prompt import seed_dqa_compile_prompt

        if seed_dqa_compile_prompt(db):
            logger.info("seeded_dqa_compile_prompt")
        from app.services.reporting.prompt_seeds import seed_reporting_prompts

        ai_prompts = seed_reporting_prompts(db)
        if ai_prompts:
            logger.info("seeded_reporting_prompts", count=ai_prompts)
        assigned = studies_service.apply_all_study_form_maps(db)
        if assigned:
            logger.info("assigned_study_form_maps", count=assigned)
        from app.services.jobs import store as job_store

        orphaned = job_store.fail_orphaned_processing(db)
        if orphaned:
            logger.info("failed_orphaned_jobs", count=orphaned)
    finally:
        db.close()

    if _serve_frontend_enabled():
        if _FRONTEND_DIST.is_dir() and (_FRONTEND_DIST / "index.html").is_file():
            logger.info("serving_frontend", path=str(_FRONTEND_DIST))
        else:
            logger.warning(
                "frontend_build_missing",
                path=str(_FRONTEND_DIST),
                hint="Run scripts/build-frontend.sh",
            )

    stop_event = asyncio.Event()
    task = asyncio.create_task(_scheduler_loop(stop_event))
    logger.info("api_started")
    try:
        yield
    finally:
        stop_event.set()
        await task
        logger.info("api_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Infosutra API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        # Reflect any Origin so LAN / other-system clients work with browsers.
        # (allow_origins=["*"] + allow_credentials=True is rejected by browsers.)
        allow_origin_regex=r".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Accept-Ranges", "Content-Range", "Content-Length", "Content-Type"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(
            "unhandled_error",
            error=str(exc),
            path=str(request.url.path),
            method=request.method,
        )
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
    app.include_router(report_templates.catalog_router, prefix=prefix)
    app.include_router(report_templates.router, prefix=prefix)
    app.include_router(report_conversations.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)
    app.include_router(settings.router, prefix=prefix)
    app.include_router(dqa.router, prefix=prefix)
    app.include_router(dqa.projects_router, prefix=prefix)
    app.include_router(audio.router, prefix=prefix)
    app.include_router(usage.router, prefix=prefix)

    # Production UI only (Pi/systemd). Local start-local uses Vite on :5173.
    if (
        _serve_frontend_enabled()
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

    return app


app = create_app()


def run() -> None:
    setup_logging()
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
        access_log=True,
        log_config=None,
    )


if __name__ == "__main__":
    run()
