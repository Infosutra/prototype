"""Final DQA report orchestration.

The report's structure lives in a Report Template: this flow resolves the study's
Final template, executes it against the close-out context, and persists the result.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.db.models import Report, Study
from app.domain.report_spec.context import ReportExecutionContext
from app.domain.reporting.final_stats import enrich_final_checklist, mismatch_detail
from app.services import triangulation as tri
from app.services.dqa_report_prompts import resolve_report_prompt
from app.services.report_execution import build_context
from app.services.report_runs import record_run
from app.services.report_tools import ReportDataContext
from app.services.report_tools.signoff import compose_signoff_checklist
from app.services.report_templates import (
    TemplateError,
    execute_template,
    persist_report,
    resolve_template,
)
from app.services.settings import get_or_create_settings
from app.services.triangulation import TriangulationError

logger = structlog.stdlib.get_logger(__name__)

__all__ = ["build_final_dqa_stats", "generate_final_dqa_report"]


def build_final_dqa_stats(
    db: Session,
    study: Study,
    *,
    run_ai: bool = True,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Triangulation summaries + sign-off checklist for Final report stats overlay.

    Phase 3: no longer bases on a full ``build_daily_dqa_stats`` collapse. Certified
    tools self-serve via entity_rows; this blob exists for ``triangulation_summary``
    and checklist enrichment only.
    """
    _ = run_ai, system_prompt  # retained for call-site compatibility
    settings = get_or_create_settings(db)
    report_date = study.end_date or datetime.now(timezone.utc).date().isoformat()
    context = ReportExecutionContext(
        report_kind="final",
        study_id=study.id,
        execution_date=report_date,
        timezone=study.timezone or "Asia/Kolkata",
        date_from=study.start_date,
        date_to=report_date,
    )
    ctx = ReportDataContext(db, context, settings=settings)

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
                    {"key": r.key, "detail": mismatch_detail(r)}
                    for r in view.rows
                    if r.mismatch
                ][:12],
            }
        except (TriangulationError, Exception):
            logger.exception("final_report_triangulation_failed", view_id=view_id)
            triangulation[view_id] = {
                "id": view_id,
                "title": info.get("title") or view_id,
                "mismatchCount": 0,
                "rowCount": 0,
                "practices": [],
                "mismatchExamples": [],
                "error": "failed",
            }

    checklist = compose_signoff_checklist(ctx)
    return {
        "studyId": study.id,
        "studyName": study.name,
        "reportKind": "final_dqa",
        "title": f"Final DQA — {study.name}",
        "reportDate": report_date,
        "triangulation": triangulation,
        "signOffChecklist": enrich_final_checklist(checklist, triangulation),
    }


def _final_template(db: Session, study: Study):
    template = resolve_template(db, study, "final")
    if template is None:
        from app.services.report_seed_templates import seed_report_templates

        seed_report_templates(db)
        template = resolve_template(db, study, "final")
    if template is None:
        raise TemplateError("No Final report template is available for this study.")
    return template


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

    settings = get_or_create_settings(db)
    template = _final_template(db, study)
    context = build_context(study, report_kind="final")
    style_guidance, prompt_id, prompt_name = resolve_report_prompt(db, study, "final")

    executed, version = execute_template(
        db,
        template,
        context,
        settings=settings,
        run_ai=run_ai,
        style_guidance=style_guidance,
    )
    row = persist_report(
        db,
        executed,
        template=template,
        version=version,
        title=f"Final DQA — {study.name}",
        description="Study close-out DQA with study-defined triangulation views",
        prompt_id=prompt_id,
        prompt_name=prompt_name,
        report_type="final_dqa",
    )
    narratives = executed.narratives
    record_run(
        db,
        mode="execute",
        status="ok" if not executed.errors else "invalid",
        study_id=study.id,
        template_id=template.id,
        template_version_id=version.id,
        report_id=row.id,
        provider=narratives.provider,
        model=narratives.model,
        prompt_tokens=narratives.prompt_tokens,
        completion_tokens=narratives.completion_tokens,
        latency_ms=narratives.latency_ms,
        tool_calls=[
            {"dataSource": key, "rows": len(value) if isinstance(value, list) else 1}
            for key, value in executed.data.items()
        ],
        validation_errors=[
            {"dataSource": key, "message": message} for key, message in executed.errors.items()
        ],
        error=narratives.error,
    )
    return row
