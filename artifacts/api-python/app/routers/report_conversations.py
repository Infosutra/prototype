"""Conversational report-building endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import ReportConversation
from app.db.session import get_db
from app.schemas.common import OkResponse
from app.schemas.report_templates import (
    CreateReportConversationInput,
    ReportConversationOut,
    ReportConversationMessageOut,
    ReportConversationTurnInput,
    ReportConversationTurnOut,
    SaveConversationAsTemplateInput,
    TemplatePlanResultOut,
    UpdateReportConversationInput,
)
from app.services import report_conversations as conversations
from app.services.report_conversations import ConversationError
from app.services.report_templates import TemplateError
from app.routers.report_templates import _detail_out, _kind, _resolve_study

router = APIRouter(prefix="/report-conversations", tags=["report-conversations"])


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _conversation_or_404(db: Session, conversation_id: str) -> ReportConversation:
    row = conversations.get_conversation(db, conversation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report conversation not found")
    return row


def _conversation_out(conversation: ReportConversation) -> ReportConversationOut:
    return ReportConversationOut(
        id=conversation.id,
        study_id=conversation.study_id,
        title=conversation.title,
        status=conversation.status,
        saved_template_id=conversation.saved_template_id,
        spec=conversation.working_spec_json,
        messages=[
            ReportConversationMessageOut(
                id=message.id,
                role=message.role,
                content=message.content,
                spec=message.spec_snapshot_json,
                changes=list(message.changes_json or []),
                created_at=_iso(message.created_at),
            )
            for message in conversation.messages
        ],
        created_at=_iso(conversation.created_at),
        updated_at=_iso(conversation.updated_at),
    )


@router.get("", response_model=list[ReportConversationOut], operation_id="listReportConversations")
def list_conversations(
    study_id: str | None = Query(default=None, alias="studyId"),
    db: Session = Depends(get_db),
) -> list[ReportConversationOut]:
    return [
        _conversation_out(row)
        for row in conversations.list_conversations(db, study_id=study_id)
    ]


@router.post("", response_model=ReportConversationTurnOut, operation_id="createReportConversation")
def create_conversation(
    payload: CreateReportConversationInput,
    db: Session = Depends(get_db),
) -> ReportConversationTurnOut:
    study = _resolve_study(db, payload.study_id)
    conversation = conversations.create_conversation(
        db, study, title=payload.title, commit=not bool(payload.message.strip())
    )
    if not payload.message.strip():
        return ReportConversationTurnOut(
            status="ok", conversation=_conversation_out(conversation)
        )
    return _apply(
        db,
        conversation,
        message=payload.message,
        spec=payload.spec,
        unmapped=payload.unmapped,
        judgement=payload.judgement,
    )


@router.get(
    "/{conversation_id}",
    response_model=ReportConversationOut,
    operation_id="getReportConversation",
)
def get_conversation(
    conversation_id: str, db: Session = Depends(get_db)
) -> ReportConversationOut:
    return _conversation_out(_conversation_or_404(db, conversation_id))


@router.patch(
    "/{conversation_id}",
    response_model=ReportConversationOut,
    operation_id="updateReportConversation",
)
def update_conversation(
    conversation_id: str,
    payload: UpdateReportConversationInput,
    db: Session = Depends(get_db),
) -> ReportConversationOut:
    conversation = _conversation_or_404(db, conversation_id)
    if payload.title is None:
        return _conversation_out(conversation)
    try:
        conversations.update_conversation(db, conversation, title=payload.title)
    except ConversationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _conversation_out(conversation)


@router.delete(
    "/{conversation_id}",
    response_model=OkResponse,
    operation_id="deleteReportConversation",
)
def delete_conversation(
    conversation_id: str, db: Session = Depends(get_db)
) -> OkResponse:
    conversation = _conversation_or_404(db, conversation_id)
    conversations.delete_conversation(db, conversation)
    return OkResponse(success=True)


@router.post(
    "/{conversation_id}/messages",
    response_model=ReportConversationTurnOut,
    operation_id="addReportConversationMessage",
)
def add_message(
    conversation_id: str,
    payload: ReportConversationTurnInput,
    db: Session = Depends(get_db),
) -> ReportConversationTurnOut:
    conversation = _conversation_or_404(db, conversation_id)
    return _apply(
        db,
        conversation,
        message=payload.message,
        spec=payload.spec,
        unmapped=payload.unmapped,
        judgement=payload.judgement,
    )


def _apply(
    db: Session,
    conversation: ReportConversation,
    *,
    message: str,
    spec: dict | None = None,
    unmapped: list | None = None,
    judgement: dict | None = None,
) -> ReportConversationTurnOut:
    try:
        result = conversations.apply_turn(
            db,
            conversation,
            message=message,
            spec=spec,
            unmapped=unmapped,
            judgement=judgement,
        )
    except ConversationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(conversation)
    return ReportConversationTurnOut(
        status=result.get("status") or "ok",
        conversation=_conversation_out(conversation),
        summary=result.get("summary"),
        answer=result.get("answer"),
        unmapped=list(result.get("unmapped") or []),
        judgement=result.get("judgement"),
        spec=result.get("spec"),
    )


@router.post(
    "/{conversation_id}/save-as-template",
    response_model=TemplatePlanResultOut,
    operation_id="saveReportConversationAsTemplate",
)
def save_as_template(
    conversation_id: str,
    payload: SaveConversationAsTemplateInput,
    db: Session = Depends(get_db),
) -> TemplatePlanResultOut:
    conversation = _conversation_or_404(db, conversation_id)
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    try:
        template, _version = conversations.save_as_template(
            db,
            conversation,
            name=payload.name,
            description=payload.description,
            report_kind=_kind(payload.report_kind),
        )
    except (ConversationError, TemplateError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TemplatePlanResultOut(
        status="ok",
        template=_detail_out(db, template),
        summary="Saved conversation as template.",
    )
