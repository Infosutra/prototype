"""Upsert per-submission DQA quality rollups for Query IR."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import DqaFlag, Submission, SubmissionQuality


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def upsert_quality_for_submission(
    db: Session,
    submission_id: str,
    *,
    project_id: str | None = None,
    study_id: str | None = None,
) -> None:
    """Upsert ``SubmissionQuality`` from current ``DqaFlag`` rows.

    When ``study_id`` is null, any existing quality row is deleted and no
    projection is written (orphan / unassigned project).
    """
    if project_id is None or study_id is None:
        submission = db.get(Submission, submission_id)
        if submission is not None:
            if project_id is None:
                project_id = submission.project_id
            if study_id is None:
                study_id = submission.study_id

    if not study_id:
        db.execute(
            delete(SubmissionQuality).where(SubmissionQuality.submission_id == submission_id)
        )
        return

    if not project_id:
        submission = db.get(Submission, submission_id)
        if submission is None:
            return
        project_id = submission.project_id

    rows = list(
        db.scalars(select(DqaFlag).where(DqaFlag.submission_id == submission_id)).all()
    )
    flag_count = len(rows)
    red_count = sum(1 for f in rows if str(f.severity or "").lower() == "red")
    amber_count = sum(1 for f in rows if str(f.severity or "").lower() == "amber")
    if red_count:
        max_severity: str | None = "red"
    elif amber_count:
        max_severity = "amber"
    else:
        max_severity = None

    quality = db.get(SubmissionQuality, submission_id)
    if quality is None:
        quality = SubmissionQuality(
            submission_id=submission_id,
            study_id=study_id,
            project_id=project_id,
            is_clean=flag_count == 0,
            max_severity=max_severity,
            flag_count=flag_count,
            red_count=red_count,
            amber_count=amber_count,
            updated_at=_now(),
        )
        db.add(quality)
    else:
        quality.study_id = study_id
        quality.project_id = project_id
        quality.is_clean = flag_count == 0
        quality.max_severity = max_severity
        quality.flag_count = flag_count
        quality.red_count = red_count
        quality.amber_count = amber_count
        quality.updated_at = _now()
