from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Prompt
from app.db.session import get_db
from app.schemas.misc import PromptInput, PromptOut, PromptUpdate

router = APIRouter(prefix="/prompts", tags=["prompts"])


def _map(row: Prompt) -> PromptOut:
    return PromptOut(
        id=row.id,
        name=row.name,
        description=row.description,
        content=row.content,
        category=row.category,
        project_ids=list(row.project_ids or []),
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("", response_model=list[PromptOut])
def list_prompts(db: Session = Depends(get_db)) -> list[PromptOut]:
    return [_map(row) for row in db.scalars(select(Prompt).order_by(Prompt.name)).all()]


@router.post("", response_model=PromptOut)
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


@router.get("/{prompt_id}", response_model=PromptOut)
def get_prompt(prompt_id: str, db: Session = Depends(get_db)) -> PromptOut:
    row = db.get(Prompt, prompt_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return _map(row)


@router.put("/{prompt_id}", response_model=PromptOut)
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
        row.category = payload.category
    if payload.project_ids is not None:
        row.project_ids = payload.project_ids
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    return _map(row)


@router.delete("/{prompt_id}")
def delete_prompt(prompt_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.get(Prompt, prompt_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prompt not found")
    db.delete(row)
    db.commit()
    return {"success": True}
