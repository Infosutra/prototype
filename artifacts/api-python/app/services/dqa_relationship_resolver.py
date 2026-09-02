"""Resolve study DQA relationships to related submissions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DqaRelationship, Submission
from app.domain.dqa.context import RelatedResolution
from app.domain.dqa.join import index_submissions_by_join_key, join_key_from_submission, pick_latest_submission
from app.domain.dqa.operands import collect_relationship_codes
from app.domain.dqa.related import _related_submission_ref
from app.services.dqa_rule_packs import get_pack_for_project


def load_study_relationships(db: Session, study_id: str) -> dict[str, DqaRelationship]:
    rows = db.scalars(
        select(DqaRelationship).where(DqaRelationship.study_id == study_id)
    ).all()
    return {row.code: row for row in rows}


def resolve_relationship(
    db: Session,
    *,
    relationship: DqaRelationship,
    current: Submission,
    source_pack: dict[str, Any],
    target_rows: list[Submission] | None = None,
    target_pack: dict[str, Any] | None = None,
) -> RelatedResolution:
    code = relationship.code
    data = current.data if isinstance(current.data, dict) else {}
    join_key = join_key_from_submission(data, source_pack, relationship.source_join_field)
    if not join_key:
        return RelatedResolution(
            relationship_code=code,
            status="missing_key",
            join_key=None,
        )

    target_pack = target_pack or get_pack_for_project(db, relationship.target_project_id) or {}
    if target_rows is None:
        target_rows = list(
            db.scalars(
                select(Submission).where(
                    Submission.project_id == relationship.target_project_id
                )
            ).all()
        )
    groups = index_submissions_by_join_key(
        target_rows, target_pack, relationship.target_join_field
    )
    matches = groups.get(join_key, [])
    candidates = tuple(_related_submission_ref(row) for row in matches)
    cardinality = str(relationship.cardinality or "one").lower()

    if not matches:
        return RelatedResolution(
            relationship_code=code,
            status="none",
            join_key=join_key,
            candidates=candidates,
        )

    if len(matches) > 1 and cardinality == "one":
        return RelatedResolution(
            relationship_code=code,
            status="ambiguous",
            join_key=join_key,
            candidates=candidates,
        )

    picked = pick_latest_submission(matches) if len(matches) > 1 else matches[0]
    picked_data = picked.data if isinstance(picked.data, dict) else {}
    return RelatedResolution(
        relationship_code=code,
        status="resolved",
        submission=picked,
        data=picked_data,
        pack=target_pack,
        join_key=join_key,
        candidates=candidates,
    )


def build_related_context(
    db: Session,
    *,
    current: Submission,
    source_pack: dict[str, Any],
    check: dict[str, Any] | None,
    study_id: str | None,
    relationships: dict[str, DqaRelationship] | None = None,
    target_rows_cache: dict[str, list[Submission]] | None = None,
    target_pack_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, RelatedResolution]:
    if not study_id or not check:
        return {}
    codes = collect_relationship_codes(check)
    if not codes:
        return {}
    rel_map = relationships or load_study_relationships(db, study_id)
    target_rows_cache = target_rows_cache or {}
    target_pack_cache = target_pack_cache or {}
    out: dict[str, RelatedResolution] = {}
    for code in codes:
        rel = rel_map.get(code)
        if not rel:
            out[code] = RelatedResolution(relationship_code=code, status="none")
            continue
        tid = rel.target_project_id
        if tid not in target_rows_cache:
            target_rows_cache[tid] = list(
                db.scalars(select(Submission).where(Submission.project_id == tid)).all()
            )
        if tid not in target_pack_cache:
            target_pack_cache[tid] = get_pack_for_project(db, tid) or {}
        out[code] = resolve_relationship(
            db,
            relationship=rel,
            current=current,
            source_pack=source_pack,
            target_rows=target_rows_cache[tid],
            target_pack=target_pack_cache[tid],
        )
    return out


def source_projects_for_target(
    db: Session, target_project_id: str
) -> list[str]:
    rows = db.scalars(
        select(DqaRelationship.source_project_id).where(
            DqaRelationship.target_project_id == target_project_id
        )
    ).all()
    return list(dict.fromkeys(rows))
