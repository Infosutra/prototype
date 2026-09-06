from __future__ import annotations

from app.schemas.common import CamelModel


class ProjectOut(CamelModel):
    id: str
    uid: str
    name: str
    description: str | None = None
    status: str
    submission_count: int
    form_count: int
    enumerator_count: int
    question_count: int
    owner: str | None = None
    last_edited_by: str | None = None
    last_modified_at: str | None = None
    last_submission_at: str | None = None
    last_sync_at: str | None = None
    created_at: str
    deployed_at: str | None = None
    form_version_id: str | None = None
    deployed_version_id: str | None = None
    current_version_number: int | None = None
    deployed_version_number: int | None = None
    sync_status: str
    sync_error: str | None = None
    sector: str | None = None
    country: str | None = None
    label_language: str
    available_label_languages: list[str]
    study_id: str | None = None
    study_tool_id: str | None = None
    tool_code: str | None = None
    study_name: str | None = None


class ProjectUpdate(CamelModel):
    label_language: str | None = None
    study_id: str | None = None
    study_tool_id: str | None = None
    tool_code: str | None = None


class SyncResult(CamelModel):
    success: bool
    projects_synced: int
    submissions_fetched: int
    new_submissions: int
    deleted_submissions: int = 0
    synced_at: str
    errors: list[str]
