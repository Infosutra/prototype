from __future__ import annotations

from app.schemas.common import CamelModel


class KoboSettings(CamelModel):
    server_url: str
    api_token: str
    username: str
    auto_sync: bool
    sync_interval_hours: int
    connected: bool
    last_tested_at: str | None = None


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


class DqaDailySettings(CamelModel):
    """Separate from the submission daily digest — DQA Daily HTML+PDF email."""

    enabled: bool = False
    send_time: str = "21:30"
    timezone: str = "Asia/Kolkata"
    recipients: list[str] = []
    last_sent_on: str | None = None
    study_id: str | None = None


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
    ai_temperature: float = 0.3
    ai_max_tokens: int = 2048
    ai_timeout_seconds: int = 60
    report_logo_url: str | None = None


class SettingsOut(CamelModel):
    kobo: KoboSettings
    smtp: SmtpSettings
    daily_report: DailyReportSettings
    dqa_daily: DqaDailySettings
    general: GeneralSettings


class SettingsUpdate(CamelModel):
    kobo: KoboSettings | None = None
    smtp: SmtpSettings | None = None
    daily_report: DailyReportSettings | None = None
    dqa_daily: DqaDailySettings | None = None
    general: GeneralSettings | None = None


class ConnectionTestResult(CamelModel):
    success: bool
    message: str
    details: str | None = None
