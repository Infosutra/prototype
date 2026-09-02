"""Preview DQA rules against recent submissions without persisting flags."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, Submission
from app.services.dqa_evaluation import evaluate_rule
from app.services.dqa_relationship_resolver import build_related_context, load_study_relationships
from app.services.dqa_rule_packs import get_pack_for_project


def preview_rule(
    db: Session,
    project_id: str,
    rule: dict[str, Any],
    *,
    limit: int = 50,
) -> dict[str, Any]:
    pack = get_pack_for_project(db, project_id) or {}
    project = db.get(Project, project_id)
    study_id = project.study_id if project else None
    rel_map = load_study_relationships(db, study_id) if study_id else {}
    target_rows_cache: dict[str, list[Submission]] = {}
    target_pack_cache: dict[str, dict[str, Any]] = {}
    limit = max(1, min(int(limit or 50), 200))
    all_rows = list(
        db.scalars(select(Submission).where(Submission.project_id == project_id)).all()
    )
    submissions = sorted(
        all_rows,
        key=lambda row: row.submitted_at or row.id,
        reverse=True,
    )[:limit]

    check = rule.get("check")
    if check is None and rule.get("checks"):
        check = {"op": "all", "checks": rule["checks"]}

    flag_count = 0
    pass_count = 0
    not_applicable_count = 0
    examples: list[dict[str, Any]] = []
    flagged_examples = 0
    passing_examples = 0

    for submission in submissions:
        data = submission.data if isinstance(submission.data, dict) else {}
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
            project_rows=all_rows,
            current=submission,
            related=related,
            study_id=study_id,
        )
        would_flag = flag is not None
        if would_flag:
            flag_count += 1
        else:
            pass_count += 1
            if isinstance(check, dict) and check.get("op") == "if_then":
                not_applicable_count += 1

        if would_flag and flagged_examples < 5:
            examples.append(_example_row(submission, would_flag=True, details=flag.details if flag else {}))
            flagged_examples += 1
        elif not would_flag and passing_examples < 2:
            examples.append(_example_row(submission, would_flag=False, details={}))
            passing_examples += 1

    return {
        "submissions_checked": len(submissions),
        "flag_count": flag_count,
        "pass_count": pass_count,
        "not_applicable_count": not_applicable_count,
        "examples": examples,
    }


def _example_row(submission: Submission, *, would_flag: bool, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "submission_id": submission.id,
        "kobo_id": submission.kobo_id,
        "enumerator": submission.enumerator,
        "would_flag": would_flag,
        "details": details or {},
    }
