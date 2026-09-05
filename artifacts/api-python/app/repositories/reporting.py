"""Data loading for DQA report stats."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DqaFlag, Project, StudyTool, Submission
from app.domain.reporting.helpers import day_bounds
from app.services.dqa_engine import get_pack_for_project


def load_study_report_inputs(
    db: Session,
    study_id: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    tz_name: str = "Asia/Kolkata",
) -> dict[str, Any]:
    """Load projects, tools, submissions, flags, and rule packs for a study.

    When ``date_from`` / ``date_to`` (ISO YYYY-MM-DD) are set, submissions are
    restricted to that inclusive calendar range in ``tz_name``, and flags are
    limited to those submissions. When both are None, all study submissions and
    flags are loaded (unchanged default).
    """
    projects = list(
        db.scalars(
            select(Project)
            .where(Project.study_id == study_id)
            .order_by(Project.name)
        ).all()
    )
    tools_by_code = {
        (t.code or "").upper(): t
        for t in db.scalars(select(StudyTool).where(StudyTool.study_id == study_id)).all()
    }
    targets = {code: t.target_count for code, t in tools_by_code.items()}
    project_ids = [p.id for p in projects]
    all_subs: list[Submission] = []
    if project_ids:
        sub_stmt = select(Submission).where(Submission.project_id.in_(project_ids))
        if date_from is not None:
            range_start, _ = day_bounds(date_from, tz_name)
            sub_stmt = sub_stmt.where(Submission.submitted_at >= range_start)
        if date_to is not None:
            _, range_end = day_bounds(date_to, tz_name)
            sub_stmt = sub_stmt.where(Submission.submitted_at <= range_end)
        all_subs = list(db.scalars(sub_stmt).all())
    all_flags: list[DqaFlag] = []
    if project_ids:
        if date_from is None and date_to is None:
            all_flags = list(
                db.scalars(select(DqaFlag).where(DqaFlag.project_id.in_(project_ids))).all()
            )
        else:
            sub_ids = [s.id for s in all_subs]
            if sub_ids:
                all_flags = list(
                    db.scalars(select(DqaFlag).where(DqaFlag.submission_id.in_(sub_ids))).all()
                )
    pack_cache: dict[str, dict | None] = {}
    for pid in project_ids:
        pack_cache[pid] = get_pack_for_project(db, pid)
    return {
        "projects": projects,
        "targets": targets,
        "all_subs": all_subs,
        "all_flags": all_flags,
        "pack_cache": pack_cache,
    }
