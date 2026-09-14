from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Project, Prompt, Report, ReportProject, Study
from app.db.session import get_db
from app.schemas.common import OkResponse, ReportsListQuery
from app.schemas.jobs import JobCreated
from app.schemas.misc import (
    GenerateReportInput,
    ReportInput,
    ReportOut,
    ShareReportInput,
)
from app.services.jobs import store as job_store
from app.services.report_storage import docx_path_for, pdf_path_for, read_report_result
from app.services.reporting.schedule_email import enqueue_execute

router = APIRouter(prefix="/reports", tags=["reports"])


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return aware.isoformat().replace("+00:00", "Z")


def _map(row: Report) -> ReportOut:
    return ReportOut(
        id=row.id,
        title=row.title,
        description=row.description,
        status=row.status,
        format=row.format,
        report_type=getattr(row, "report_type", None) or "custom",
        study_id=getattr(row, "study_id", None),
        report_date=getattr(row, "report_date", None),
        prompt_id=row.prompt_id,
        prompt_name=row.prompt_name,
        project_ids=list(row.project_ids or []),
        project_names=list(row.project_names or []),
        result_ref=None,
        download_url=row.download_url,
        page_count=row.page_count,
        file_size_kb=row.file_size_kb,
        generated_at=_iso_utc(row.generated_at),
        created_at=_iso_utc(row.created_at) or "",
    )


def _attach_projects(db: Session, report: Report, project_ids: list[str]) -> None:
    report.report_projects.clear()
    db.flush()
    if not project_ids:
        return
    projects = {
        p.id: p
        for p in db.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    }
    for pid in project_ids:
        project = projects.get(pid)
        report.report_projects.append(
            ReportProject(
                project_id=pid,
                project_name=project.name if project else None,
            )
        )


@router.get("", response_model=list[ReportOut], operation_id="getReports")
def list_reports(
    q: Annotated[ReportsListQuery, Query()],
    db: Session = Depends(get_db),
) -> list[ReportOut]:
    if not q.study_id:
        raise HTTPException(status_code=400, detail="studyId is required")
    query = (
        select(Report)
        .options(joinedload(Report.report_projects))
        .order_by(Report.created_at.desc())
    )
    query = query.where(Report.study_id == q.study_id)
    if q.report_type:
        query = query.where(Report.report_type == q.report_type)
    return [_map(row) for row in db.scalars(query).unique().all()]


