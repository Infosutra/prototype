"""Report template lifecycle: create, version, resolve and execute.

A template pairs the natural-language prompt (the human definition) with the Report
Specification (the machine definition). Daily and Final flows execute a template
rather than carrying their own structure.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AppSettings,
    Project,
    Report,
    ReportProject,
    ReportTemplate,
    ReportTemplateVersion,
    Study,
)
from app.domain.report_spec.context import ReportExecutionContext, ReportKind
from app.domain.report_spec.spec import ReportSpec
from app.domain.report_spec.validation import (
    SpecIssue,
    parse_spec,
    repair_spec,
    validate_spec,
)
from app.services.report_execution import ExecutedReport, execute_spec
from app.services.report_storage import docx_path_for, pdf_path_for
from app.services.report_tools import descriptors_by_id

logger = logging.getLogger(__name__)


class TemplateError(Exception):
    """A template could not be created, loaded or executed."""

    def __init__(self, message: str, *, issues: list[SpecIssue] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Loading ----------------------------------------------------------------


def load_spec(version: ReportTemplateVersion, *, allow_repair: bool = True) -> ReportSpec:
    """Parse and validate a stored specification against the current catalog.

    Catalogs evolve; a stored spec referencing a retired data source is repaired by
    dropping the affected components rather than failing the whole report.
    """
    parsed = parse_spec(version.spec_json or {})
    if parsed.spec is None:
        raise TemplateError(
            "Stored report specification is not valid.", issues=parsed.errors
        )
    sources = descriptors_by_id()
    result = validate_spec(parsed.spec, sources)
    if result.valid:
        return parsed.spec
    if not allow_repair:
        raise TemplateError("Stored report specification is not valid.", issues=result.errors)
    repaired, notes = repair_spec(parsed.spec, sources)
    logger.warning(
        "Repaired stored spec for template version %s: %s",
        version.id,
        "; ".join(note.message for note in notes) or "no changes",
    )
    if not repaired.sections:
        raise TemplateError(
            "Stored report specification has no executable components.",
            issues=result.errors,
        )
    return repaired


def current_version(db: Session, template: ReportTemplate) -> ReportTemplateVersion:
    if template.current_version_id:
        version = db.get(ReportTemplateVersion, template.current_version_id)
        if version is not None:
            return version
    version = db.scalars(
        select(ReportTemplateVersion)
        .where(ReportTemplateVersion.template_id == template.id)
        .order_by(ReportTemplateVersion.version.desc())
    ).first()
    if version is None:
        raise TemplateError(f"Template '{template.name}' has no versions.")
    return version


def get_version(
    db: Session, template_id: str, version_number: int
) -> ReportTemplateVersion | None:
    return db.scalars(
        select(ReportTemplateVersion).where(
            ReportTemplateVersion.template_id == template_id,
            ReportTemplateVersion.version == version_number,
        )
    ).first()


# --- Creation and versioning ------------------------------------------------


def validate_or_raise(spec: ReportSpec) -> None:
    result = validate_spec(spec, descriptors_by_id())
    if not result.valid:
        raise TemplateError(
            "Report specification failed validation.", issues=result.errors
        )


def create_template(
    db: Session,
    *,
    name: str,
    spec: ReportSpec,
    prompt_text: str = "",
    description: str = "",
    study_id: str | None = None,
    report_kind: ReportKind = "adhoc",
    source: str = "template",
    planner_model: str | None = None,
    planner_prompt_id: str | None = None,
    template_id: str | None = None,
    is_system: bool = False,
    notes: str = "",
    default_execution_date: str | None = None,
    commit: bool = True,
) -> tuple[ReportTemplate, ReportTemplateVersion]:
    validate_or_raise(spec)
    template = ReportTemplate(
        id=template_id or str(uuid.uuid4()),
        name=name,
        description=description,
        study_id=study_id,
        report_kind=report_kind,
        status="active",
        is_system=is_system,
        default_execution_date=default_execution_date,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(template)
    db.flush()
    version = _append_version(
        db,
        template,
        spec=spec,
        prompt_text=prompt_text,
        source=source,
        planner_model=planner_model,
        planner_prompt_id=planner_prompt_id,
        notes=notes,
        version_number=1,
    )
    if commit:
        db.commit()
        db.refresh(template)
    return template, version


def add_version(
    db: Session,
    template: ReportTemplate,
    *,
    spec: ReportSpec,
    prompt_text: str = "",
    source: str = "template",
    planner_model: str | None = None,
    planner_prompt_id: str | None = None,
    notes: str = "",
    commit: bool = True,
) -> ReportTemplateVersion:
    """Append a new version. Earlier versions are never modified or removed."""
    validate_or_raise(spec)
    latest = db.scalars(
        select(ReportTemplateVersion)
        .where(ReportTemplateVersion.template_id == template.id)
        .order_by(ReportTemplateVersion.version.desc())
    ).first()
    next_number = (latest.version + 1) if latest else 1
    version = _append_version(
        db,
        template,
        spec=spec,
        prompt_text=prompt_text,
        source=source,
        planner_model=planner_model,
        planner_prompt_id=planner_prompt_id,
        notes=notes,
        version_number=next_number,
    )
    if commit:
        db.commit()
    return version


def _append_version(
    db: Session,
    template: ReportTemplate,
    *,
    spec: ReportSpec,
    prompt_text: str,
    source: str,
    planner_model: str | None,
    planner_prompt_id: str | None,
    notes: str,
    version_number: int,
) -> ReportTemplateVersion:
    version = ReportTemplateVersion(
        id=str(uuid.uuid4()),
        template_id=template.id,
        version=version_number,
        prompt_text=prompt_text or "",
        spec_json=spec.model_dump(by_alias=True),
        spec_version=spec.spec_version,
        planner_model=planner_model,
        planner_prompt_id=planner_prompt_id,
        source=source,
        notes=notes or "",
        created_at=_now(),
    )
    db.add(version)
    db.flush()
    template.current_version_id = version.id
    template.updated_at = _now()
    return version


def diff_versions(
    previous: ReportTemplateVersion | None, current: ReportTemplateVersion
) -> list[str]:
    """Plain-language summary of what changed between two template versions."""
    if previous is None:
        return ["Initial version."]
    old = parse_spec(previous.spec_json or {}).spec
    new = parse_spec(current.spec_json or {}).spec
    if old is None or new is None:
        return ["Specification changed."]
    changes: list[str] = []
    if old.title != new.title:
        changes.append(f"Title changed from '{old.title}' to '{new.title}'.")
    old_sections = {s.title for s in old.sections}
    new_sections = {s.title for s in new.sections}
    for title in sorted(new_sections - old_sections):
        changes.append(f"Added section '{title}'.")
    for title in sorted(old_sections - new_sections):
        changes.append(f"Removed section '{title}'.")
    old_count = old.component_count()
    new_count = new.component_count()
    if old_count != new_count:
        changes.append(f"Components changed from {old_count} to {new_count}.")
    old_sources = set(old.data_source_ids())
    new_sources = set(new.data_source_ids())
    for source_id in sorted(new_sources - old_sources):
        changes.append(f"Now uses data source '{source_id}'.")
    for source_id in sorted(old_sources - new_sources):
        changes.append(f"No longer uses data source '{source_id}'.")
    if previous.prompt_text != current.prompt_text:
        changes.append("Prompt text edited.")
    return changes or ["No structural change."]


# --- Resolution -------------------------------------------------------------


def resolve_template(
    db: Session, study: Study, kind: ReportKind
) -> ReportTemplate | None:
    """Template a study should use for a report kind.

    Study assignment wins, then a study-scoped template, then the seeded system
    template for that kind.
    """
    assigned_id = (
        study.daily_report_template_id if kind == "daily" else study.final_report_template_id
    )
    if assigned_id:
        template = db.get(ReportTemplate, assigned_id)
        if template is not None:
            return template
    scoped = db.scalars(
        select(ReportTemplate)
        .where(
            ReportTemplate.study_id == study.id,
            ReportTemplate.report_kind == kind,
            ReportTemplate.status == "active",
        )
        .order_by(ReportTemplate.created_at)
    ).first()
    if scoped is not None:
        return scoped
    return db.scalars(
        select(ReportTemplate)
        .where(
            ReportTemplate.is_system.is_(True),
            ReportTemplate.report_kind == kind,
            ReportTemplate.status == "active",
        )
        .order_by(ReportTemplate.created_at)
    ).first()


# --- Execution and persistence ----------------------------------------------


def execute_template(
    db: Session,
    template: ReportTemplate,
    context: ReportExecutionContext,
    *,
    version: ReportTemplateVersion | None = None,
    settings: AppSettings | None = None,
    run_ai: bool = True,
    style_guidance: str | None = None,
    stats: dict[str, Any] | None = None,
) -> tuple[ExecutedReport, ReportTemplateVersion]:
    version = version or current_version(db, template)
    spec = load_spec(version)
    executed = execute_spec(
        db,
        spec,
        context,
        settings=settings,
        run_ai=run_ai,
        style_guidance=style_guidance,
        stats=stats,
    )
    return executed, version


_REPORT_TYPE_BY_KIND: dict[str, str] = {
    "daily": "daily_dqa",
    "final": "final_dqa",
    "adhoc": "custom",
}


def persist_report(
    db: Session,
    executed: ExecutedReport,
    *,
    template: ReportTemplate | None = None,
    version: ReportTemplateVersion | None = None,
    title: str | None = None,
    description: str = "",
    prompt_id: str | None = None,
    prompt_name: str | None = None,
    report_type: str | None = None,
    commit: bool = True,
) -> Report:
    """Write rendered artifacts to disk and record the Report row."""
    context = executed.context
    html_body = executed.render_html()
    plain = executed.render_plaintext()
    pdf_bytes = executed.render_pdf()
    docx_bytes = executed.render_docx()

    report_id = str(uuid.uuid4())
    pdf_path_for(report_id).write_bytes(pdf_bytes)
    docx_path_for(report_id).write_bytes(docx_bytes)

    payload = {
        "spec": executed.spec.model_dump(by_alias=True),
        "data": executed.data,
        "html": html_body,
        "plainText": plain,
        "aiSource": executed.narratives.source,
        "unavailable": executed.errors,
    }
    now = _now()
    row = Report(
        id=report_id,
        title=title or executed.spec.title,
        description=description,
        status="ready",
        format="pdf",
        report_type=report_type or _REPORT_TYPE_BY_KIND.get(context.report_kind, "custom"),
        study_id=context.study_id,
        report_date=context.execution_date,
        prompt_id=prompt_id,
        prompt_name=prompt_name,
        template_id=template.id if template else None,
        template_version_id=version.id if version else None,
        spec_json=executed.spec.model_dump(by_alias=True),
        execution_context_json=context.model_dump(by_alias=True),
        generated_content=json.dumps(payload, default=str),
        download_url=f"/api/reports/{report_id}/download",
        page_count=max(1, 1 + executed.spec.component_count() // 6),
        file_size_kb=round(len(pdf_bytes) / 1024, 1),
        generated_at=now,
        created_at=now,
    )
    db.add(row)
    db.flush()
    projects = list(
        db.scalars(select(Project).where(Project.study_id == context.study_id)).all()
    )
    for project in projects:
        row.report_projects.append(
            ReportProject(project_id=project.id, project_name=project.name)
        )
    if commit:
        db.commit()
        db.refresh(row)
    return row


def template_summary(db: Session, template: ReportTemplate) -> dict[str, Any]:
    versions = list(
        db.scalars(
            select(ReportTemplateVersion)
            .where(ReportTemplateVersion.template_id == template.id)
            .order_by(ReportTemplateVersion.version.desc())
        ).all()
    )
    latest = versions[0] if versions else None
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "study_id": template.study_id,
        "report_kind": template.report_kind,
        "status": template.status,
        "is_system": template.is_system,
        "version_count": len(versions),
        "current_version": latest.version if latest else 0,
        "prompt_text": latest.prompt_text if latest else "",
        "default_execution_date": template.default_execution_date,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }
