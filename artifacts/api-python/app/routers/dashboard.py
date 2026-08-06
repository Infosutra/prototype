from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models import Project, Report, Submission
from app.db.session import get_db
from app.schemas.misc import (
    ActivityItem,
    DashboardSummary,
    ProjectSummary,
    StatusCount,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary, operation_id="getDashboardSummary")
def dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummary:
    total_projects = db.scalar(select(func.count()).select_from(Project)) or 0
    total_submissions = db.scalar(select(func.count()).select_from(Submission)) or 0
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1)
    submissions_this_month = (
        db.scalar(
            select(func.count())
            .select_from(Submission)
            .where(Submission.submitted_at >= month_start)
        )
        or 0
    )
    active_enumerators = (
        db.scalar(select(func.count(distinct(Submission.enumerator)))) or 0
    )
    pending_reports = (
        db.scalar(
            select(func.count()).select_from(Report).where(Report.status == "draft")
        )
        or 0
    )
    last_sync = db.scalar(select(func.max(Project.last_sync_at)))

    status_rows = db.execute(
        select(Submission.status, func.count())
        .group_by(Submission.status)
    ).all()
    top = db.execute(
        select(Project)
        .order_by(Project.submission_count.desc())
        .limit(5)
    ).scalars().all()

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
        top_projects=[
            ProjectSummary(
                id=p.id,
                name=p.name,
                submission_count=p.submission_count,
                last_submission_at=p.last_submission_at.isoformat() if p.last_submission_at else None,
            )
            for p in top
        ],
    )


@router.get("/activity", response_model=list[ActivityItem], operation_id="getDashboardActivity")
def dashboard_activity(db: Session = Depends(get_db)) -> list[ActivityItem]:
    rows = db.scalars(
        select(Submission).order_by(Submission.submitted_at.desc()).limit(20)
    ).all()
    return [
        ActivityItem(
            id=row.id,
            type="submission",
            message=f"New submission in {row.project_name}",
            project_name=row.project_name,
            timestamp=row.submitted_at.isoformat(),
            icon="file",
        )
        for row in rows
    ]
