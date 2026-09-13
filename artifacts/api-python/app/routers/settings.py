from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.models import ReportSchedule, Study
from app.db.session import SessionLocal, get_db
from app.integrations.smtp import SmtpError
from app.schemas.common import StudyIdQuery
from app.schemas.settings import ConnectionTestResult, SettingsOut, SettingsUpdate
from app.services import settings as settings_service
from app.services.kobo_sync import sync_all_projects
from app.services.reporting.schedule_email import enqueue_execute_then_email
from sqlalchemy import select

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


def _background_sync_study(study_id: str) -> None:
    """Sync a study after settings PATCH/PUT returns (own DB session)."""
    db = SessionLocal()
    try:
        sync_all_projects(db, study_id)
        logger.info("active_study_sync_complete", study_id=study_id)
    except Exception:
        logger.exception("active_study_sync_failed", study_id=study_id)
    finally:
        db.close()


@router.get("", response_model=SettingsOut, operation_id="getSettings")
def get_settings(db: Session = Depends(get_db)) -> SettingsOut:
    row = settings_service.get_or_create_settings(db)
    return settings_service.to_settings_out(row)


@router.put(
    "",
    response_model=SettingsOut,
    operation_id="updateSettings",
    responses={400: {"description": "Bad request"}},
)
def put_settings(
    payload: SettingsUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> SettingsOut:
    try:
        out, sync_study_id = settings_service.update_settings(db, payload)
    except (ValueError, SmtpError) as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    if sync_study_id:
        background_tasks.add_task(_background_sync_study, sync_study_id)
        logger.info("active_study_sync_scheduled", study_id=sync_study_id)
    return out


@router.post("/test-smtp", response_model=ConnectionTestResult, operation_id="testSmtpConnection")
def test_smtp(db: Session = Depends(get_db)) -> ConnectionTestResult:
    return settings_service.test_smtp(db)


@router.post(
    "/send-report-now",
    response_model=ConnectionTestResult,
    operation_id="sendReportNow",
    responses={400: {"description": "Bad request"}},
)
def send_report_now(
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> ConnectionTestResult:
    """Enqueue execute then email for the study's scheduled template."""
    if not q.study_id:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Failed to enqueue report",
                "details": "studyId is required",
            },
        )
    study = db.get(Study, q.study_id)
    if study is None:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "message": "Failed to enqueue report",
                "details": "Study not found",
            },
        )
    schedule = db.scalars(
        select(ReportSchedule).where(
            ReportSchedule.study_id == q.study_id,
            ReportSchedule.report_type == "daily_dqa",
        )
    ).first()
    if schedule is None or not schedule.template_id:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Failed to enqueue report",
                "details": (
                    "Create and assign a report template to the study schedule first."
                ),
            },
        )
    recipients = [e.strip() for e in (schedule.recipients or []) if e and e.strip()]
    if not recipients:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Failed to enqueue report",
                "details": "Configure schedule recipients before sending.",
            },
        )
    try:
        job_id = enqueue_execute_then_email(
            db,
            study_id=q.study_id,
            template_id=schedule.template_id,
            recipients=recipients,
        )
        return ConnectionTestResult(
            success=True,
            message="Report job enqueued",
            details=f"Execute+email job {job_id} queued for {len(recipients)} recipient(s).",
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Failed to enqueue report",
                "details": str(exc),
            },
        )
