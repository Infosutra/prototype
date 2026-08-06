"""DQA evaluation orchestration and flag persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import DqaFlag, Submission
from app.domain.dqa.eval import eval_check
from app.domain.dqa.highlights import resolve_highlight_fields
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
) -> DqaFlag | None:

    check = rule.get("check")
    if check is None and rule.get("checks"):
        check = {"op": "all", "checks": rule["checks"]}
    ok, details = eval_check(
        check, data=data, pack=pack, project_rows=project_rows, current=current
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
) -> list[DqaFlag]:
    pack = pack or get_pack_for_project(db, submission.project_id)
    db.execute(delete(DqaFlag).where(DqaFlag.submission_id == submission.id))
    if not pack:
        if commit:
            db.commit()
        return []

    data = submission.data if isinstance(submission.data, dict) else {}
    flags: list[DqaFlag] = []
    for rule in pack.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        flag = evaluate_rule(
            rule,
            data=data,
            pack=pack,
            project_rows=project_rows,
            current=submission,
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
