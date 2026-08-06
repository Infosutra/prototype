"""DQA Daily report orchestration: load → compute → narrate → render → persist."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppSettings, Project, Report, ReportProject, Study
from app.domain.reporting.daily_stats import compute_daily_dqa_stats
from app.domain.reporting.helpers import day_bounds, today_in_tz
from app.domain.reporting.narratives import _fallback_coverage, _fallback_headline
from app.rendering.daily import render_html, render_pdf, render_plaintext
from app.rendering.docx import render_daily_docx
from app.repositories.reporting import load_study_report_inputs
from app.services.dqa_daily_narratives import generate_ai_narratives
from app.services.report_storage import docx_path_for, pdf_path_for
from app.services.settings import get_or_create_settings
from app.services.studies import study_day_number

logger = logging.getLogger(__name__)


def build_daily_dqa_stats(
    db: Session,
    study: Study,
    *,
    report_date: str | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    """Aggregate today + cumulative DQA stats for one study. Local DB only."""
    settings = settings or get_or_create_settings(db)
    tz_name = study.timezone or "Asia/Kolkata"
    date_key = report_date or today_in_tz(tz_name)
    start_utc, end_utc = day_bounds(date_key, tz_name)
    day_n = study_day_number(study, on=date.fromisoformat(date_key))
    loaded = load_study_report_inputs(db, study.id)
    return compute_daily_dqa_stats(
        study_id=study.id,
        study_name=study.name,
        study_start_date=study.start_date,
        tz_name=tz_name,
        date_key=date_key,
        day_n=day_n,
        organization_name=settings.organization_name,
        projects=loaded["projects"],
        targets=loaded["targets"],
        all_subs=loaded["all_subs"],
        all_flags=loaded["all_flags"],
        pack_cache=loaded["pack_cache"],
        start_utc=start_utc,
        end_utc=end_utc,
    )



def _set_report_projects(db: Session, report: Report, projects: list[Project]) -> None:
    report.report_projects.clear()
    db.flush()
    for project in projects:
        report.report_projects.append(
            ReportProject(project_id=project.id, project_name=project.name)
        )


def generate_daily_dqa_report(
    db: Session,
    *,
    study_id: str | None = None,
    report_date: str | None = None,
    run_ai: bool = True,
) -> Report:
    settings = get_or_create_settings(db)
    if not study_id:
        raise ValueError("study_id is required")
    sid = study_id
    study = db.get(Study, sid)
    if not study:
        raise ValueError(f"Study not found: {sid}")

    stats = build_daily_dqa_stats(db, study, report_date=report_date, settings=settings)
    if run_ai:
        narratives = generate_ai_narratives(stats, settings)
        stats["aiHeadline"] = narratives["aiHeadline"]
        stats["aiCoverageNote"] = narratives["aiCoverageNote"]
        stats["aiSource"] = narratives["aiSource"]
    else:
        stats["aiHeadline"] = _fallback_headline(stats)
        stats["aiCoverageNote"] = _fallback_coverage(stats)
        stats["aiSource"] = "skipped"

    html_body = render_html(stats)
    plain = render_plaintext(stats)
    pdf_bytes = render_pdf(stats)
    docx_bytes = render_daily_docx(stats)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    report_id = str(uuid.uuid4())
    path = pdf_path_for(report_id)
    path.write_bytes(pdf_bytes)
    docx_path_for(report_id).write_bytes(docx_bytes)

    projects = list(db.scalars(select(Project).where(Project.study_id == study.id)).all())
    payload = {
        "stats": stats,
        "html": html_body,
        "plainText": plain,
        "aiSource": stats.get("aiSource"),
    }
    row = Report(
        id=report_id,
        title=f"DQA Daily — {study.name} — {stats['reportDate']}",
        description=f"Day {stats.get('dayNumber')} study DQA daily report",
        status="ready",
        format="pdf",
        report_type="daily_dqa",
        study_id=study.id,
        report_date=stats["reportDate"],
        prompt_id=None,
        prompt_name="DQA Daily",
        generated_content=json.dumps(payload),
        download_url=f"/api/reports/{report_id}/download",
        page_count=max(1, 2 + len(stats["redPriority"]) // 20),
        file_size_kb=round(len(pdf_bytes) / 1024, 1),
        generated_at=now,
        created_at=now,
    )
    db.add(row)
    db.flush()
    _set_report_projects(db, row, projects)
    db.commit()
    db.refresh(row)
    return row
