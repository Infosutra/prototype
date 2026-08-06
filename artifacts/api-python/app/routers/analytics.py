from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Project, Submission
from app.db.session import get_db
from app.schemas.misc import (
    AnalyticsOverview,
    ChartDataPoint,
    EnumeratorStat,
    ProjectAnalytics,
    StatusCount,
    TrendPoint,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview, operation_id="getAnalyticsOverview")
def analytics_overview(db: Session = Depends(get_db)) -> AnalyticsOverview:
    total = db.scalar(select(func.count()).select_from(Submission)) or 0
    by_status = db.execute(
        select(Submission.status, func.count()).group_by(Submission.status)
    ).all()
    by_project = db.execute(
        select(Project.name, func.count())
        .join(Submission, Submission.project_id == Project.id)
        .group_by(Project.name)
        .order_by(func.count().desc())
    ).all()
    by_enumerator = db.execute(
        select(Submission.enumerator, func.count())
        .group_by(Submission.enumerator)
        .order_by(func.count().desc())
        .limit(20)
    ).all()
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
    db: Session = Depends(get_db),
) -> list[TrendPoint]:
    days = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}.get(period, 30)
    start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    rows = db.execute(
        select(
            func.date(Submission.submitted_at),
            func.count(),
            func.count(func.distinct(Submission.project_id)),
        )
        .where(Submission.submitted_at >= start)
        .group_by(func.date(Submission.submitted_at))
        .order_by(func.date(Submission.submitted_at))
    ).all()
    return [
        TrendPoint(date=str(day), submissions=int(count), projects=int(project_count))
        for day, count, project_count in rows
    ]
