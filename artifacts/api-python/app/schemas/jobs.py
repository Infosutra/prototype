"""Wire schemas for the jobs API."""

from __future__ import annotations

from typing import Any

from app.schemas.common import CamelModel


class JobCreate(CamelModel):
    type: str
    study_id: str | None = None
    payload: dict[str, Any] | None = None


class JobCreated(CamelModel):
    job_id: str


class JobStatusOut(CamelModel):
    job_id: str
    type: str
    status: str
    study_id: str | None = None
    result: Any | None = None
    error: str | None = None
