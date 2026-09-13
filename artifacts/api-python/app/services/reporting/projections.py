"""Helpers that compose answer + quality projection writers."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    DqaFlag,
    Submission,
    SubmissionAnswer,
    SubmissionQuality,
)
from app.services.reporting.answers import replace_answers_for_submission


def project_submission_facts(
    db: Session,
    submission: Submission,
    project=None,
    study_timezone: str | None = None,
) -> None:
    """Project answers + duration + calendar_day + study_id for one submission."""
    replace_answers_for_submission(
        db,
        submission,
        project=project,
        study_timezone=study_timezone,
    )


def resync_study_id_for_project(
    db: Session,
    project_id: str,
    new_study_id: str | None,
) -> None:
    """Rewrite or clear denormalized ``study_id`` for a project's children.

    When ``new_study_id`` is None, delete answer/quality projections (they require
    a study). Submissions and flags get ``study_id`` cleared. When set, rewrite
    ``study_id`` on submissions, flags, answers, and quality rows.
    """
    db.execute(
        update(Submission)
        .where(Submission.project_id == project_id)
        .values(study_id=new_study_id)
    )
    db.execute(
        update(DqaFlag)
        .where(DqaFlag.project_id == project_id)
        .values(study_id=new_study_id)
    )

    submission_ids = list(
        db.scalars(select(Submission.id).where(Submission.project_id == project_id)).all()
    )
    if not submission_ids:
        return

    if new_study_id is None:
        db.execute(
            delete(SubmissionAnswer).where(SubmissionAnswer.submission_id.in_(submission_ids))
        )
        db.execute(
            delete(SubmissionQuality).where(SubmissionQuality.submission_id.in_(submission_ids))
        )
        # Clear duration/day denorm when unassigned (optional; keep values harmless).
        db.execute(
            update(Submission)
            .where(Submission.project_id == project_id)
            .values(duration_minutes=None, calendar_day=None)
        )
        return

    db.execute(
        update(SubmissionAnswer)
        .where(SubmissionAnswer.submission_id.in_(submission_ids))
        .values(study_id=new_study_id)
    )
    db.execute(
        update(SubmissionQuality)
        .where(SubmissionQuality.submission_id.in_(submission_ids))
        .values(study_id=new_study_id)
    )
