"""Related-submission helpers for uniqueness / sample-cap flags."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.dqa.values import _as_str, get_value


def _iso_naive(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _related_submission_ref(row: Any) -> dict[str, Any]:
    return {
        "submissionId": row.id,
        "koboId": row.kobo_id,
        "enumerator": row.enumerator,
        "submittedAt": _iso_naive(row.submitted_at),
        "projectName": row.project.name if row.project is not None else row.form_name,
    }


def find_related_submissions(
    *,
    pack: dict[str, Any],
    field_ref: str | None,
    value: str,
    project_rows: list[Any],
) -> list[dict[str, Any]]:

    if not field_ref or not value:
        return []
    related: list[dict[str, Any]] = []
    for row in project_rows:
        row_data = row.data if isinstance(row.data, dict) else {}
        other = _as_str(get_value(row_data, pack, field_ref))
        if other == value:
            related.append(_related_submission_ref(row))
    return related


def enrich_flag_related_submissions(
    *,
    pack: dict[str, Any] | None,
    rule: dict[str, Any] | None,
    details: dict[str, Any] | None,
    project_rows: list[Any],
) -> list[dict[str, Any]]:

    """Resolve sibling submissions for uniqueness / sample-cap flags."""
    if not isinstance(details, dict):
        return []
    existing = details.get("relatedSubmissions")
    if isinstance(existing, list) and existing:
        return [item for item in existing if isinstance(item, dict)]
    if not pack:
        return []
    op = str(details.get("op") or "")
    value = _as_str(details.get("value"))
    if not value or op not in {"unique_in_project", "group_count_lte"}:
        check = (rule or {}).get("check") if rule else None
        if isinstance(check, dict) and check.get("op") in {"unique_in_project", "group_count_lte"}:
            op = str(check.get("op"))
            field_ref = check.get("field")
            if not value:
                return []
            return find_related_submissions(
                pack=pack, field_ref=field_ref, value=value, project_rows=project_rows
            )
        return []
    field_ref = None
    if rule:
        check = rule.get("check")
        if isinstance(check, dict):
            field_ref = check.get("field")
    if not field_ref:
        return []
    return find_related_submissions(
        pack=pack, field_ref=field_ref, value=value, project_rows=project_rows
    )