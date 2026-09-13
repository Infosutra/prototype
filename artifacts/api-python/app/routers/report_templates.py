"""Report specification catalog and report template endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, get_args

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReportTemplate, ReportTemplateVersion, Study
from app.db.session import get_db
from app.domain.reporting.catalog import (
    ANSWER_FIELDS,
    FLAG_FIELDS,
    SUBMISSION_FIELDS,
)
from app.domain.reporting.spec import ComponentType, ReportSpec
from app.schemas.common import OkResponse
from app.schemas.report_templates import (
    CreateReportTemplateInput,
    ReportTemplateDetailOut,
    ReportTemplateMetaInput,
    ReportTemplateOut,
    ReportTemplateVersionOut,
    SpecCatalogComponentOut,
    SpecCatalogOut,
    SpecCatalogSourceOut,
    SpecIssueOut,
    TemplatePlanResultOut,
    UpdateReportTemplatePromptInput,
)
from app.services import report_templates as templates_service
from app.services.report_dates import extract_report_date, study_start_date

catalog_router = APIRouter(prefix="/report-spec", tags=["report-spec"])
router = APIRouter(prefix="/report-templates", tags=["report-templates"])

_VALID_KINDS: set[str] = {"daily", "final", "adhoc"}
ReportKind = Literal["daily", "final", "adhoc"]
COMPONENT_TYPES = list(get_args(ComponentType))


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


@catalog_router.get("/catalog", response_model=SpecCatalogOut, operation_id="getReportSpecCatalog")
def get_catalog(
    include_schema: bool = Query(default=False, alias="includeSchema"),
) -> SpecCatalogOut:
    """Query IR component types and entity field allowlists (no certified tools)."""
    components = [
        SpecCatalogComponentOut(type=t, description=f"ReportSpec component type '{t}'")
        for t in sorted(COMPONENT_TYPES)
    ]
    data_sources = [
        SpecCatalogSourceOut(
            id="submission",
            title="Submissions",
            kind="entity",
            description="Submission aggregates and quality facts",
            fields=sorted(SUBMISSION_FIELDS),
        ),
        SpecCatalogSourceOut(
            id="flag",
            title="DQA flags",
            kind="entity",
            description="DQA flag rows",
            fields=sorted(FLAG_FIELDS),
        ),
        SpecCatalogSourceOut(
            id="answer",
            title="Answers",
            kind="entity",
            description="Projected form answers",
            fields=sorted(ANSWER_FIELDS),
        ),
    ]
    return SpecCatalogOut(
        spec_version="1.0",
        component_types=sorted(COMPONENT_TYPES),
        components=components,
        data_sources=data_sources,
        spec_schema=ReportSpec.model_json_schema() if include_schema else {},
    )


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


def _spec_issues(issues: list) -> list[SpecIssueOut]:
    out: list[SpecIssueOut] = []
    for issue in issues or []:
        if isinstance(issue, SpecIssueOut):
            out.append(issue)
            continue
        if hasattr(issue, "path"):
            out.append(
                SpecIssueOut(
                    path=getattr(issue, "path", "$"),
                    code=getattr(issue, "code", "invalid"),
                    message=getattr(issue, "message", str(issue)),
                )
            )
            continue
        out.append(SpecIssueOut(path="$", code="invalid", message=str(issue)))
    return out


@router.post("", response_model=TemplatePlanResultOut, operation_id="createReportTemplate")
def create_template(
    payload: CreateReportTemplateInput,
    db: Session = Depends(get_db),
) -> TemplatePlanResultOut:
    """Save a pre-planned ReportSpec as a new template (no LLM on this path)."""
    kind = _kind(payload.report_kind)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if payload.spec is None:
        raise HTTPException(
            status_code=400,
            detail="spec is required. Plan via POST /jobs type=plan, then save the result.",
        )
    if not payload.study_id:
        raise HTTPException(status_code=400, detail="studyId is required")

    try:
        template, _version = templates_service.create_template(
            db,
            name=payload.name.strip(),
            description=payload.description,
            prompt_text=payload.prompt,
            spec=payload.spec,
            study_id=payload.study_id,
            report_kind=kind,
            source="template",
            default_execution_date=_default_execution_date_for_prompt(
                db, payload.prompt, payload.study_id
            ),
        )
    except templates_service.TemplateError as exc:
        return TemplatePlanResultOut(
            status="invalid",
            reason=str(exc),
            errors=_spec_issues(exc.issues),
        )

    return TemplatePlanResultOut(
        status="ok",
        template=_detail_out(db, template),
        spec=payload.spec,
        summary="Template saved.",
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
    """Save a pre-planned ReportSpec as a new version (no LLM on this path)."""
    template = _template_or_404(db, template_id)
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    if payload.spec is None:
        raise HTTPException(
            status_code=400,
            detail="spec is required. Plan via POST /jobs type=plan, then save.",
        )

    try:
        templates_service.parse_and_validate_spec(payload.spec)
    except templates_service.TemplateError as exc:
        return TemplatePlanResultOut(
            status="invalid", reason=str(exc), errors=_spec_issues(exc.issues)
        )

    if not payload.commit:
        return TemplatePlanResultOut(
            status="ok",
            spec=payload.spec,
            summary="Draft specification validated.",
        )

    try:
        templates_service.add_version(
            db,
            template,
            spec=payload.spec,
            prompt_text=payload.prompt,
            notes=payload.notes,
        )
    except templates_service.TemplateError as exc:
        return TemplatePlanResultOut(
            status="invalid", reason=str(exc), errors=_spec_issues(exc.issues)
        )

    template.default_execution_date = _default_execution_date_for_prompt(
        db, payload.prompt, template.study_id
    )
    db.commit()
    db.refresh(template)

    return TemplatePlanResultOut(
        status="ok",
        template=_detail_out(db, template),
        spec=payload.spec,
        summary="Template version saved.",
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


@router.post(
    "/{template_id}/versions/{version}/restore",
    response_model=ReportTemplateDetailOut,
    operation_id="restoreReportTemplateVersion",
)
def restore_template_version(
    template_id: str,
    version: int,
    db: Session = Depends(get_db),
) -> ReportTemplateDetailOut:
    """Restore an earlier version by appending a new version with its prompt and spec."""
    template = _template_or_404(db, template_id)
    try:
        restored = templates_service.restore_version(db, template, version, commit=False)
    except templates_service.TemplateError as exc:
        status = 404 if "was not found" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    template.default_execution_date = _default_execution_date_for_prompt(
        db, restored.prompt_text, template.study_id
    )
    db.commit()
    db.refresh(template)
    return _detail_out(db, template)


@router.delete("/{template_id}", response_model=OkResponse, operation_id="deleteReportTemplate")
def delete_template(template_id: str, db: Session = Depends(get_db)) -> OkResponse:
    template = _template_or_404(db, template_id)
    db.delete(template)
    db.commit()
    return OkResponse(success=True)
