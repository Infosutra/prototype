from __future__ import annotations

from app.schemas.common import CamelModel


class StudyToolOut(CamelModel):
    id: str
    code: str
    label: str = ""
    target_count: int = 0
    sort_order: int = 0


class StudyToolIn(CamelModel):
    code: str
    label: str = ""
    target_count: int = 0
    sort_order: int = 0
    id: str | None = None


class StudyCredentialSummary(CamelModel):
    connected: bool = False
    server_url: str = "https://kf.kobotoolbox.org"
    username: str = ""
    api_token: str = ""
    last_tested_at: str | None = None


class StudyKoboUpdate(CamelModel):
    server_url: str | None = None
    api_token: str | None = None
    username: str | None = None


class StudyProjectOut(CamelModel):
    id: str
    uid: str
    name: str
    tool_code: str | None = None
    study_tool_id: str | None = None
    submission_count: int = 0
    sync_status: str = "never"


class StudyOut(CamelModel):
    id: str
    name: str
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    timezone: str = "Asia/Kolkata"
    tools: list[StudyToolOut] = []
    credential: StudyCredentialSummary | None = None
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
    tools: list[StudyToolIn] = []


class StudyUpdate(CamelModel):
    name: str | None = None
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    timezone: str | None = None
    tools: list[StudyToolIn] | None = None


class StudyAssignProject(CamelModel):
    project_id: str
    tool_code: str | None = None
    study_tool_id: str | None = None
