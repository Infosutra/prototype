from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.audio import UsageEventOut, UsageSummaryOut
from app.services import usage as usage_service

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("", response_model=list[UsageEventOut], operation_id="getUsageEvents")
def get_usage_events(
    study_id: str | None = Query(default=None, alias="studyId"),
    category: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> list[UsageEventOut]:
    return usage_service.list_usage_events(
        db,
        study_id=study_id,
        category=category,
        limit=limit,
    )


@router.get("/summary", response_model=UsageSummaryOut, operation_id="getUsageSummary")
def get_usage_summary(
    study_id: str | None = Query(default=None, alias="studyId"),
    category: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> UsageSummaryOut:
    return usage_service.usage_summary(db, study_id=study_id, category=category)
