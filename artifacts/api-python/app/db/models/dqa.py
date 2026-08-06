from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.study import Study


class RulePack(Base):
    __tablename__ = "rule_packs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    pack: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TriangulationView(Base):
    """Study-defined triangulation view (cross-form join or claim vs observation)."""

    __tablename__ = "triangulation_views"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    study_id: Mapped[str] = mapped_column(
        ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    study: Mapped[Study] = relationship(back_populates="triangulation_views")

    __table_args__ = (
        UniqueConstraint("study_id", "code", name="triangulation_views_study_code_uidx"),
        Index("triangulation_views_study_idx", "study_id"),
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
