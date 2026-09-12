from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.integrations.smtp import SmtpError
from app.schemas.common import StudyIdQuery
from app.schemas.settings import ConnectionTestResult, SettingsOut, SettingsUpdate
from app.services import daily_report as daily_report_service
from app.services import dqa_daily_email as dqa_daily_email
from app.services import settings as settings_service
from app.services.kobo_sync import sync_all_projects

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
    "/send-daily-report",
    response_model=ConnectionTestResult,
    operation_id="sendDailyReport",
    responses={400: {"description": "Bad request"}},
)
def send_daily_report(
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> ConnectionTestResult:
    if not q.study_id:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Failed to send daily report",
                "details": "studyId is required",
            },
        )
    try:
        report, recipients = daily_report_service.send_daily_report_now(
            db, study_id=q.study_id
        )
        study_bit = f" ({report.study_name})" if report.study_name else ""
        return ConnectionTestResult(
            success=True,
            message="Daily report sent",
            details=(
                f"Report for {report.report_date}{study_bit} sent to {len(recipients)} recipient(s). "
                f"{report.grand_total} submissions ({report.invalid_total} invalid)."
            ),
        )
    except (ValueError, SmtpError) as exc:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Failed to send daily report",
                "details": str(exc),
            },
        )


@router.post(
    "/send-dqa-daily-report",
    response_model=ConnectionTestResult,
    operation_id="sendDqaDailyReport",
    responses={400: {"description": "Bad request"}},
)
def send_dqa_daily_report(
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> ConnectionTestResult:
    """Generate and email today's DQA Daily (separate from submission digest)."""
    if not q.study_id:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Failed to send DQA Daily",
                "details": "studyId is required",
            },
        )
    try:
        report, recipients = dqa_daily_email.send_dqa_daily_now(db, study_id=q.study_id)
        return ConnectionTestResult(
            success=True,
            message="DQA Daily sent",
            details=f"{report.title} emailed to {len(recipients)} recipient(s).",
        )
    except (ValueError, SmtpError) as exc:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Failed to send DQA Daily",
                "details": str(exc),
            },
        )
