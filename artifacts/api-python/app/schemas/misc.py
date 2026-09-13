from __future__ import annotations

from typing import Any

from app.schemas.common import CamelModel


class HealthStatus(CamelModel):
    status: str


class StatusCount(CamelModel):
    status: str
    count: int


class ProjectSummary(CamelModel):
    id: str
    name: str
    submission_count: int
    last_submission_at: str | None = None


class DashboardSummary(CamelModel):
    total_projects: int
    total_submissions: int
    submissions_this_month: int
    active_enumerators: int
    pending_reports: int
    last_sync_at: str | None = None
    submissions_by_status: list[StatusCount]
    top_projects: list[ProjectSummary]


class ActivityItem(CamelModel):
    id: str
    type: str
    message: str
    project_name: str | None = None
    timestamp: str
    icon: str | None = None


class EnumeratorStat(CamelModel):
    name: str
    count: int
    project_count: int | None = None


class ChartDataPoint(CamelModel):
    label: str
    value: float


class FieldDistribution(CamelModel):
    field: str
    type: str
    data: list[ChartDataPoint]


class AnalyticsOverview(CamelModel):
    total_submissions: int
    submissions_by_status: list[StatusCount]
    submissions_by_project: list[ChartDataPoint]
    enumerator_performance: list[EnumeratorStat]
    field_distributions: list[FieldDistribution] = []


class ProjectAnalytics(CamelModel):
    project_id: str
    project_name: str
    total_submissions: int
    submissions_by_status: list[StatusCount]
    enumerator_stats: list[EnumeratorStat]
    field_distributions: list[FieldDistribution] = []
    timeline: list[ChartDataPoint] = []


class TrendPoint(CamelModel):
    date: str
    submissions: int
    projects: int


class InsightOut(CamelModel):
    id: str
    title: str
    summary: str
    content: str
    type: str
    study_id: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    severity: str
    tags: list[str]
    created_at: str


class InsightInput(CamelModel):
    title: str
    summary: str = ""
    content: str = ""
    type: str = "summary"
    study_id: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    severity: str = "info"
    tags: list[str] = []


class InsightGenerateInput(CamelModel):
    question: str
    study_id: str
    project_id: str | None = None


class ReportScheduleOut(CamelModel):
    id: str
    study_id: str
    report_type: str
    template_id: str
    enabled: bool
    time: str
    timezone: str
    recipients: list[str]
    last_sent_on: str | None = None


class ReportScheduleUpdate(CamelModel):
    enabled: bool | None = None
    time: str | None = None
    timezone: str | None = None
    recipients: list[str] | None = None
    template_id: str | None = None


class PromptOut(CamelModel):
    id: str
    name: str
    description: str
    content: str
    category: str
    project_ids: list[str]
    study_ids: list[str] = []
    is_system: bool = False
    created_at: str
    updated_at: str


class PromptInput(CamelModel):
    name: str
    description: str = ""
    content: str = ""
    category: str = "general"
    project_ids: list[str] = []


class PromptUpdate(CamelModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    category: str | None = None
    project_ids: list[str] | None = None


class ReportOut(CamelModel):
    id: str
    title: str
    description: str
    status: str
    format: str
    report_type: str = "custom"
    study_id: str | None = None
    report_date: str | None = None
    prompt_id: str | None = None
    prompt_name: str | None = None
    project_ids: list[str]
    project_names: list[str]
    result_ref: str | None = None
    download_url: str | None = None
    page_count: int | None = None
    file_size_kb: float | None = None
    generated_at: str | None = None
    created_at: str


class ReportInput(CamelModel):
    title: str
    description: str = ""
    format: str = "pdf"
    report_type: str = "custom"
    study_id: str | None = None
    report_date: str | None = None
    prompt_id: str | None = None
    project_ids: list[str] = []


class GenerateReportInput(CamelModel):
    """Generate from a user-saved template (enqueue execute job)."""

    study_id: str
    template_id: str
    window: dict | None = None
    send_email: bool = False
    recipients: list[str] | None = None


class ShareReportInput(CamelModel):
    recipients: list[str]
    subject: str | None = None
    message: str | None = None
