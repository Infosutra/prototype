"""Conversational report-building endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import ReportConversation
from app.db.session import get_db
from app.schemas.report_templates import (
    CreateReportConversationInput,
    ExecuteTemplateInput,
    ExecutedReportOut,
    ReportConversationOut,
    ReportConversationMessageOut,
    ReportConversationTurnInput,
    ReportConversationTurnOut,
    SaveConversationAsTemplateInput,
    TemplatePlanResultOut,
)
from app.services import report_conversations as conversations
from app.services.report_conversations import ConversationError
from app.services.report_execution import build_context, execute_spec
from app.services.report_runs import record_run
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
        return ReportConversationTurnOut(status="ok", conversation=_conversation_out(conversation))
    return _apply(db, conversation, payload.message)


@router.get(
    "/{conversation_id}",
    response_model=ReportConversationOut,
    operation_id="getReportConversation",
)
def get_conversation(
    conversation_id: str, db: Session = Depends(get_db)
) -> ReportConversationOut:
    return _conversation_out(_conversation_or_404(db, conversation_id))


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
    return _apply(db, conversation, payload.message)


def _apply(
    db: Session, conversation: ReportConversation, message: str
) -> ReportConversationTurnOut:
    try:
        result, _changes = conversations.apply_turn(db, conversation, message=message)
    except ConversationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_run(
        db,
        mode="patch" if result.intent == "patch" else "plan",
        status=result.status,
        study_id=conversation.study_id,
        conversation_id=conversation.id,
        provider=result.telemetry.provider,
        model=result.telemetry.model,
        prompt_id=result.telemetry.prompt_id,
        attempts=result.telemetry.attempts,
        prompt_tokens=result.telemetry.prompt_tokens,
        completion_tokens=result.telemetry.completion_tokens,
        latency_ms=result.telemetry.latency_ms,
        structured_output=result.telemetry.structured_output,
        validation_errors=result.error_dicts(),
        error=result.reason,
    )
    db.refresh(conversation)
    return ReportConversationTurnOut(
        status=result.status,
        conversation=_conversation_out(conversation),
        summary=result.summary,
        answer=result.summary or result.question or result.reason,
        question=result.question,
        reason=result.reason,
        errors=result.errors,
    )


@router.post(
    "/{conversation_id}/preview",
    response_model=ExecutedReportOut,
    operation_id="previewReportConversation",
)
def preview_conversation(
    conversation_id: str,
    payload: ExecuteTemplateInput,
    db: Session = Depends(get_db),
) -> ExecutedReportOut:
    conversation = _conversation_or_404(db, conversation_id)
    original = conversations.working_spec(conversation)
    needs_rebuild = original is not None and conversations.is_descriptive_only_spec(original)
    spec = conversations.ensure_executable_spec(
        db, conversation, report_kind=_kind(payload.report_kind or "adhoc")
    )
    if spec is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "This conversation's specification only describes tables and KPIs in text, "
                "so a real data preview cannot be rendered. Send another message asking for "
                "actual KPI/table components, then preview again."
                if needs_rebuild
                else "No specification to preview yet"
            ),
        )
    study = _resolve_study(db, payload.study_id or conversation.study_id)
    context = build_context(
        study,
        report_kind=_kind(payload.report_kind or "adhoc"),
        execution_date=payload.execution_date,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    executed = execute_spec(db, spec, context, run_ai=payload.run_ai)
    narratives = executed.narratives
    record_run(
        db,
        mode="analyze" if narratives.source == "ai" else "execute",
        status="ok",
        study_id=study.id,
        conversation_id=conversation.id,
        provider=narratives.provider,
        model=narratives.model,
        prompt_tokens=narratives.prompt_tokens,
        completion_tokens=narratives.completion_tokens,
        latency_ms=narratives.latency_ms,
        error=narratives.error,
    )
    return ExecutedReportOut(
        spec=executed.spec.model_dump(by_alias=True),
        data=executed.data,
        narratives=narratives.texts,
        unavailable=executed.errors,
        meta={
            "organizationName": executed.payload.meta.get("organizationName"),
            "rows": [list(row) for row in executed.payload.meta.get("rows", [])],
            "footer": executed.payload.meta.get("footer"),
        },
        html=executed.render_html(),
        plain_text=executed.render_plaintext(),
        ai_source=narratives.source,
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
        summary="Conversation saved as a template.",
    )
