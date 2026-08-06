from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.project import Project


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kobo_id: Mapped[str] = mapped_column(String, nullable=False)
    uuid: Mapped[str | None] = mapped_column(String, nullable=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
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
