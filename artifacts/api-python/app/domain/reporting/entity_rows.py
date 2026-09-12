"""Flatten ORM report inputs into submission/flag entity-row dicts."""

from __future__ import annotations

from typing import Any

from app.domain.reporting.aggregate import with_derived_columns
from app.domain.reporting.helpers import duration_minutes, local_calendar_day


def build_submission_entity_rows(
    projects: list[Any], submissions: list[Any]
) -> list[dict[str, Any]]:
    project_by_id = {p.id: p for p in projects}
    rows: list[dict[str, Any]] = []
    for sub in submissions:
        project = project_by_id.get(sub.project_id)
        if project is None:
            continue
        tool = (project.tool_code or "—").upper()
        name = (sub.enumerator or "Unknown").strip() or "Unknown"
        rows.append(
            {
                "enumerator": name,
                "toolCode": tool,
                "projectId": sub.project_id,
                "submissionId": sub.id,
                "durationMinutes": duration_minutes(sub),
                # Window filter clock; used to derive sparse `day` buckets.
                "submitted_at": sub.submitted_at,
            }
        )
    return rows


def build_flag_entity_rows(
    projects: list[Any],
    submissions: list[Any],
    flags: list[Any],
) -> list[dict[str, Any]]:
    project_by_id = {p.id: p for p in projects}
    subs_by_id = {s.id: s for s in submissions}
    rows: list[dict[str, Any]] = []
    for flag in flags:
        project = project_by_id.get(flag.project_id)
        tool = ((project.tool_code if project else None) or "—").upper()
        sub = subs_by_id.get(flag.submission_id)
        name = (
            ((sub.enumerator or "Unknown").strip() or "Unknown") if sub else "Unknown"
        )
        rows.append(
            {
                "enumerator": name,
                "toolCode": tool if tool != "—" else "—",
                "projectId": flag.project_id,
                "severity": flag.severity,
                "ruleId": flag.rule_id,
                "title": flag.title,
                "message": flag.message,
                "submissionId": flag.submission_id,
                # Same clock as load_study_report_inputs windowing — never evaluated_at.
                "submitted_at": sub.submitted_at if sub is not None else None,
            }
        )
    return rows


def derive_entity_day_column(
    rows: list[dict[str, Any]], *, tz_name: str
) -> list[dict[str, Any]]:
    """Attach study-timezone ``day`` from each row's ``submitted_at``."""
    return with_derived_columns(
        rows,
        {"day": lambda r, tz=tz_name: local_calendar_day(r.get("submitted_at"), tz)},
    )
