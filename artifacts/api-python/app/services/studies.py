"""Study domain: group Kobo forms for DQA, reporting, and analytics."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Project, Prompt, Study, StudyCredential, StudyTool
from app.seeds import (
    DEFAULT_STUDY_DESCRIPTION,
    DEFAULT_STUDY_FORMS,
    DEFAULT_STUDY_ID,
    DEFAULT_STUDY_NAME,
    DEFAULT_STUDY_START_DATE,
    DEFAULT_STUDY_TARGETS,
    DEFAULT_STUDY_TIMEZONE,
)
from app.services.settings import MASK, _iso


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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


def _credential_summary(cred: StudyCredential | None) -> dict[str, Any] | None:
    if cred is None:
        return None
    return {
        "connected": bool(cred.connected),
        "server_url": cred.kobo_server_url or "https://kf.kobotoolbox.org",
        "username": cred.kobo_username or "",
        "api_token": MASK if cred.kobo_token_encrypted else "",
        "last_tested_at": _iso(cred.last_tested_at),
    }


def study_to_dict(study: Study, *, projects: list[Project] | None = None) -> dict[str, Any]:
    project_rows = projects if projects is not None else list(study.projects or [])
    tools = list(study.tools or [])
    return {
        "id": study.id,
        "name": study.name,
        "description": study.description,
        "start_date": study.start_date,
        "end_date": study.end_date,
        "timezone": study.timezone or "Asia/Kolkata",
        "daily_dqa_prompt_id": study.daily_dqa_prompt_id,
        "final_dqa_prompt_id": study.final_dqa_prompt_id,
        "tools": [
            {
                "id": t.id,
                "code": t.code,
                "label": t.label,
                "target_count": t.target_count,
                "sort_order": t.sort_order,
            }
            for t in sorted(tools, key=lambda row: (row.sort_order, row.code))
        ],
        "credential": _credential_summary(study.credential),
        "day_number": study_day_number(study),
        "project_count": len(project_rows),
        "submission_count": sum(p.submission_count for p in project_rows),
        "projects": [
            {
                "id": p.id,
                "uid": p.uid,
                "name": p.name,
                "tool_code": p.tool_code,
                "study_tool_id": p.study_tool_id,
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


def _load_study(db: Session, study_id: str) -> Study | None:
    return db.scalars(
        select(Study)
        .options(
            joinedload(Study.tools),
            joinedload(Study.credential),
            joinedload(Study.projects).joinedload(Project.study_tool),
        )
        .where(Study.id == study_id)
    ).unique().first()


def _ensure_credential(db: Session, study: Study) -> StudyCredential:
    if study.credential is not None:
        return study.credential
    cred = StudyCredential(
        id=_new_id("cred"),
        study_id=study.id,
    )
    db.add(cred)
    db.flush()
    study.credential = cred
    return cred


def _sync_tools(db: Session, study: Study, tools_payload: list[dict[str, Any]]) -> None:
    existing = {t.id: t for t in (study.tools or [])}
    keep_ids: set[str] = set()
    for index, entry in enumerate(tools_payload):
        code = str(entry.get("code") or "").strip().upper()
        if not code:
            continue
        tool_id = entry.get("id")
        tool = existing.get(tool_id) if tool_id else None
        if tool is None:
            tool = next((t for t in existing.values() if t.code == code), None)
        if tool is None:
            tool = StudyTool(id=_new_id("tool"), study_id=study.id, code=code)
            db.add(tool)
        tool.code = code
        tool.label = str(entry.get("label") or "").strip()
        tool.target_count = int(entry.get("target_count") or entry.get("targetCount") or 0)
        tool.sort_order = int(
            entry.get("sort_order")
            if entry.get("sort_order") is not None
            else entry.get("sortOrder")
            if entry.get("sortOrder") is not None
            else index
        )
        keep_ids.add(tool.id)
    for tool in list(study.tools or []):
        if tool.id not in keep_ids:
            for project in list(tool.projects or []):
                project.study_tool_id = None
            db.delete(tool)
    db.flush()


def seed_default_study(db: Session) -> Study:
    """Ensure the default demo study exists with tools, credential, and triangulation views."""
    from app.services import triangulation as tri

    existing = _load_study(db, DEFAULT_STUDY_ID)
    if existing:
        apply_seed_tool_links(db, existing)
        tri.seed_triangulation_views(db, existing.id)
        return existing

    study = Study(
        id=DEFAULT_STUDY_ID,
        name=DEFAULT_STUDY_NAME,
        description=DEFAULT_STUDY_DESCRIPTION,
        start_date=DEFAULT_STUDY_START_DATE,
        end_date=None,
        timezone=DEFAULT_STUDY_TIMEZONE,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(study)
    db.flush()

    for index, entry in enumerate(DEFAULT_STUDY_FORMS):
        code = str(entry["toolCode"]).upper()
        db.add(
            StudyTool(
                id=_new_id("tool"),
                study_id=study.id,
                code=code,
                label=str(entry.get("label") or code),
                target_count=int(DEFAULT_STUDY_TARGETS.get(code) or 0),
                sort_order=index,
            )
        )
    db.add(StudyCredential(id=_new_id("cred"), study_id=study.id))
    db.commit()
    study = _load_study(db, DEFAULT_STUDY_ID)
    assert study is not None
    apply_seed_tool_links(db, study)
    tri.seed_triangulation_views(db, study.id)
    return study


def apply_seed_tool_links(db: Session, study: Study) -> int:
    """Assign known seed UIDs to this study's tools when projects exist locally."""
    if study.id != DEFAULT_STUDY_ID:
        return 0
    tools_by_code = {t.code.upper(): t for t in (study.tools or [])}
    assigned = 0
    for entry in DEFAULT_STUDY_FORMS:
        uid = str(entry.get("projectUid") or "").strip()
        code = str(entry.get("toolCode") or "").strip().upper()
        tool = tools_by_code.get(code)
        if not uid or not tool:
            continue
        project = db.get(Project, uid) or db.scalars(
            select(Project).where(Project.uid == uid)
        ).first()
        if not project:
            continue
        if project.study_id and project.study_id != study.id:
            continue
        changed = False
        if project.study_id != study.id:
            project.study_id = study.id
            changed = True
        if project.study_tool_id != tool.id:
            project.study_tool_id = tool.id
            changed = True
        if changed:
            assigned += 1
    if assigned:
        db.commit()
    return assigned


