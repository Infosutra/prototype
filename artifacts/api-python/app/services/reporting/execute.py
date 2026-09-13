"""Execute a ReportSpec: run Query IR per component, assemble ExecuteResult.

Narrative LLM is stubbed in Phase 3 (fixed string from ``uses`` datasets).
Phase 4 wires the real analyst prompt.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Report, ReportTemplate, ReportTemplateVersion, Study
from app.domain.reporting.spec import ReportSpec
from app.domain.reporting.validation import SpecValidationError, validate_report_spec
from app.domain.time_window import (
    ResolvedTimeWindow,
    TimeWindowError,
    TimeWindowInput,
    resolve_time_window,
)
from app.services.report_storage import pdf_path_for, write_report_result
from app.services.reporting.config import ReportingConfig, get_reporting_config
from app.services.reporting.query_engine import QueryError, run as run_query
from app.services.reporting.render_pdf import render_pdf

# Phase 3: no LLM. Phase 4 replaces this with the report-analyst prompt path.
NARRATIVE_STUB_TEXT = (
    "Phase 3 narrative stub: review the linked KPI, enumerator, and red-flag "
    "datasets for concerns. (LLM analyst deferred to Phase 4.)"
)


class ExecuteError(ValueError):
    """Fatal execute failure (bad payload / missing study / invalid spec)."""


def execute_report(
    db: Session,
    *,
    study_id: str,
    window_input: TimeWindowInput | dict[str, Any],
    spec: ReportSpec | dict[str, Any] | None = None,
    template_id: str | None = None,
    config: ReportingConfig | None = None,
    title: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Run all component queries and persist Report + ExecuteResult + PDF.

    Returns the ExecuteResult dict (also written to ``data/reports/{id}.json``
    and used as the job artifact payload).
    """
    cfg = config or get_reporting_config(db)
    study = db.get(Study, study_id)
    if study is None:
        raise ExecuteError(f"Study '{study_id}' not found")

    template: ReportTemplate | None = None
    version: ReportTemplateVersion | None = None
    parsed_spec = _load_spec(db, spec=spec, template_id=template_id)
    template, version = _maybe_load_template(db, template_id)

    errs = validate_report_spec(parsed_spec, cfg)
    if errs:
        raise SpecValidationError(errs)

    tz = (study.timezone or "UTC").strip() or "UTC"
    try:
        job_window = resolve_time_window(
            window_input,
            timezone=tz,
            study_start_date=study.start_date,
            max_range_days=cfg.time_range_max_days,
        )
    except TimeWindowError as exc:
        raise ExecuteError(str(exc)) from exc

    execution_anchor = _execution_anchor(window_input, job_window)

    # First pass: query-backed components (skip narrative/text until uses ready).
    component_results: dict[str, dict[str, Any]] = {}
    datasets: dict[str, Any] = {}

    for section in parsed_spec.sections:
        for comp in section.components:
            if comp.type in {"narrative", "text"}:
                continue
            entry = _run_data_component(
                db,
                comp,
                study_id=study_id,
                job_window=job_window,
                execution_anchor=execution_anchor,
                study_start_date=study.start_date,
                timezone=tz,
                config=cfg,
            )
            component_results[comp.id] = entry
            if "data" in entry and "error" not in entry:
                datasets[comp.id] = entry["data"]

    # Second pass: narrative / text
    for section in parsed_spec.sections:
        for comp in section.components:
            if comp.type == "text":
                body = (comp.display or {}).get("body", "")
                component_results[comp.id] = {
                    "id": comp.id,
                    "type": comp.type,
                    "data": {"body": body},
                }
            elif comp.type == "narrative":
                component_results[comp.id] = _run_narrative(comp, datasets)

    sections_out: list[dict[str, Any]] = []
    for section in parsed_spec.sections:
        comps_out = []
        for comp in section.components:
            comps_out.append(component_results.get(comp.id) or {
                "id": comp.id,
                "type": comp.type,
                "error": "Component was not executed",
            })
        sections_out.append(
            {
                "id": section.id,
                "title": section.title,
                "components": comps_out,
            }
        )

    report_id = str(uuid.uuid4())
    report_title = title or parsed_spec.title
    result: dict[str, Any] = {
        "reportId": report_id,
        "title": report_title,
        "window": {
            "from": job_window.from_date.isoformat(),
            "to": job_window.to_date.isoformat(),
        },
        "sections": sections_out,
        "artifacts": {},
    }

    pdf_bytes = render_pdf(result)
    pdf_path = pdf_path_for(report_id)
    pdf_path.write_bytes(pdf_bytes)
    result["artifacts"] = {
        "pdf": f"/api/reports/{report_id}/download",
    }

    result_ref = write_report_result(report_id, result)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = Report(
        id=report_id,
        title=report_title,
        description=parsed_spec.subtitle or "",
        status="ready",
        format="pdf",
        report_type="custom",
        study_id=study_id,
        report_date=job_window.to_date.isoformat(),
        template_id=template.id if template else None,
        template_version_id=version.id if version else None,
        spec_json=parsed_spec.model_dump(by_alias=True),
        execution_context_json={
            "window": result["window"],
            "timezone": tz,
            "source": job_window.source,
        },
        result_ref=result_ref,
        download_url=f"/api/reports/{report_id}/download",
        page_count=max(1, 1 + sum(len(s.components) for s in parsed_spec.sections) // 6),
        file_size_kb=round(len(pdf_bytes) / 1024, 1),
        generated_at=now,
        created_at=now,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()

    return result


def _load_spec(
    db: Session,
    *,
    spec: ReportSpec | dict[str, Any] | None,
    template_id: str | None,
) -> ReportSpec:
    if spec is not None and template_id is not None:
        raise ExecuteError("Provide either spec or templateId, not both")
    if spec is None and not template_id:
        raise ExecuteError("Provide spec or templateId")

    if template_id:
        template = db.get(ReportTemplate, template_id)
        if template is None:
            raise ExecuteError(f"Template '{template_id}' not found")
        version = _current_version(db, template)
        if version is None or not version.spec_json:
            raise ExecuteError(f"Template '{template_id}' has no current version spec")
        return ReportSpec.model_validate(version.spec_json)

    if isinstance(spec, ReportSpec):
        return spec
    assert spec is not None
    return ReportSpec.model_validate(spec)


def _maybe_load_template(
    db: Session, template_id: str | None
) -> tuple[ReportTemplate | None, ReportTemplateVersion | None]:
    if not template_id:
        return None, None
    template = db.get(ReportTemplate, template_id)
    if template is None:
        return None, None
    return template, _current_version(db, template)


def _current_version(
    db: Session, template: ReportTemplate
) -> ReportTemplateVersion | None:
    if template.current_version_id:
        ver = db.get(ReportTemplateVersion, template.current_version_id)
        if ver is not None:
            return ver
    versions = sorted(template.versions or [], key=lambda v: v.version, reverse=True)
    return versions[0] if versions else None


def _execution_anchor(
    window_input: TimeWindowInput | dict[str, Any],
    job_window: ResolvedTimeWindow,
) -> str:
    if isinstance(window_input, dict):
        tw = TimeWindowInput.model_validate(window_input)
    else:
        tw = window_input
    if tw.execution_date:
        return tw.execution_date
    # Absolute range or preset without executionDate: use resolved end day.
    return job_window.to_date.isoformat()


def _component_window(
    *,
    query_window_preset: str,
    job_window: ResolvedTimeWindow,
    execution_anchor: str,
    timezone: str,
    study_start_date: str | None,
    max_range_days: int,
) -> ResolvedTimeWindow:
    """Absolute job window overrides every component preset; else resolve preset."""
    if job_window.source == "range":
        return job_window
    return resolve_time_window(
        {"preset": query_window_preset, "executionDate": execution_anchor},
        timezone=timezone,
        study_start_date=study_start_date,
        max_range_days=max_range_days,
    )


def _run_data_component(
    db: Session,
    comp: Any,
    *,
    study_id: str,
    job_window: ResolvedTimeWindow,
    execution_anchor: str,
    study_start_date: str | None,
    timezone: str,
    config: ReportingConfig,
) -> dict[str, Any]:
    base: dict[str, Any] = {"id": comp.id, "type": comp.type}
    if comp.query is None:
        base["error"] = "Missing query"
        return base
    try:
        window = _component_window(
            query_window_preset=comp.query.window,
            job_window=job_window,
            execution_anchor=execution_anchor,
            timezone=timezone,
            study_start_date=study_start_date,
            max_range_days=config.time_range_max_days,
        )
        raw = run_query(
            db,
            comp.query,
            study_id=study_id,
            window=window,
            config=config,
        )
        base["data"] = _shape_data(comp, raw)
    except (QueryError, TimeWindowError, ValueError) as exc:
        base["error"] = str(exc)
    return base


def _shape_data(comp: Any, raw: Any) -> Any:
    """Map query_engine output into ExecuteResult data shapes (§3.5)."""
    if comp.type == "metric":
        field = (comp.display or {}).get("field")
        if isinstance(raw, dict) and field in raw:
            return {"value": raw[field]}
        if isinstance(raw, (int, float)):
            return {"value": raw}
        return raw
    if comp.type == "kpi_group":
        if isinstance(raw, dict):
            return raw
        return raw
    # table / chart / progress
    return raw


def _run_narrative(comp: Any, datasets: dict[str, Any]) -> dict[str, Any]:
    """Phase 3 stub — fixed string; does not call an LLM."""
    uses = list(comp.uses or [])
    # Touch datasets so the stub is clearly tied to uses (and unused-ref noise is avoided).
    _ = {uid: datasets.get(uid) for uid in uses}
    return {
        "id": comp.id,
        "type": "narrative",
        "data": {"text": NARRATIVE_STUB_TEXT},
    }

