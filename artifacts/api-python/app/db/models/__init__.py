from __future__ import annotations

from datetime import datetime

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


class Study(Base):
    """A field study that groups one or more Kobo forms (projects)."""

    __tablename__ = "studies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ISO date strings YYYY-MM-DD; end_date null = ongoing
    start_date: Mapped[str | None] = mapped_column(String, nullable=True)
    end_date: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="Asia/Kolkata")
    # { "T1": 440, "T2": 960, "T3": 880 } — planned submission counts by tool
    targets: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # [{ "toolCode": "T1", "projectUid": "...", "label": "Facility" }, ...]
    form_map: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    projects: Mapped[list["Project"]] = relationship(back_populates="study")

    __table_args__ = (Index("studies_name_idx", "name"),)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    uid: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    asset_type: Mapped[str] = mapped_column(String, nullable=False, default="survey")
    submission_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    form_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enumerator_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    last_edited_by: Mapped[str | None] = mapped_column(String, nullable=True)
    current_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deployed_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    form_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    deployed_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    form_definition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_submission_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    kobo_date_modified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_watermark: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_status: Mapped[str] = mapped_column(String, nullable=False, default="never")
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    label_language: Mapped[str] = mapped_column(String, nullable=False, default="English")
    study_id: Mapped[str | None] = mapped_column(
        ForeignKey("studies.id", ondelete="SET NULL"), nullable=True
    )
    # Role within a study: T1, T2, T3, …
    tool_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    study: Mapped[Study | None] = relationship(back_populates="projects")
    submissions: Mapped[list[Submission]] = relationship(back_populates="project")

    __table_args__ = (
        Index("projects_status_idx", "status"),
        Index("projects_last_sync_idx", "last_sync_at"),
        Index("projects_study_idx", "study_id"),
    )


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kobo_id: Mapped[str] = mapped_column(String, nullable=False)
    uuid: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    project_name: Mapped[str] = mapped_column(String, nullable=False)
    form_id: Mapped[str] = mapped_column(String, nullable=False)
    form_name: Mapped[str] = mapped_column(String, nullable=False)
    enumerator: Mapped[str] = mapped_column(String, nullable=False, default="Unknown")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="submissions")

    __table_args__ = (
        UniqueConstraint("project_id", "kobo_id", name="submissions_project_kobo_id_uidx"),
        Index("submissions_project_idx", "project_id"),
        Index("submissions_submitted_at_idx", "submitted_at"),
    )


class AppSettings(Base):
    __tablename__ = "settings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default="singleton")
    kobo_server_url: Mapped[str] = mapped_column(String, nullable=False, default="https://kf.kobotoolbox.org")
    kobo_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kobo_username: Mapped[str] = mapped_column(String, nullable=False, default="")
    kobo_auto_sync: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kobo_sync_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    kobo_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kobo_last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    smtp_host: Mapped[str] = mapped_column(String, nullable=False, default="smtp-relay.brevo.com")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    smtp_username: Mapped[str] = mapped_column(String, nullable=False, default="")
    smtp_password_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    smtp_from_name: Mapped[str] = mapped_column(String, nullable=False, default="Infosutra")
    smtp_from_email: Mapped[str] = mapped_column(String, nullable=False, default="")
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    smtp_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    smtp_last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    daily_report_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    daily_report_time: Mapped[str] = mapped_column(String, nullable=False, default="21:00")
    daily_report_timezone: Mapped[str] = mapped_column(String, nullable=False, default="Asia/Kolkata")
    daily_report_recipients: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    daily_report_last_sent_on: Mapped[str | None] = mapped_column(String, nullable=True)

    organization_name: Mapped[str] = mapped_column(String, nullable=False, default="Sight Savers 2026")
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="UTC")
    date_format: Mapped[str] = mapped_column(String, nullable=False, default="YYYY-MM-DD")
    language: Mapped[str] = mapped_column(String, nullable=False, default="en")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_provider: Mapped[str] = mapped_column(String, nullable=False, default="openrouter")
    ai_api_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    ai_base_url: Mapped[str] = mapped_column(
        String, nullable=False, default="https://openrouter.ai/api/v1"
    )
    ai_model: Mapped[str] = mapped_column(
        String, nullable=False, default="nvidia/nemotron-3-super-120b-a12b:free"
    )
    ai_temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    ai_max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    ai_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    report_logo_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Separate from submission daily digest — DQA Daily email (HTML + PDF).
    dqa_daily_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dqa_daily_time: Mapped[str] = mapped_column(String, nullable=False, default="21:30")
    dqa_daily_timezone: Mapped[str] = mapped_column(String, nullable=False, default="Asia/Kolkata")
    dqa_daily_recipients: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    dqa_daily_last_sent_on: Mapped[str | None] = mapped_column(String, nullable=True)
    dqa_daily_study_id: Mapped[str | None] = mapped_column(String, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(String, nullable=False, default="summary")
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


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    format: Mapped[str] = mapped_column(String, nullable=False, default="pdf")
    # daily_dqa | final_dqa | custom
    report_type: Mapped[str] = mapped_column(String, nullable=False, default="custom")
    study_id: Mapped[str | None] = mapped_column(
        ForeignKey("studies.id", ondelete="SET NULL"), nullable=True
    )
    report_date: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_name: Mapped[str | None] = mapped_column(String, nullable=True)
    project_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    project_names: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    generated_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_url: Mapped[str | None] = mapped_column(String, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_kb: Mapped[float | None] = mapped_column(Float, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class RulePack(Base):
    __tablename__ = "rule_packs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    pack: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DqaFlag(Base):
    __tablename__ = "dqa_flags"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="amber")
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("dqa_flags_project_idx", "project_id"),
        Index("dqa_flags_submission_idx", "submission_id"),
        Index("dqa_flags_severity_idx", "severity"),
        UniqueConstraint("submission_id", "rule_id", name="dqa_flags_submission_rule_uidx"),
    )