def apply_all_study_form_maps(db: Session) -> int:
    """Back-compat alias used at startup — links seed UIDs to StudyTools."""
    total = 0
    for study in db.scalars(select(Study)).all():
        loaded = _load_study(db, study.id)
        if loaded:
            total += apply_seed_tool_links(db, loaded)
    return total


def list_studies(db: Session) -> list[dict[str, Any]]:
    studies = list(
        db.scalars(
            select(Study)
            .options(
                joinedload(Study.tools),
                joinedload(Study.credential),
                joinedload(Study.projects).joinedload(Project.study_tool),
            )
            .order_by(Study.name)
        )
        .unique()
        .all()
    )
    return [study_to_dict(s) for s in studies]


def get_study(db: Session, study_id: str) -> Study | None:
    return _load_study(db, study_id)


def _normalize_prompt_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_prompt(db: Session, prompt_id: str | None) -> Prompt | None:
    if not prompt_id:
        return None
    row = db.get(Prompt, prompt_id)
    if row is None:
        raise ValueError(f"Prompt not found: {prompt_id}")
    return row


def create_study(db: Session, payload: dict[str, Any]) -> Study:
    study_id = str(payload.get("id") or f"study-{uuid.uuid4().hex[:12]}")
    daily_prompt_id = _normalize_prompt_id(
        payload.get("daily_dqa_prompt_id") or payload.get("dailyDqaPromptId")
    )
    final_prompt_id = _normalize_prompt_id(
        payload.get("final_dqa_prompt_id") or payload.get("finalDqaPromptId")
    )
    _resolve_prompt(db, daily_prompt_id)
    _resolve_prompt(db, final_prompt_id)
    study = Study(
        id=study_id,
        name=str(payload["name"]).strip(),
        description=(str(payload["description"]).strip() if payload.get("description") else None),
        start_date=payload.get("start_date") or payload.get("startDate"),
        end_date=payload.get("end_date") or payload.get("endDate"),
        timezone=str(payload.get("timezone") or "Asia/Kolkata"),
        daily_dqa_prompt_id=daily_prompt_id,
        final_dqa_prompt_id=final_prompt_id,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(study)
    db.flush()
    tools_payload = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    _sync_tools(db, study, tools_payload)
    _ensure_credential(db, study)
    db.commit()
    loaded = _load_study(db, study.id)
    assert loaded is not None
    return loaded


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
    if "daily_dqa_prompt_id" in payload or "dailyDqaPromptId" in payload:
        daily_prompt_id = _normalize_prompt_id(
            payload.get("daily_dqa_prompt_id")
            if "daily_dqa_prompt_id" in payload
            else payload.get("dailyDqaPromptId")
        )
        _resolve_prompt(db, daily_prompt_id)
        study.daily_dqa_prompt_id = daily_prompt_id
    if "final_dqa_prompt_id" in payload or "finalDqaPromptId" in payload:
        final_prompt_id = _normalize_prompt_id(
            payload.get("final_dqa_prompt_id")
            if "final_dqa_prompt_id" in payload
            else payload.get("finalDqaPromptId")
        )
        _resolve_prompt(db, final_prompt_id)
        study.final_dqa_prompt_id = final_prompt_id
    if "tools" in payload and isinstance(payload["tools"], list):
        _sync_tools(db, study, payload["tools"])
    study.updated_at = _now()
    db.commit()
    loaded = _load_study(db, study.id)
    assert loaded is not None
    return loaded


def delete_study(db: Session, study: Study) -> None:
    for project in db.scalars(select(Project).where(Project.study_id == study.id)).all():
        project.study_id = None
        project.study_tool_id = None
    db.delete(study)
    db.commit()


def _resolve_tool(
    study: Study,
    *,
    tool_code: str | None = None,
    study_tool_id: str | None = None,
) -> StudyTool | None:
    if study_tool_id:
        for tool in study.tools or []:
            if tool.id == study_tool_id:
                return tool
        return None
    if tool_code:
        code = tool_code.strip().upper()
        for tool in study.tools or []:
            if tool.code.upper() == code:
                return tool
    return None


def _ensure_tool(
    db: Session,
    study: Study,
    *,
    tool_code: str | None = None,
    study_tool_id: str | None = None,
    label: str | None = None,
) -> StudyTool | None:
    tool = _resolve_tool(study, tool_code=tool_code, study_tool_id=study_tool_id)
    if tool is not None:
        if label is not None:
            cleaned = str(label).strip()
            if cleaned:
                tool.label = cleaned
        return tool
    if study_tool_id is not None and tool_code is None:
        return None
    if not tool_code or not str(tool_code).strip():
        return None
    code = str(tool_code).strip().upper()
    tool = StudyTool(
        id=_new_id("tool"),
        study_id=study.id,
        code=code,
        label=(str(label).strip() if label else "") or code,
        target_count=0,
        sort_order=len(study.tools or []),
    )
    db.add(tool)
    db.flush()
    if study.tools is None:
        study.tools = []
    study.tools.append(tool)
    return tool


def assign_project(
    db: Session,
    study: Study,
    project: Project,
    *,
    tool_code: str | None = None,
    study_tool_id: str | None = None,
    label: str | None = None,
) -> Project:
    project.study_id = study.id
    if study_tool_id is not None or tool_code is not None:
        tool = _ensure_tool(
            db,
            study,
            tool_code=tool_code,
            study_tool_id=study_tool_id,
            label=label,
        )
        project.study_tool_id = tool.id if tool else None
    study.updated_at = _now()
    db.commit()
    db.refresh(project)
    return project


def unassign_project(db: Session, project: Project) -> Project:
    project.study_id = None
    project.study_tool_id = None
    db.commit()
    db.refresh(project)
    return project
