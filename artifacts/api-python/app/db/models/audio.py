from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.study import Study


class AudioRecording(Base):
    """Study-scoped audio file with optional transcription."""

    __tablename__ = "audio_recordings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    study_id: Mapped[str] = mapped_column(
        ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    name_normalized: Mapped[str] = mapped_column(String, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    original_filename: Mapped[str] = mapped_column(String, nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String, nullable=False, default="")
    storage_folder: Mapped[str] = mapped_column(String, nullable=False, default="")
    storage_path: Mapped[str] = mapped_column(String, nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    transcription_status: Mapped[str] = mapped_column(String, nullable=False, default="none")
    transcription_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    transcription_language: Mapped[str | None] = mapped_column(String, nullable=True)
    transcription_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcription_job_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    study: Mapped[Study] = relationship(back_populates="audio_recordings")

    __table_args__ = (
        Index("audio_recordings_study_idx", "study_id"),
        Index("audio_recordings_status_idx", "transcription_status"),
        UniqueConstraint("study_id", "name_normalized", name="audio_recordings_study_name_uidx"),
    )


class UsageEvent(Base):
    """Install-wide usage ledger for transcription, LLM tokens, subscriptions, etc."""

    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    category: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False, default="")
    operation: Mapped[str] = mapped_column(String, nullable=False, default="")
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unit: Mapped[str] = mapped_column(String, nullable=False, default="")
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="INR")
    study_id: Mapped[str | None] = mapped_column(
        ForeignKey("studies.id", ondelete="SET NULL"), nullable=True
    )
    resource_type: Mapped[str | None] = mapped_column(String, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    __table_args__ = (
        Index("usage_events_category_idx", "category"),
        Index("usage_events_study_idx", "study_id"),
        Index("usage_events_occurred_idx", "occurred_at"),
    )
