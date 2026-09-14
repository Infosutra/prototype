"""In-process job worker: claim pending jobs and dispatch by type."""

from __future__ import annotations

import threading
from typing import Any, Callable

import structlog
from sqlalchemy.orm import Session

from app.db.models import Job
from app.services.jobs import store

logger = structlog.stdlib.get_logger(__name__)

Handler = Callable[[Session, Job], Any]

_HANDLERS: dict[str, Handler] = {}


def register_handler(job_type: str, handler: Handler) -> None:
    _HANDLERS[job_type] = handler


def _echo_handler(_db: Session, job: Job) -> Any:
    payload = job.payload if isinstance(job.payload, dict) else {}
    return payload if payload else {"ok": True}


def _execute_handler(db: Session, job: Job) -> Any:
    """Run ReportSpec via query engine; return ExecuteResult (no ReportRun)."""
    from app.services.jobs import store as job_store
    from app.services.reporting.execute import execute_report

    if not job.study_id:
        raise ValueError("execute job requires studyId")
    payload = job.payload if isinstance(job.payload, dict) else {}
    window = payload.get("window")
    if not window:
        raise ValueError("execute job payload requires window")
    # Authoring / demo preview: run queries but do not create a Reports-tab row.
    preview = bool(payload.get("preview"))
    persist = False if preview else bool(payload.get("persist", True))
    result = execute_report(
        db,
        study_id=job.study_id,
        window_input=window,
        spec=payload.get("spec"),
        template_id=payload.get("templateId"),
        title=payload.get("title"),
        persist=persist,
    )
    recipients = payload.get("emailRecipients")
    if (
        persist
        and recipients
        and isinstance(recipients, list)
        and result.get("reportId")
    ):
        job_store.enqueue(
            db,
            job_type="email",
            payload={
                "reportId": result["reportId"],
                "recipients": recipients,
            },
            study_id=job.study_id,
        )
    return result


def _email_handler(db: Session, job: Job) -> Any:
    """Email an existing report PDF to recipients."""
    from app.db.models import Report
    from app.services.reporting.schedule_email import send_report_email

    payload = job.payload if isinstance(job.payload, dict) else {}
    report_id = payload.get("reportId")
    if not report_id:
        raise ValueError("email job payload requires reportId")
    report = db.get(Report, report_id)
    if report is None:
        raise ValueError(f"Report not found: {report_id}")
    recipients = payload.get("recipients")
    if not isinstance(recipients, list) or not recipients:
        raise ValueError("email job payload requires recipients")
    _, sent_to = send_report_email(db, report, recipients=list(recipients))
    return {"reportId": report_id, "recipientsCount": len(sent_to)}


def _kobo_sync_handler(db: Session, job: Job) -> Any:
    """Pull Kobo forms/submissions for a study (or one project)."""
    from app.schemas.projects import SyncResult
    from app.services.kobo_sync import sync_all_projects, sync_project

    payload = job.payload if isinstance(job.payload, dict) else {}
    project_id = payload.get("projectId")
    logger.info(
        "kobo_sync_job_started",
        job_id=job.id,
        study_id=job.study_id,
        project_id=project_id,
    )
    if project_id:
        raw = sync_project(db, str(project_id))
    else:
        if not job.study_id:
            raise ValueError("kobo_sync job requires studyId")
        raw = sync_all_projects(db, job.study_id)
    return SyncResult.model_validate(raw).model_dump(by_alias=True)


def _plan_handler(db: Session, job: Job) -> Any:
    """Plan ReportSpec from English instructions; return PlanResult JSON."""
    from app.services.reporting.planner import plan_report

    if not job.study_id:
        raise ValueError("plan job requires studyId")
    payload = job.payload if isinstance(job.payload, dict) else {}
    instructions = payload.get("instructions")
    if not instructions or not str(instructions).strip():
        raise ValueError("plan job payload requires instructions")
    current = payload.get("currentSpec")
    if current is not None and not isinstance(current, dict):
        raise ValueError("plan job currentSpec must be an object")
    return plan_report(
        db,
        study_id=job.study_id,
        instructions=str(instructions),
        current_spec=current,
    )


register_handler("echo", _echo_handler)
register_handler("execute", _execute_handler)
register_handler("plan", _plan_handler)
register_handler("email", _email_handler)
register_handler("kobo_sync", _kobo_sync_handler)


def process_job(db: Session, job: Job) -> None:
    handler = _HANDLERS.get(job.type)
    if handler is None:
        store.fail(db, job, f"Unknown job type: {job.type}")
        return
    logger.info("job_started", job_id=job.id, job_type=job.type, study_id=job.study_id)
    try:
        result = handler(db, job)
        store.complete(db, job, result if result is not None else {"ok": True})
    except Exception as exc:
        logger.exception("job_handler_failed", job_id=job.id, job_type=job.type)
        # Domain message only — never raw traceback to the client.
        store.fail(db, job, str(exc) or "Job handler failed")


def run_claimed(db: Session, *, limit: int = 2) -> int:
    """Claim up to ``limit`` jobs and process them. Returns count processed."""
    claimed = store.claim(db, limit=limit)
    if claimed:
        logger.info(
            "jobs_claimed",
            count=len(claimed),
            types=[job.type for job in claimed],
            job_ids=[job.id for job in claimed],
        )
    for job in claimed:
        process_job(db, job)
    return len(claimed)


def kick_own_session(*, limit: int = 2) -> int:
    """Process pending jobs on a fresh session (for a detached worker thread)."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        return run_claimed(db, limit=limit)
    except Exception:
        logger.exception("job_kick_failed")
        return 0
    finally:
        db.close()


def kick_in_thread(*, limit: int = 2) -> None:
    """Start the worker on a daemon thread so the HTTP request can finish.

    FastAPI BackgroundTasks (and Starlette TestClient) wait until the task
    returns. Running the Kobo sync there holds POST /projects/sync open for
    the whole pull, so the UI spinner never clears and uvicorn access logs
    do not appear until the sync ends.
    """
    threading.Thread(
        target=kick_own_session,
        kwargs={"limit": limit},
        name="job-worker-kick",
        daemon=True,
    ).start()
