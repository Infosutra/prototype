"""Study domain: group Kobo forms for DQA, reporting, and analytics."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, Study

# Known form UIDs for the seeded Sightsavers 2030 study (Kobo asset UIDs).
SIGHTSAVERS_2030_ID = "study-sightsavers-2030"
SIGHTSAVERS_2030_FORMS = [
    {
        "toolCode": "T1",
        "projectUid": "ajHnaDiKywwDknGB3L2nLC",
        "label": "Facility / School Assessment",
    },
    {
        "toolCode": "T2",
        "projectUid": "a5qKLPgxnHTaYbrDWeeg9v",
        "label": "Teachers & Anganwadi Workers",
    },
    {
        "toolCode": "T3",
        "projectUid": "aN5bufzTGmh9SibWSDZBr8",
        "label": "Parents & Caregivers",
    },
]
# Placeholder planned counts from the DQA report sample — editable in UI.
SIGHTSAVERS_2030_TARGETS = {"T1": 440, "T2": 960, "T3": 880}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def study_day_number(study: Study, on: date | None = None) -> int | None:
    """1-based day index from study.start_date; None if start_date unset."""
    if not study.start_date:
        return None
    try:
        start = date.fromisoformat(study.start_date)
    except ValueError:
        return None
    current = on or datetime.now(timezone.utc).date()
    delta = (current - start).days
    return delta + 1 if delta >= 0 else None


def study_to_dict(study: Study, *, projects: list[Project] | None = None) -> dict[str, Any]:
    project_rows = projects if projects is not None else list(study.projects or [])
    return {
        "id": study.id,
        "name": study.name,
        "description": study.description,
        "start_date": study.start_date,
        "end_date": study.end_date,
        "timezone": study.timezone or "Asia/Kolkata",
        "targets": study.targets if isinstance(study.targets, dict) else {},
        "form_map": study.form_map if isinstance(study.form_map, list) else [],
        "day_number": study_day_number(study),
        "project_count": len(project_rows),
        "submission_count": sum(p.submission_count for p in project_rows),
        "projects": [
            {
                "id": p.id,
                "uid": p.uid,
                "name": p.name,
                "tool_code": p.tool_code,
                "submission_count": p.submission_count,
                "sync_status": p.sync_status,
            }
            for p in sorted(
                project_rows,
                key=lambda row: (row.tool_code or "Z", row.name),
            )
        ],
        "created_at": study.created_at.isoformat() if study.created_at else None,
        "updated_at": study.updated_at.isoformat() if study.updated_at else None,
    }


def seed_default_study(db: Session) -> Study:
    """Ensure Sightsavers 2030 study exists. Does not call Kobo."""
    existing = db.get(Study, SIGHTSAVERS_2030_ID)
    if existing:
        apply_form_map_to_projects(db, existing)
        return existing

    study = Study(
        id=SIGHTSAVERS_2030_ID,
        name="Sightsavers 2030",
        description=(
            "AKF Schools2030 Inclusive Education Baseline, Bihar — "
            "T1 Facility/School · T2 Teacher & AWW KAP · T3 Parents/Caregivers"
        ),
        start_date="2026-07-20",
        end_date=None,
        timezone="Asia/Kolkata",
        targets=dict(SIGHTSAVERS_2030_TARGETS),
        form_map=list(SIGHTSAVERS_2030_FORMS),
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    apply_form_map_to_projects(db, study)
    return study


def apply_form_map_to_projects(db: Session, study: Study) -> int:
    """Assign synced projects to this study using form_map UIDs. Local DB only.

    Never steals a form already assigned to a different study — reassignment
    must go through assign_project / the Studies UI.
    """
    form_map = study.form_map if isinstance(study.form_map, list) else []
    assigned = 0
    for entry in form_map:
        if not isinstance(entry, dict):
            continue
        uid = str(entry.get("projectUid") or entry.get("project_uid") or "").strip()
        tool = str(entry.get("toolCode") or entry.get("tool_code") or "").strip().upper()
        if not uid:
            continue
        project = db.get(Project, uid) or db.scalars(
            select(Project).where(Project.uid == uid)
        ).first()
        if not project:
            continue
        # Respect manual study ownership from other studies.
        if project.study_id and project.study_id != study.id:
            continue
        changed = False
        if project.study_id != study.id:
            project.study_id = study.id
            changed = True
        if tool and project.tool_code != tool:
            project.tool_code = tool
            changed = True
        if changed:
            assigned += 1
    if assigned:
        db.commit()
    return assigned


def apply_all_study_form_maps(db: Session) -> int:
    total = 0
    for study in db.scalars(select(Study)).all():
        total += apply_form_map_to_projects(db, study)
    return total


def _remove_uid_from_other_studies(db: Session, project: Project, keep_study_id: str) -> None:
    """Drop this project's UID from every study form_map except keep_study_id."""
    for other in db.scalars(select(Study).where(Study.id != keep_study_id)).all():
        form_map = other.form_map if isinstance(other.form_map, list) else []
        filtered = [
            entry
            for entry in form_map
            if not (
                isinstance(entry, dict)
                and (
                    entry.get("projectUid") == project.uid
                    or entry.get("project_uid") == project.uid
                )
            )
        ]
        if len(filtered) != len(form_map):
            other.form_map = filtered
            other.updated_at = _now()


