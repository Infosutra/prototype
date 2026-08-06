from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import SecretError, decrypt_secret, encrypt_secret
from app.db.models import AppSettings, StudyCredential
from app.integrations.kobo import KoboApiError, KoboClient, normalize_kobo_server_url
from app.integrations.smtp import SmtpConfig, SmtpError, send_test_email, test_smtp_connection
from app.schemas.settings import (
    ConnectionTestResult,
    DailyReportSettings,
    GeneralSettings,
    SettingsOut,
    SettingsUpdate,
    SmtpSettings,
)
from app.schemas.studies import StudyCredentialSummary, StudyKoboUpdate


MASK = "••••••••"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _is_masked(value: str | None) -> bool:
    return bool(value and ("•" in value or "*" in value))


def get_or_create_settings(db: Session) -> AppSettings:
    row = db.get(AppSettings, "singleton")
    if row:
        return row
    row = AppSettings(id="singleton")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def to_settings_out(row: AppSettings) -> SettingsOut:
    return SettingsOut(
        smtp=SmtpSettings(
            host=row.smtp_host,
            port=row.smtp_port,
            username=row.smtp_username,
            password=MASK if row.smtp_password_encrypted else "",
            from_name=row.smtp_from_name,
            from_email=row.smtp_from_email,
            use_tls=row.smtp_use_tls,
            connected=row.smtp_connected,
            last_tested_at=_iso(row.smtp_last_tested_at),
        ),
        daily_report=DailyReportSettings(
            enabled=row.daily_report_enabled,
            send_time=row.daily_report_time or "21:00",
            timezone=row.daily_report_timezone or "Asia/Kolkata",
            recipients=list(row.daily_report_recipients or []),
            last_sent_on=row.daily_report_last_sent_on,
        ),
        general=GeneralSettings(
            organization_name=row.organization_name,
            timezone=row.timezone,
            date_format=row.date_format,
            language=row.language,
            ai_enabled=row.ai_enabled,
            ai_provider=row.ai_provider or "openrouter",
            ai_api_key=MASK if row.ai_api_key else "",
            ai_base_url=getattr(row, "ai_base_url", None) or "https://openrouter.ai/api/v1",
            ai_model=getattr(row, "ai_model", None)
            or "nvidia/nemotron-3-super-120b-a12b:free",
            ai_temperature=float(getattr(row, "ai_temperature", None) or 0.3),
            ai_max_tokens=int(getattr(row, "ai_max_tokens", None) or 2048),
            ai_timeout_seconds=int(getattr(row, "ai_timeout_seconds", None) or 60),
            report_logo_url=row.report_logo_url,
        ),
    )


def clear_undecryptable_secrets(db: Session) -> bool:
    """Drop ciphertext that no longer matches the active encryption key."""
    row = get_or_create_settings(db)
    changed = False
    if row.smtp_password_encrypted:
        try:
            decrypt_secret(row.smtp_password_encrypted)
        except SecretError:
            row.smtp_password_encrypted = ""
            row.smtp_connected = False
            changed = True

    for cred in db.scalars(select(StudyCredential)).all():
        if not cred.kobo_token_encrypted:
            continue
        try:
            decrypt_secret(cred.kobo_token_encrypted)
        except SecretError:
            cred.kobo_token_encrypted = ""
            cred.connected = False
            changed = True

    if changed:
        db.commit()
        db.refresh(row)
    return changed


def get_smtp_password(row: AppSettings) -> str:
    if not row.smtp_password_encrypted:
        return ""
    try:
        return decrypt_secret(row.smtp_password_encrypted)
    except SecretError as exc:
        raise ValueError(str(exc)) from exc


def smtp_config_from_row(row: AppSettings, password: str) -> SmtpConfig:
    return SmtpConfig(
        host=row.smtp_host,
        port=row.smtp_port,
        username=row.smtp_username,
        password=password,
        from_name=row.smtp_from_name,
        from_email=row.smtp_from_email,
        use_tls=row.smtp_use_tls,
    )


def update_settings(db: Session, payload: SettingsUpdate) -> SettingsOut:
    row = get_or_create_settings(db)

    if payload.smtp is not None:
        smtp = payload.smtp
        has_new_password = bool(smtp.password and not _is_masked(smtp.password))
        password = smtp.password.strip() if has_new_password else get_smtp_password(row)

        row.smtp_host = smtp.host.strip()
        row.smtp_port = smtp.port
        row.smtp_username = smtp.username.strip()
        row.smtp_from_name = smtp.from_name.strip()
        row.smtp_from_email = smtp.from_email.strip()
        row.smtp_use_tls = smtp.use_tls
        if has_new_password:
            row.smtp_password_encrypted = encrypt_secret(password)

        changed = has_new_password or not row.smtp_connected
        if changed:
            if not password:
                raise ValueError("An SMTP password / SMTP key is required to configure email")
            test_smtp_connection(smtp_config_from_row(row, password))
            row.smtp_connected = True
            row.smtp_last_tested_at = datetime.now(timezone.utc)

    if payload.daily_report is not None:
        daily = payload.daily_report
        row.daily_report_enabled = daily.enabled
        row.daily_report_time = daily.send_time.strip()
        row.daily_report_timezone = daily.timezone.strip() or "Asia/Kolkata"
        row.daily_report_recipients = list(daily.recipients or [])

    if payload.general is not None:
        general = payload.general
        row.organization_name = general.organization_name
        row.timezone = general.timezone
        row.date_format = general.date_format
        row.language = general.language
        row.ai_enabled = general.ai_enabled
        row.ai_provider = general.ai_provider or "openrouter"
        if general.ai_api_key and not _is_masked(general.ai_api_key):
            row.ai_api_key = general.ai_api_key
        row.ai_base_url = (general.ai_base_url or "https://openrouter.ai/api/v1").strip()
        row.ai_model = (
            general.ai_model or "nvidia/nemotron-3-super-120b-a12b:free"
        ).strip()
        row.ai_temperature = float(general.ai_temperature)
        row.ai_max_tokens = int(general.ai_max_tokens)
        row.ai_timeout_seconds = int(general.ai_timeout_seconds)
        row.report_logo_url = general.report_logo_url

    db.commit()
    db.refresh(row)
    return to_settings_out(row)


