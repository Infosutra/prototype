from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.study import Study


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    format: Mapped[str] = mapped_column(String, nullable=False, default="pdf")
    # daily_dqa | final_dqa | custom
    report_type: Mapped[str] = mapped_column(String, nullable=False, default="custom")
    # Prefer NOT NULL on new writes; nullable kept so existing rows / draft creates do not break.
    study_id: Mapped[str | None] = mapped_column(
        ForeignKey("studies.id", ondelete="SET NULL"), nullable=True
    )
    report_date: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set when the report was produced by executing a template version.
    template_id: Mapped[str | None] = mapped_column(
        ForeignKey("report_templates.id", ondelete="SET NULL"), nullable=True
    )
    template_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("report_template_versions.id", ondelete="SET NULL"), nullable=True
    )
    # The exact specification and context this output was produced from.
    spec_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    execution_context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Path/key to ExecuteResult JSON file (canonical). No generated_content blob.
    result_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    download_url: Mapped[str | None] = mapped_column(String, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_kb: Mapped[float | None] = mapped_column(Float, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    report_projects: Mapped[list[ReportProject]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )

    @property
    def project_ids(self) -> list[str]:
        return [rp.project_id for rp in (self.report_projects or [])]

    @property
    def project_names(self) -> list[str]:
        return [
            rp.project_name or ""
            for rp in (self.report_projects or [])
        ]


class ReportProject(Base):
    """Association between a report and the projects it covered at generation time."""

    __tablename__ = "report_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    project_name: Mapped[str | None] = mapped_column(String, nullable=True)

    report: Mapped[Report] = relationship(back_populates="report_projects")

    __table_args__ = (
        UniqueConstraint("report_id", "project_id", name="report_projects_report_project_uidx"),
    )


class ReportTemplate(Base):
    """Reusable report definition: a natural-language prompt plus its specification.

    Daily and Final flows execute a template against different contexts rather than
    each hard-coding their own structure.
    """

    __tablename__ = "report_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    study_id: Mapped[str] = mapped_column(
        ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    # daily | final | adhoc — the context a template is designed to be executed in.
    report_kind: Mapped[str] = mapped_column(String, nullable=False, default="adhoc")
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    # Denormalized pointer to the version currently used by execution.
    current_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # When the prompt names a calendar day, preview/execute default to that ISO date.
    # Specs still use "today" sources; that day becomes the execution date.
    default_execution_date: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list[ReportTemplateVersion]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="ReportTemplateVersion.version",
    )

    __table_args__ = (
        Index("report_templates_study_idx", "study_id"),
        Index("report_templates_kind_idx", "report_kind"),
    )


class ReportTemplateVersion(Base):
    """Append-only version of a template. History is never overwritten."""

    __tablename__ = "report_template_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("report_templates.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # The human-readable definition the specification was generated from.
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The machine-readable definition used to execute and render.
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    spec_version: Mapped[str] = mapped_column(String, nullable=False, default="1.0")
    planner_model: Mapped[str | None] = mapped_column(String, nullable=True)
    planner_prompt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # template | conversation | seed — how this version came to exist.
    source: Mapped[str] = mapped_column(String, nullable=False, default="template")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    template: Mapped[ReportTemplate] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("template_id", "version", name="report_template_versions_uidx"),
        Index("report_template_versions_template_idx", "template_id"),
    )


class ReportConversation(Base):
    """A dynamic report-building session holding a working specification."""

    __tablename__ = "report_conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    study_id: Mapped[str] = mapped_column(
        ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False, default="Untitled report")
    working_spec_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # active | saved
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    saved_template_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[ReportConversationMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ReportConversationMessage.created_at",
    )

    __table_args__ = (Index("report_conversations_study_idx", "study_id"),)


class ReportConversationMessage(Base):
    """One conversation turn, with the specification snapshot it produced."""

    __tablename__ = "report_conversation_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("report_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    spec_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Ops the planner applied for this turn, for "what changed" explanations.
    changes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    conversation: Mapped[ReportConversation] = relationship(back_populates="messages")

    __table_args__ = (Index("report_conversation_messages_conv_idx", "conversation_id"),)


class ReportSchedule(Base):
    """Per-study scheduled report delivery."""

    __tablename__ = "report_schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    study_id: Mapped[str] = mapped_column(
        ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    report_type: Mapped[str] = mapped_column(String, nullable=False, default="daily_dqa")
    # Every schedule must point at an explicit user template.
    template_id: Mapped[str] = mapped_column(
        ForeignKey("report_templates.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    time: Mapped[str] = mapped_column(String, nullable=False, default="21:30")
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="Asia/Kolkata")
    recipients: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_sent_on: Mapped[str | None] = mapped_column(String, nullable=True)

    study: Mapped[Study] = relationship(back_populates="report_schedules")


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(String, nullable=False, default="summary")
    study_id: Mapped[str | None] = mapped_column(
        ForeignKey("studies.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    project_name: Mapped[str | None] = mapped_column(String, nullable=True)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="info")
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String, nullable=False, default="general")
    project_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
