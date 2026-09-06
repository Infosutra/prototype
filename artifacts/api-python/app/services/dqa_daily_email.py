"""Email delivery and scheduling for DQA Daily reports."""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Report, ReportSchedule, ReportTemplate, Study
from app.integrations.smtp import SmtpError, send_email
from app.services.daily_report import parse_send_time
from app.services.dqa_daily_report import generate_daily_dqa_report
from app.services.dqa_final_report import generate_final_dqa_report
from app.services.report_execution import build_context
from app.services.report_templates import execute_template, persist_report
from app.services.report_storage import pdf_path_for
from app.services.settings import (
    get_or_create_settings,
    get_smtp_password,
    smtp_config_from_row,
)

logger = logging.getLogger(__name__)


def _daily_schedule_for_study(db: Session, study_id: str) -> ReportSchedule | None:
    return db.scalars(
        select(ReportSchedule).where(
            ReportSchedule.study_id == study_id,
            ReportSchedule.report_type == "daily_dqa",
        )
    ).first()

def send_dqa_daily_email(
    db: Session,
    report: Report,
    *,
    recipients: list[str] | None = None,
) -> tuple[Report, list[str]]:
    settings = get_or_create_settings(db)
    if recipients is not None:
        to = list(recipients)
    else:
        schedule = _daily_schedule_for_study(db, report.study_id) if report.study_id else None
        to = list(schedule.recipients or []) if schedule else []
    to = [e.strip() for e in to if e and e.strip()]
    if not to:
        raise SmtpError("No DQA Daily recipients configured")

    password = get_smtp_password(settings)
    if not password:
        raise SmtpError("SMTP password is not configured")

    payload: dict[str, Any] = {}
    if report.generated_content:
        try:
            payload = json.loads(report.generated_content)
        except json.JSONDecodeError:
            payload = {}
    html_body = payload.get("html") or f"<p>{html.escape(report.title)}</p>"
    plain = payload.get("plainText") or report.title
    pdf_file = pdf_path_for(report.id)
    attachments = []
    if pdf_file.is_file():
        attachments.append(
            (f"{report.title.replace(' ', '_')[:80]}.pdf", pdf_file.read_bytes(), "application/pdf")
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


def send_dqa_daily_now(
    db: Session,
    *,
    study_id: str | None = None,
    report_date: str | None = None,
) -> tuple[Report, list[str]]:
    report = generate_daily_dqa_report(
        db, study_id=study_id, report_date=report_date, run_ai=True
    )
    return send_dqa_daily_email(db, report)


def _generate_for_schedule(db: Session, schedule: ReportSchedule, date_key: str) -> Report:
    """Execute the schedule's template when set, otherwise the study default for that kind."""
    if schedule.template_id:
        template = db.get(ReportTemplate, schedule.template_id)
        study = db.get(Study, schedule.study_id)
        if template is None or study is None:
            raise ValueError("Scheduled template or study is missing")
        kind = template.report_kind if template.report_kind in {"daily", "final", "adhoc"} else "daily"
        context = build_context(study, report_kind=kind, execution_date=date_key)
        executed, version = execute_template(db, template, context, run_ai=True)
        return persist_report(db, executed, template=template, version=version)
    if schedule.report_type == "final_dqa":
        return generate_final_dqa_report(db, study_id=schedule.study_id, run_ai=True)
    return generate_daily_dqa_report(
        db, study_id=schedule.study_id, report_date=date_key, run_ai=True
    )


def maybe_send_scheduled_dqa_daily(db: Session) -> bool:
    """Scheduler tick for report schedules (templates or study Daily/Final defaults)."""
    sent_any = False
    schedules = list(
        db.scalars(select(ReportSchedule).where(ReportSchedule.enabled.is_(True))).all()
    )
    for schedule in schedules:
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
        try:
            report = _generate_for_schedule(db, schedule, date_key)
            send_dqa_daily_email(db, report)
            schedule.last_sent_on = date_key
            db.commit()
            logger.info(
                "Scheduled report sent for study %s on %s (template=%s)",
                schedule.study_id,
                date_key,
                schedule.template_id,
            )
            sent_any = True
        except Exception:
            logger.exception("Scheduled report failed for study %s", schedule.study_id)
    return sent_any
