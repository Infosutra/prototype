"""Final DQA report orchestration: load → compute → render → persist."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, Report, ReportProject, Study
from app.domain.reporting.final_stats import enrich_final_checklist, mismatch_detail
from app.services.dqa_final_narratives import _build_final_narratives
from app.rendering.docx import render_final_docx
from app.rendering.final import render_final_html, render_final_pdf
from app.services import dqa_daily_report as daily
from app.services import triangulation as tri
from app.services.report_storage import docx_path_for, pdf_path_for
from app.services.settings import get_or_create_settings
from app.services.triangulation import TriangulationError

logger = logging.getLogger(__name__)


def build_final_dqa_stats(
    db: Session,
    study: Study,
    *,
    run_ai: bool = True,
) -> dict[str, Any]:
    """Cumulative study stats + triangulation summaries for Final report."""
    settings = get_or_create_settings(db)
    report_date = (
        study.end_date
        or datetime.now(timezone.utc).date().isoformat()
    )
    base = daily.build_daily_dqa_stats(
        db, study, report_date=report_date, settings=settings
    )
    base["reportKind"] = "final_dqa"
    base["title"] = f"Final DQA — {study.name}"

    triangulation: dict[str, Any] = {}
    view_infos = tri.list_views(db, study.id)
    for info in view_infos:
        view_id = info["id"]
        try:
            view = tri.build_view(db, view_id, study_id=study.id)
            row = tri.get_view_row(db, study.id, view_id)
            kind = None
            if row and isinstance(row.definition, dict):
                kind = row.definition.get("kind")
            triangulation[view_id] = {
                "id": view.id,
                "title": view.title,
                "description": view.description,
                "kind": kind,
                "mismatchCount": view.mismatch_count,
                "rowCount": len(view.rows),
                "practices": [p.model_dump(by_alias=True) for p in view.practices],
                "mismatchExamples": [
                    {
                        "key": r.key,
                        "detail": mismatch_detail(r),
                    }
                    for r in view.rows
                    if r.mismatch
                ][:12],
            }
        except (TriangulationError, Exception):
            logger.exception("Triangulation %s failed for final report", view_id)
            triangulation[view_id] = {
                "id": view_id,
                "title": info.get("title") or view_id,
                "mismatchCount": 0,
                "rowCount": 0,
                "practices": [],
                "mismatchExamples": [],
                "error": "failed",
            }
    base["triangulation"] = triangulation
    base["signOffChecklist"] = enrich_final_checklist(
        list(base.get("signOffChecklist") or []), triangulation
    )
    narratives = _build_final_narratives(base, settings, run_ai=run_ai)
    base.update(narratives)
    return base


def generate_final_dqa_report(
    db: Session,
    *,
    study_id: str | None = None,
    run_ai: bool = True,
) -> Report:
    if not study_id:
        raise ValueError("study_id is required")
    study = db.get(Study, study_id)
    if not study:
        raise ValueError(f"Study not found: {study_id}")

    stats = build_final_dqa_stats(db, study, run_ai=run_ai)
    html_body = render_final_html(stats)
    plain = f"{stats.get('title')}\n\n{stats.get('aiHeadline')}\n"
    pdf_bytes = render_final_pdf(stats)
    docx_bytes = render_final_docx(stats)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    report_id = str(uuid.uuid4())
    pdf_path_for(report_id).write_bytes(pdf_bytes)
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
        title=stats.get("title") or f"Final DQA — {study.name}",
        description="Study close-out DQA with study-defined triangulation views",
        status="ready",
        format="pdf",
        report_type="final_dqa",
        study_id=study.id,
        report_date=stats["reportDate"],
        prompt_name="Final DQA",
        generated_content=json.dumps(payload),
        download_url=f"/api/reports/{report_id}/download",
        page_count=5,
        file_size_kb=round(len(pdf_bytes) / 1024, 1),
        generated_at=now,
        created_at=now,
    )
    db.add(row)
    db.flush()
    for project in projects:
        row.report_projects.append(
            ReportProject(project_id=project.id, project_name=project.name)
        )
    db.commit()
    db.refresh(row)
    return row
