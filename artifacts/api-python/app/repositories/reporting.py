"""Data loading for DQA report stats."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DqaFlag, Project, StudyTool, Submission
from app.services.dqa_engine import get_pack_for_project


def load_study_report_inputs(
    db: Session,
    study_id: str,
) -> dict[str, Any]:
    """Load projects, tools, submissions, flags, and rule packs for a study."""
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
        all_subs = list(
            db.scalars(select(Submission).where(Submission.project_id.in_(project_ids))).all()
        )
    all_flags: list[DqaFlag] = []
    if project_ids:
        all_flags = list(
            db.scalars(select(DqaFlag).where(DqaFlag.project_id.in_(project_ids))).all()
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
