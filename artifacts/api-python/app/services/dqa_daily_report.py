"""DQA Daily report orchestration.

The report's structure lives in a Report Template, not in this module: this flow
resolves the study's Daily template, executes it against today's context, and
persists the result. The request/response contract is unchanged.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db.models import Report, Study
from app.services.dqa_report_prompts import resolve_report_prompt
from app.services.report_execution import build_context
from app.services.report_runs import record_run
from app.services.report_stats import build_daily_dqa_stats
from app.services.report_templates import (
    TemplateError,
    execute_template,
    persist_report,
    resolve_template,
)
from app.services.settings import get_or_create_settings

logger = logging.getLogger(__name__)

__all__ = ["build_daily_dqa_stats", "generate_daily_dqa_report"]


def _daily_template(db: Session, study: Study):
    template = resolve_template(db, study, "daily")
    if template is None:
        # First run on an existing database: make sure the seeded system template exists.
        from app.services.report_seed_templates import seed_report_templates

        seed_report_templates(db)
        template = resolve_template(db, study, "daily")
    if template is None:
        raise TemplateError("No Daily report template is available for this study.")
    return template


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
    study = db.get(Study, study_id)
    if not study:
        raise ValueError(f"Study not found: {study_id}")

    template = _daily_template(db, study)
    context = build_context(study, report_kind="daily", execution_date=report_date)
    style_guidance, prompt_id, prompt_name = resolve_report_prompt(db, study, "daily")

    executed, version = execute_template(
        db,
        template,
        context,
        settings=settings,
        run_ai=run_ai,
        style_guidance=style_guidance,
    )

    header = executed.data.get("study_metadata") or {}
    day_number = header.get("dayNumber")
    row = persist_report(
        db,
        executed,
        template=template,
        version=version,
        title=f"DQA Daily — {study.name} — {context.execution_date}",
        description=f"Day {day_number} study DQA daily report",
        prompt_id=prompt_id,
        prompt_name=prompt_name,
        report_type="daily_dqa",
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
