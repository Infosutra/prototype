from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models import Project, Submission
from app.domain.reporting.helpers import day_bounds
from app.integrations.smtp import SmtpError, send_email
from app.services.form_labels import extract_enumerator_name
from app.services.settings import (
    get_or_create_settings,
    get_smtp_password,
    smtp_config_from_row,
)

logger = logging.getLogger(__name__)

CONSENT_FIELDS = ("CONSENT", "K_CONSENT", "P_CONSENT")


@dataclass
class InvalidSubmission:
    display_id: str
    enumerator: str | None
    reasons: list[str]


@dataclass
class ProjectSection:
    project_name: str
    total_submissions_today: int
    total_submissions_in_project: int
    enumerator_stats: list[tuple[str, int]] = field(default_factory=list)
    invalid_submissions: list[InvalidSubmission] = field(default_factory=list)


@dataclass
class DailyReport:
    report_date: str
    timezone: str
    organization_name: str
    projects: list[ProjectSection]
    grand_total: int
    invalid_total: int


def parse_send_time(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", value.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _find_field(data: dict, field_name: str):
    if field_name in data:
        return data[field_name]
    suffix = f"/{field_name}"
    for key, value in data.items():
        if key.endswith(suffix):
            return value
    return None


def _consent_refusal(data: dict) -> str | None:
    for name in CONSENT_FIELDS:
        value = _find_field(data, name)
        if value is None:
            continue
        text = str(value).strip().lower()
        if text in {"0", "no", "false", "n"}:
            return f"Consent refused ({name}={value})"
    return None


def _validation_rejection(data: dict) -> str | None:
    status = data.get("_validation_status")
    if not isinstance(status, dict):
        return None
    uid = str(status.get("uid") or "").lower()
    label = str(status.get("label") or "").lower()
    combined = f"{uid} {label}"
    if any(token in combined for token in ("not_approved", "rejected", "on_hold", "not approved")):
        display = status.get("label") or status.get("uid") or "rejected"
        return f"Kobo validation status: {display}"
    return None


def collect_invalid_reasons(submission: Submission, enumerator: str | None) -> list[str]:
    reasons: list[str] = []
    if not enumerator:
        reasons.append("Missing enumerator name (first form question is empty)")

    # Prefer persisted DQA RED flags when available.
    try:
        from app.db.models import DqaFlag
        from sqlalchemy.orm import object_session

        session = object_session(submission)
        if session is not None:
            flags = session.scalars(
                select(DqaFlag).where(
                    DqaFlag.submission_id == submission.id,
                    DqaFlag.severity == "red",
                )
            ).all()
            for flag in flags:
                reasons.append(f"{flag.rule_id}: {flag.message}")
    except Exception:
        logger.exception("Failed loading DQA flags for submission %s", submission.id)

    data = submission.data if isinstance(submission.data, dict) else {}
    if submission.status == "flagged" and not any(r.startswith("T") for r in reasons):
        reasons.append("Submission status is flagged")
    validation = _validation_rejection(data)
    if validation:
        reasons.append(validation)

    # Fallback legacy consent check if no pack flags yet
    if not any("Consent" in r or r.startswith("T1-1") or r.startswith("T2-1") or r.startswith("T3-1") for r in reasons):
        consent = _consent_refusal(data)
        if consent:
            reasons.append(consent)
    return reasons


def build_daily_report(db: Session, report_date: str, tz_name: str, organization_name: str) -> DailyReport:
    start, end = day_bounds(report_date, tz_name)
    projects = db.scalars(select(Project).order_by(Project.name)).all()
    todays = db.scalars(
        select(Submission).where(
            and_(Submission.submitted_at >= start, Submission.submitted_at <= end)
        )
    ).all()
    by_project: dict[str, list[Submission]] = {}
    for row in todays:
        by_project.setdefault(row.project_id, []).append(row)

    sections: list[ProjectSection] = []
    for project in projects:
        rows = by_project.get(project.id, [])
        form_definition = project.form_definition if isinstance(project.form_definition, dict) else None
        enumerator_counts: dict[str, int] = {}
        invalids: list[InvalidSubmission] = []
        for row in rows:
            data = row.data if isinstance(row.data, dict) else {}
            enumerator = extract_enumerator_name(data, form_definition)
            if enumerator:
                enumerator_counts[enumerator] = enumerator_counts.get(enumerator, 0) + 1
            reasons = collect_invalid_reasons(row, enumerator)
            if reasons:
                invalids.append(
                    InvalidSubmission(
                        display_id=f"Submission-{row.kobo_id}",
                        enumerator=enumerator,
                        reasons=reasons,
                    )
                )
        sections.append(
            ProjectSection(
                project_name=project.name,
                total_submissions_today=len(rows),
                total_submissions_in_project=project.submission_count,
                enumerator_stats=sorted(
                    enumerator_counts.items(), key=lambda item: (-item[1], item[0])
                ),
                invalid_submissions=invalids,
            )
        )

    return DailyReport(
        report_date=report_date,
        timezone=tz_name,
        organization_name=organization_name,
        projects=sections,
        grand_total=sum(s.total_submissions_today for s in sections),
        invalid_total=sum(len(s.invalid_submissions) for s in sections),
    )


def format_email(report: DailyReport) -> tuple[str, str, str]:
    subject = f"Infosutra daily report — {report.report_date}"
    text_parts = [
        f"{report.organization_name} — Daily submissions report",
        f"Date: {report.report_date} ({report.timezone})",
        f"Total Submissions today: {report.grand_total}",
        f"Invalid submissions: {report.invalid_total}",
        "",
    ]
    html_sections: list[str] = []
    for project in report.projects:
        text_parts.append(f"## {project.project_name}")
        text_parts.append(f"Total submissions in project: {project.total_submissions_in_project}")
        text_parts.append(f"Total submissions today: {project.total_submissions_today}")
        text_parts.append("Enumerator counts:")
        if not project.enumerator_stats:
            text_parts.append("  (none)")
            enum_rows = '<tr><td colspan="2" style="padding:4px 0;color:#666;">No submissions with enumerator names</td></tr>'
        else:
            enum_rows = ""
            for name, count in project.enumerator_stats:
                text_parts.append(f"  - {name}: {count}")
                enum_rows += (
                    f'<tr><td style="padding:4px 12px 4px 0;">{html.escape(name)}</td>'
                    f'<td style="padding:4px 0;text-align:right;">{count}</td></tr>'
                )
        text_parts.append("Invalid submissions:")
        if not project.invalid_submissions:
            text_parts.append("  (none)")
            invalid_html = '<p style="margin:8px 0 0;color:#666;">No invalid submissions</p>'
        else:
            items = []
            for invalid in project.invalid_submissions:
                who = f" ({invalid.enumerator})" if invalid.enumerator else ""
                text_parts.append(
                    f"  - {invalid.display_id}{who}: {'; '.join(invalid.reasons)}"
                )
                who_html = f" — {html.escape(invalid.enumerator)}" if invalid.enumerator else ""
                items.append(
                    f'<li style="margin-bottom:6px;"><strong>{html.escape(invalid.display_id)}</strong>'
                    f'{who_html}<br/><span style="color:#b45309;">{html.escape("; ".join(invalid.reasons))}</span></li>'
                )
            invalid_html = f'<ul style="margin:8px 0 0;padding-left:18px;">{"".join(items)}</ul>'
        text_parts.append("")
        html_sections.append(
            f"""
            <section style="margin:0 0 28px;padding-bottom:20px;border-bottom:1px solid #e5e7eb;">
              <h2 style="margin:0 0 8px;font-size:18px;">{html.escape(project.project_name)}</h2>
              <p style="margin:0 0 4px;"><strong>Total submissions in project:</strong> {project.total_submissions_in_project}</p>
              <p style="margin:0 0 12px;"><strong>Total submissions today:</strong> {project.total_submissions_today}</p>
              <h3 style="margin:0 0 6px;font-size:14px;">Enumerator submissions</h3>
              <table style="border-collapse:collapse;width:100%;max-width:420px;">{enum_rows}</table>
              <h3 style="margin:16px 0 0;font-size:14px;">Invalid submissions</h3>
              {invalid_html}
            </section>
            """
        )

    html_body = f"""
    <div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#111;line-height:1.45;">
      <h1 style="margin:0 0 8px;font-size:22px;">{html.escape(report.organization_name)} — Daily report</h1>
      <p style="margin:0 0 4px;"><strong>Date:</strong> {html.escape(report.report_date)} ({html.escape(report.timezone)})</p>
      <p style="margin:0 0 20px;"><strong>Total Submissions today:</strong> {report.grand_total} &nbsp;|&nbsp; <strong>Invalid:</strong> {report.invalid_total}</p>
      {''.join(html_sections)}
      <p style="margin:24px 0 0;color:#666;font-size:12px;">Sent by Infosutra</p>
    </div>
    """
    return subject, "\n".join(text_parts), html_body


def send_daily_report_now(db: Session) -> tuple[DailyReport, list[str]]:
    settings = get_or_create_settings(db)
    recipients = [r.strip() for r in (settings.daily_report_recipients or []) if str(r).strip()]
    if not recipients:
        raise ValueError("No report recipients configured")
    password = get_smtp_password(settings)
    if not settings.smtp_host or not settings.smtp_username or not password or not settings.smtp_from_email:
        raise ValueError("SMTP is not configured")

    tz_name = settings.daily_report_timezone or "Asia/Kolkata"
    report_date = datetime.now(ZoneInfo(tz_name)).date().isoformat()
    report = build_daily_report(
        db,
        report_date,
        tz_name,
        settings.organization_name or "Infosutra",
    )
    subject, text, html_body = format_email(report)
    send_email(
        smtp_config_from_row(settings, password),
        to=recipients,
        subject=subject,
        text=text,
        html=html_body,
    )
    settings.daily_report_last_sent_on = report_date
    db.commit()
    return report, recipients


def maybe_send_scheduled_report(db: Session) -> None:
    settings = get_or_create_settings(db)
    if not settings.daily_report_enabled:
        return
    recipients = [r.strip() for r in (settings.daily_report_recipients or []) if str(r).strip()]
    if not recipients:
        return
    parsed = parse_send_time(settings.daily_report_time or "21:00")
    if not parsed:
        logger.warning("Invalid daily report send time: %s", settings.daily_report_time)
        return
    hour, minute = parsed
    tz_name = settings.daily_report_timezone or "Asia/Kolkata"
    now_local = datetime.now(ZoneInfo(tz_name))
    if now_local.hour != hour or now_local.minute != minute:
        return
    date_key = now_local.date().isoformat()
    if settings.daily_report_last_sent_on == date_key:
        return
    try:
        send_daily_report_now(db)
        logger.info("Scheduled daily report sent for %s", date_key)
    except (ValueError, SmtpError) as exc:
        logger.warning("Scheduled daily report skipped/failed: %s", exc)
    except Exception:
        logger.exception("Scheduled daily report failed")
