"""Execute a ReportSpec: run Query IR per component, assemble ExecuteResult.

Narratives use the report-analyst LLM when available, with a deterministic
fallback built from the linked ``uses`` datasets (never invents figures).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.db.models import Report, ReportTemplate, ReportTemplateVersion, Study
from app.domain.reporting.spec import ReportSpec
from app.domain.reporting.query import Query
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

logger = structlog.stdlib.get_logger(__name__)

# Kept for tests / callers that still import the old stub string.
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
    persist: bool = True,
) -> dict[str, Any]:
    """Run all component queries and return an ExecuteResult.

    When ``persist`` is True (default), also writes Report + PDF + JSON under
    ``data/reports/``. Authoring live preview should pass ``persist=False`` so
    drafts never appear on the Reports tab.
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

    # Second pass: narrative / text (narratives may call the analyst LLM once).
    narrative_comps: list[Any] = []
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
                narrative_comps.append(comp)

    if narrative_comps:
        narrative_texts = _generate_narratives(
            db,
            narrative_comps,
            datasets,
            report_title=parsed_spec.title or title or "Report",
        )
        for comp in narrative_comps:
            component_results[comp.id] = {
                "id": comp.id,
                "type": "narrative",
                "data": {"text": narrative_texts.get(comp.id) or _deterministic_narrative(comp, datasets)},
            }

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

    report_title = title or parsed_spec.title
    result: dict[str, Any] = {
        "title": report_title,
        "window": {
            "from": job_window.from_date.isoformat(),
            "to": job_window.to_date.isoformat(),
        },
        "sections": sections_out,
        "artifacts": {},
        "preview": not persist,
    }

    if not persist:
        return result

    report_id = str(uuid.uuid4())
    result["reportId"] = report_id

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
    display = getattr(comp, "display", None)
    if comp.type == "chart" and display is not None:
        if hasattr(display, "model_dump"):
            base["display"] = display.model_dump(by_alias=True)
        elif isinstance(display, dict):
            base["display"] = display
    if comp.type == "kpi_group" and _kpi_group_is_per_item(comp):
        return _run_kpi_group_per_item(
            db,
            comp,
            base=base,
            study_id=study_id,
            job_window=job_window,
            execution_anchor=execution_anchor,
            study_start_date=study_start_date,
            timezone=timezone,
            config=config,
        )
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


def _kpi_group_is_per_item(comp: Any) -> bool:
    items = (comp.display or {}).get("items") or []
    for item in items:
        if isinstance(item, dict) and item.get("query") is not None:
            return True
    return False


