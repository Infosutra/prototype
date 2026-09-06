"""Wire schemas for report specifications, templates and conversations."""

from __future__ import annotations

from typing import Any

from app.domain.report_spec.catalog import ComponentDescriptor, DataSourceDescriptor
from app.schemas.common import CamelModel
from app.schemas.misc import ReportOut


class SpecCatalogOut(CamelModel):
    spec_version: str
    component_types: list[str]
    components: list[ComponentDescriptor]
    data_sources: list[DataSourceDescriptor]
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
    is_system: bool = False
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
    #: Natural-language definition. The planner turns it into a specification.
    prompt: str = ""
    #: Supply a specification directly to skip planning (used by tests and imports).
    spec: dict[str, Any] | None = None


class UpdateReportTemplatePromptInput(CamelModel):
    prompt: str
    notes: str = ""


class ReportTemplateMetaInput(CamelModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class ExecuteTemplateInput(CamelModel):
    study_id: str | None = None
    #: Overrides the resolved reporting day. Omit for "today" in the study timezone.
    execution_date: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    report_kind: str | None = None
    run_ai: bool = True
    version: int | None = None


class PlanFailureOut(CamelModel):
    status: str
    question: str | None = None
    reason: str | None = None
    errors: list[SpecIssueOut] = []


class TemplatePlanResultOut(CamelModel):
    """Result of planning: either a saved template or something the user must resolve."""

    status: str
    template: ReportTemplateDetailOut | None = None
    summary: str | None = None
    question: str | None = None
    reason: str | None = None
    errors: list[SpecIssueOut] = []
    warnings: list[SpecIssueOut] = []


class ExecutedReportOut(CamelModel):
    """Rendered preview: specification, resolved data and HTML, without persisting."""

    template_id: str | None = None
    template_version: int | None = None
    spec: dict[str, Any]
    data: dict[str, Any]
    narratives: dict[str, str] = {}
    unavailable: dict[str, str] = {}
    meta: dict[str, Any] = {}
    html: str
    plain_text: str
    ai_source: str = "none"


class ExecuteTemplateResultOut(CamelModel):
    """Persisted report plus the same rendered payload Preview returns."""

    report: ReportOut
    preview: ExecutedReportOut


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
    #: Optional opening request; when present the planner runs immediately.
    message: str = ""


class ReportConversationTurnInput(CamelModel):
    message: str


class ReportConversationTurnOut(CamelModel):
    status: str
    conversation: ReportConversationOut
    summary: str | None = None
    answer: str | None = None
    question: str | None = None
    reason: str | None = None
    errors: list[SpecIssueOut] = []


class SaveConversationAsTemplateInput(CamelModel):
    name: str
    description: str = ""
    report_kind: str = "adhoc"
