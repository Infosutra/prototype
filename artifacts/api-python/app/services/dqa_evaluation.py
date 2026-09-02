"""DQA evaluation orchestration and flag persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import DqaFlag, Project, Submission
from app.domain.dqa.eval import eval_check
from app.domain.dqa.highlights import resolve_highlight_fields
from app.services.dqa_relationship_resolver import (
    build_related_context,
    load_study_relationships,
    source_projects_for_target,
)
from app.services.dqa_rule_packs import get_pack_for_project


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def evaluate_rule(
    rule: dict[str, Any],
    *,
    data: dict[str, Any],
    pack: dict[str, Any],
    project_rows: list[Submission] | None,
    current: Submission,
    related: dict | None = None,
    study_id: str | None = None,
) -> DqaFlag | None:

    check = rule.get("check")
    if check is None and rule.get("checks"):
        check = {"op": "all", "checks": rule["checks"]}
    ok, details = eval_check(
        check,
        data=data,
        pack=pack,
        project_rows=project_rows,
        current=current,
        related=related,
        study_id=study_id,
    )
    flag_when = str(rule.get("flag_when") or "fail").lower()
    should_flag = (not ok) if flag_when == "fail" else ok
    if not should_flag:
        return None
    submission_data = data if isinstance(data, dict) else {}
    highlight = resolve_highlight_fields(
        pack=pack, check=check, details=details, data=submission_data
    )
    enriched = dict(details or {})
    if highlight:
        enriched["highlightFields"] = highlight
    return DqaFlag(
        id=str(uuid.uuid4()),
        submission_id=current.id,
        project_id=current.project_id,
        rule_id=str(rule.get("id") or "unknown"),
        severity=str(rule.get("severity") or "amber").lower(),
        title=str(rule.get("title") or rule.get("id") or "Flag"),
        message=str(rule.get("message") or rule.get("title") or "Rule failed"),
        details=enriched,
        evaluated_at=_now(),
    )


def evaluate_submission(
    db: Session,
    submission: Submission,
    *,
    pack: dict[str, Any] | None = None,
    project_rows: list[Submission] | None = None,
    commit: bool = True,
    study_id: str | None = None,
    rel_map: dict | None = None,
    target_rows_cache: dict[str, list[Submission]] | None = None,
    target_pack_cache: dict[str, dict[str, Any]] | None = None,
) -> list[DqaFlag]:
    pack = pack or get_pack_for_project(db, submission.project_id)
    db.execute(delete(DqaFlag).where(DqaFlag.submission_id == submission.id))
    if not pack:
        if commit:
            db.commit()
        return []

    if study_id is None:
        project = db.get(Project, submission.project_id)
        study_id = project.study_id if project else None
    if study_id and rel_map is None:
        rel_map = load_study_relationships(db, study_id)
    target_rows_cache = target_rows_cache or {}
    target_pack_cache = target_pack_cache or {}

    data = submission.data if isinstance(submission.data, dict) else {}
    flags: list[DqaFlag] = []
    for rule in pack.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        check = rule.get("check")
        if check is None and rule.get("checks"):
            check = {"op": "all", "checks": rule["checks"]}
        related = (
            build_related_context(
                db,
                current=submission,
                source_pack=pack,
                check=check,
                study_id=study_id,
                relationships=rel_map,
                target_rows_cache=target_rows_cache,
                target_pack_cache=target_pack_cache,
            )
            if study_id
            else {}
        )
        flag = evaluate_rule(
            rule,
            data=data,
            pack=pack,
            project_rows=project_rows,
            current=submission,
            related=related,
            study_id=study_id,
        )
        if flag:
            flags.append(flag)
            db.add(flag)

    has_red = any(f.severity == "red" for f in flags)
    if has_red:
        submission.status = "flagged"
    elif submission.status == "flagged":
        submission.status = "validated"

    if commit:
        db.commit()
    return flags


def evaluate_project(db: Session, project_id: str) -> dict[str, int]:
    pack = get_pack_for_project(db, project_id)
    project = db.get(Project, project_id)
    study_id = project.study_id if project else None
    rel_map = load_study_relationships(db, study_id) if study_id else {}
    target_rows_cache: dict[str, list[Submission]] = {}
    target_pack_cache: dict[str, dict[str, Any]] = {}
    rows = list(
        db.scalars(
            select(Submission).where(Submission.project_id == project_id)
        ).all()
    )
    flagged_submissions = 0
    total_flags = 0
    for submission in rows:
        flags = evaluate_submission(
            db,
            submission,
            pack=pack,
            project_rows=rows,
            commit=False,
            study_id=study_id,
            rel_map=rel_map,
            target_rows_cache=target_rows_cache,
            target_pack_cache=target_pack_cache,
        )
        total_flags += len(flags)
        if flags:
            flagged_submissions += 1
    db.commit()
    return {
        "submissions": len(rows),
        "flagged_submissions": flagged_submissions,
        "flags": total_flags,
    }


def evaluate_project_cascade(db: Session, project_id: str) -> dict[str, Any]:
    """Recompute project and source projects that depend on it as a relationship target."""
    stats = evaluate_project(db, project_id)
    cascade_projects = [project_id]
    for source_id in source_projects_for_target(db, project_id):
        if source_id in cascade_projects:
            continue
        source_stats = evaluate_project(db, source_id)
        cascade_projects.append(source_id)
        for key in ("submissions", "flagged_submissions", "flags"):
            stats[key] = stats.get(key, 0) + source_stats.get(key, 0)
    stats["cascade_projects"] = cascade_projects
    return stats
