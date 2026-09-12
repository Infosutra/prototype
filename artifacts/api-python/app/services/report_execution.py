"""Execute a Report Specification against a context and render deterministic output.

Definition (the spec) and execution (the context) stay separate: the same template
produces a daily report today and a close-out report over the full study window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.db.models import AppSettings, Study
from app.domain.report_spec.context import ReportExecutionContext, ReportKind
from app.domain.report_spec.keys import required_data_keys
from app.domain.report_spec.spec import ReportSpec
from app.domain.reporting.helpers import (
    format_report_date,
    format_report_datetime,
    today_in_tz,
)
from app.rendering.spec import (
    RenderPayload,
    render_spec_docx,
    render_spec_html,
    render_spec_pdf,
    render_spec_plaintext,
)
from app.services.report_analyst import NarrativeResult, generate_narratives
from app.services.report_tools import ReportDataContext, ReportToolError, call_tool
from app.services.settings import get_or_create_settings
from app.services.studies import study_day_number

logger = structlog.stdlib.get_logger(__name__)

_KIND_LABEL: dict[str, str] = {
    "daily": "Daily",
    "final": "Final / close-out",
    "adhoc": "Ad hoc",
}

#: Data source backing the report header, resolved for every execution.
HEADER_SOURCE = "study_metadata"


@dataclass
class ExecutedReport:
    spec: ReportSpec
    context: ReportExecutionContext
    payload: RenderPayload
    narratives: NarrativeResult
    data: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def render_html(self) -> str:
        return render_spec_html(self.payload)

    def render_plaintext(self) -> str:
        return render_spec_plaintext(self.payload)

    def render_pdf(self) -> bytes:
        return render_spec_pdf(self.payload)

    def render_docx(self) -> bytes:
        return render_spec_docx(self.payload)


def build_context(
    study: Study,
    *,
    report_kind: ReportKind = "adhoc",
    execution_date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    project_ids: list[str] | None = None,
) -> ReportExecutionContext:
    """Resolve the semantic reporting window for a study."""
    tz_name = study.timezone or "Asia/Kolkata"
    if execution_date:
        resolved = execution_date
    elif report_kind == "final":
        resolved = study.end_date or today_in_tz(tz_name)
    else:
        resolved = today_in_tz(tz_name)
    return ReportExecutionContext(
        report_kind=report_kind,
        study_id=study.id,
        execution_date=resolved,
        timezone=tz_name,
        date_from=date_from or (study.start_date if report_kind == "final" else None),
        date_to=date_to or (resolved if report_kind == "final" else None),
        project_ids=list(project_ids or []),
    )


def resolve_data(
    data_context: ReportDataContext, spec: ReportSpec
) -> tuple[dict[str, Any], dict[str, str]]:
    """Fetch every data source the specification needs.

    A failing source marks only its own components unavailable; the rest of the
    report still renders.
    """
    data: dict[str, Any] = {}
    errors: dict[str, str] = {}
    # The report header is a property of execution rather than of the specification,
    # so its source is always resolved even when no component references it.
    required = [(HEADER_SOURCE, HEADER_SOURCE, {})] + [
        entry for entry in required_data_keys(spec) if entry[0] != HEADER_SOURCE
    ]
    for key, source_id, params in required:
        try:
            data[key] = call_tool(data_context, source_id, params)
        except ReportToolError as exc:
            logger.warning("report_data_source_unavailable", source_id=source_id, error=str(exc))
            errors[key] = str(exc)
        except Exception:
            logger.exception("report_data_source_failed", source_id=source_id)
            errors[key] = f"'{source_id}' data is not available for this reporting period."
    return data, errors


def _meta(
    study: Study,
    context: ReportExecutionContext,
    settings: AppSettings,
    data: dict[str, Any],
) -> dict[str, Any]:
    metadata = data.get("study_metadata") if isinstance(data.get("study_metadata"), dict) else {}
    day_number = metadata.get("dayNumber")
    if day_number is None:
        try:
            day_number = study_day_number(study, on=date.fromisoformat(context.execution_date))
        except ValueError:
            day_number = None
    window = metadata.get("reportDateDisplay") or format_report_date(context.execution_date)
    rows: list[tuple[str, Any]] = [
        (
            "Report",
            f"{_KIND_LABEL.get(context.report_kind, 'Report')}"
            + (f" — Day {day_number}" if day_number is not None else ""),
        ),
        ("Study", study.name),
        ("Data window", f"{window} ({context.timezone})"),
    ]
    if context.report_kind == "final" and context.date_from:
        rows.insert(
            2, ("Period", f"{format_report_date(context.date_from)} – {window}")
        )
    kobo = metadata.get("lastKoboPullDisplay")
    if kobo:
        rows.append(("KoBo pull", kobo))
    rows.append(
        (
            "Generated",
            metadata.get("generatedAtDisplay")
            or format_report_datetime(None, tz_name=context.timezone),
        )
    )
    return {
        "organizationName": settings.organization_name or "Infosutra",
        "rows": rows,
        "footer": (
            "Generated by Infosutra · KoboToolbox is source of truth (read-only sync) · "
            "Figures come from the application data layer, not from the language model."
        ),
    }


def _spec_needs_stats_collapse(spec: ReportSpec, context: ReportExecutionContext) -> bool:
    """Whether execute_spec must materialize ctx.stats() (full collapse / final overlay).

    Common adhoc/daily reports use Phase 2 tools + tool-data fallbacks and do not
    need the eager collapse. Final reports and specs that include triangulation_summary
    still require it.
    """
    if context.report_kind == "final":
        return True
    for _key, source_id, _params in required_data_keys(spec):
        if source_id == "triangulation_summary":
            return True
    return False


def execute_spec(
    db: Session,
    spec: ReportSpec,
    context: ReportExecutionContext,
    *,
    settings: AppSettings | None = None,
    run_ai: bool = True,
    analyst_prompt: str | None = None,
    style_guidance: str | None = None,
    stats: dict[str, Any] | None = None,
) -> ExecutedReport:
    """Resolve data, generate narrative prose, and assemble the render payload."""
    settings = settings or get_or_create_settings(db)
    data_context = ReportDataContext(db, context, settings=settings, stats=stats)
    study = data_context.study

    data, errors = resolve_data(data_context, spec)

    stats_for_narratives: dict[str, Any] | None = stats
    if stats_for_narratives is None and _spec_needs_stats_collapse(spec, context):
        try:
            stats_for_narratives = data_context.stats()
        except Exception:
            logger.exception("study_statistics_compute_failed")

    narratives = generate_narratives(
        db,
        spec,
        data,
        settings=settings,
        context_summary=context.model_dump(by_alias=True),
        system_prompt=analyst_prompt,
        style_guidance=style_guidance,
        stats=stats_for_narratives,
        run_ai=run_ai,
    )

    payload = RenderPayload(
        spec=spec,
        data=data,
        narratives=narratives.texts,
        errors=errors,
        meta=_meta(study, context, settings, data),
    )
    return ExecutedReport(
        spec=spec,
        context=context,
        payload=payload,
        narratives=narratives,
        data=data,
        errors=errors,
    )
