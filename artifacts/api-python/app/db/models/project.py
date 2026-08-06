from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.study import Study, StudyTool
    from app.db.models.submission import Submission


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
    study_tool_id: Mapped[str | None] = mapped_column(
        ForeignKey("study_tools.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    study: Mapped[Study | None] = relationship(back_populates="projects")
    study_tool: Mapped[StudyTool | None] = relationship(back_populates="projects")
    submissions: Mapped[list[Submission]] = relationship(back_populates="project")

    @property
    def tool_code(self) -> str | None:
        """Backwards-compat: derive tool code from the linked StudyTool."""
        if self.study_tool is not None:
            return self.study_tool.code
        return None

    __table_args__ = (
        Index("projects_status_idx", "status"),
        Index("projects_last_sync_idx", "last_sync_at"),
        Index("projects_study_idx", "study_id"),
        Index("projects_study_tool_idx", "study_tool_id"),
    )
