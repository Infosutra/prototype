"""Study-scoped DQA relationship CRUD and schema helpers."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DqaRelationship, Project
from app.domain.dqa.form_fields import list_form_fields
from app.domain.dqa.validate import ValidationIssue, ValidationResult, build_allowed_field_refs
from app.services.dqa_rule_packs import get_pack_for_project


class RelationshipError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def list_relationships(db: Session, study_id: str) -> list[DqaRelationship]:
    return list(
        db.scalars(
            select(DqaRelationship)
            .where(DqaRelationship.study_id == study_id)
            .order_by(DqaRelationship.code)
        ).all()
    )


def get_relationship(db: Session, study_id: str, relationship_id: str) -> DqaRelationship | None:
    row = db.get(DqaRelationship, relationship_id)
    if not row or row.study_id != study_id:
        return None
    return row


def _project_in_study(db: Session, study_id: str, project_id: str) -> Project | None:
    project = db.get(Project, project_id)
    if not project or project.study_id != study_id:
        return None
    return project


def validate_relationship_payload(
    db: Session,
    study_id: str,
    payload: dict[str, Any],
    *,
    existing: DqaRelationship | None = None,
) -> ValidationResult:
    result = ValidationResult(valid=True)
    code = str(payload.get("code") or (existing.code if existing else "")).strip()
    if not code:
        result.valid = False
        result.errors.append(ValidationIssue("code", "missing_code", "code is required"))
    elif not code.replace("_", "").isalnum():
        result.valid = False
        result.errors.append(
            ValidationIssue("code", "invalid_code", "code must be alphanumeric with underscores")
        )

    source_id = str(payload.get("source_project_id") or (existing.source_project_id if existing else "")).strip()
    target_id = str(payload.get("target_project_id") or (existing.target_project_id if existing else "")).strip()
    source_field = str(payload.get("source_join_field") or (existing.source_join_field if existing else "")).strip()
    target_field = str(payload.get("target_join_field") or (existing.target_join_field if existing else "")).strip()
    cardinality = str(payload.get("cardinality") or (existing.cardinality if existing else "one")).lower()

    source = _project_in_study(db, study_id, source_id) if source_id else None
    if not source:
        result.valid = False
        result.errors.append(
            ValidationIssue("source_project_id", "invalid_project", "source project not in study")
        )
    target = _project_in_study(db, study_id, target_id) if target_id else None
    if not target:
        result.valid = False
        result.errors.append(
            ValidationIssue("target_project_id", "invalid_project", "target project not in study")
        )

    if cardinality not in {"one", "latest"}:
        result.valid = False
        result.errors.append(
            ValidationIssue("cardinality", "invalid_cardinality", "cardinality must be one or latest")
        )

    if source and source_field:
        allowed = _allowed_fields(db, source)
        if source_field not in allowed:
            result.valid = False
            result.errors.append(
                ValidationIssue(
                    "source_join_field",
                    "unknown_field",
                    f"Unknown source join field: {source_field}",
                )
            )
    if target and target_field:
        allowed = _allowed_fields(db, target)
        if target_field not in allowed:
            result.valid = False
            result.errors.append(
                ValidationIssue(
                    "target_join_field",
                    "unknown_field",
                    f"Unknown target join field: {target_field}",
                )
            )

    if code and not existing:
        dup = db.scalars(
            select(DqaRelationship).where(
                DqaRelationship.study_id == study_id,
                DqaRelationship.code == code,
            )
        ).first()
        if dup:
            result.valid = False
            result.errors.append(
                ValidationIssue("code", "duplicate_code", f"Relationship code already exists: {code}")
            )
    return result


def create_relationship(db: Session, study_id: str, payload: dict[str, Any]) -> DqaRelationship:
    validation = validate_relationship_payload(db, study_id, payload)
    if not validation.valid:
        raise RelationshipError(
            "Invalid relationship",
            status_code=400,
        )
    row = DqaRelationship(
        id=str(uuid.uuid4()),
        study_id=study_id,
        code=str(payload["code"]).strip(),
        title=str(payload.get("title") or payload["code"]).strip(),
        source_project_id=str(payload["source_project_id"]).strip(),
        target_project_id=str(payload["target_project_id"]).strip(),
        source_join_field=str(payload["source_join_field"]).strip(),
        target_join_field=str(payload["target_join_field"]).strip(),
        cardinality=str(payload.get("cardinality") or "one").lower(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_relationship(
    db: Session,
    study_id: str,
    relationship_id: str,
    payload: dict[str, Any],
) -> DqaRelationship:
    row = get_relationship(db, study_id, relationship_id)
    if not row:
        raise RelationshipError("Relationship not found", status_code=404)
    merged = {
        "code": payload.get("code", row.code),
        "source_project_id": payload.get("source_project_id", row.source_project_id),
        "target_project_id": payload.get("target_project_id", row.target_project_id),
        "source_join_field": payload.get("source_join_field", row.source_join_field),
        "target_join_field": payload.get("target_join_field", row.target_join_field),
        "cardinality": payload.get("cardinality", row.cardinality),
        "title": payload.get("title", row.title),
    }
    validation = validate_relationship_payload(db, study_id, merged, existing=row)
    if not validation.valid:
        raise RelationshipError("Invalid relationship", status_code=400)
    row.code = str(merged["code"]).strip()
    row.title = str(merged.get("title") or row.code).strip()
    row.source_project_id = str(merged["source_project_id"]).strip()
    row.target_project_id = str(merged["target_project_id"]).strip()
    row.source_join_field = str(merged["source_join_field"]).strip()
    row.target_join_field = str(merged["target_join_field"]).strip()
    row.cardinality = str(merged["cardinality"]).lower()
    db.commit()
    db.refresh(row)
    return row


def delete_relationship(db: Session, study_id: str, relationship_id: str) -> None:
    row = get_relationship(db, study_id, relationship_id)
    if not row:
        raise RelationshipError("Relationship not found", status_code=404)
    db.delete(row)
    db.commit()


def _allowed_fields(db: Session, project: Project) -> set[str]:
    pack = get_pack_for_project(db, project.id) or {}
    form_fields = list_form_fields(
        project.form_definition if isinstance(project.form_definition, dict) else None
    )
    return build_allowed_field_refs(form_fields=form_fields, pack=pack)


def related_fields_for_project(db: Session, project_id: str) -> set[str]:
    project = db.get(Project, project_id)
    if not project:
        return set()
    return _allowed_fields(db, project)


def build_relationship_schema(db: Session, study_id: str) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    """Compact relationship catalog + allowed related fields per code (for compiler/validator)."""
    rows = list_relationships(db, study_id)
    catalog: list[dict[str, Any]] = []
    related_map: dict[str, set[str]] = {}
    for row in rows:
        catalog.append(
            {
                "code": row.code,
                "title": row.title,
                "source_project_id": row.source_project_id,
                "target_project_id": row.target_project_id,
                "source_join_field": row.source_join_field,
                "target_join_field": row.target_join_field,
                "cardinality": row.cardinality,
            }
        )
        related_map[row.code] = related_fields_for_project(db, row.target_project_id)
    return catalog, related_map


def relationships_for_source_project(
    db: Session, study_id: str, project_id: str
) -> list[DqaRelationship]:
    return [
        row
        for row in list_relationships(db, study_id)
        if row.source_project_id == project_id
    ]