def _run_kpi_group_per_item(
    db: Session,
    comp: Any,
    *,
    base: dict[str, Any],
    study_id: str,
    job_window: ResolvedTimeWindow,
    execution_anchor: str,
    study_start_date: str | None,
    timezone: str,
    config: ReportingConfig,
) -> dict[str, Any]:
    items_out: list[dict[str, Any]] = []
    for item in (comp.display or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip() or "KPI"
        raw_q = item.get("query")
        entry: dict[str, Any] = {"label": label}
        if raw_q is None:
            entry["error"] = "Missing query"
            items_out.append(entry)
            continue
        try:
            query = raw_q if hasattr(raw_q, "window") else Query.model_validate(raw_q)
            window = _component_window(
                query_window_preset=query.window,
                job_window=job_window,
                execution_anchor=execution_anchor,
                timezone=timezone,
                study_start_date=study_start_date,
                max_range_days=config.time_range_max_days,
            )
            raw = run_query(
                db,
                query,
                study_id=study_id,
                window=window,
                config=config,
            )
            entry["value"] = _scalar_from_query_result(raw, item)
        except (QueryError, TimeWindowError, ValueError) as exc:
            entry["error"] = str(exc)
        items_out.append(entry)
    base["data"] = {"items": items_out}
    return base


def _scalar_from_query_result(raw: Any, item: dict[str, Any]) -> Any:
    """Pick a single number from an ungrouped measure query."""
    field = item.get("field")
    if isinstance(raw, dict):
        if isinstance(field, str) and field in raw:
            return raw[field]
        if len(raw) == 1:
            return next(iter(raw.values()))
        # Prefer a measure named value, else first measure id from the query.
        if "value" in raw:
            return raw["value"]
        return next(iter(raw.values()), None)
    return raw


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
        # Legacy shared-query mode: map measure ids → labels for glance UI.
        if isinstance(raw, dict):
            items = (comp.display or {}).get("items") or []
            if items and all(
                isinstance(it, dict) and it.get("query") is None for it in items
            ):
                shaped: list[dict[str, Any]] = []
                for it in items:
                    label = str(it.get("label") or "").strip() or "KPI"
                    field = it.get("field")
                    value = raw.get(field) if isinstance(field, str) else None
                    shaped.append({"label": label, "value": value})
                return {"items": shaped}
            return raw
        return raw
    # table / chart / progress
    return raw


def _run_narrative(comp: Any, datasets: dict[str, Any]) -> dict[str, Any]:
    """Legacy single-comp helper — deterministic text only (no LLM)."""
    return {
        "id": comp.id,
        "type": "narrative",
        "data": {"text": _deterministic_narrative(comp, datasets)},
    }


def _generate_narratives(
    db: Session,
    comps: list[Any],
    datasets: dict[str, Any],
    *,
    report_title: str,
) -> dict[str, str]:
    """Prefer analyst LLM; fall back per-component to deterministic summaries."""
    fallback = {comp.id: _deterministic_narrative(comp, datasets) for comp in comps}
    if not comps:
        return fallback
    try:
        from app.services.reporting.planner import _default_llm_invoker
        from app.services.reporting.prompt_seeds import (
            DEFAULT_ANALYST_PROMPT,
            REPORT_ANALYST_PROMPT_ID,
            resolve_prompt_content,
        )

        system = resolve_prompt_content(
            db, REPORT_ANALYST_PROMPT_ID, default=DEFAULT_ANALYST_PROMPT
        )
        requests = []
        for comp in comps:
            display = comp.display if isinstance(comp.display, dict) else {}
            uses = list(comp.uses or [])
            requests.append(
                {
                    "id": comp.id,
                    "instruction": display.get("instruction")
                    or display.get("role")
                    or "Write a short insight from the linked datasets.",
                    "maxWords": display.get("maxWords") or 120,
                    "uses": uses,
                    "datasets": {uid: datasets.get(uid) for uid in uses},
                }
            )
        user = json.dumps(
            {
                "reportTitle": report_title,
                "components": requests,
                "rules": [
                    "Use only the supplied datasets — never invent figures.",
                    "If a rate/percentage is not in the data, describe counts instead.",
                    "Plain paragraphs only; no markdown.",
                ],
            },
            default=str,
        )
        invoker = _default_llm_invoker(db)
        reply = invoker(system=system, user=user, purpose="narrative")
    except Exception as exc:
        logger.warning("narrative_llm_failed", error=str(exc))
        return fallback

    out = dict(fallback)
    if not isinstance(reply, dict):
        return out
    for comp in comps:
        raw = reply.get(comp.id)
        if isinstance(raw, str) and raw.strip():
            out[comp.id] = raw.strip()
        elif isinstance(raw, dict):
            text = raw.get("text") or raw.get("body") or raw.get("prose")
            if isinstance(text, str) and text.strip():
                out[comp.id] = text.strip()
    return out


def _deterministic_narrative(comp: Any, datasets: dict[str, Any]) -> str:
    """Data-only prose when the analyst LLM is unavailable."""
    uses = list(comp.uses or [])
    chunks: list[str] = []
    for uid in uses:
        summary = _summarize_dataset(uid, datasets.get(uid))
        if summary:
            chunks.append(summary)
    if chunks:
        return " ".join(chunks)
    instruction = ""
    if isinstance(comp.display, dict):
        instruction = str(comp.display.get("instruction") or "").strip()
    if instruction:
        return (
            f"Linked datasets for this insight are empty, so the requested note "
            f"({instruction}) cannot be filled from numbers yet."
        )
    return "No linked data was available for this narrative."


def _summarize_dataset(uid: str, data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        bits = []
        for item in data["items"][:6]:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            value = item.get("value")
            if label is not None:
                bits.append(f"{label} {value}")
        if bits:
            return f"{uid.replace('_', ' ')}: " + "; ".join(bits) + "."
        return ""

    if not isinstance(data, list) or not data:
        return ""

    rows = [row for row in data if isinstance(row, dict)]
    if not rows:
        return ""

    # Coverage: submissions vs target by tool
    if "target" in rows[0] and ("total" in rows[0] or "toolCode" in rows[0]):
        behind: list[str] = []
        ahead: list[str] = []
        unknown = 0
        for row in rows:
            tool = row.get("toolCode") or row.get("tool_code") or "(unknown)"
            total = row.get("total")
            target = row.get("target")
            if not isinstance(total, (int, float)):
                continue
            if not isinstance(target, (int, float)) or target <= 0:
                unknown += 1
                continue
            label = str(tool)
            if total < target:
                behind.append(f"{label} ({int(total):,}/{int(target):,})")
            else:
                ahead.append(f"{label} ({int(total):,}/{int(target):,})")
        parts = ["Against plan, cumulative submissions by tool:"]
        if behind:
            parts.append(
                "behind target — " + ", ".join(behind[:5]) + ("…" if len(behind) > 5 else "") + "."
            )
        else:
            parts.append("no tools are behind their target.")
        if ahead:
            parts.append(
                "At or above target — " + ", ".join(ahead[:4]) + ("…" if len(ahead) > 4 else "") + "."
            )
        if unknown:
            parts.append(f"{unknown} tool row(s) have no usable target.")
        return " ".join(parts)

    # Flag volume by day (counts — not a computed rate)
    if "day" in rows[0] and "total" in rows[0]:
        ordered = sorted(rows, key=lambda r: str(r.get("day") or ""))
        first = ordered[0]
        last = ordered[-1]
        first_n = first.get("total")
        last_n = last.get("total")
        if isinstance(first_n, (int, float)) and isinstance(last_n, (int, float)):
            direction = (
                "rose"
                if last_n > first_n
                else "fell"
                if last_n < first_n
                else "was unchanged"
            )
            return (
                f"Flag counts by study day {direction} from {int(first_n):,} on "
                f"{first.get('day')} to {int(last_n):,} on {last.get('day')} "
                f"({len(ordered)} day(s) with flags). "
                f"These are flag volumes, not a percentage flag rate."
            )

    # Generic short table summary
    n = len(rows)
    keys = [k for k in rows[0].keys() if k != "id"][:3]
    preview = ", ".join(f"{k}={rows[0].get(k)}" for k in keys)
    return f"{uid.replace('_', ' ')} has {n} row(s); e.g. {preview}."

