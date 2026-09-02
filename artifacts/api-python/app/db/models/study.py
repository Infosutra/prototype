from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.audio import AudioRecording
    from app.db.models.dqa import TriangulationView
    from app.db.models.project import Project
    from app.db.models.reporting import ReportSchedule


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
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    projects: Mapped[list[Project]] = relationship(back_populates="study")
    credential: Mapped[StudyCredential | None] = relationship(
        back_populates="study", uselist=False, cascade="all, delete-orphan"
    )
    tools: Mapped[list[StudyTool]] = relationship(
        back_populates="study",
        cascade="all, delete-orphan",
        order_by="StudyTool.sort_order",
    )
    report_schedules: Mapped[list[ReportSchedule]] = relationship(
        back_populates="study", cascade="all, delete-orphan"
    )
    triangulation_views: Mapped[list[TriangulationView]] = relationship(
        back_populates="study", cascade="all, delete-orphan"
    )
    audio_recordings: Mapped[list[AudioRecording]] = relationship(
        back_populates="study", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("studies_name_idx", "name"),)


class StudyCredential(Base):
    """One Kobo account per study."""

    __tablename__ = "study_credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    study_id: Mapped[str] = mapped_column(
        ForeignKey("studies.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    kobo_server_url: Mapped[str] = mapped_column(
        String, nullable=False, default="https://kf.kobotoolbox.org"
    )
    kobo_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kobo_username: Mapped[str] = mapped_column(String, nullable=False, default="")
    connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    study: Mapped[Study] = relationship(back_populates="credential")


class StudyTool(Base):
    """Study-defined tool codes (e.g. T1/T2/T3) with optional coverage counts."""

    __tablename__ = "study_tools"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    study_id: Mapped[str] = mapped_column(
        ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False, default="")
    target_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    study: Mapped[Study] = relationship(back_populates="tools")
    projects: Mapped[list[Project]] = relationship(back_populates="study_tool")

    __table_args__ = (
        UniqueConstraint("study_id", "code", name="study_tools_study_code_uidx"),
        Index("study_tools_study_idx", "study_id"),
    )
