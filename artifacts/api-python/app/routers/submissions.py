from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import DqaFlag, Project, Submission
from app.db.session import get_db
from app.repositories.dqa import parse_submitted_at_bound
from app.schemas.common import SubmissionsListQuery
from app.schemas.submissions import FormResponse, SubmissionOut, SubmissionsPage
from app.services.form_labels import build_form_responses

router = APIRouter(prefix="/submissions", tags=["submissions"])


def _iso(value: datetime) -> str:
    return value.isoformat()


def _dqa_summary(flags: list[DqaFlag]) -> tuple[str | None, int, int]:
    red = sum(1 for flag in flags if (flag.severity or "").lower() == "red")
    amber = len(flags) - red
    if red:
        return "red", red, amber
    if amber:
        return "amber", red, amber
    return None, 0, 0


def _flagged_ids(project_id: str | None = None, study_id: str | None = None):
    query = select(DqaFlag.submission_id)
    if project_id:
        query = query.where(DqaFlag.project_id == project_id)
    elif study_id:
        query = query.where(
            DqaFlag.project_id.in_(select(Project.id).where(Project.study_id == study_id))
        )
    return query


def _dqa_condition(
    dqa: str | None,
    *,
    project_id: str | None,
    study_id: str | None,
):
    sev = (dqa or "").strip().lower()
    if sev in {"", "all"}:
        return None
    flagged = _flagged_ids(project_id=project_id, study_id=study_id)
    if sev in {"red", "amber"}:
        return Submission.id.in_(flagged.where(DqaFlag.severity == sev))
    if sev == "flagged":
        return Submission.id.in_(flagged)
    if sev == "clean":
        return ~Submission.id.in_(flagged)
    return None


def _map_submission(
    row: Submission,
    responses: list[dict] | None = None,
    *,
    flags: list[DqaFlag] | None = None,
) -> SubmissionOut:
    project_name = row.project.name if row.project is not None else row.form_name
    severity, red, amber = _dqa_summary(flags or [])
    return SubmissionOut(
        id=row.id,
        display_id=f"Submission-{row.kobo_id}",
        project_id=row.project_id,
        project_name=project_name,
        form_id=row.form_id,
        form_name=row.form_name,
        enumerator=row.enumerator,
        status=row.status,
        submitted_at=_iso(row.submitted_at),
        location=row.location,
        data=row.data if isinstance(row.data, dict) else {},
        responses=[FormResponse.model_validate(item) for item in (responses or [])],
        attachment_count=row.attachment_count,
        dqa_severity=severity,
        red_flags=red,
        amber_flags=amber,
    )


def _flags_by_submission(db: Session, submission_ids: list[str]) -> dict[str, list[DqaFlag]]:
    grouped: dict[str, list[DqaFlag]] = {sid: [] for sid in submission_ids}
    if not submission_ids:
        return grouped
    for flag in db.scalars(select(DqaFlag).where(DqaFlag.submission_id.in_(submission_ids))).all():
        grouped.setdefault(flag.submission_id, []).append(flag)
    return grouped


@router.get("", response_model=SubmissionsPage, operation_id="getSubmissions")
def list_submissions(
    params: Annotated[SubmissionsListQuery, Query()],
    db: Session = Depends(get_db),
) -> SubmissionsPage:
    project_id = params.project_id
    study_id = params.study_id
    if not project_id and not study_id:
        raise HTTPException(
            status_code=400, detail="studyId or projectId is required"
        )
    status = params.status
    date_from = params.date_from
    date_to = params.date_to
    page = params.page
    limit = params.limit
    conditions: list[Any] = []
    if project_id:
        conditions.append(Submission.project_id == project_id)
    elif study_id:
        conditions.append(
            Submission.project_id.in_(select(Project.id).where(Project.study_id == study_id))
        )
    if status and status != "all":
        conditions.append(Submission.status == status)
    start = parse_submitted_at_bound(date_from, end=False)
    finish = parse_submitted_at_bound(date_to, end=True)
    if start is not None:
        conditions.append(Submission.submitted_at >= start)
    if finish is not None:
        conditions.append(Submission.submitted_at <= finish)
    dqa_filter = _dqa_condition(params.dqa, project_id=project_id, study_id=study_id)
    if dqa_filter is not None:
        conditions.append(dqa_filter)

    where = and_(*conditions) if conditions else None
    total = db.scalar(select(func.count()).select_from(Submission).where(where)) or 0
    offset = max(page - 1, 0) * limit
    query = (
        select(Submission)
        .options(joinedload(Submission.project))
        .order_by(Submission.submitted_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if where is not None:
        query = query.where(where)
    rows = list(db.scalars(query).unique().all())
    flags = _flags_by_submission(db, [row.id for row in rows])
    return SubmissionsPage(
        data=[_map_submission(row, flags=flags.get(row.id, [])) for row in rows],
        total=int(total),
        page=page,
        limit=limit,
        total_pages=ceil(total / limit) if limit else 0,
    )


@router.get("/{submission_id}", response_model=SubmissionOut, operation_id="getSubmission")
def get_submission(submission_id: str, db: Session = Depends(get_db)) -> SubmissionOut:
    row = db.scalars(
        select(Submission)
        .options(joinedload(Submission.project))
        .where(Submission.id == submission_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Submission not found")
    project = row.project or db.get(Project, row.project_id)
    form_definition = (
        project.form_definition
        if project and isinstance(project.form_definition, dict)
        else None
    )
    label_language = project.label_language if project else "English"
    data = row.data if isinstance(row.data, dict) else {}
    responses = build_form_responses(data, form_definition, label_language)
    flags = _flags_by_submission(db, [row.id]).get(row.id, [])
    return _map_submission(row, responses, flags=flags)
