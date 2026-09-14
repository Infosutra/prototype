"""Interactive report-template authoring: plan → bind → conflict pause → user judge."""

from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import ReportTemplate
from app.domain.reporting.conflicts import find_field_tool_conflicts
from app.domain.reporting.spec_walk import iter_queries
from app.services.reporting.binder import bind_spec
from app.services.reporting.catalog_for_llm import catalog_for_llm
from app.services.reporting.plan_explain import (
    humanize_plan_issues,
    humanize_validation_error,
    partial_issue_question,
)
from app.services.reporting.planner import LlmInvoker, PlanError, plan_report
from app.services.reporting.section_labels import (
    append_components_to_section,
    apply_section_numbers,
    extract_section_asks,
    merge_scaffolded_section,
    missing_ask_issues,
    missing_section_asks,
    omitted_section_numbers,
    remove_section_by_number,
    scaffold_section_for_ask,
    scaffold_section_from_free_text,
    section_asks_for_missing_check,
    section_number_in_text,
    spec_fingerprint,
    visual_choice_from_text,
    wants_enumerator_quality_ask,
)

WELCOME_MESSAGE = (
    "Describe the report you want. I'll draft a specification and stop to ask "
    "when something is unclear — for example which form a question belongs to, "
    "or whether a nickname like “interviewer” should mean enumerator."
)

_CONFIRM = re.compile(
    r"^\s*(yes|yeah|yep|y|ok|okay|looks good|that'?s (right|it|correct)|"
    r"confirm|proceed|save( it)?|correct|keep( it)?|leave it off)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_NO = re.compile(
    r"^\s*(no|nope|not that|wrong|change|don't|do not)\b",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_authoring() -> dict[str, Any]:
    return {
        "status": "drafting",
        "messages": [
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": WELCOME_MESSAGE,
                "createdAt": _now_iso(),
                "steps": [],
            }
        ],
        "pendingQuestions": [],
        "promptText": "",
        "unmapped": [],
        "binderMappings": [],
    }


def authoring_state(template: ReportTemplate) -> dict[str, Any]:
    raw = template.authoring_json
    if isinstance(raw, dict) and raw.get("messages"):
        return copy.deepcopy(raw)
    return default_authoring()


