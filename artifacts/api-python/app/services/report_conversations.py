"""Dynamic report conversations: a working specification refined turn by turn."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReportConversation, ReportConversationMessage, Study
from app.domain.report_spec.catalog import build_catalog
from app.domain.report_spec.spec import ReportSpec
from app.domain.report_spec.validation import parse_spec, validate_spec
from app.services.report_planner import PlanResult, patch_spec, plan_spec
from app.services.report_templates import TemplateError, create_template, diff_versions
from app.services.report_tools import all_descriptors, descriptors_by_id

import re


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


def working_spec(conversation: ReportConversation) -> ReportSpec | None:
    if not conversation.working_spec_json:
        return None
    parsed = parse_spec(conversation.working_spec_json)
    return parsed.spec


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
        if message.role == "user" and (message.content or "").strip()
    ]
    if extra and extra.strip():
        parts.append(extra.strip())
    return "\n\n".join(parts)


def is_descriptive_only_spec(spec: ReportSpec) -> bool:
    """True when the spec only captions KPIs/tables instead of binding real data."""
    check = validate_spec(spec, descriptors_by_id())
    codes = {issue.code for issue in check.errors}
    return bool(codes & {"text_standing_in_for_data", "no_data_bound_content"})


def ensure_executable_spec(
    db: Session,
    conversation: ReportConversation,
    *,
    report_kind: str = "adhoc",
) -> ReportSpec | None:
    """Return a data-bound working spec, rebuilding caption-only specs from user turns."""
    spec = working_spec(conversation)
    if spec is None:
        return None
    if not is_descriptive_only_spec(spec):
        return spec

    instructions = user_instructions(conversation)
    if not instructions.strip():
        return None

    reinforced = (
        f"{instructions.strip()}\n\n"
        "Output requirements: emit real data-bound components only "
        "(metric, kpi_group, table, ranking, progress, or chart) with a dataSource and "
        "catalog field names. Never use text components that describe what a KPI, table, "
        "or chart would show."
    )

    rebuilt: ReportSpec | None = None
    for _attempt in range(2):
        result = plan_spec(db, instructions=reinforced, report_kind=report_kind)
        if (
            result.ok
            and result.spec is not None
            and not is_descriptive_only_spec(result.spec)
        ):
            rebuilt = result.spec
            break

    if rebuilt is None:
        # Last resort for daily-style asks: use the system Daily template structure.
        lowered = instructions.lower()
        if "daily" in lowered or "dqa" in lowered:
            from app.services.report_templates import resolve_template
            from app.db.models import Study

            study = db.get(Study, conversation.study_id)
            template = resolve_template(db, study, "daily") if study else None
            if template is not None and template.current_version_id:
                from app.db.models import ReportTemplateVersion

                version = db.get(ReportTemplateVersion, template.current_version_id)
                parsed = parse_spec(version.spec_json if version else None)
                if parsed.spec is not None and not is_descriptive_only_spec(parsed.spec):
                    rebuilt = parsed.spec

    if rebuilt is None:
        return None

    conversation.working_spec_json = rebuilt.model_dump(by_alias=True)
    if not conversation.title or conversation.title.startswith("Untitled"):
        conversation.title = rebuilt.title or conversation.title
    conversation.updated_at = _now()
    db.commit()
    db.refresh(conversation)
    return rebuilt



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


def _append_message(
    db: Session,
    conversation: ReportConversation,
    *,
    role: str,
    content: str,
    spec: ReportSpec | None = None,
    changes: list[str] | None = None,
) -> ReportConversationMessage:
    message = ReportConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conversation.id,
        role=role,
        content=content,
        spec_snapshot_json=spec.model_dump(by_alias=True) if spec is not None else None,
        changes_json=changes or [],
        created_at=_now(),
    )
    db.add(message)
    conversation.updated_at = _now()
    if spec is not None:
        conversation.working_spec_json = spec.model_dump(by_alias=True)
        if conversation.title == "Untitled report" and spec.title:
            conversation.title = spec.title
    db.flush()
    return message


def _assistant_reply(result: PlanResult, changes: list[str]) -> str:
    """User-visible reply for a planning turn. Never claim failure on success."""
    if result.ok:
        if result.summary:
            return result.summary
        if changes:
            return changes[0]
        title = result.spec.title if result.spec else None
        return f"Updated the report{f' “{title}”' if title else ''}."
    if result.status in {"clarification", "answer"} and result.question:
        return result.question
    if result.question:
        return result.question
    if result.reason:
        return result.reason
    if result.errors:
        first = result.errors[0]
        return first.message or "The planned specification was invalid."
    return "I could not update the report."


_HELP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*help\s*[?.!]?\s*$",
        r"\bwhat can (you|i|we)\b",
        r"\bwhat (charts?|components?|tables?|tools?|sources?|kpi|metrics?)\b",
        r"\b(available|supported)\b.+\b(chart|component|table|source|tool|kpi)\b",
        r"\b(chart|component|table|source|tool|kpi)s?\b.+\b(available|supported)\b",
        r"\bgive (me )?(some )?examples?\b",
        r"\bshow (me )?(some )?(examples?|options?)\b",
        r"\bhow (do|can) i\b.+\b(report|chart|table|kpi)\b",
        r"\bwhat (do you|does this) (support|offer)\b",
    )
)

_COMPONENT_HELP_BLURBS: dict[str, str] = {
    "metric": "A single headline number (e.g. submissions today).",
    "kpi_group": "A row of related headline KPIs from one object source.",
    "text": "Static author prose — not for figures or tables.",
    "table": "A sortable data table with columns bound to a row source.",
    "ranking": "A top/bottom list ordered by a numeric field.",
    "bar_chart": "Vertical or horizontal bars comparing categories.",
    "stacked_bar_chart": "Stacked bars for parts of a whole by category.",
    "line_chart": "Trends over a sequence (e.g. study days).",
    "pie_chart": "Share of a total across categories.",
    "progress": "Bars toward a target (coverage vs plan).",
    "insight": "AI narrative summarizing selected data sources.",
    "warning": "AI callout of risks or open issues.",
    "action_plan": "AI recommended next steps for the field team.",
}


def is_help_intent(text: str) -> bool:
    """True when the user is asking what Compose can build, not describing a report."""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > 280:
        return False
    return any(pattern.search(stripped) for pattern in _HELP_PATTERNS)


def build_catalog_help_reply() -> str:
    """Deterministic help text from the live report-spec catalog."""
    catalog = build_catalog(all_descriptors())
    lines = [
        "Here’s what you can put in a report. Ask for these by name, or open Help for visual samples.",
        "",
        "Components:",
    ]
    for component in catalog.components:
        blurb = _COMPONENT_HELP_BLURBS.get(component.type, "Report building block.")
        lines.append(f"- `{component.type}` — {blurb}")
    lines.append("")
    lines.append("Data sources (bind figures to these ids):")
    for source in catalog.data_sources:
        lines.append(f"- `{source.id}` — {source.title}: {source.description}")
    lines.extend(
        [
            "",
            "Examples you can paste:",
            "- Show today's submissions, flagged percent, and open RED count as a KPI group.",
            "- Table of enumerator submission quality with clean, RED and AMBER counts.",
            "- Bar chart of RED and AMBER flags by tool.",
            "- Ranking of enumerators by flag rate today, worst first.",
        ]
    )
    return "\n".join(lines)


def apply_turn(
    db: Session,
    conversation: ReportConversation,
    *,
    message: str,
    report_kind: str = "adhoc",
) -> tuple[PlanResult, list[str]]:
    """Plan or patch the working specification from a user turn."""
    text = (message or "").strip()
    if not text:
        raise ConversationError("message is required")

    if is_help_intent(text):
        help_text = build_catalog_help_reply()
        result = PlanResult(status="answer", question=help_text)
        _append_message(db, conversation, role="user", content=text)
        _append_message(
            db,
            conversation,
            role="assistant",
            content=help_text,
            changes=["Showed available components and data sources."],
        )
        db.commit()
        db.refresh(conversation)
        return result, ["Showed available components and data sources."]

    current = working_spec(conversation)
    # Caption-only specs from earlier planner failures cannot be patched usefully —
    # rebuild from the full user request history instead.
    if current is not None and is_descriptive_only_spec(current):
        result = plan_spec(
            db,
            instructions=user_instructions(conversation, extra=text),
            report_kind=report_kind,
        )
        current = None
    elif current is None:
        result = plan_spec(db, instructions=text, report_kind=report_kind)
    else:
        result = patch_spec(
            db,
            instructions=text,
            current_spec=current,
            conversation=history(conversation),
            report_kind=report_kind,
        )

    changes: list[str] = []
    if result.ok and result.spec is not None:
        if current is None:
            changes = ["Initial specification planned."]
        else:
            # Reuse version-diff language against two in-memory snapshots.
            class _Snap:
                def __init__(self, spec: ReportSpec, prompt: str) -> None:
                    self.spec_json = spec.model_dump(by_alias=True)
                    self.prompt_text = prompt

            changes = [
                note
                for note in diff_versions(_Snap(current, ""), _Snap(result.spec, text))
                if note != "Initial version."
            ] or ["Specification updated."]

    _append_message(db, conversation, role="user", content=text)
    reply = _assistant_reply(result, changes)
    _append_message(
        db,
        conversation,
        role="assistant",
        content=reply,
        spec=result.spec if result.ok else working_spec(conversation),
        changes=changes,
    )
    db.commit()
    db.refresh(conversation)
    return result, changes


def save_as_template(
    db: Session,
    conversation: ReportConversation,
    *,
    name: str,
    description: str = "",
    report_kind: str = "adhoc",
) -> tuple:
    spec = working_spec(conversation)
    if spec is None:
        raise ConversationError("This conversation has no specification to save yet.")
    if is_descriptive_only_spec(spec):
        rebuilt = ensure_executable_spec(db, conversation, report_kind=report_kind)
        if rebuilt is None or is_descriptive_only_spec(rebuilt):
            raise ConversationError(
                "This conversation's specification only describes tables/KPIs in text. "
                "Send another message asking for real tables or KPIs, then save again."
            )
        spec = rebuilt
    prompt_text = user_instructions(conversation)
    from app.services.report_dates import extract_report_date, study_start_date
    from app.db.models import Study

    study = db.get(Study, conversation.study_id)
    try:
        template, version = create_template(
            db,
            name=name.strip() or spec.title,
            description=description,
            prompt_text=prompt_text,
            spec=spec,
            study_id=conversation.study_id,
            report_kind=report_kind,
            source="conversation",
            notes="Saved from a report conversation.",
            default_execution_date=extract_report_date(
                prompt_text,
                study_start=study_start_date(getattr(study, "start_date", None) if study else None),
            ),
        )
    except TemplateError as exc:
        raise ConversationError(str(exc)) from exc
    conversation.saved_template_id = template.id
    conversation.status = "saved"
    conversation.updated_at = _now()
    db.commit()
    return template, version
