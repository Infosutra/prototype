from __future__ import annotations

from datetime import datetime, timedelta, timezone

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Project, Study, Submission
from app.db.session import get_db
from app.domain.time_window import resolve_optional_submitted_at_bounds
from app.schemas.common import StudyIdQuery
from app.schemas.misc import (
    AnalyticsOverview,
    ChartDataPoint,
    EnumeratorStat,
    ProjectAnalytics,
    StatusCount,
    TrendPoint,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _submission_study_filter(study_id: str | None):
    """Restrict submission aggregates to projects in a study when studyId is set."""
    if not study_id:
        return None
    return Submission.project_id.in_(
        select(Project.id).where(Project.study_id == study_id)
    )


@router.get("/overview", response_model=AnalyticsOverview, operation_id="getAnalyticsOverview")
def analytics_overview(
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> AnalyticsOverview:
    if not q.study_id:
        raise HTTPException(status_code=400, detail="studyId is required")
    study_filter = _submission_study_filter(q.study_id)
    total_q = select(func.count()).select_from(Submission)
    if study_filter is not None:
        total_q = total_q.where(study_filter)
    total = db.scalar(total_q) or 0

    status_q = select(Submission.status, func.count()).group_by(Submission.status)
    if study_filter is not None:
        status_q = status_q.where(study_filter)
    by_status = db.execute(status_q).all()

    project_q = (
        select(Project.name, func.count())
        .join(Submission, Submission.project_id == Project.id)
        .group_by(Project.name)
        .order_by(func.count().desc())
    )
    if q.study_id:
        project_q = project_q.where(Project.study_id == q.study_id)
    by_project = db.execute(project_q).all()

    enum_q = (
        select(Submission.enumerator, func.count())
        .group_by(Submission.enumerator)
        .order_by(func.count().desc())
        .limit(20)
    )
    if study_filter is not None:
        enum_q = enum_q.where(study_filter)
    by_enumerator = db.execute(enum_q).all()

    return AnalyticsOverview(
        total_submissions=int(total),
        submissions_by_status=[
            StatusCount(status=s, count=int(c)) for s, c in by_status
        ],
        submissions_by_project=[
            ChartDataPoint(label=name or "Unknown", value=float(count))
            for name, count in by_project
        ],
        enumerator_performance=[
            EnumeratorStat(name=name or "Unknown", count=int(count))
            for name, count in by_enumerator
        ],
    )


@router.get("/projects/{project_id}", response_model=ProjectAnalytics, operation_id="getProjectAnalytics")
def project_analytics(project_id: str, db: Session = Depends(get_db)) -> ProjectAnalytics:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    total = (
        db.scalar(
            select(func.count())
            .select_from(Submission)
            .where(Submission.project_id == project_id)
        )
        or 0
    )
    by_status = db.execute(
        select(Submission.status, func.count())
        .where(Submission.project_id == project_id)
        .group_by(Submission.status)
    ).all()
    by_enumerator = db.execute(
        select(Submission.enumerator, func.count())
        .where(Submission.project_id == project_id)
        .group_by(Submission.enumerator)
        .order_by(func.count().desc())
    ).all()
    return ProjectAnalytics(
        project_id=project.id,
        project_name=project.name,
        total_submissions=int(total),
        submissions_by_status=[
            StatusCount(status=s, count=int(c)) for s, c in by_status
        ],
        enumerator_stats=[
            EnumeratorStat(name=name or "Unknown", count=int(count))
            for name, count in by_enumerator
        ],
    )


@router.get("/trends", response_model=list[TrendPoint], operation_id="getSubmissionTrends")
def submission_trends(
    period: str = Query(default="30d"),
    study_id: str | None = Query(default=None, alias="studyId"),
    date_from: str | None = Query(default=None, alias="dateFrom"),
    date_to: str | None = Query(default=None, alias="dateTo"),
    db: Session = Depends(get_db),
) -> list[TrendPoint]:
    if not study_id:
        raise HTTPException(status_code=400, detail="studyId is required")
    study_filter = _submission_study_filter(study_id)
    conditions = []
    if study_filter is not None:
        conditions.append(study_filter)

    study = db.get(Study, study_id)
    tz = ((study.timezone if study else None) or "UTC").strip() or "UTC"
    start, finish = resolve_optional_submitted_at_bounds(
        date_from,
        date_to,
        timezone=tz,
    )
    if start is None and finish is None:
        days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
        start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    if start is not None:
        conditions.append(Submission.submitted_at >= start)
    if finish is not None:
        conditions.append(Submission.submitted_at < finish)

    rows = db.execute(
        select(
            func.date(Submission.submitted_at),
            func.count(),
            func.count(func.distinct(Submission.project_id)),
        )
        .where(*conditions)
        .group_by(func.date(Submission.submitted_at))
        .order_by(func.date(Submission.submitted_at))
    ).all()
    return [
        TrendPoint(date=str(day), submissions=int(count), projects=int(project_count))
        for day, count, project_count in rows
    ]