def _append_message(
    state: dict[str, Any],
    *,
    role: str,
    content: str,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message = {
        "id": str(uuid.uuid4()),
        "role": role,
        "content": content,
        "createdAt": _now_iso(),
        "steps": steps or [],
    }
    messages = list(state.get("messages") or [])
    messages.append(message)
    state["messages"] = messages
    return message


def _event(name: str, **data: Any) -> dict[str, Any]:
    return {"event": name, **data}


def _match_option(question: dict[str, Any], text: str) -> str | None:
    needle = (text or "").strip().lower()
    if not needle:
        return None
    for option in question.get("options") or []:
        if not isinstance(option, dict):
            continue
        for key in ("id", "value", "label"):
            value = str(option.get(key) or "").strip().lower()
            if value and (needle == value or value in needle or needle in value):
                return str(option.get("value") or option.get("id") or "")
    return None


def _apply_tool_filter(spec: dict[str, Any], path: str, tool_code: str) -> None:
    for existing_path, query in iter_queries(spec):
        if existing_path != path:
            continue
        filters = query.get("filters")
        if not isinstance(filters, list):
            filters = []
            query["filters"] = filters
        filters.append({"field": "toolCode", "op": "eq", "value": tool_code})
        return


def _resolve_answer(
    spec: dict[str, Any] | None,
    question: dict[str, Any],
    text: str,
) -> tuple[bool, str, bool]:
    """Return (resolved, note, need_replan)."""
    kind = str(question.get("kind") or "")
    matched = _match_option(question, text)
    confirm = bool(_CONFIRM.match(text or ""))
    deny = bool(_NO.match(text or ""))

    if kind == "field_tool_conflict":
        code = matched
        if not code and confirm:
            return False, "", False
        if not code:
            code = (text or "").strip()
        if spec and code:
            path = str(question.get("path") or "")
            _apply_tool_filter(spec, path, code)
            return True, f"Use toolCode {code} for {question.get('fieldKey')}.", False
        return False, "", False

    if kind == "binder_confirm":
        mapping = question.get("mapping") or {}
        source = mapping.get("from")
        dest = mapping.get("to")
        if deny or (matched and str(matched).lower() in {"no", "false"}):
            return True, f"Do not map {source} to {dest}.", True
        if confirm or (matched and str(matched).lower() in {"yes", "true", dest}):
            return True, f"Keep mapping {source} → {dest}.", False
        return False, "", False

    if kind == "unmapped":
        if deny or (matched and "leave" in str(matched).lower()):
            return True, "Leave the unmapped request off the report.", False
        if matched and "explain" in str(matched).lower():
            # Wait for free-text explanation; do not replan on the button alone.
            return False, "", False
        if confirm:
            intent = question.get("userIntent") or question.get("prompt")
            return True, f"The user still wants: {intent}. Re-bind it if possible.", True
        # Free-text after "I'll explain" (or direct typed answer).
        return True, f"The user still wants: {text}. Re-bind it if possible.", True

    if kind == "confirm_spec":
        if deny:
            return True, f"Revise the spec: {text}", True
        if confirm:
            return True, "User confirmed the working spec.", False
        return True, f"Revise the spec: {text}", True

    if kind == "plan_partial":
        if matched and str(matched).lower() in {"skip", "leave"}:
            number = section_number_in_text(str(question.get("prompt") or ""))
            if number:
                return (
                    True,
                    f"Omit section {number} from the report.",
                    False,
                )
            return True, "Leave the unfinished part off for now.", False
        if matched and str(matched).lower() in {"clarify", "retry"}:
            # Button alone is not a clarification — wait for free text.
            return False, "", False
        number = section_number_in_text(str(question.get("prompt") or ""))
        visual = visual_choice_from_text(str(matched or text or ""))
        prompt_blob = str(question.get("prompt") or text or "")
        if number and visual:
            shape = "table" if visual == "table" else f"{visual.replace('_', ' ')} chart"
            return (
                True,
                _partial_visual_note(number=number, shape=shape, prompt=prompt_blob),
                True,
            )
        if confirm:
            return True, f"Clarification for the unfinished part: {text}", True
        # Free-text clarification → replan with their wording.
        return True, f"Clarification for the unfinished part: {text}", True

    if kind == "section_placement":
        ask = str(question.get("userAsk") or text or "").strip()
        choice = str(matched or "").strip()
        if choice in {"leave", "skip"} or deny:
            return True, "Leave that request off the report.", False
        if choice == "new":
            built = scaffold_section_from_free_text(ask, spec=spec)
            if built and spec is not None:
                merged = merge_scaffolded_section(spec, built)
                if merged is not None:
                    spec.clear()
                    spec.update(merged)
                    return (
                        True,
                        f"Added a new section for: {ask}",
                        False,
                    )
            return True, f"Add a new section for this request: {ask}", True
        if choice.startswith("section:"):
            section_id = choice.split(":", 1)[1].strip()
            title = _section_title_by_id(spec, section_id) or section_id
            built = scaffold_section_from_free_text(ask, spec=spec)
            comps = (
                list(built.get("components") or [])
                if isinstance(built, dict)
                else []
            )
            if comps and spec is not None:
                merged = append_components_to_section(
                    spec, section_id=section_id, components=comps
                )
                if merged is not None:
                    spec.clear()
                    spec.update(merged)
                    return (
                        True,
                        f"Added into existing section “{title}”: {ask}",
                        False,
                    )
            return (
                True,
                f'Add into the existing section “{title}” (sectionId={section_id}): {ask}',
                True,
            )
        return False, "", False

    return False, "", False


def _section_title_by_id(spec: dict[str, Any] | None, section_id: str) -> str | None:
    if not isinstance(spec, dict) or not section_id:
        return None
    sections = spec.get("sections")
    if not isinstance(sections, list):
        return None
    for row in sections:
        if isinstance(row, dict) and str(row.get("id") or "") == section_id:
            title = str(row.get("title") or "").strip()
            return title or section_id
    return None


def _partial_visual_note(*, number: str, shape: str, prompt: str) -> str:
    """Shape-choice note tailored to the stuck section — not hardcoded to 1.4."""
    blob = prompt.lower()
    if any(
        token in blob
        for token in (
            "enumerator",
            "submission quality",
            "clean forms",
            "flagged forms",
            "dqa issue",
        )
    ):
        return (
            f"Clarification for section {number}: add enumerator quality as a {shape} "
            "with forms submitted, clean forms, and flagged forms, plus exact DQA "
            "issues (enumerator × rule). Use catalog counts only — no invented rates."
        )
    if "flag rate" in blob or "coverage" in blob or "against target" in blob or "against plan" in blob:
        return (
            f"Clarification for section {number}: add it with plain counts "
            f"(no rate/ratio measure). Use a {shape} for cumulative submissions "
            "against target by tool and/or flag counts by study day."
        )
    return (
        f"Clarification for section {number}: add it as a {shape} using catalog "
        "counts only (group-bys and measures that exist — no invented rates)."
    )


def _unmapped_questions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or []:
        intent = str(item.get("userIntent") or item.get("name") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not intent:
            continue
        out.append(
            {
                "id": f"unmapped:{intent}",
                "kind": "unmapped",
                "prompt": (
                    f'I cannot put “{intent}” on the report'
                    + (f" ({reason})" if reason else "")
                    + ". Leave it off, or explain how it should bind to the catalog?"
                ),
                "userIntent": intent,
                "options": [
                    {"id": "leave", "label": "Leave it off", "value": "leave"},
                    {"id": "explain", "label": "I'll explain", "value": "explain"},
                ],
            }
        )
    return out


def _partial_questions(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(issues or []):
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or "").strip()
        section = str(item.get("section") or "").strip()
        prompt = reason or (
            f'I could not finish “{section}”. Clarify what you want there, or leave it off.'
            if section
            else "I could not finish that part. Clarify it, or leave it off."
        )
        dropped = (
            item.get("droppedComponent")
            if isinstance(item.get("droppedComponent"), dict)
            else None
        )
        out.append(
            partial_issue_question(prompt, index=index, dropped_component=dropped)
        )
    return out


def _binder_questions(mappings: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in mappings or []:
        source = item.get("from")
        dest = item.get("to")
        if not source or not dest:
            continue
        out.append(
            {
                "id": f"binder:{source}:{dest}",
                "kind": "binder_confirm",
                "prompt": f'I heard “{source}” as {dest}. Keep that?',
                "mapping": {"from": source, "to": dest},
                "options": [
                    {"id": "yes", "label": "Yes, keep it", "value": "yes"},
                    {"id": "no", "label": "No, use something else", "value": "no"},
                ],
            }
        )
    return out


def _confirm_question() -> dict[str, Any]:
    return {
        "id": "confirm-spec",
        "kind": "confirm_spec",
        "prompt": "Is this the report you meant? Say yes to keep it, or tell me what to change.",
        "options": [
            {"id": "yes", "label": "Yes, that's it", "value": "yes"},
        ],
    }


def _is_unplaced_content_request(text: str) -> bool:
    """True when the latest message looks like content that should land in the draft."""
    message = (text or "").strip()
    if len(message) < 12:
        return False
    if _CONFIRM.match(message):
        return False
    if extract_section_asks(message) or omitted_section_numbers(message):
        return False
    if re.match(
        r"(?is)^\s*(rename|change the title|update the title|call it|title\s*:)\b",
        message,
    ):
        return False
    return True


def _placement_question(ask: str, spec: dict[str, Any] | None) -> dict[str, Any]:
    clipped = (ask or "").strip()
    if len(clipped) > 220:
        clipped = clipped[:217].rstrip() + "…"
    options: list[dict[str, str]] = [
        {"id": "new", "label": "Add as a new section", "value": "new"},
    ]
    sections = spec.get("sections") if isinstance(spec, dict) else None
    if isinstance(sections, list):
        for row in sections:
            if not isinstance(row, dict):
                continue
            sid = str(row.get("id") or "").strip()
            if not sid:
                continue
            title = str(row.get("title") or "").strip() or sid
            options.append(
                {
                    "id": f"section:{sid}",
                    "label": f"Add to: {title}",
                    "value": f"section:{sid}",
                }
            )
    options.append({"id": "leave", "label": "Leave it off", "value": "leave"})
    return {
        "id": f"placement:{uuid.uuid4().hex[:10]}",
        "kind": "section_placement",
        "prompt": (
            f'I didn’t add this to the draft yet:\n“{clipped}”\n\n'
            "Should I add it as a new section, or put it into an existing one?"
        ),
        "userAsk": (ask or "").strip(),
        "options": options,
    }


def _persist(template: ReportTemplate, state: dict[str, Any], spec: dict[str, Any] | None) -> None:
    template.authoring_json = copy.deepcopy(state)
    template.working_spec_json = copy.deepcopy(spec) if spec else None
    template.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    flag_modified(template, "authoring_json")
    flag_modified(template, "working_spec_json")


def _message_bypasses_pending(question: dict[str, Any], text: str) -> bool:
    """True when the user moved on instead of answering the open question."""
    message = (text or "").strip()
    if not message:
        return False
    kind = str(question.get("kind") or "")
    q_num = section_number_in_text(str(question.get("prompt") or ""))
    latest_asks = extract_section_asks(message)
    if latest_asks and (not q_num or all(ask.get("number") != q_num for ask in latest_asks)):
        return True
    if omitted_section_numbers(message):
        return True
    # Brand-new report framing while a partial/unmapped/placement question is open.
    if kind in {"plan_partial", "unmapped", "section_placement"} and re.match(
        r"(?is)^\s*(title\s*:|create\s+(a\s+)?(new\s+)?report|start\s+over)\b",
        message,
    ):
        return True
    # New free-text request that does not address the stuck section / options.
    if kind in {"plan_partial", "unmapped"} and q_num:
        optionish = re.search(
            r"(?i)\b(try as|use a|show (it )?as|leave|skip|bar chart|line chart|"
            r"horizontal|table|clarify|simplify|rephrase)\b",
            message,
        )
        if q_num not in message and not optionish and not latest_asks:
            return True
    if kind == "section_placement":
        optionish = re.search(
            r"(?i)\b(new section|existing|add to|leave|skip|leave it off)\b",
            message,
        )
        prior_ask = str(question.get("userAsk") or "").strip()
        if not optionish and not latest_asks and message != prior_ask:
            return True
    return False


def author_turn(
    db: Session,
    template: ReportTemplate,
    *,
    message: str,
    answer: dict[str, str] | None = None,
    llm: LlmInvoker | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield SSE-shaped events, then persist authoring state on the template."""
    state = authoring_state(template)
    steps: list[dict[str, Any]] = []
    text = (message or "").strip()
    if answer and answer.get("value") and not text:
        text = str(answer.get("value"))
    if not text:
        yield _event("error", message="message is required")
        return

    _append_message(state, role="user", content=text)
    prompt_parts = [str(state.get("promptText") or "").strip(), text]
    spec: dict[str, Any] | None = copy.deepcopy(template.working_spec_json) if template.working_spec_json else None
    catalog = catalog_for_llm(db, template.study_id)
    study_keys = ((catalog.get("entities") or {}).get("answer") or {}).get("studyFieldKeys") or []
    notes: list[str] = []
    need_replan = False
    pending = list(state.get("pendingQuestions") or [])
    clarifying_question: dict[str, Any] | None = None
    latest_user_message = text

    if pending:
        target = None
        if answer and answer.get("questionId"):
            target = next(
                (q for q in pending if str(q.get("id")) == str(answer.get("questionId"))),
                pending[0],
            )
            text = str(answer.get("value") or text)
        else:
            target = pending[0]

        # Explicit option click always answers the question. Free-text may move on.
        clicked = bool(answer and answer.get("questionId") and answer.get("value"))
        if not clicked and target and _message_bypasses_pending(target, latest_user_message):
            stuck_number = section_number_in_text(str(target.get("prompt") or ""))
            if stuck_number and stuck_number not in {
                ask.get("number") for ask in extract_section_asks(latest_user_message)
            }:
                notes.append(f"Omit section {stuck_number} from the report.")
            pending = []
            state["pendingQuestions"] = []
            need_replan = True
            yield _event(
                "step",
                id="resolve",
                title="Applying your answer",
                status="done",
                detail="Moved on from the previous clarification.",
            )
            steps.append(
                {
                    "id": "resolve",
                    "title": "Applying your answer",
                    "status": "done",
                    "detail": "Moved on from the previous clarification.",
                }
            )
        else:
            clarifying_question = target
            resolved, note, replan = _resolve_answer(spec, target, text)
            yield _event(
                "step",
                id="resolve",
                title="Applying your answer",
                status="running",
                detail=target.get("prompt"),
            )
            if not resolved:
                yield _event(
                    "step",
                    id="resolve",
                    title="Applying your answer",
                    status="done",
                    detail="Still need a clearer choice.",
                )
                assistant = (
                    "I still need this answered:\n"
                    + str(target.get("prompt") or "Please pick one of the options.")
                )
                msg = _append_message(state, role="assistant", content=assistant)
                yield _event("assistant", text=assistant, messageId=msg["id"])
                yield _event("questions", questions=pending)
                yield _event("done", status=state.get("status") or "awaiting_user")
                _persist(template, state, spec)
                db.commit()
                return
            notes.append(note)
            need_replan = need_replan or replan
            pending = [q for q in pending if q.get("id") != target.get("id")]
            state["pendingQuestions"] = pending
            yield _event(
                "step",
                id="resolve",
                title="Applying your answer",
                status="done",
                detail=note,
            )
            steps.append(
                {"id": "resolve", "title": "Applying your answer", "status": "done", "detail": note}
            )
            if pending and not need_replan:
                assistant = "Next question:\n" + str(pending[0].get("prompt") or "")
                state["status"] = "awaiting_user"
                msg = _append_message(state, role="assistant", content=assistant, steps=steps)
                yield _event("assistant", text=assistant, messageId=msg["id"])
                yield _event("questions", questions=pending)
                if spec:
                    yield _event("spec", spec=spec)
                yield _event("done", status="awaiting_user")
                _persist(template, state, spec)
                db.commit()
                return
            if not need_replan and spec and not pending:
                # Fall through to conflict re-check + confirm without a full plan.
                pass
            else:
                spec = spec if not need_replan else spec

    instructions = "\n".join(part for part in prompt_parts + notes if part).strip()

    # Honour remove/leave-off notes even when we skip a full re-plan.
    if spec:
        for number in omitted_section_numbers(instructions):
            spec = remove_section_by_number(spec, number)

    if state.get("status") == "ready" and _CONFIRM.match(text) and not need_replan:
        assistant = "This spec is confirmed. Save it as a template version when you are ready."
        state["status"] = "ready"
        state["promptText"] = instructions
        msg = _append_message(state, role="assistant", content=assistant, steps=steps)
        yield _event("assistant", text=assistant, messageId=msg["id"])
        if spec:
            yield _event("spec", spec=spec)
        yield _event("done", status="ready")
        _persist(template, state, spec)
        db.commit()
        return

    skip_plan = bool(spec) and not need_replan and any(s.get("id") == "resolve" for s in steps)

    mappings: list[dict[str, str]] = list(state.get("binderMappings") or [])
    binder_unmapped: list[dict[str, Any]] = []
    prior_spec = copy.deepcopy(spec) if spec else None
    partial_issues: list[dict[str, Any]] = []
    try:
        if not skip_plan:
            yield _event(
                "step",
                id="plan",
                title="Drafting the report spec",
                status="running",
                detail="Planner is mapping your request onto the study catalog.",
            )
            planned = plan_report(
                db,
                study_id=template.study_id,
                instructions=instructions,
                current_spec=spec,
                llm=llm,
                judge=False,
                partial_ok=True,
            )
            section_asks = extract_section_asks(instructions)
            spec = apply_section_numbers(planned["spec"], section_asks) or planned["spec"]
            for number in omitted_section_numbers(instructions):
                spec = remove_section_by_number(spec, number)
            state["unmapped"] = planned.get("unmapped") or []
            explain_llm = llm or _require_llm(db, llm)
            partial_issues = humanize_plan_issues(
                list(planned.get("issues") or []),
                instructions=instructions,
                spec=spec or prior_spec,
                invoker=explain_llm,
            )
            missing_scope = section_asks_for_missing_check(
                instructions=instructions,
                latest_message=latest_user_message,
                clarifying_question=clarifying_question,
            )
            dropped_asks = missing_section_asks(spec, missing_scope)
            if dropped_asks:
                visual = visual_choice_from_text(latest_user_message)
                if not visual:
                    for note in reversed(notes):
                        visual = visual_choice_from_text(str(note))
                        if visual:
                            break
                still_missing: list[dict[str, str]] = []
                for ask in dropped_asks:
                    ask_visual = visual
                    if not ask_visual and wants_enumerator_quality_ask(
                        ask, instructions=instructions
                    ):
                        ask_visual = "table"
                    if not ask_visual:
                        still_missing.append(ask)
                        continue
                    scaffold = scaffold_section_for_ask(
                        ask, visual=ask_visual, instructions=instructions
                    )
                    merged = merge_scaffolded_section(spec, scaffold)
                    if merged is None:
                        still_missing.append(ask)
                        continue
                    spec = merged
                dropped_asks = still_missing
                if dropped_asks:
                    partial_issues.extend(
                        missing_ask_issues(dropped_asks, instructions=instructions)
                    )
            # Unnumbered asks the planner ignored: ask where to place them
            # (new section vs an existing one) instead of special-casing content.
            if (
                prior_spec
                and _is_unplaced_content_request(latest_user_message)
                and spec_fingerprint(spec) == spec_fingerprint(prior_spec)
            ):
                state["pendingPlacementAsk"] = latest_user_message.strip()
            kept_from = planned.get("keptFrom")
            plan_detail = f"{_section_count(spec)} section(s)."
            if planned.get("partial") or dropped_asks:
                plan_detail = (
                    f"Kept {_section_count(spec)} section(s)"
                    + (f" ({kept_from})" if kept_from else "")
                    + f"; {len(partial_issues)} part(s) need clarification."
                )
            yield _event(
                "step",
                id="plan",
                title="Drafting the report spec",
                status="done",
                detail=plan_detail,
            )
            steps.append(
                {
                    "id": "plan",
                    "title": "Drafting the report spec",
                    "status": "done",
                    "detail": plan_detail,
                }
            )
            yield _event(
                "step",
                id="bind",
                title="Binding names to the catalog",
                status="running",
                detail="Matching nicknames to allowed field names.",
            )
            bound = bind_spec(
                spec or {},
                catalog,
                invoker=llm or _require_llm(db, llm),
            )
            spec = bound["spec"]
            mappings = bound.get("mappings") or []
            binder_unmapped = bound.get("unmapped") or []
            state["binderMappings"] = mappings
            detail = (
                ", ".join(f"{m['from']} → {m['to']}" for m in mappings)
                if mappings
                else "No nickname remaps needed."
            )
            yield _event(
                "step",
                id="bind",
                title="Binding names to the catalog",
                status="done",
                detail=detail,
            )
            steps.append(
                {
                    "id": "bind",
                    "title": "Binding names to the catalog",
                    "status": "done",
                    "detail": detail,
                }
            )
        else:
            yield _event(
                "step",
                id="plan",
                title="Keeping the current spec",
                status="done",
                detail="Applied your clarification without a full re-plan.",
            )
            steps.append(
                {
                    "id": "plan",
                    "title": "Keeping the current spec",
                    "status": "done",
                    "detail": "Applied your clarification without a full re-plan.",
                }
            )

        yield _event(
            "step",
            id="conflicts",
            title="Checking form-name clashes",
            status="running",
            detail="Looking for fieldKeys that exist on more than one tool.",
        )
        conflicts = find_field_tool_conflicts(spec or {}, study_keys)
        yield _event(
            "step",
            id="conflicts",
            title="Checking form-name clashes",
            status="done",
            detail=f"{len(conflicts)} clash(es)." if conflicts else "No shared fieldKeys without a form.",
        )
        steps.append(
            {
                "id": "conflicts",
                "title": "Checking form-name clashes",
                "status": "done",
                "detail": f"{len(conflicts)} clash(es)." if conflicts else "No shared fieldKeys without a form.",
            }
        )
    except PlanError as exc:
        # Keep whatever already worked; ask in plain language.
        spec = prior_spec
        friendly = humanize_validation_error(
            str(exc),
            spec=prior_spec,
            instructions=instructions,
            invoker=llm or _require_llm(db, llm),
        )
        yield _event(
            "step",
            id="plan",
            title="Drafting the report spec",
            status="done",
            detail="Could not map the latest request; earlier draft kept.",
        )
        steps.append(
            {
                "id": "plan",
                "title": "Drafting the report spec",
                "status": "done",
                "detail": "Could not map the latest request; earlier draft kept.",
            }
        )
        questions = [
            partial_issue_question(
                friendly
                if prior_spec
                else (
                    friendly
                    + " Tip: send one section at a time so we can keep what already works."
                ),
                index=0,
            )
        ]
        assistant = (
            (
                f"I kept the {_section_count(prior_spec)} section(s) that already worked.\n\n"
                if prior_spec
                else "I could not draft a valid report from that request yet.\n\n"
            )
            + friendly
        )
        state["status"] = "awaiting_user"
        state["pendingQuestions"] = questions
        state["promptText"] = instructions
        msg = _append_message(state, role="assistant", content=assistant, steps=steps)
        yield _event("assistant", text=assistant, messageId=msg["id"], steps=steps)
        yield _event("questions", questions=questions)
        if spec:
            yield _event("spec", spec=spec)
        yield _event("done", status="awaiting_user", templateName=template.name)
        _persist(template, state, spec)
        db.commit()
        return
    except Exception as exc:  # noqa: BLE001
        assistant = str(exc)
        yield _event("error", message=assistant)
        msg = _append_message(state, role="assistant", content=assistant, steps=steps)
        yield _event("assistant", text=assistant, messageId=msg["id"])
        yield _event("done", status=state.get("status") or "drafting")
        _persist(template, state, prior_spec or spec)
        db.commit()
        return

    questions: list[dict[str, Any]] = []
    questions.extend(conflicts)
    if not skip_plan:
        questions.extend(_binder_questions(mappings))
        questions.extend(_unmapped_questions(list(state.get("unmapped") or []) + binder_unmapped))
        questions.extend(_partial_questions(partial_issues))
    placement_ask = str(state.pop("pendingPlacementAsk", "") or "").strip()
    if placement_ask:
        questions.append(_placement_question(placement_ask, spec))
    if not questions:
        questions = [_confirm_question()]
        status = "awaiting_user"
        # Prompt lives on the question card — do not repeat it in the assistant bubble.
        assistant = _spec_summary(spec)
    else:
        status = "awaiting_user"
        if any(q.get("kind") == "section_placement" for q in questions):
            assistant = (
                _spec_summary(spec)
                + "\n\nI kept the current draft, but wasn’t sure where to put your "
                "latest request. Use the options below."
            )
        elif partial_issues:
            assistant = (
                _spec_summary(spec)
                + "\n\nI kept what already worked, but need help with the rest. "
                "Use the options below."
            )
        else:
            assistant = (
                _spec_summary(spec)
                + "\n\nI need a couple of clarifications before this spec is ready. "
                "Use the options below."
            )

    # Belt-and-suspenders: never echo an active question prompt in the bubble.
    for question in questions:
        prompt = str(question.get("prompt") or "").strip()
        if prompt and assistant.rstrip().endswith(prompt):
            assistant = assistant.rstrip()[: -len(prompt)].rstrip()

    if questions and all(q.get("kind") == "confirm_spec" for q in questions) and _CONFIRM.match(text) and skip_plan:
        status = "ready"
        questions = []
        assistant = "This spec is confirmed. Save it as a template version when you are ready."

    state["status"] = status
    state["pendingQuestions"] = questions
    state["promptText"] = instructions
    title = str((spec or {}).get("title") or "").strip()
    if title and (not template.name or template.name.startswith("Untitled")):
        template.name = title[:120]
    msg = _append_message(state, role="assistant", content=assistant, steps=steps)
    yield _event("assistant", text=assistant, messageId=msg["id"], steps=steps)
    if questions:
        yield _event("questions", questions=questions)
    if spec:
        yield _event("spec", spec=spec)
    yield _event("done", status=status, templateName=template.name)
    _persist(template, state, spec)
    db.commit()


def _section_count(spec: dict[str, Any] | None) -> int:
    if not spec:
        return 0
    sections = spec.get("sections")
    return len(sections) if isinstance(sections, list) else 0


def _spec_summary(spec: dict[str, Any] | None) -> str:
    if not spec:
        return "I drafted an empty spec."
    title = str(spec.get("title") or "Untitled report")
    sections = spec.get("sections") if isinstance(spec.get("sections"), list) else []
    n = len(sections)
    lines = [f'Draft spec: "{title}" with {n} section{"s" if n != 1 else ""}.']
    for row in sections:
        if not isinstance(row, dict):
            continue
        section_title = str(row.get("title") or "").strip() or "(untitled)"
        lines.append(f"• {section_title}")
    return "\n".join(lines)


def _require_llm(db: Session, llm: LlmInvoker | None) -> LlmInvoker:
    if llm is not None:
        return llm
    from app.services.reporting.planner import _default_llm_invoker

    return _default_llm_invoker(db)
