"""Wire schemas for report specifications, templates and conversations."""

from __future__ import annotations

from typing import Any

from app.schemas.common import CamelModel


class SpecCatalogComponentOut(CamelModel):
    type: str
    description: str = ""


class SpecCatalogSourceOut(CamelModel):
    id: str
    title: str
    kind: str = "entity"
    description: str = ""
    fields: list[str] = []


class SpecCatalogOut(CamelModel):
    spec_version: str
    component_types: list[str]
    components: list[SpecCatalogComponentOut]
    data_sources: list[SpecCatalogSourceOut]
    spec_schema: dict[str, Any] = {}


class SpecIssueOut(CamelModel):
    path: str
    code: str
    message: str


class ReportTemplateOut(CamelModel):
    id: str
    name: str
    description: str
    study_id: str | None = None
    report_kind: str
    status: str
    version_count: int = 0
    current_version: int = 0
    prompt_text: str = ""
    default_execution_date: str | None = None
    created_at: str
    updated_at: str


class ReportTemplateVersionOut(CamelModel):
    id: str
    template_id: str
    version: int
    prompt_text: str
    spec: dict[str, Any]
    spec_version: str
    planner_model: str | None = None
    source: str
    notes: str
    changes: list[str] = []
    created_at: str


class ReportTemplateDetailOut(ReportTemplateOut):
    spec: dict[str, Any] = {}
    versions: list[ReportTemplateVersionOut] = []


class CreateReportTemplateInput(CamelModel):
    name: str
    description: str = ""
    study_id: str | None = None
    report_kind: str = "adhoc"
    prompt: str = ""
    spec: dict[str, Any] | None = None


class UpdateReportTemplatePromptInput(CamelModel):
    prompt: str
    notes: str = ""
    commit: bool = True
    spec: dict[str, Any] | None = None


class ReportTemplateMetaInput(CamelModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class PlanFailureOut(CamelModel):
    status: str
    question: str | None = None
    reason: str | None = None
    errors: list[SpecIssueOut] = []


class TemplatePlanResultOut(CamelModel):
    status: str
    template: ReportTemplateDetailOut | None = None
    spec: dict[str, Any] | None = None
    summary: str | None = None
    question: str | None = None
    reason: str | None = None
    errors: list[SpecIssueOut] = []
    warnings: list[SpecIssueOut] = []


class ReportConversationMessageOut(CamelModel):
    id: str
    role: str
    content: str
    spec: dict[str, Any] | None = None
    changes: list[str] = []
    created_at: str


class ReportConversationOut(CamelModel):
    id: str
    study_id: str
    title: str
    status: str
    saved_template_id: str | None = None
    spec: dict[str, Any] | None = None
    messages: list[ReportConversationMessageOut] = []
    created_at: str
    updated_at: str


class CreateReportConversationInput(CamelModel):
    study_id: str | None = None
    title: str = "Untitled report"
    message: str = ""
    spec: dict[str, Any] | None = None
    unmapped: list[dict[str, Any]] | None = None
    judgement: dict[str, Any] | None = None


class UpdateReportConversationInput(CamelModel):
    title: str | None = None


class ReportConversationTurnInput(CamelModel):
    message: str
    spec: dict[str, Any] | None = None
    unmapped: list[dict[str, Any]] | None = None
    judgement: dict[str, Any] | None = None


class ReportConversationTurnOut(CamelModel):
    status: str
    conversation: ReportConversationOut
    summary: str | None = None
    answer: str | None = None
    question: str | None = None
    reason: str | None = None
    errors: list[SpecIssueOut] = []
    unmapped: list[dict[str, Any]] = []
    judgement: dict[str, Any] | None = None
    spec: dict[str, Any] | None = None


class SaveConversationAsTemplateInput(CamelModel):
    name: str
    description: str = ""
    report_kind: str = "adhoc"
