"""Typed submission projections for Query IR (writers land in Phase 1)."""

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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SubmissionAnswer(Base):
    """One typed answer cell projected from Submission.data."""

    __tablename__ = "submission_answers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    study_id: Mapped[str] = mapped_column(String, nullable=False)
    field_key: Mapped[str] = mapped_column(String, nullable=False)
    field_label: Mapped[str | None] = mapped_column(String, nullable=True)
    # string | number | boolean | datetime
    value_type: Mapped[str] = mapped_column(String, nullable=False)
    value_text: Mapped[str | None] = mapped_column(String, nullable=True)
    value_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_datetime: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "submission_id", "field_key", name="submission_answers_submission_field_uidx"
        ),
        Index("submission_answers_study_field_idx", "study_id", "field_key"),
        Index("submission_answers_study_submission_idx", "study_id", "submission_id"),
    )


class SubmissionQuality(Base):
    """Per-submission DQA quality rollup (is_clean iff zero flags)."""

    __tablename__ = "submission_quality"

    submission_id: Mapped[str] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True
    )
    study_id: Mapped[str] = mapped_column(String, nullable=False)
    project_id: Mapped[str] = mapped_column(String, nullable=False)
    is_clean: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # null | amber | red (red wins)
    max_severity: Mapped[str | None] = mapped_column(String, nullable=True)
    flag_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    red_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amber_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("submission_quality_study_idx", "study_id"),
    )
