"""Schedule tick + email delivery for user-authored report templates.

Schedules require ``template_id``. Send-now / schedule enqueue ``execute`` then
``email`` jobs (PDF + recipients). No legacy Daily/Final generators.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Report, ReportSchedule, ReportTemplate, Study
from app.domain.reporting.helpers import today_in_tz
from app.integrations.smtp import SmtpError, send_email
from app.services.jobs import store as job_store
from app.services.kobo_sync import sync_all_projects
from app.services.report_storage import pdf_path_for
from app.services.settings import (
    get_or_create_settings,
    get_smtp_password,
    smtp_config_from_row,
)

logger = structlog.stdlib.get_logger(__name__)


def parse_send_time(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", value.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def send_report_email(
    db: Session,
    report: Report,
    *,
    recipients: list[str] | None = None,
) -> tuple[Report, list[str]]:
    settings = get_or_create_settings(db)
    to = [e.strip() for e in (recipients or []) if e and e.strip()]
    if not to:
        raise SmtpError("No email recipients configured")

    password = get_smtp_password(settings)
    if not password:
        raise SmtpError("SMTP password is not configured")

    payload: dict[str, Any] = {}
    if report.result_ref:
        try:
            from app.services.jobs import artifacts as job_artifacts

            loaded = job_artifacts.read_job_result(report.result_ref)
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}

    html_body = payload.get("html") or f"<p>{html.escape(report.title)}</p>"
    plain = payload.get("plainText") or report.title
    pdf_file = pdf_path_for(report.id)
    attachments = []
    if pdf_file.is_file():
        attachments.append(
            (
                f"{report.title.replace(' ', '_')[:80]}.pdf",
                pdf_file.read_bytes(),
                "application/pdf",
            )
        )

    send_email(
        smtp_config_from_row(settings, password),
        to=to,
        subject=report.title,
        text=plain,
        html=html_body,
        attachments=attachments,
    )
    return report, to


def enqueue_execute_then_email(
    db: Session,
    *,
    study_id: str,
    template_id: str,
    recipients: list[str],
    window: dict[str, Any] | None = None,
    title: str | None = None,
) -> str:
    """Enqueue an execute job that chains an email job on success. Returns jobId."""
    template = db.get(ReportTemplate, template_id)
    if template is None:
        raise ValueError(f"Template not found: {template_id}")
    if template.study_id and template.study_id != study_id:
        raise ValueError("Template does not belong to this study")
    study = db.get(Study, study_id)
    if study is None:
        raise ValueError(f"Study not found: {study_id}")

    to = [e.strip() for e in recipients if e and e.strip()]
    if not to:
        raise ValueError("At least one recipient is required to email a report")

    if window is None:
        tz = (study.timezone or "UTC").strip() or "UTC"
        window = {
            "preset": "execution_date",
            "executionDate": today_in_tz(tz),
        }

    payload: dict[str, Any] = {
        "templateId": template_id,
        "window": window,
        "emailRecipients": to,
    }
    if title:
        payload["title"] = title

    job = job_store.enqueue(
        db,
        job_type="execute",
        payload=payload,
        study_id=study_id,
    )
    return job.id


def enqueue_execute(
    db: Session,
    *,
    study_id: str,
    template_id: str,
    window: dict[str, Any] | None = None,
    title: str | None = None,
    email_recipients: list[str] | None = None,
) -> str:
    """Enqueue execute for a user-saved template. Optional email chain."""
    template = db.get(ReportTemplate, template_id)
    if template is None:
        raise ValueError(f"Template not found: {template_id}")
    if template.study_id and template.study_id != study_id:
        raise ValueError("Template does not belong to this study")
    study = db.get(Study, study_id)
    if study is None:
        raise ValueError(f"Study not found: {study_id}")

    if window is None:
        tz = (study.timezone or "UTC").strip() or "UTC"
        window = {
            "preset": "execution_date",
            "executionDate": today_in_tz(tz),
        }

    payload: dict[str, Any] = {
        "templateId": template_id,
        "window": window,
    }
    if title:
        payload["title"] = title
    if email_recipients:
        payload["emailRecipients"] = [
            e.strip() for e in email_recipients if e and e.strip()
        ]

    job = job_store.enqueue(
        db,
        job_type="execute",
        payload=payload,
        study_id=study_id,
    )
    return job.id


def maybe_send_scheduled_reports(db: Session) -> bool:
    """Scheduler tick: enqueue execute+email for due schedules with template_id."""
    enqueued_any = False
    schedules = list(
        db.scalars(select(ReportSchedule).where(ReportSchedule.enabled.is_(True))).all()
    )
    for schedule in schedules:
        if not schedule.template_id:
            logger.warning(
                "scheduled_report_skipped_no_template",
                study_id=schedule.study_id,
                schedule_id=schedule.id,
            )
            continue
        parsed = parse_send_time(schedule.time or "21:30")
        if not parsed:
            continue
        hour, minute = parsed
        tz_name = schedule.timezone or "Asia/Kolkata"
        now_local = datetime.now(ZoneInfo(tz_name))
        if now_local.hour != hour or now_local.minute != minute:
            continue
        date_key = now_local.date().isoformat()
        if schedule.last_sent_on == date_key:
            continue
        recipients = [e.strip() for e in (schedule.recipients or []) if e and e.strip()]
        if not recipients:
            logger.warning(
                "scheduled_report_skipped_no_recipients",
                study_id=schedule.study_id,
            )
            continue
        try:
            try:
                sync_all_projects(db, schedule.study_id)
                db.expire_all()
            except Exception:
                logger.exception(
                    "scheduled_report_pre_sync_failed",
                    study_id=schedule.study_id,
                )
            job_id = enqueue_execute_then_email(
                db,
                study_id=schedule.study_id,
                template_id=schedule.template_id,
                recipients=recipients,
                window={
                    "preset": "execution_date",
                    "executionDate": date_key,
                },
            )
            schedule.last_sent_on = date_key
            db.commit()
            logger.info(
                "scheduled_report_enqueued",
                study_id=schedule.study_id,
                date=date_key,
                template_id=schedule.template_id,
                job_id=job_id,
            )
            enqueued_any = True
        except Exception:
            logger.exception("scheduled_report_failed", study_id=schedule.study_id)
    return enqueued_any