@router.post(
    "/generate",
    response_model=JobCreated,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="generateReportFromTemplate",
)
def generate_from_template(
    payload: GenerateReportInput,
    db: Session = Depends(get_db),
) -> JobCreated:
    """Enqueue execute for a user-saved template. Refuses without templateId."""
    if not payload.template_id or not str(payload.template_id).strip():
        raise HTTPException(
            status_code=400,
            detail="templateId is required. Create and save a report template first.",
        )
    if not payload.study_id or db.get(Study, payload.study_id) is None:
        raise HTTPException(status_code=404, detail="Study not found")
    try:
        if payload.send_email:
            recipients = list(payload.recipients or [])
            if not recipients:
                raise ValueError(
                    "recipients are required when sendEmail is true"
                )
            job_id = enqueue_execute(
                db,
                study_id=payload.study_id,
                template_id=payload.template_id.strip(),
                window=payload.window,
                email_recipients=recipients,
            )
        else:
            job_id = enqueue_execute(
                db,
                study_id=payload.study_id,
                template_id=payload.template_id.strip(),
                window=payload.window,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JobCreated(job_id=job_id)


@router.post("", response_model=ReportOut, operation_id="createReport")
def create_report(payload: ReportInput, db: Session = Depends(get_db)) -> ReportOut:
    prompt_name = None
    if payload.prompt_id:
        prompt = db.get(Prompt, payload.prompt_id)
        prompt_name = prompt.name if prompt else None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = Report(
        id=str(uuid.uuid4()),
        title=payload.title,
        description=payload.description,
        status="draft",
        format=payload.format,
        report_type=payload.report_type or "custom",
        study_id=payload.study_id,
        report_date=payload.report_date,
        prompt_id=payload.prompt_id,
        prompt_name=prompt_name,
        created_at=now,
    )
    db.add(row)
    db.flush()
    _attach_projects(db, row, list(payload.project_ids or []))
    db.commit()
    db.refresh(row)
    return _map(row)


@router.get("/{report_id}", response_model=ReportOut, operation_id="getReport")
def get_report(report_id: str, db: Session = Depends(get_db)) -> ReportOut:
    row = db.scalars(
        select(Report)
        .options(joinedload(Report.report_projects))
        .where(Report.id == report_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return _map(row)


@router.get(
    "/{report_id}/result",
    operation_id="getReportResult",
)
def get_report_result(report_id: str, db: Session = Depends(get_db)) -> dict:
    """Return the stored ExecuteResult JSON for an in-app web preview."""
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    if not row.result_ref:
        raise HTTPException(status_code=404, detail="Report result not available")
    try:
        payload = read_report_result(row.result_ref)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Report result file missing — regenerate the report"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail="Report result could not be loaded"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Report result is invalid")
    return payload


@router.get(
    "/{report_id}/preview",
    response_class=HTMLResponse,
    responses={200: {"content": {"text/html": {}}}},
    operation_id="previewReport",
)
def preview_report(report_id: str, db: Session = Depends(get_db)) -> HTMLResponse:
    """Legacy HTML stub. Prefer the SPA route ``/reports/{id}/preview``."""
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    title = (row.title or "Report").replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        content=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{title}</title></head><body style='font-family:system-ui;padding:2rem'>"
            f"<h1>{title}</h1>"
            "<p>Open this report in the Infosutra app for the full web preview:</p>"
            f"<p><a href='/reports/{report_id}/preview'>/reports/{report_id}/preview</a></p>"
            "</body></html>"
        )
    )


@router.get(
    "/{report_id}/download",
    response_model=None,
    operation_id="downloadReport",
    responses={
        200: {
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
            }
        }
    },
)
def download_report(
    report_id: str,
    format: str = Query(default="pdf", pattern="^(pdf|docx)$"),
    db: Session = Depends(get_db),
):
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")

    safe_title = row.title.replace("/", "-")[:80]
    ascii_title = (
        safe_title.encode("ascii", "replace").decode("ascii").replace("?", "-").strip()
        or "report"
    )
    if format == "pdf":
        path = pdf_path_for(report_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="PDF file not found — regenerate the report")
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=f"{ascii_title}.pdf",
        )

    path = docx_path_for(report_id)
    if path.is_file():
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{ascii_title}.docx",
        )

    raise HTTPException(
        status_code=404,
        detail="DOCX not available — regenerate the report",
    )


@router.delete("/{report_id}", response_model=OkResponse, operation_id="deleteReport")
def delete_report(report_id: str, db: Session = Depends(get_db)) -> OkResponse:
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    pdf_path = pdf_path_for(report_id)
    docx_path = docx_path_for(report_id)
    db.delete(row)
    db.commit()
    if pdf_path.is_file():
        pdf_path.unlink(missing_ok=True)
    if docx_path.is_file():
        docx_path.unlink(missing_ok=True)
    return OkResponse(success=True)


@router.post(
    "/{report_id}/share",
    response_model=JobCreated,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="shareReport",
)
def share_report(
    report_id: str,
    payload: ShareReportInput,
    db: Session = Depends(get_db),
) -> JobCreated:
    """Enqueue email job for an existing report. Does not SMTP in the request."""
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    recipients = [e.strip() for e in (payload.recipients or []) if e and str(e).strip()]
    if not recipients:
        raise HTTPException(status_code=400, detail="recipients are required")
    job = job_store.enqueue(
        db,
        job_type="email",
        payload={"reportId": report_id, "recipients": recipients},
        study_id=row.study_id,
    )
    return JobCreated(job_id=job.id)
