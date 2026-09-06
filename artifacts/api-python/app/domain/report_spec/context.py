"""Execution context: WHEN and FOR WHAT DATA a specification is executed.

A specification is reusable precisely because it holds no concrete date. The Daily
flow supplies today in the study timezone; the Final flow supplies the close-out
range. Same template, different context.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.report_spec.base import SpecModel

ReportKind = Literal["daily", "final", "adhoc"]

# Semantic date tokens a spec may reference. Literal dates are rejected by validation.
DATE_TOKENS: frozenset[str] = frozenset({"execution_date", "study_to_date", "date_range"})


class ReportExecutionContext(SpecModel):
    report_kind: ReportKind = "adhoc"
    study_id: str
    # ISO YYYY-MM-DD in the study timezone; the business day the report describes.
    execution_date: str
    timezone: str = "Asia/Kolkata"
    # Inclusive range for cumulative/final scopes; defaults to study start .. execution_date.
    date_from: str | None = None
    date_to: str | None = None
    project_ids: list[str] = Field(default_factory=list)

    @property
    def effective_date_to(self) -> str:
        return self.date_to or self.execution_date
