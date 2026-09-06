from __future__ import annotations

from typing import Any

from app.schemas.common import CamelModel


class FormResponse(CamelModel):
    key: str
    label: str
    question_type: str
    value: Any


class SubmissionOut(CamelModel):
    id: str
    display_id: str
    project_id: str
    project_name: str
    form_id: str
    form_name: str
    enumerator: str
    status: str
    submitted_at: str
    location: str | None = None
    data: dict[str, Any]
    responses: list[FormResponse] = []
    attachment_count: int
    dqa_severity: str | None = None
    red_flags: int = 0
    amber_flags: int = 0


class SubmissionsPage(CamelModel):
    data: list[SubmissionOut]
    total: int
    page: int
    limit: int
    total_pages: int


class GridColumn(CamelModel):
    key: str
    code: str
    label: str
    type: str = ""
    filled: int = 0
    flagged: int = 0
    extra: bool = False


class GridFlagRef(CamelModel):
    id: str
    rule_id: str
    severity: str
    title: str
    message: str


class GridCell(CamelModel):
    value: str = ""
    severity: str | None = None
    flags: list[GridFlagRef] = []


class GridRow(CamelModel):
    submission_id: str
    display_id: str
    kobo_id: str | None = None
    enumerator: str = ""
    submitted_at: str = ""
    status: str = ""
    location: str | None = None
    severity: str | None = None
    red_flags: int = 0
    amber_flags: int = 0
    cells: dict[str, GridCell] = {}
    row_flags: list[GridFlagRef] = []


class SubmissionGrid(CamelModel):
    project_id: str
    project_name: str
    label_language: str | None = None
    columns: list[GridColumn]
    rows: list[GridRow]
    total: int
    page: int
    limit: int
    total_pages: int
