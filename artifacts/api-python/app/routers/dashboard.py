from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, distinct, func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Project, Report, Study, Submission
from app.db.session import get_db
from app.domain.time_window import resolve_optional_submitted_at_bounds
from app.schemas.common import StudyDateRangeQuery
from app.schemas.misc import (
    ActivityItem,
    DashboardSummary,
    ProjectSummary,
    StatusCount,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _study_project_ids(study_id: str):
    return select(Project.id).where(Project.study_id == study_id)


def _apply_submitted_at_window(
    query: Select[Any],
    *,
    date_from: str | None,
    date_to: str | None,
    timezone: str,
) -> Select[Any]:
    start, finish = resolve_optional_submitted_at_bounds(
        date_from, date_to, timezone=timezone
    )
    if start is not None:
        query = query.where(Submission.submitted_at >= start)
    if finish is not None:
        query = query.where(Submission.submitted_at < finish)
    return query


def _require_study(db: Session, study_id: str | None) -> tuple[str, str]:
    if not study_id:
        raise HTTPException(status_code=400, detail="studyId is required")
    study = db.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    tz = (study.timezone or "UTC").strip() or "UTC"
    return study_id, tz


@router.get("/summary", response_model=DashboardSummary, operation_id="getDashboardSummary")
def dashboard_summary(
    q: Annotated[StudyDateRangeQuery, Query()],
    db: Session = Depends(get_db),
) -> DashboardSummary:
    study_id, tz = _require_study(db, q.study_id)
    project_ids = _study_project_ids(study_id)
    total_projects = (
        db.scalar(
            select(func.count()).select_from(Project).where(Project.study_id == study_id)
        )
        or 0
    )

    sub_count_q = select(func.count()).select_from(Submission).where(
        Submission.project_id.in_(project_ids)
    )
    sub_count_q = _apply_submitted_at_window(
        sub_count_q, date_from=q.date_from, date_to=q.date_to, timezone=tz
    )
    total_submissions = db.scalar(sub_count_q) or 0

    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1)
    month_q = select(func.count()).select_from(Submission).where(
        Submission.project_id.in_(project_ids),
        Submission.submitted_at >= month_start,
    )
    month_q = _apply_submitted_at_window(
        month_q, date_from=q.date_from, date_to=q.date_to, timezone=tz
    )
    submissions_this_month = db.scalar(month_q) or 0

    enum_q = select(func.count(distinct(Submission.enumerator))).where(
        Submission.project_id.in_(project_ids)
    )
    enum_q = _apply_submitted_at_window(
        enum_q, date_from=q.date_from, date_to=q.date_to, timezone=tz
    )
    active_enumerators = db.scalar(enum_q) or 0

    pending_reports = (
        db.scalar(
            select(func.count())
            .select_from(Report)
            .where(Report.status == "draft", Report.study_id == study_id)
        )
        or 0
    )
    last_sync = db.scalar(
        select(func.max(Project.last_sync_at)).where(Project.study_id == study_id)
    )

    status_q = (
        select(Submission.status, func.count())
        .where(Submission.project_id.in_(project_ids))
        .group_by(Submission.status)
    )
    status_q = _apply_submitted_at_window(
        status_q, date_from=q.date_from, date_to=q.date_to, timezone=tz
    )
    status_rows = db.execute(status_q).all()

    if q.date_from or q.date_to:
        ranked = (
            select(
                Submission.project_id,
                func.count().label("cnt"),
                func.max(Submission.submitted_at).label("last_at"),
            )
            .where(Submission.project_id.in_(project_ids))
        )
        ranked = _apply_submitted_at_window(
        ranked, date_from=q.date_from, date_to=q.date_to, timezone=tz
    )
        ranked = ranked.group_by(Submission.project_id).subquery()
        top_rows = db.execute(
            select(Project, ranked.c.cnt, ranked.c.last_at)
            .join(ranked, ranked.c.project_id == Project.id)
            .where(Project.study_id == study_id)
            .order_by(ranked.c.cnt.desc())
            .limit(5)
        ).all()
        top_projects = [
            ProjectSummary(
                id=project.id,
                name=project.name,
                submission_count=int(cnt),
                last_submission_at=last_at.isoformat() if last_at else None,
            )
            for project, cnt, last_at in top_rows
        ]
    else:
        top = db.execute(
            select(Project)
            .where(Project.study_id == study_id)
            .order_by(Project.submission_count.desc())
            .limit(5)
        ).scalars().all()
        top_projects = [
            ProjectSummary(
                id=p.id,
                name=p.name,
                submission_count=p.submission_count,
                last_submission_at=p.last_submission_at.isoformat()
                if p.last_submission_at
                else None,
            )
            for p in top
        ]

    return DashboardSummary(
        total_projects=int(total_projects),
        total_submissions=int(total_submissions),
        submissions_this_month=int(submissions_this_month),
        active_enumerators=int(active_enumerators),
        pending_reports=int(pending_reports),
        last_sync_at=last_sync.isoformat() if last_sync else None,
        submissions_by_status=[
            StatusCount(status=status, count=int(count)) for status, count in status_rows
        ],
        top_projects=top_projects,
    )


@router.get("/activity", response_model=list[ActivityItem], operation_id="getDashboardActivity")
def dashboard_activity(
    q: Annotated[StudyDateRangeQuery, Query()],
    db: Session = Depends(get_db),
) -> list[ActivityItem]:
    study_id, tz = _require_study(db, q.study_id)

    activity_q = (
        select(Submission)
        .options(joinedload(Submission.project))
        .where(Submission.project_id.in_(_study_project_ids(study_id)))
        .order_by(Submission.submitted_at.desc())
        .limit(20)
    )
    activity_q = _apply_submitted_at_window(
        activity_q, date_from=q.date_from, date_to=q.date_to, timezone=tz
    )
    rows = db.scalars(activity_q).unique().all()
    return [
        ActivityItem(
            id=row.id,
            type="submission",
            message=_activity_message(row),
            project_name=row.project.name if row.project else row.form_name,
            timestamp=row.submitted_at.isoformat(),
            icon="file",
        )
        for row in rows
    ]


def _activity_message(row: Submission) -> str:
    form_name = row.project.name if row.project else row.form_name or "a form"
    enumerator = (row.enumerator or "").strip() or "Unknown enumerator"
    return f"{enumerator} submitted {form_name}"
