from __future__ import annotations

from app.schemas.common import CamelModel


class SmtpSettings(CamelModel):
    host: str
    port: int
    username: str
    password: str
    from_name: str
    from_email: str
    use_tls: bool
    connected: bool
    last_tested_at: str | None = None


class DailyReportSettings(CamelModel):
    enabled: bool
    send_time: str
    timezone: str
    recipients: list[str]
    last_sent_on: str | None = None


class GeneralSettings(CamelModel):
    organization_name: str
    timezone: str
    date_format: str
    language: str
    ai_enabled: bool
    ai_provider: str
    ai_api_key: str
    ai_base_url: str = "https://openrouter.ai/api/v1"
    ai_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    ai_compile_model: str = ""
    ai_report_planner_model: str = ""
    ai_temperature: float = 0.3
    ai_max_tokens: int = 2048
    ai_timeout_seconds: int = 60
    report_logo_url: str | None = None
    transcription_enabled: bool = False
    transcription_provider: str = "sarvam"
    transcription_api_key: str = ""
    transcription_base_url: str = "https://api.sarvam.ai"
    transcription_model: str = "saaras:v3"
    transcription_currency: str = "INR"
    transcription_rate_per_minute: float = 0.0


class SettingsOut(CamelModel):
    smtp: SmtpSettings
    daily_report: DailyReportSettings
    general: GeneralSettings
    active_study_id: str | None = None


class SettingsUpdate(CamelModel):
    smtp: SmtpSettings | None = None
    daily_report: DailyReportSettings | None = None
    general: GeneralSettings | None = None
    active_study_id: str | None = None


class ConnectionTestResult(CamelModel):
    success: bool
    message: str
    details: str | None = None
