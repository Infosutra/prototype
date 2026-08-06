from __future__ import annotations

from typing import Any

from app.schemas.common import CamelModel


class StudyFormMapEntry(CamelModel):
    tool_code: str | None = None
    project_uid: str
    label: str | None = None


class StudyProjectOut(CamelModel):
    id: str
    uid: str
    name: str
    tool_code: str | None = None
    submission_count: int = 0
    sync_status: str = "never"


class StudyOut(CamelModel):
    id: str
    name: str
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    timezone: str = "Asia/Kolkata"
    targets: dict[str, Any] = {}
    form_map: list[dict[str, Any]] = []
    day_number: int | None = None
    project_count: int = 0
    submission_count: int = 0
    projects: list[StudyProjectOut] = []
    created_at: str | None = None
    updated_at: str | None = None


class StudyCreate(CamelModel):
    name: str
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    timezone: str = "Asia/Kolkata"
    targets: dict[str, Any] = {}
    form_map: list[dict[str, Any]] = []


class StudyUpdate(CamelModel):
    name: str | None = None
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    timezone: str | None = None
    targets: dict[str, Any] | None = None
    form_map: list[dict[str, Any]] | None = None


class StudyAssignProject(CamelModel):
    project_id: str
    tool_code: str | None = None