def test_smtp(db: Session) -> ConnectionTestResult:
    row = get_or_create_settings(db)
    password = get_smtp_password(row)
    if not row.smtp_host or not row.smtp_username or not password:
        return ConnectionTestResult(
            success=False,
            message="SMTP credentials not configured",
            details="Please enter your SMTP host, username, and SMTP key first.",
        )
    if not row.smtp_from_email:
        return ConnectionTestResult(
            success=False,
            message="From email not configured",
            details="Please enter a verified Brevo sender email first.",
        )
    try:
        config = smtp_config_from_row(row, password)
        test_smtp_connection(config)
        send_test_email(config)
        row.smtp_connected = True
        row.smtp_last_tested_at = datetime.now(timezone.utc)
        db.commit()
        return ConnectionTestResult(
            success=True,
            message="SMTP test email sent",
            details=f"A test email was sent to {row.smtp_from_email}.",
        )
    except SmtpError as exc:
        row.smtp_connected = False
        row.smtp_last_tested_at = datetime.now(timezone.utc)
        db.commit()
        return ConnectionTestResult(
            success=False,
            message="SMTP connection test failed",
            details=str(exc),
        )


def get_study_credential(db: Session, study_id: str) -> StudyCredential | None:
    return db.scalars(
        select(StudyCredential).where(StudyCredential.study_id == study_id)
    ).first()


def get_kobo_token_from_credential(cred: StudyCredential) -> str:
    if not cred.kobo_token_encrypted:
        return ""
    try:
        return decrypt_secret(cred.kobo_token_encrypted)
    except SecretError as exc:
        raise ValueError(str(exc)) from exc


def credential_to_summary(cred: StudyCredential) -> StudyCredentialSummary:
    return StudyCredentialSummary(
        connected=bool(cred.connected),
        server_url=cred.kobo_server_url or "https://kf.kobotoolbox.org",
        username=cred.kobo_username or "",
        api_token=MASK if cred.kobo_token_encrypted else "",
        last_tested_at=_iso(cred.last_tested_at),
    )


def update_study_kobo(
    db: Session,
    study_id: str,
    payload: StudyKoboUpdate,
) -> StudyCredentialSummary:
    from app.services import studies as studies_service

    study = studies_service.get_study(db, study_id)
    if not study:
        raise LookupError("Study not found")
    cred = study.credential
    if cred is None:
        cred = studies_service._ensure_credential(db, study)

    server_url = (
        normalize_kobo_server_url(payload.server_url)
        if payload.server_url is not None
        else cred.kobo_server_url
    )
    has_new_token = bool(payload.api_token and not _is_masked(payload.api_token))
    token = (
        payload.api_token.strip()
        if has_new_token
        else get_kobo_token_from_credential(cred)
    )

    if (payload.server_url is not None or has_new_token) and not token:
        raise ValueError("A Kobo API token is required to configure the connection")

    if payload.server_url is not None or has_new_token:
        KoboClient(server_url, token).test_connection()
        cred.kobo_server_url = server_url
        cred.connected = True
        cred.last_tested_at = datetime.now(timezone.utc)

    if has_new_token:
        cred.kobo_token_encrypted = encrypt_secret(token)
    if payload.username is not None:
        cred.kobo_username = payload.username

    db.commit()
    db.refresh(cred)
    return credential_to_summary(cred)


def test_study_kobo(db: Session, study_id: str) -> ConnectionTestResult:
    cred = get_study_credential(db, study_id)
    if not cred:
        return ConnectionTestResult(
            success=False,
            message="KoboToolbox credentials not configured",
            details="Please enter your server URL and API token for this study first.",
        )
    try:
        token = get_kobo_token_from_credential(cred)
    except ValueError as exc:
        return ConnectionTestResult(
            success=False,
            message="KoboToolbox credentials not configured",
            details=str(exc),
        )
    if not token or not cred.kobo_server_url:
        return ConnectionTestResult(
            success=False,
            message="KoboToolbox credentials not configured",
            details="Please enter your server URL and API token for this study first.",
        )
    try:
        KoboClient(cred.kobo_server_url, token).test_connection()
        cred.connected = True
        cred.last_tested_at = datetime.now(timezone.utc)
        db.commit()
        return ConnectionTestResult(
            success=True,
            message="Connection successful",
            details="KoboToolbox credentials are valid.",
        )
    except KoboApiError as exc:
        cred.connected = False
        cred.last_tested_at = datetime.now(timezone.utc)
        db.commit()
        return ConnectionTestResult(
            success=False, message="Connection test failed", details=str(exc)
        )
