from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
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
    study_id: Mapped[str | None] = mapped_column(
        ForeignKey("studies.id", ondelete="SET NULL"), nullable=True
    )
    report_date: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_name: Mapped[str | None] = mapped_column(String, nullable=True)
    generated_content: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class ReportSchedule(Base):
    """Per-study scheduled report delivery (replaces AppSettings.dqa_daily_*)."""

    __tablename__ = "report_schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    study_id: Mapped[str] = mapped_column(
        ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    report_type: Mapped[str] = mapped_column(String, nullable=False, default="daily_dqa")
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
