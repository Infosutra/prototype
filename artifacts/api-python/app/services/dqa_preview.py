"""Preview DQA rules against recent submissions without persisting flags."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.dqa_test import run_rule_test


def preview_rule(
    db: Session,
    project_id: str,
    rule: dict[str, Any],
    *,
    limit: int = 50,
) -> dict[str, Any]:
    result = run_rule_test(db, project_id, rule, limit=limit)
    return {
        "submissions_checked": result["submissions_checked"],
        "flag_count": result["flag_count"],
        "pass_count": result["pass_count"],
        "not_applicable_count": result["not_applicable_count"],
        "examples": [
            {
                "submission_id": row["submission_id"],
                "kobo_id": row.get("kobo_id"),
                "enumerator": row.get("enumerator"),
                "would_flag": row.get("would_flag"),
                "details": row.get("details") or {},
                "outcome": row.get("outcome"),
                "explanation": row.get("explanation"),
            }
            for row in result.get("examples") or []
        ],
        "warnings": result.get("warnings") or [],
    }
