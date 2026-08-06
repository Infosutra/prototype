from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models import Project, Submission
from app.db.session import get_db
from app.schemas.common import SubmissionsListQuery
from app.schemas.submissions import FormResponse, SubmissionOut, SubmissionsPage
from app.services.form_labels import build_form_responses

router = APIRouter(prefix="/submissions", tags=["submissions"])


def _iso(value: datetime) -> str:
    return value.isoformat()


def _map_submission(row: Submission, responses: list[dict] | None = None) -> SubmissionOut:
    return SubmissionOut(
        id=row.id,
        display_id=f"Submission-{row.kobo_id}",
        project_id=row.project_id,
        project_name=row.project_name,
        form_id=row.form_id,
        form_name=row.form_name,
        enumerator=row.enumerator,
        status=row.status,
        submitted_at=_iso(row.submitted_at),
        location=row.location,
        data=row.data if isinstance(row.data, dict) else {},
        responses=[FormResponse.model_validate(item) for item in (responses or [])],
        attachment_count=row.attachment_count,
    )


@router.get("", response_model=SubmissionsPage, operation_id="getSubmissions")
def list_submissions(
    params: Annotated[SubmissionsListQuery, Query()],
    db: Session = Depends(get_db),
) -> SubmissionsPage:
    project_id = params.project_id
    status = params.status
    date_from = params.date_from
    date_to = params.date_to
    page = params.page
    limit = params.limit
    conditions = []
    if project_id:
        conditions.append(Submission.project_id == project_id)
    if status and status != "all":
        conditions.append(Submission.status == status)
    if date_from:
        conditions.append(Submission.submitted_at >= datetime.fromisoformat(date_from.replace("Z", "+00:00")).replace(tzinfo=None))
    if date_to:
        conditions.append(Submission.submitted_at <= datetime.fromisoformat(date_to.replace("Z", "+00:00")).replace(tzinfo=None))

    where = and_(*conditions) if conditions else None
    total = db.scalar(select(func.count()).select_from(Submission).where(where)) or 0
    offset = max(page - 1, 0) * limit
    query = select(Submission).order_by(Submission.submitted_at.desc()).offset(offset).limit(limit)
    if where is not None:
        query = query.where(where)
    rows = db.scalars(query).all()
    return SubmissionsPage(
        data=[_map_submission(row) for row in rows],
        total=int(total),
        page=page,
        limit=limit,
        total_pages=ceil(total / limit) if limit else 0,
    )


@router.get("/{submission_id}", response_model=SubmissionOut, operation_id="getSubmission")
def get_submission(submission_id: str, db: Session = Depends(get_db)) -> SubmissionOut:
    row = db.get(Submission, submission_id)
    if not row:
        raise HTTPException(status_code=404, detail="Submission not found")
    project = db.get(Project, row.project_id)
    form_definition = (
        project.form_definition
        if project and isinstance(project.form_definition, dict)
        else None
    )
    label_language = project.label_language if project else "English"
    data = row.data if isinstance(row.data, dict) else {}
    responses = build_form_responses(data, form_definition, label_language)
    return _map_submission(row, responses)
