"""Report specification catalog and report template endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReportTemplate, ReportTemplateVersion, Study
from app.db.session import get_db
from app.domain.report_spec.catalog import build_catalog
from app.domain.report_spec.context import ReportKind
from app.domain.report_spec.validation import parse_spec
from app.schemas.common import OkResponse
from app.schemas.report_templates import (
    CreateReportTemplateInput,
    ExecuteTemplateInput,
    ExecuteTemplateResultOut,
    ExecutedReportOut,
    ReportTemplateDetailOut,
    ReportTemplateMetaInput,
    ReportTemplateOut,
    ReportTemplateVersionOut,
    SpecCatalogOut,
    TemplatePlanResultOut,
    UpdateReportTemplatePromptInput,
)
from app.services import report_templates as templates_service
from app.services.report_dates import extract_report_date, study_start_date
from app.services.report_execution import build_context
from app.services.report_planner import plan_spec, plan_spec_stream
from app.services.report_runs import record_run
from app.services.report_tools import all_descriptors
from app.services.settings import get_or_create_settings

logger = logging.getLogger(__name__)

catalog_router = APIRouter(prefix="/report-spec", tags=["report-spec"])
router = APIRouter(prefix="/report-templates", tags=["report-templates"])

_VALID_KINDS: set[str] = {"daily", "final", "adhoc"}


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_study(db: Session, study_id: str | None) -> Study:
    if study_id:
        study = db.get(Study, study_id)
        if study is None:
            raise HTTPException(status_code=404, detail=f"Study not found: {study_id}")
        return study
    study = db.scalars(select(Study).order_by(Study.created_at)).first()
    if study is None:
        raise HTTPException(status_code=400, detail="No study exists yet")
    return study


def _kind(value: str | None, default: str = "adhoc") -> ReportKind:
    kind = (value or default).strip().lower()
    if kind not in _VALID_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"reportKind must be one of {', '.join(sorted(_VALID_KINDS))}",
        )
    return kind  # type: ignore[return-value]


def _template_or_404(db: Session, template_id: str) -> ReportTemplate:
    template = db.get(ReportTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Report template not found")
    return template


def _version_out(
    db: Session, version: ReportTemplateVersion, *, with_changes: bool = False
) -> ReportTemplateVersionOut:
    changes: list[str] = []
    if with_changes:
        previous = (
            templates_service.get_version(db, version.template_id, version.version - 1)
            if version.version > 1
            else None
        )
        changes = templates_service.diff_versions(previous, version)
    return ReportTemplateVersionOut(
        id=version.id,
        template_id=version.template_id,
        version=version.version,
        prompt_text=version.prompt_text,
        spec=version.spec_json or {},
        spec_version=version.spec_version,
        planner_model=version.planner_model,
        source=version.source,
        notes=version.notes,
        changes=changes,
        created_at=_iso(version.created_at),
    )


def _summary_out(db: Session, template: ReportTemplate) -> ReportTemplateOut:
    data = templates_service.template_summary(db, template)
    return ReportTemplateOut(
        id=data["id"],
        name=data["name"],
        description=data["description"],
        study_id=data["study_id"],
        report_kind=data["report_kind"],
        status=data["status"],
        is_system=data["is_system"],
        version_count=data["version_count"],
        current_version=data["current_version"],
        prompt_text=data["prompt_text"],
        default_execution_date=data.get("default_execution_date"),
        created_at=_iso(data["created_at"]),
        updated_at=_iso(data["updated_at"]),
    )


def _default_execution_date_for_prompt(
    db: Session, prompt: str, study_id: str | None
) -> str | None:
    study = db.get(Study, study_id) if study_id else None
    return extract_report_date(
        prompt,
        study_start=study_start_date(getattr(study, "start_date", None) if study else None),
    )


def _detail_out(db: Session, template: ReportTemplate) -> ReportTemplateDetailOut:
    base = _summary_out(db, template)
    versions = list(
        db.scalars(
            select(ReportTemplateVersion)
            .where(ReportTemplateVersion.template_id == template.id)
            .order_by(ReportTemplateVersion.version.desc())
        ).all()
    )
    return ReportTemplateDetailOut(
        **base.model_dump(by_alias=False),
        spec=(versions[0].spec_json or {}) if versions else {},
        versions=[_version_out(db, version, with_changes=True) for version in versions],
    )


# --- Catalog ----------------------------------------------------------------


@catalog_router.get("/catalog", response_model=SpecCatalogOut, operation_id="getReportSpecCatalog")
def get_catalog(
    include_schema: bool = Query(default=False, alias="includeSchema"),
) -> SpecCatalogOut:
    """Component types and business data sources a report may use."""
    catalog = build_catalog(all_descriptors(), include_schema=include_schema)
    return SpecCatalogOut(
        spec_version=catalog.spec_version,
        component_types=catalog.component_types,
        components=catalog.components,
        data_sources=catalog.data_sources,
        spec_schema=catalog.spec_schema,
    )


# --- Templates --------------------------------------------------------------


@router.get("", response_model=list[ReportTemplateOut], operation_id="listReportTemplates")
def list_templates(
    study_id: str | None = Query(default=None, alias="studyId"),
    report_kind: str | None = Query(default=None, alias="reportKind"),
    db: Session = Depends(get_db),
) -> list[ReportTemplateOut]:
    statement = select(ReportTemplate).order_by(ReportTemplate.created_at.desc())
    if study_id:
        statement = statement.where(ReportTemplate.study_id == study_id)
    if report_kind:
        statement = statement.where(ReportTemplate.report_kind == _kind(report_kind))
    return [_summary_out(db, row) for row in db.scalars(statement).all()]


def _plan_result_out(result) -> TemplatePlanResultOut:
    return TemplatePlanResultOut(
        status=result.status,
        question=result.question,
        reason=result.reason,
        errors=result.errors,
        warnings=result.warnings,
        summary=result.summary,
    )


@router.post(
    "/create/stream",
    operation_id="createReportTemplateStream",
    response_model=None,
)
def create_template_stream(
    payload: CreateReportTemplateInput,
    db: Session = Depends(get_db),
):
    """SSE stream of planner progress, then the same create result as POST /report-templates."""
    import json

    kind = _kind(payload.report_kind)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if payload.spec is None and not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt or spec is required")

    def event_gen():
        try:
            if payload.spec is not None:
                yield (
                    "event: progress\ndata: "
                    + json.dumps(
                        {
                            "phase": "parse",
                            "message": "Validating the supplied specification…",
                        }
                    )
                    + "\n\n"
                )
                parsed = parse_spec(payload.spec)
                if parsed.spec is None:
                    body = TemplatePlanResultOut(
                        status="invalid",
                        errors=parsed.errors,
                        warnings=parsed.warnings,
                    )
                    yield (
                        "event: result\ndata: "
                        + json.dumps(body.model_dump(by_alias=True), default=str)
                        + "\n\n"
                    )
                    return
                spec = parsed.spec
                planner_model = None
                planner_prompt_id = None
                summary = "Specification supplied directly."
                warnings = parsed.warnings
            else:
                result = None
                for event in plan_spec_stream(
                    db, instructions=payload.prompt, report_kind=kind
                ):
                    name = str(event.get("event") or "message")
                    if name == "result":
                        result = event.get("result")
                        continue
                    if name == "error":
                        yield (
                            f"event: error\ndata: "
                            + json.dumps(
                                {
                                    "message": event.get("message") or "Planning failed",
                                    "code": event.get("code") or "plan_stream_error",
                                }
                            )
                            + "\n\n"
                        )
                        return
                    data = {k: v for k, v in event.items() if k != "event"}
                    yield f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"

                if result is None:
                    yield (
                        'event: error\ndata: {"message": "Planner stream ended without a result", '
                        '"code": "plan_stream_error"}\n\n'
                    )
                    return

                record_run(
                    db,
                    mode="plan",
                    status=result.status,
                    study_id=payload.study_id,
                    provider=result.telemetry.provider,
                    model=result.telemetry.model,
                    prompt_id=result.telemetry.prompt_id,
                    attempts=result.telemetry.attempts,
                    prompt_tokens=result.telemetry.prompt_tokens,
                    completion_tokens=result.telemetry.completion_tokens,
                    latency_ms=result.telemetry.latency_ms,
                    structured_output=result.telemetry.structured_output,
                    validation_errors=result.error_dicts(),
                    error=result.reason,
                )
                if not result.ok:
                    body = _plan_result_out(result)
                    yield (
                        "event: result\ndata: "
                        + json.dumps(body.model_dump(by_alias=True), default=str)
                        + "\n\n"
                    )
                    return

                yield (
                    "event: progress\ndata: "
                    + json.dumps(
                        {"phase": "save", "message": "Saving the template…"}
                    )
                    + "\n\n"
                )
                spec = result.spec
                planner_model = result.telemetry.model
                planner_prompt_id = result.telemetry.prompt_id
                summary = result.summary
                warnings = result.warnings

            try:
                template, _version = templates_service.create_template(
                    db,
                    name=payload.name.strip(),
                    description=payload.description,
                    prompt_text=payload.prompt,
                    spec=spec,
                    study_id=payload.study_id,
                    report_kind=kind,
                    source="conversation" if payload.spec is not None else "template",
                    planner_model=planner_model,
                    planner_prompt_id=planner_prompt_id,
                    default_execution_date=_default_execution_date_for_prompt(
                        db, payload.prompt, payload.study_id
                    ),
                )
            except templates_service.TemplateError as exc:
                body = TemplatePlanResultOut(
                    status="invalid", reason=str(exc), errors=exc.issues
                )
                yield (
                    "event: result\ndata: "
                    + json.dumps(body.model_dump(by_alias=True), default=str)
                    + "\n\n"
                )
                return

            body = TemplatePlanResultOut(
                status="ok",
                template=_detail_out(db, template),
                summary=summary,
                warnings=warnings,
            )
            yield (
                "event: result\ndata: "
                + json.dumps(body.model_dump(by_alias=True), default=str)
                + "\n\n"
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Template create stream failed")
            yield (
                "event: error\ndata: "
                + json.dumps({"message": str(exc), "code": "stream_error"})
                + "\n\n"
            )

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("", response_model=TemplatePlanResultOut, operation_id="createReportTemplate")
def create_template(
    payload: CreateReportTemplateInput,
    db: Session = Depends(get_db),
) -> TemplatePlanResultOut:
    """Plan a specification from the prompt (or accept one directly) and save v1."""
    kind = _kind(payload.report_kind)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name is required")

    if payload.spec is not None:
        parsed = parse_spec(payload.spec)
        if parsed.spec is None:
            return TemplatePlanResultOut(
                status="invalid", errors=parsed.errors, warnings=parsed.warnings
            )
        spec = parsed.spec
        planner_model = None
        planner_prompt_id = None
        summary = "Specification supplied directly."
        warnings = parsed.warnings
    else:
        if not payload.prompt.strip():
            raise HTTPException(status_code=400, detail="prompt or spec is required")
        result = plan_spec(db, instructions=payload.prompt, report_kind=kind)
        record_run(
            db,
            mode="plan",
            status=result.status,
            study_id=payload.study_id,
            provider=result.telemetry.provider,
            model=result.telemetry.model,
            prompt_id=result.telemetry.prompt_id,
            attempts=result.telemetry.attempts,
            prompt_tokens=result.telemetry.prompt_tokens,
            completion_tokens=result.telemetry.completion_tokens,
            latency_ms=result.telemetry.latency_ms,
            structured_output=result.telemetry.structured_output,
            validation_errors=result.error_dicts(),
            error=result.reason,
        )
        if not result.ok:
            return TemplatePlanResultOut(
                status=result.status,
                question=result.question,
                reason=result.reason,
                errors=result.errors,
                warnings=result.warnings,
            )
        spec = result.spec
        planner_model = result.telemetry.model
        planner_prompt_id = result.telemetry.prompt_id
        summary = result.summary
        warnings = result.warnings

    try:
        template, _version = templates_service.create_template(
            db,
            name=payload.name.strip(),
            description=payload.description,
            prompt_text=payload.prompt,
            spec=spec,
            study_id=payload.study_id,
            report_kind=kind,
            source="conversation" if payload.spec is not None else "template",
            planner_model=planner_model,
            planner_prompt_id=planner_prompt_id,
            default_execution_date=_default_execution_date_for_prompt(
                db, payload.prompt, payload.study_id
            ),
        )
    except templates_service.TemplateError as exc:
        return TemplatePlanResultOut(status="invalid", reason=str(exc), errors=exc.issues)

    return TemplatePlanResultOut(
        status="ok",
        template=_detail_out(db, template),
        summary=summary,
        warnings=warnings,
    )


@router.get("/{template_id}", response_model=ReportTemplateDetailOut, operation_id="getReportTemplate")
def get_template(template_id: str, db: Session = Depends(get_db)) -> ReportTemplateDetailOut:
    return _detail_out(db, _template_or_404(db, template_id))


@router.patch(
    "/{template_id}", response_model=ReportTemplateDetailOut, operation_id="updateReportTemplate"
)
def update_template(
    template_id: str,
    payload: ReportTemplateMetaInput,
    db: Session = Depends(get_db),
) -> ReportTemplateDetailOut:
    template = _template_or_404(db, template_id)
    if payload.name is not None:
        template.name = payload.name.strip() or template.name
    if payload.description is not None:
        template.description = payload.description
    if payload.status is not None:
        if payload.status not in {"active", "archived"}:
            raise HTTPException(status_code=400, detail="status must be active or archived")
        template.status = payload.status
    db.commit()
    db.refresh(template)
    return _detail_out(db, template)


@router.put(
    "/{template_id}/prompt",
    response_model=TemplatePlanResultOut,
    operation_id="updateReportTemplatePrompt",
)
def update_template_prompt(
    template_id: str,
    payload: UpdateReportTemplatePromptInput,
    db: Session = Depends(get_db),
) -> TemplatePlanResultOut:
    """Re-plan from an edited prompt and append a new version."""
    template = _template_or_404(db, template_id)
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    result = plan_spec(db, instructions=payload.prompt, report_kind=template.report_kind)
    record_run(
        db,
        mode="plan",
        status=result.status,
        study_id=template.study_id,
        template_id=template.id,
        provider=result.telemetry.provider,
        model=result.telemetry.model,
        prompt_id=result.telemetry.prompt_id,
        attempts=result.telemetry.attempts,
        prompt_tokens=result.telemetry.prompt_tokens,
        completion_tokens=result.telemetry.completion_tokens,
        latency_ms=result.telemetry.latency_ms,
        structured_output=result.telemetry.structured_output,
        validation_errors=result.error_dicts(),
        error=result.reason,
    )
    if not result.ok:
        return TemplatePlanResultOut(
            status=result.status,
            question=result.question,
            reason=result.reason,
            errors=result.errors,
            warnings=result.warnings,
        )

    try:
        templates_service.add_version(
            db,
            template,
            spec=result.spec,
            prompt_text=payload.prompt,
            planner_model=result.telemetry.model,
            planner_prompt_id=result.telemetry.prompt_id,
            notes=payload.notes,
        )
    except templates_service.TemplateError as exc:
        return TemplatePlanResultOut(status="invalid", reason=str(exc), errors=exc.issues)

    template.default_execution_date = _default_execution_date_for_prompt(
        db, payload.prompt, template.study_id
    )
    db.commit()
    db.refresh(template)

    return TemplatePlanResultOut(
        status="ok",
        template=_detail_out(db, template),
        summary=result.summary,
        warnings=result.warnings,
    )


@router.get(
    "/{template_id}/versions",
    response_model=list[ReportTemplateVersionOut],
    operation_id="listReportTemplateVersions",
)
def list_versions(
    template_id: str, db: Session = Depends(get_db)
) -> list[ReportTemplateVersionOut]:
    _template_or_404(db, template_id)
    versions = db.scalars(
        select(ReportTemplateVersion)
        .where(ReportTemplateVersion.template_id == template_id)
        .order_by(ReportTemplateVersion.version.desc())
    ).all()
    return [_version_out(db, version, with_changes=True) for version in versions]


@router.get(
    "/{template_id}/versions/{version}",
    response_model=ReportTemplateVersionOut,
    operation_id="getReportTemplateVersion",
)
def get_version(
    template_id: str, version: int, db: Session = Depends(get_db)
) -> ReportTemplateVersionOut:
    _template_or_404(db, template_id)
    row = templates_service.get_version(db, template_id, version)
    if row is None:
        raise HTTPException(status_code=404, detail="Template version not found")
    return _version_out(db, row, with_changes=True)


@router.delete("/{template_id}", response_model=OkResponse, operation_id="deleteReportTemplate")
def delete_template(template_id: str, db: Session = Depends(get_db)) -> OkResponse:
    template = _template_or_404(db, template_id)
    if template.is_system:
        raise HTTPException(status_code=400, detail="System templates cannot be deleted")
    db.delete(template)
    db.commit()
    return OkResponse(success=True)


# --- Execution --------------------------------------------------------------


def _prepare(
    db: Session, template: ReportTemplate, payload: ExecuteTemplateInput
):
    study = _resolve_study(db, payload.study_id or template.study_id)
    kind = _kind(payload.report_kind or template.report_kind, template.report_kind)
    execution_date = payload.execution_date or template.default_execution_date
    context = build_context(
        study,
        report_kind=kind,
        execution_date=execution_date,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    version = None
    if payload.version is not None:
        version = templates_service.get_version(db, template.id, payload.version)
        if version is None:
            raise HTTPException(status_code=404, detail="Template version not found")
    settings = get_or_create_settings(db)
    try:
        executed, resolved_version = templates_service.execute_template(
            db,
            template,
            context,
            version=version,
            settings=settings,
            run_ai=payload.run_ai,
        )
    except templates_service.TemplateError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return executed, resolved_version


def _executed_out(
    template: ReportTemplate,
    version: ReportTemplateVersion,
    executed,
) -> ExecutedReportOut:
    narratives = executed.narratives
    return ExecutedReportOut(
        template_id=template.id,
        template_version=version.version,
        spec=executed.spec.model_dump(by_alias=True),
        data=executed.data,
        narratives=narratives.texts,
        unavailable=executed.errors,
        meta={
            "organizationName": executed.payload.meta.get("organizationName"),
            "rows": [list(row) for row in executed.payload.meta.get("rows", [])],
            "footer": executed.payload.meta.get("footer"),
        },
        html=executed.render_html(),
        plain_text=executed.render_plaintext(),
        ai_source=narratives.source,
    )


@router.post(
    "/{template_id}/preview",
    response_model=ExecutedReportOut,
    operation_id="previewReportTemplate",
)
def preview_template(
    template_id: str,
    payload: ExecuteTemplateInput,
    db: Session = Depends(get_db),
) -> ExecutedReportOut:
    """Execute a template and return the rendered result without saving a report."""
    template = _template_or_404(db, template_id)
    executed, version = _prepare(db, template, payload)
    narratives = executed.narratives
    record_run(
        db,
        mode="analyze" if narratives.source == "ai" else "execute",
        status="ok",
        study_id=executed.context.study_id,
        template_id=template.id,
        template_version_id=version.id,
        provider=narratives.provider,
        model=narratives.model,
        prompt_tokens=narratives.prompt_tokens,
        completion_tokens=narratives.completion_tokens,
        latency_ms=narratives.latency_ms,
        validation_errors=[
            {"dataSource": key, "message": message} for key, message in executed.errors.items()
        ],
        error=narratives.error,
    )
    return _executed_out(template, version, executed)


@router.get(
    "/{template_id}/preview.html",
    response_class=HTMLResponse,
    responses={200: {"content": {"text/html": {}}}},
    operation_id="previewReportTemplateHtml",
)
def preview_template_html(
    template_id: str,
    study_id: str | None = Query(default=None, alias="studyId"),
    execution_date: str | None = Query(default=None, alias="executionDate"),
    run_ai: bool = Query(default=False, alias="runAi"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Server-rendered preview for embedding in the template editor."""
    template = _template_or_404(db, template_id)
    executed, _version = _prepare(
        db,
        template,
        ExecuteTemplateInput(study_id=study_id, execution_date=execution_date, run_ai=run_ai),
    )
    return HTMLResponse(content=executed.render_html())


@router.post(
    "/{template_id}/execute",
    response_model=ExecuteTemplateResultOut,
    operation_id="executeReportTemplate",
)
def execute_template(
    template_id: str,
    payload: ExecuteTemplateInput,
    db: Session = Depends(get_db),
) -> ExecuteTemplateResultOut:
    """Execute a template, persist the report, and return the same preview payload."""
    from app.routers.reports import _map

    template = _template_or_404(db, template_id)
    executed, version = _prepare(db, template, payload)
    row = templates_service.persist_report(
        db, executed, template=template, version=version
    )
    narratives = executed.narratives
    record_run(
        db,
        mode="execute",
        status="ok" if not executed.errors else "invalid",
        study_id=executed.context.study_id,
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
    return ExecuteTemplateResultOut(
        report=_map(row),
        preview=_executed_out(template, version, executed),
    )
