from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base


class AppSettings(Base):
    """Install-wide settings (SMTP, AI, locale). Kobo lives on StudyCredential."""

    __tablename__ = "settings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default="singleton")

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

    organization_name: Mapped[str] = mapped_column(String, nullable=False, default="Infosutra")
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
    ai_compile_model: Mapped[str] = mapped_column(String, nullable=False, default="")
    ai_report_planner_model: Mapped[str] = mapped_column(String, nullable=False, default="")
    ai_temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    ai_max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    ai_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    report_logo_url: Mapped[str | None] = mapped_column(String, nullable=True)

    transcription_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transcription_provider: Mapped[str] = mapped_column(String, nullable=False, default="sarvam")
    transcription_api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    transcription_base_url: Mapped[str] = mapped_column(
        String, nullable=False, default="https://api.sarvam.ai"
    )
    transcription_model: Mapped[str] = mapped_column(String, nullable=False, default="saaras:v3")
    transcription_currency: Mapped[str] = mapped_column(String, nullable=False, default="INR")
    transcription_rate_per_minute: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
