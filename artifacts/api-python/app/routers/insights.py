from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Insight
from app.db.session import get_db
from app.schemas.common import OkResponse
from app.schemas.misc import InsightInput, InsightOut

router = APIRouter(prefix="/ai/insights", tags=["ai"])


def _map(row: Insight) -> InsightOut:
    return InsightOut(
        id=row.id,
        title=row.title,
        summary=row.summary,
        content=row.content,
        type=row.type,
        project_id=row.project_id,
        project_name=row.project_name,
        severity=row.severity,
        tags=list(row.tags or []),
        created_at=row.created_at.isoformat(),
    )


@router.get("", response_model=list[InsightOut], operation_id="getInsights")
def list_insights(project_id: str | None = None, db: Session = Depends(get_db)) -> list[InsightOut]:
    query = select(Insight).order_by(Insight.created_at.desc())
    if project_id:
        query = query.where(Insight.project_id == project_id)
    return [_map(row) for row in db.scalars(query).all()]


@router.post("", response_model=InsightOut, operation_id="createInsight")
def create_insight(payload: InsightInput, db: Session = Depends(get_db)) -> InsightOut:
    row = Insight(
        id=str(uuid.uuid4()),
        title=payload.title,
        summary=payload.summary,
        content=payload.content,
        type=payload.type,
        project_id=payload.project_id,
        project_name=payload.project_name,
        severity=payload.severity,
        tags=payload.tags,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _map(row)


@router.get("/{insight_id}", response_model=InsightOut, operation_id="getInsight")
def get_insight(insight_id: str, db: Session = Depends(get_db)) -> InsightOut:
    row = db.get(Insight, insight_id)
    if not row:
        raise HTTPException(status_code=404, detail="Insight not found")
    return _map(row)


@router.delete("/{insight_id}", response_model=OkResponse, operation_id="deleteInsight")
def delete_insight(insight_id: str, db: Session = Depends(get_db)) -> OkResponse:
    row = db.get(Insight, insight_id)
    if not row:
        raise HTTPException(status_code=404, detail="Insight not found")
    db.delete(row)
    db.commit()
    return OkResponse(success=True)
