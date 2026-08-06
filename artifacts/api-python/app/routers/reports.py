from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, Prompt, Report
from app.db.session import get_db
from app.integrations.smtp import SmtpError
from app.schemas.misc import (
    GenerateDqaDailyInput,
    GenerateDqaFinalInput,
    ReportInput,
    ReportOut,
    ShareReportInput,
    ShareResult,
)
from app.services import dqa_daily_report as dqa_daily
from app.services import dqa_final_report as dqa_final
from app.services import report_docx

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
        # Omit heavy JSON blob from list/detail by default — clients use preview/download.
        generated_content=None,
        download_url=row.download_url,
        page_count=row.page_count,
        file_size_kb=row.file_size_kb,
        generated_at=_iso_utc(row.generated_at),
        created_at=_iso_utc(row.created_at) or "",
    )


@router.get("", response_model=list[ReportOut])
def list_reports(
    study_id: str | None = Query(default=None, alias="studyId"),
    report_type: str | None = Query(default=None, alias="reportType"),
    db: Session = Depends(get_db),
) -> list[ReportOut]:
    q = select(Report).order_by(Report.created_at.desc())
    if study_id:
        q = q.where(Report.study_id == study_id)
    if report_type:
        q = q.where(Report.report_type == report_type)
    return [_map(row) for row in db.scalars(q).all()]


@router.post("/dqa-daily", response_model=ReportOut)
def create_dqa_daily(
    payload: GenerateDqaDailyInput,
    db: Session = Depends(get_db),
) -> ReportOut:
    try:
        report = dqa_daily.generate_daily_dqa_report(
            db,
            study_id=payload.study_id,
            report_date=payload.report_date,
            run_ai=payload.run_ai,
        )
        if payload.send_email:
            dqa_daily.send_dqa_daily_email(db, report)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SmtpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DQA Daily generation failed: {exc}") from exc
    return _map(report)


@router.post("/dqa-final", response_model=ReportOut)
def create_dqa_final(
    payload: GenerateDqaFinalInput,
    db: Session = Depends(get_db),
) -> ReportOut:
    try:
        report = dqa_final.generate_final_dqa_report(
            db,
            study_id=payload.study_id,
            run_ai=payload.run_ai,
        )
        if payload.send_email:
            dqa_daily.send_dqa_daily_email(db, report)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SmtpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Final DQA generation failed: {exc}") from exc
    return _map(report)


@router.post("", response_model=ReportOut)
def create_report(payload: ReportInput, db: Session = Depends(get_db)) -> ReportOut:
    names: list[str] = []
    if payload.project_ids:
        projects = db.scalars(
            select(Project).where(Project.id.in_(payload.project_ids))
        ).all()
        names = [p.name for p in projects]
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
        project_ids=payload.project_ids,
        project_names=names,
        created_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _map(row)


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: str, db: Session = Depends(get_db)) -> ReportOut:
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return _map(row)


@router.get("/{report_id}/preview")
def preview_report(report_id: str, db: Session = Depends(get_db)) -> HTMLResponse:
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    html_body = "<p>No HTML preview available.</p>"
    if row.generated_content:
        try:
            payload = json.loads(row.generated_content)
            html_body = payload.get("html") or html_body
        except json.JSONDecodeError:
            html_body = f"<pre>{row.generated_content}</pre>"
    return HTMLResponse(content=html_body)


@router.get("/{report_id}/download", response_model=None)
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
        path = dqa_daily.pdf_path_for(report_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="PDF file not found — regenerate the report")
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=f"{ascii_title}.pdf",
        )

    path = dqa_daily.docx_path_for(report_id)
    if path.is_file():
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{ascii_title}.docx",
        )

    # Rebuild from stored stats so older reports still download as DOCX.
    stats: dict | None = None
    if row.generated_content:
        try:
            payload = json.loads(row.generated_content)
            stats = payload.get("stats") if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            stats = None
    if not isinstance(stats, dict):
        raise HTTPException(
            status_code=404,
            detail="DOCX not available — regenerate the report",
        )
    try:
        docx_bytes = report_docx.render_report_docx(row.report_type, stats)
    except Exception as exc:  # noqa: BLE001 — surface generation failures cleanly
        raise HTTPException(status_code=500, detail=f"Failed to build DOCX: {exc}") from exc
    path.write_bytes(docx_bytes)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_title}.docx"',
        },
    )