def list_studies(db: Session) -> list[dict[str, Any]]:
    studies = list(db.scalars(select(Study).order_by(Study.name)).all())
    return [study_to_dict(s) for s in studies]


def get_study(db: Session, study_id: str) -> Study | None:
    return db.get(Study, study_id)


def create_study(db: Session, payload: dict[str, Any]) -> Study:
    study_id = str(payload.get("id") or f"study-{uuid.uuid4().hex[:12]}")
    study = Study(
        id=study_id,
        name=str(payload["name"]).strip(),
        description=(str(payload["description"]).strip() if payload.get("description") else None),
        start_date=payload.get("start_date") or payload.get("startDate"),
        end_date=payload.get("end_date") or payload.get("endDate"),
        timezone=str(payload.get("timezone") or "Asia/Kolkata"),
        targets=payload.get("targets") if isinstance(payload.get("targets"), dict) else {},
        form_map=payload.get("form_map")
        if isinstance(payload.get("form_map"), list)
        else payload.get("formMap")
        if isinstance(payload.get("formMap"), list)
        else [],
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    apply_form_map_to_projects(db, study)
    return study


def update_study(db: Session, study: Study, payload: dict[str, Any]) -> Study:
    if "name" in payload and payload["name"] is not None:
        study.name = str(payload["name"]).strip()
    if "description" in payload:
        value = payload["description"]
        study.description = str(value).strip() if value else None
    if "start_date" in payload or "startDate" in payload:
        study.start_date = payload.get("start_date") or payload.get("startDate")
    if "end_date" in payload or "endDate" in payload:
        study.end_date = payload.get("end_date") or payload.get("endDate")
    if "timezone" in payload and payload["timezone"]:
        study.timezone = str(payload["timezone"])
    if "targets" in payload and isinstance(payload["targets"], dict):
        study.targets = payload["targets"]
    if "form_map" in payload and isinstance(payload["form_map"], list):
        study.form_map = payload["form_map"]
    elif "formMap" in payload and isinstance(payload["formMap"], list):
        study.form_map = payload["formMap"]
    study.updated_at = _now()
    db.commit()
    db.refresh(study)
    apply_form_map_to_projects(db, study)
    return study


def delete_study(db: Session, study: Study) -> None:
    for project in db.scalars(select(Project).where(Project.study_id == study.id)).all():
        project.study_id = None
        project.tool_code = None
    db.delete(study)
    db.commit()


def assign_project(
    db: Session,
    study: Study,
    project: Project,
    *,
    tool_code: str | None = None,
) -> Project:
    # Clear ownership from any other study so sync auto-attach cannot reclaim it.
    if project.study_id and project.study_id != study.id:
        previous = db.get(Study, project.study_id)
        if previous and isinstance(previous.form_map, list):
            previous.form_map = [
                entry
                for entry in previous.form_map
                if not (
                    isinstance(entry, dict)
                    and (
                        entry.get("projectUid") == project.uid
                        or entry.get("project_uid") == project.uid
                    )
                )
            ]
            previous.updated_at = _now()
    _remove_uid_from_other_studies(db, project, study.id)

    project.study_id = study.id
    if tool_code is not None:
        project.tool_code = tool_code.strip().upper() or None
    # Keep form_map in sync
    form_map = list(study.form_map or []) if isinstance(study.form_map, list) else []
    updated = False
    for entry in form_map:
        if isinstance(entry, dict) and (
            entry.get("projectUid") == project.uid or entry.get("project_uid") == project.uid
        ):
            if tool_code:
                entry["toolCode"] = tool_code.strip().upper()
            entry["label"] = project.name
            updated = True
            break
    if not updated:
        form_map.append(
            {
                "toolCode": (tool_code or project.tool_code or "").strip().upper() or None,
                "projectUid": project.uid,
                "label": project.name,
            }
        )
    study.form_map = form_map
    study.updated_at = _now()
    db.commit()
    db.refresh(project)
    return project


def unassign_project(db: Session, project: Project) -> Project:
    study_id = project.study_id
    project.study_id = None
    project.tool_code = None
    if study_id:
        study = db.get(Study, study_id)
        if study and isinstance(study.form_map, list):
            study.form_map = [
                entry
                for entry in study.form_map
                if not (
                    isinstance(entry, dict)
                    and (entry.get("projectUid") == project.uid or entry.get("project_uid") == project.uid)
                )
            ]
            study.updated_at = _now()
    db.commit()
    db.refresh(project)
    return project
