from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Prompt, Study
from app.db.session import get_db
from app.schemas.common import OkResponse
from app.schemas.misc import PromptInput, PromptOut, PromptUpdate
from app.services.dqa_report_prompts import SYSTEM_PROMPT_IDS, revert_system_prompt

router = APIRouter(prefix="/prompts", tags=["prompts"])


def _prompt_study_ids(db: Session, prompt_ids: list[str]) -> dict[str, list[str]]:
    usage: dict[str, list[str]] = {pid: [] for pid in prompt_ids}
    if not prompt_ids:
        return usage
    studies = db.scalars(
        select(Study).where(
            or_(
                Study.daily_dqa_prompt_id.in_(prompt_ids),
                Study.final_dqa_prompt_id.in_(prompt_ids),
            )
        ).order_by(Study.name)
    ).all()
    for study in studies:
        for pid in (study.daily_dqa_prompt_id, study.final_dqa_prompt_id):
            if pid in usage and study.id not in usage[pid]:
                usage[pid].append(study.id)
    return usage


def _map(row: Prompt, study_ids: list[str] | None = None) -> PromptOut:
    return PromptOut(
        id=row.id,
        name=row.name,
        description=row.description,
        content=row.content,
        category=row.category,
        project_ids=list(row.project_ids or []),
        study_ids=list(study_ids or []),
        is_system=row.id in SYSTEM_PROMPT_IDS,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("", response_model=list[PromptOut], operation_id="getPrompts")
def list_prompts(db: Session = Depends(get_db)) -> list[PromptOut]:
    rows = list(db.scalars(select(Prompt).order_by(Prompt.name)).all())
    usage = _prompt_study_ids(db, [row.id for row in rows])
    return [_map(row, usage.get(row.id, [])) for row in rows]


@router.post("", response_model=PromptOut, operation_id="createPrompt")
def create_prompt(payload: PromptInput, db: Session = Depends(get_db)) -> PromptOut:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = Prompt(
        id=str(uuid.uuid4()),
        name=payload.name,
        description=payload.description,
        content=payload.content,
        category=payload.category,
        project_ids=payload.project_ids,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _map(row)


@router.get("/{prompt_id}", response_model=PromptOut, operation_id="getPrompt")
def get_prompt(prompt_id: str, db: Session = Depends(get_db)) -> PromptOut:
    row = db.get(Prompt, prompt_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt not found")
    usage = _prompt_study_ids(db, [row.id])
    return _map(row, usage.get(row.id, []))


@router.put("/{prompt_id}", response_model=PromptOut, operation_id="updatePrompt")
def update_prompt(
    prompt_id: str,
    payload: PromptUpdate,
    db: Session = Depends(get_db),
) -> PromptOut:
    row = db.get(Prompt, prompt_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if payload.name is not None:
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    if payload.content is not None:
        row.content = payload.content
    if payload.category is not None:
        if row.id in SYSTEM_PROMPT_IDS:
            # Keep system prompts in the category report generation expects.
            pass
        else:
            row.category = payload.category
    if payload.project_ids is not None:
        row.project_ids = payload.project_ids
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    usage = _prompt_study_ids(db, [row.id])
    return _map(row, usage.get(row.id, []))


@router.delete("/{prompt_id}", response_model=OkResponse, operation_id="deletePrompt")
def delete_prompt(prompt_id: str, db: Session = Depends(get_db)) -> OkResponse:
    row = db.get(Prompt, prompt_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if row.id in SYSTEM_PROMPT_IDS:
        raise HTTPException(
            status_code=400,
            detail="This is a default system prompt. Edit it, or create a dedicated copy for a study.",
        )
    db.delete(row)
    db.commit()
    return OkResponse(success=True)


@router.post(
    "/{prompt_id}/revert",
    response_model=PromptOut,
    operation_id="revertPrompt",
)
def revert_prompt(prompt_id: str, db: Session = Depends(get_db)) -> PromptOut:
    """Restore a seeded system prompt to its packaged original content."""
    if prompt_id not in SYSTEM_PROMPT_IDS:
        raise HTTPException(
            status_code=400,
            detail="Only seeded system prompts can be reverted to the original version.",
        )
    try:
        row = revert_system_prompt(db, prompt_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    usage = _prompt_study_ids(db, [row.id])
    return _map(row, usage.get(row.id, []))