@router.delete("/{report_id}")
def delete_report(report_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    pdf_path = dqa_daily.pdf_path_for(report_id)
    docx_path = dqa_daily.docx_path_for(report_id)
    db.delete(row)
    db.commit()
    if pdf_path.is_file():
        pdf_path.unlink(missing_ok=True)
    if docx_path.is_file():
        docx_path.unlink(missing_ok=True)
    return {"success": True}


@router.post("/{report_id}/generate", response_model=ReportOut)
def generate_report(report_id: str, db: Session = Depends(get_db)) -> ReportOut:
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    if (row.report_type or "") == "daily_dqa" or row.study_id:
        try:
            fresh = dqa_daily.generate_daily_dqa_report(
                db,
                study_id=row.study_id,
                report_date=row.report_date,
                run_ai=True,
            )
        except Exception as exc:
            row.status = "failed"
            db.commit()
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        # Replace draft with generated row metadata on the same id if draft.
        if row.status == "draft":
            path_old = dqa_daily.pdf_path_for(fresh.id)
            path_new = dqa_daily.pdf_path_for(row.id)
            if path_old.is_file():
                path_new.write_bytes(path_old.read_bytes())
                path_old.unlink(missing_ok=True)
            docx_old = dqa_daily.docx_path_for(fresh.id)
            docx_new = dqa_daily.docx_path_for(row.id)
            if docx_old.is_file():
                docx_new.write_bytes(docx_old.read_bytes())
                docx_old.unlink(missing_ok=True)
            row.title = fresh.title
            row.description = fresh.description
            row.status = "ready"
            row.report_type = "daily_dqa"
            row.study_id = fresh.study_id
            row.report_date = fresh.report_date
            row.project_ids = fresh.project_ids
            row.project_names = fresh.project_names
            row.generated_content = fresh.generated_content
            row.download_url = f"/api/reports/{row.id}/download"
            row.page_count = fresh.page_count
            row.file_size_kb = fresh.file_size_kb
            row.generated_at = fresh.generated_at
            db.delete(fresh)
            db.commit()
            db.refresh(row)
            return _map(row)
        return _map(fresh)

    # Legacy stub for custom reports
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    from app.db.models import DqaFlag, Submission

    project_ids = list(row.project_ids or [])
    lines = [f"# {row.title}", "", "## Data quality summary", ""]
    if project_ids:
        subs = db.scalars(select(Submission).where(Submission.project_id.in_(project_ids))).all()
        flags = db.scalars(select(DqaFlag).where(DqaFlag.project_id.in_(project_ids))).all()
    else:
        subs = db.scalars(select(Submission)).all()
        flags = db.scalars(select(DqaFlag)).all()
    flagged = {f.submission_id for f in flags}
    red = [f for f in flags if f.severity == "red"]
    amber = [f for f in flags if f.severity == "amber"]
    lines.append(f"- Total submissions: {len(subs)}")
    lines.append(f"- Submissions with any flag: {len(flagged)}")
    lines.append(f"- RED flags: {len(red)}")
    lines.append(f"- AMBER flags: {len(amber)}")
    row.status = "ready"
    row.generated_content = "\n".join(lines)
    row.download_url = None
    row.page_count = max(1, len(lines) // 40)
    row.file_size_kb = round(len(row.generated_content) / 1024, 1)
    row.generated_at = now
    db.commit()
    db.refresh(row)
    return _map(row)


@router.post("/{report_id}/share", response_model=ShareResult)
def share_report(
    report_id: str,
    payload: ShareReportInput,
    db: Session = Depends(get_db),
) -> ShareResult:
    row = db.get(Report, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        _, recipients = dqa_daily.send_dqa_daily_email(
            db, row, recipients=payload.recipients
        )
    except SmtpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ShareResult(
        success=True,
        recipients_count=len(recipients),
        message=f"DQA Daily emailed to {len(recipients)} recipient(s).",
    )
