"""Dynamic report conversations: working ReportSpec refined turn by turn.

Planning runs via ``POST /jobs`` type=plan. This service stores message history
and planned-spec snapshots — it does not call the LLM.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReportConversation, ReportConversationMessage, Study
from app.domain.reporting.spec import ReportSpec
from app.domain.reporting.validation import validate_report_spec
from app.services.report_templates import TemplateError, create_template


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ConversationError(Exception):
    """A conversation could not be created or updated."""


def get_conversation(db: Session, conversation_id: str) -> ReportConversation | None:
    return db.get(ReportConversation, conversation_id)


def list_conversations(db: Session, study_id: str | None = None) -> list[ReportConversation]:
    statement = select(ReportConversation).order_by(ReportConversation.updated_at.desc())
    if study_id:
        statement = statement.where(ReportConversation.study_id == study_id)
    return list(db.scalars(statement).all())


def working_spec_dict(conversation: ReportConversation) -> dict[str, Any] | None:
    raw = conversation.working_spec_json
    return raw if isinstance(raw, dict) else None


def history(conversation: ReportConversation) -> list[dict[str, str]]:
    return [
        {"role": message.role, "content": message.content}
        for message in conversation.messages
        if message.role in {"user", "assistant"}
    ]


def user_instructions(conversation: ReportConversation, *, extra: str | None = None) -> str:
    parts = [
        message.content
        for message in conversation.messages
        if message.role in {"user"} and (message.content or "").strip()
    ]
    if extra and extra.strip():
        parts.append(extra.strip())
    return "\n\n".join(parts)


def create_conversation(
    db: Session,
    study: Study,
    *,
    title: str = "Untitled report",
    commit: bool = True,
) -> ReportConversation:
    conversation = ReportConversation(
        id=str(uuid.uuid4()),
        study_id=study.id,
        title=(title or "").strip() or "Untitled report",
        status="active",
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(conversation)
    db.flush()
    if commit:
        db.commit()
        db.refresh(conversation)
    return conversation


def update_conversation(
    db: Session,
    conversation: ReportConversation,
    *,
    title: str | None = None,
    commit: bool = True,
) -> ReportConversation:
    if title is not None:
        cleaned = title.strip()
        if not cleaned:
            raise ConversationError("title is required")
        conversation.title = cleaned
    conversation.updated_at = _now()
    if commit:
        db.commit()
        db.refresh(conversation)
    return conversation


def delete_conversation(
    db: Session,
    conversation: ReportConversation,
    *,
    commit: bool = True,
) -> None:
    db.delete(conversation)
    if commit:
        db.commit()


def _append_message(
    db: Session,
    conversation: ReportConversation,
    *,
    role: str,
    content: str,
    spec: dict[str, Any] | None = None,
    changes: list[str] | None = None,
) -> ReportConversationMessage:
    message = ReportConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        role=role,
        content=content,
        spec_snapshot_json=spec,
        changes_json=changes or [],
        created_at=_now(),
    )
    db.add(message)
    conversation.updated_at = _now()
    if spec is not None:
        conversation.working_spec_json = spec
        title = str(spec.get("title") or "").strip()
        if conversation.title == "Untitled report" and title:
            conversation.title = title
    db.flush()
    return message


_HELP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*help\s*[?.!]?\s*$",
        r"\bwhat can (you|i|we)\b",
        r"\bwhat (charts?|components?|tables?|kpi|metrics?)\b",
        r"\b(available|supported)\b.+\b(chart|component|table|kpi)\b",
        r"\bgive (me )?(some )?examples?\b",
        r"\bshow (me )?(some )?(examples?|options?)\b",
    )
)


def is_help_intent(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped or len(stripped) > 280:
        return False
    return any(pattern.search(stripped) for pattern in _HELP_PATTERNS)


def build_catalog_help_reply() -> str:
    return (
        "Describe the report in English, then Plan. The planner builds a ReportSpec "
        "using Query IR entities (submission, flag, answer) — KPIs, tables, charts, "
        "progress, and narratives. Anything that cannot be bound (email, Slack, raw "
        "dumps) shows up as unmapped. Preview runs an execute job against your study."
    )


def apply_turn(
    db: Session,
    conversation: ReportConversation,
    *,
    message: str,
    spec: dict[str, Any] | None = None,
    unmapped: list[dict[str, Any]] | None = None,
    judgement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a user turn and optional PlanResult snapshot (from a plan job)."""
    text = (message or "").strip()
    if not text:
        raise ConversationError("message is required")

    if is_help_intent(text) and spec is None:
        help_text = build_catalog_help_reply()
        _append_message(db, conversation, role="user", content=text)
        _append_message(
            db,
            conversation,
            role="assistant",
            content=help_text,
            changes=["Showed compose help."],
        )
        db.commit()
        db.refresh(conversation)
        return {
            "status": "answer",
            "summary": help_text,
            "answer": help_text,
            "unmapped": [],
            "judgement": None,
        }

    if spec is None:
        raise ConversationError(
            "spec is required. Plan via POST /jobs type=plan, then send the resulting spec."
        )

    errors = validate_report_spec(spec)
    if errors:
        raise ConversationError("Invalid ReportSpec: " + "; ".join(errors))

    parsed = ReportSpec.model_validate(spec)
    spec_json = parsed.model_dump(by_alias=True)

    changes = ["Specification updated."] if working_spec_dict(conversation) else [
        "Initial specification planned."
    ]
    unmapped_list = list(unmapped or [])
    judge = judgement if isinstance(judgement, dict) else None

    summary_bits = [changes[0]]
    if unmapped_list:
        summary_bits.append(f"{len(unmapped_list)} request(s) could not be mapped.")
    if judge and judge.get("faithful") is False:
        summary_bits.append("Judge flagged faithfulness issues.")
    summary = " ".join(summary_bits)

    _append_message(db, conversation, role="user", content=text)
    _append_message(
        db,
        conversation,
        role="assistant",
        content=summary,
        spec=spec_json,
        changes=changes,
    )
    db.commit()
    db.refresh(conversation)
    return {
        "status": "ok",
        "summary": summary,
        "answer": summary,
        "unmapped": unmapped_list,
        "judgement": judge,
        "spec": spec_json,
    }


def save_as_template(
    db: Session,
    conversation: ReportConversation,
    *,
    name: str,
    description: str = "",
    report_kind: str = "adhoc",
) -> tuple:
    spec = working_spec_dict(conversation)
    if spec is None:
        raise ConversationError("This conversation has no specification to save yet.")
    prompt_text = user_instructions(conversation)
    from app.db.models import Study
    from app.services.report_dates import extract_report_date, study_start_date

    study = db.get(Study, conversation.study_id)
    try:
        template, version = create_template(
            db,
            name=name.strip() or str(spec.get("title") or "Report"),
            description=description,
            prompt_text=prompt_text,
            spec=spec,
            study_id=conversation.study_id,
            report_kind=report_kind,  # type: ignore[arg-type]
            source="conversation",
            notes="Saved from a report conversation.",
            default_execution_date=extract_report_date(
                prompt_text,
                study_start=study_start_date(
                    getattr(study, "start_date", None) if study else None
                ),
            ),
        )
    except TemplateError as exc:
        raise ConversationError(str(exc)) from exc
    conversation.saved_template_id = template.id
    conversation.status = "saved"
    conversation.updated_at = _now()
    db.commit()
    return template, version
