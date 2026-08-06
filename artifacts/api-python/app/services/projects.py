from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.models import Project
from app.services.form_labels import get_form_translations, resolve_label_language


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def project_to_dict(project: Project) -> dict[str, Any]:
    form_definition = project.form_definition if isinstance(project.form_definition, dict) else None
    available = get_form_translations(form_definition)
    label_language = (
        resolve_label_language(project.label_language, form_definition)
        or project.label_language
        or "English"
    )
    study_name = None
    if project.study_id and getattr(project, "study", None) is not None:
        study_name = project.study.name
    return {
        "id": project.id,
        "uid": project.uid,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "submission_count": project.submission_count,
        "form_count": project.form_count,
        "enumerator_count": project.enumerator_count,
        "question_count": project.question_count,
        "owner": project.owner,
        "last_edited_by": project.last_edited_by,
        "last_modified_at": _iso(project.kobo_date_modified),
        "last_submission_at": _iso(project.last_submission_at),
        "last_sync_at": _iso(project.last_sync_at),
        "created_at": _iso(project.created_at) or datetime.now(timezone.utc).isoformat(),
        "deployed_at": _iso(project.deployed_at),
        "form_version_id": project.form_version_id,
        "deployed_version_id": project.deployed_version_id,
        "current_version_number": project.current_version_number,
        "deployed_version_number": project.deployed_version_number,
        "sync_status": project.sync_status,
        "sync_error": project.sync_error,
        "sector": project.sector,
        "country": project.country,
        "label_language": label_language,
        "available_label_languages": available or ["English", "Hindi"],
        "study_id": project.study_id,
        "study_tool_id": project.study_tool_id,
        "tool_code": project.tool_code,
        "study_name": study_name,
    }
