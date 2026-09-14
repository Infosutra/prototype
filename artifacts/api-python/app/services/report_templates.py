"""Report template lifecycle: create, version, and resolve ReportSpec 1.0.

Authoring saves a pre-planned ReportSpec. Planning and execute run via jobs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReportTemplate, ReportTemplateVersion
from app.domain.reporting.spec import ReportSpec
from app.domain.reporting.validation import validate_report_spec

logger = structlog.stdlib.get_logger(__name__)

ReportKind = Literal["daily", "final", "adhoc"]


class TemplateError(Exception):
    """A template could not be created, loaded or executed."""

    def __init__(self, message: str, *, issues: list[Any] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SpecIssue:
    def __init__(self, path: str, code: str, message: str) -> None:
        self.path = path
        self.code = code
        self.message = message


def _issues_from_strings(messages: list[str]) -> list[SpecIssue]:
    return [SpecIssue(path="$", code="invalid", message=msg) for msg in messages]


def is_report_spec_v1(payload: dict[str, Any] | ReportSpec | Any) -> bool:
    if isinstance(payload, ReportSpec):
        return True
    if isinstance(payload, dict):
        return str(payload.get("specVersion") or payload.get("spec_version") or "") == "1.0"
    version = getattr(payload, "spec_version", None)
    return str(version or "") == "1.0"


def parse_and_validate_spec(
    payload: dict[str, Any] | ReportSpec,
) -> tuple[dict[str, Any], str]:
    """Return (spec_json camelCase, spec_version). Raises TemplateError on failure."""
    if isinstance(payload, ReportSpec):
        data = payload.model_dump(by_alias=True)
        errors = validate_report_spec(data)
        if errors:
            raise TemplateError(
                "Report specification failed validation.",
                issues=_issues_from_strings(errors),
            )
        return data, "1.0"

    if not isinstance(payload, dict):
        raise TemplateError("Report specification must be an object.")

    if not is_report_spec_v1(payload):
        raise TemplateError(
            "Only ReportSpec 1.0 is supported. Plan via POST /jobs type=plan.",
        )

    errors = validate_report_spec(payload)
    if errors:
        raise TemplateError(
            "Report specification failed validation.",
            issues=_issues_from_strings(errors),
        )
    parsed = ReportSpec.model_validate(payload)
    return parsed.model_dump(by_alias=True), "1.0"


def validate_or_raise(spec: ReportSpec | dict[str, Any]) -> None:
    parse_and_validate_spec(spec)


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


def create_template(
    db: Session,
    *,
    name: str,
    spec: ReportSpec | dict[str, Any],
    prompt_text: str = "",
    description: str = "",
    study_id: str | None = None,
    report_kind: ReportKind = "adhoc",
    source: str = "template",
    planner_model: str | None = None,
    planner_prompt_id: str | None = None,
    template_id: str | None = None,
    notes: str = "",
    default_execution_date: str | None = None,
    commit: bool = True,
) -> tuple[ReportTemplate, ReportTemplateVersion]:
    if not study_id:
        raise TemplateError("study_id is required for report templates.")
    spec_json, spec_version = parse_and_validate_spec(spec)
    template = ReportTemplate(
        id=template_id or str(uuid.uuid4()),
        name=name,
        description=description,
        study_id=study_id,
        report_kind=report_kind,
        status="active",
        default_execution_date=default_execution_date,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(template)
    db.flush()
    version = _append_version(
        db,
        template,
        spec_json=spec_json,
        spec_version=spec_version,
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


def create_draft(
    db: Session,
    *,
    study_id: str,
    name: str = "Untitled template",
    description: str = "",
    report_kind: ReportKind = "adhoc",
    commit: bool = True,
) -> ReportTemplate:
    """Create a template with no published version — authoring starts in chat."""
    if not study_id:
        raise TemplateError("study_id is required for report templates.")
    from app.services.reporting.authoring import default_authoring

    template = ReportTemplate(
        id=str(uuid.uuid4()),
        name=(name or "").strip() or "Untitled template",
        description=description,
        study_id=study_id,
        report_kind=report_kind,
        status="draft",
        working_spec_json=None,
        authoring_json=default_authoring(),
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(template)
    db.flush()
    if commit:
        db.commit()
        db.refresh(template)
    return template


def add_version(
    db: Session,
    template: ReportTemplate,
    *,
    spec: ReportSpec | dict[str, Any],
    prompt_text: str = "",
    source: str = "template",
    planner_model: str | None = None,
    planner_prompt_id: str | None = None,
    notes: str = "",
    commit: bool = True,
) -> ReportTemplateVersion:
    """Append a new version. Earlier versions are never modified or removed.

    If the latest version already has the same specification, return it unchanged
    so re-saving does not bump the version number.
    """
    spec_json, spec_version = parse_and_validate_spec(spec)
    latest = db.scalars(
        select(ReportTemplateVersion)
        .where(ReportTemplateVersion.template_id == template.id)
        .order_by(ReportTemplateVersion.version.desc())
    ).first()
    if (
        source == "template"
        and latest is not None
        and (latest.spec_json or {}) == spec_json
    ):
        return latest
    next_number = (latest.version + 1) if latest else 1
    version = _append_version(
        db,
        template,
        spec_json=spec_json,
        spec_version=spec_version,
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


def restore_version(
    db: Session,
    template: ReportTemplate,
    version_number: int,
    *,
    commit: bool = True,
) -> ReportTemplateVersion:
    source = get_version(db, template.id, version_number)
    if source is None:
        raise TemplateError(f"Template version {version_number} was not found.")
    current = current_version(db, template)
    if source.id == current.id:
        raise TemplateError(f"Version {version_number} is already the current version.")

    return add_version(
        db,
        template,
        spec=source.spec_json or {},
        prompt_text=source.prompt_text,
        source="rollback",
        planner_model=source.planner_model,
        planner_prompt_id=source.planner_prompt_id,
        notes=f"Restored from v{version_number}.",
        commit=commit,
    )


def _append_version(
    db: Session,
    template: ReportTemplate,
    *,
    spec_json: dict[str, Any],
    spec_version: str,
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
        prompt_text=prompt_text,
        spec_json=spec_json,
        spec_version=spec_version,
        planner_model=planner_model,
        planner_prompt_id=planner_prompt_id,
        source=source,
        notes=notes,
        created_at=_now(),
    )
    db.add(version)
    db.flush()
    template.current_version_id = version.id
    template.updated_at = _now()
    return version


def update_meta(
    db: Session,
    template: ReportTemplate,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    report_kind: ReportKind | None = None,
    default_execution_date: str | None = None,
    commit: bool = True,
) -> ReportTemplate:
    if name is not None:
        template.name = name
    if description is not None:
        template.description = description
    if status is not None:
        template.status = status
    if report_kind is not None:
        template.report_kind = report_kind
    if default_execution_date is not None:
        template.default_execution_date = default_execution_date or None
    template.updated_at = _now()
    if commit:
        db.commit()
        db.refresh(template)
    return template


def diff_versions(
    previous: ReportTemplateVersion | None, current: ReportTemplateVersion
) -> list[str]:
    if previous is None:
        return ["Initial version"]
    changes: list[str] = []
    if (previous.prompt_text or "") != (current.prompt_text or ""):
        changes.append("Prompt text changed")
    if (previous.spec_json or {}) != (current.spec_json or {}):
        changes.append("Specification changed")
    if previous.source != current.source:
        changes.append(f"Source: {previous.source} → {current.source}")
    return changes or ["No detectable changes"]


def resolve_study_template(
    db: Session, study: Any, kind: ReportKind
) -> ReportTemplate | None:
    """Oldest active study-scoped template for that kind label (not a seed)."""
    return db.scalars(
        select(ReportTemplate)
        .where(
            ReportTemplate.study_id == study.id,
            ReportTemplate.report_kind == kind,
            ReportTemplate.status == "active",
        )
        .order_by(ReportTemplate.created_at)
    ).first()


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
        "version_count": len(versions),
        "current_version": latest.version if latest else 0,
        "prompt_text": latest.prompt_text if latest else "",
        "default_execution_date": template.default_execution_date,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }
