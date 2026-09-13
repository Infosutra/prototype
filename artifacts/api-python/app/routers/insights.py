from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Insight, Project, Submission
from app.db.session import get_db
from app.integrations.llm import LlmError, llm_config_from_app_settings
from app.schemas.common import OkResponse, StudyProjectQuery
from app.schemas.misc import InsightGenerateInput, InsightInput, InsightOut
from app.services.insights import generate_insight_payload
from app.services.settings import get_or_create_settings

router = APIRouter(prefix="/ai/insights", tags=["ai"])


def _map(row: Insight) -> InsightOut:
    return InsightOut(
        id=row.id,
        title=row.title,
        summary=row.summary,
        content=row.content,
        type=row.type,
        study_id=row.study_id,
        project_id=row.project_id,
        project_name=row.project_name,
        severity=row.severity,
        tags=list(row.tags or []),
        created_at=row.created_at.isoformat(),
    )


@router.get("", response_model=list[InsightOut], operation_id="getInsights")
def list_insights(
    q: Annotated[StudyProjectQuery, Query()],
    db: Session = Depends(get_db),
) -> list[InsightOut]:
    if not q.project_id and not q.study_id:
        raise HTTPException(
            status_code=400, detail="studyId or projectId is required"
        )
    query = select(Insight).order_by(Insight.created_at.desc())
    if q.project_id:
        query = query.where(Insight.project_id == q.project_id)
    elif q.study_id:
        query = query.where(Insight.study_id == q.study_id)
    return [_map(row) for row in db.scalars(query).all()]


@router.post("", response_model=InsightOut, operation_id="createInsight")
def create_insight(payload: InsightInput, db: Session = Depends(get_db)) -> InsightOut:
    row = Insight(
        id=str(uuid.uuid4()),
        title=payload.title,
        summary=payload.summary,
        content=payload.content,
        type=payload.type,
        study_id=payload.study_id,
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


@router.post("/generate", response_model=InsightOut, operation_id="generateInsight")
def generate_insight(
    payload: InsightGenerateInput,
    db: Session = Depends(get_db),
) -> InsightOut:
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    if not payload.study_id:
        raise HTTPException(status_code=400, detail="studyId is required")

    settings = get_or_create_settings(db)
    if not settings.ai_enabled:
        raise HTTPException(
            status_code=400,
            detail="AI is disabled. Enable it under Settings → General.",
        )
    llm = llm_config_from_app_settings(settings)
    if not llm.api_key:
        raise HTTPException(
            status_code=400,
            detail="OpenRouter API key is not configured. Add it under Settings → General.",
        )

    project_rows = list(
        db.scalars(
            select(Project).where(Project.study_id == payload.study_id).order_by(Project.name)
        ).all()
    )
    if payload.project_id:
        project_rows = [p for p in project_rows if p.id == payload.project_id]
        if not project_rows:
            raise HTTPException(status_code=404, detail="Project not found in this study")

    project_ids = [p.id for p in project_rows]
    project_name = project_rows[0].name if len(project_rows) == 1 else None

    recent: list[Submission] = []
    if project_ids:
        recent = list(
            db.scalars(
                select(Submission)
                .where(Submission.project_id.in_(project_ids))
                .order_by(Submission.submitted_at.desc())
                .limit(40)
            ).all()
        )

    status_rows = []
    if project_ids:
        status_rows = db.execute(
            select(Submission.status, func.count())
            .where(Submission.project_id.in_(project_ids))
            .group_by(Submission.status)
        ).all()

    context = {
        "studyId": payload.study_id,
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "toolCode": p.tool_code,
                "submissionCount": p.submission_count,
            }
            for p in project_rows
        ],
        "statusCounts": {str(s): int(c) for s, c in status_rows},
        "recentSubmissions": [
            {
                "id": s.id,
                "projectId": s.project_id,
                "enumerator": s.enumerator,
                "status": s.status,
                "submittedAt": s.submitted_at.isoformat() if s.submitted_at else None,
                "location": s.location,
                "sampleFields": {
                    k: v
                    for k, v in list((s.data or {}).items())[:12]
                    if not str(k).startswith("_")
                },
            }
            for s in recent
        ],
    }

    try:
        parsed = generate_insight_payload(settings, question=question, context=context)
    except LlmError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw = str(parsed.pop("_raw", "") or "")
    title = str(parsed.get("title") or question[:80] or "AI Insight").strip()
    summary = str(parsed.get("summary") or "").strip() or title
    content = str(parsed.get("content") or raw).strip()
    insight_type = str(parsed.get("type") or "summary").strip().lower()
    if insight_type not in {"anomaly", "trend", "recommendation", "summary"}:
        insight_type = "summary"
    severity = str(parsed.get("severity") or "info").strip().lower()
    if severity not in {"critical", "warning", "info"}:
        severity = "info"
    tags = parsed.get("tags") if isinstance(parsed.get("tags"), list) else ["ai-generated"]
    tags = [str(t) for t in tags][:12]

    row = Insight(
        id=str(uuid.uuid4()),
        title=title,
        summary=summary,
        content=content,
        type=insight_type,
        study_id=payload.study_id,
        project_id=payload.project_id,
        project_name=project_name,
        severity=severity,
        tags=tags,
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
