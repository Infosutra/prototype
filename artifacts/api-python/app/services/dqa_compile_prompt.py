"""Default prompt template and assembly for DQA rule compilation."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Prompt
from app.domain.dqa.catalog import operator_catalog_for_prompt

DQA_COMPILE_CATEGORY = "dqa-compile"
DQA_COMPILE_PROMPT_ID = "seed-dqa-compile"
MAX_SCHEMA_FIELDS = 250
MAX_LABEL_LEN = 120

DEFAULT_DQA_COMPILE_PROMPT = """You are a DQA rule compiler for KoBo survey forms.

Your job is to translate natural-language data quality requirements into a structured JSON rule that a deterministic evaluator will run on each submission.

Evaluator polarity (critical):
- Every check returns passes=true when the submission is OK for that rule, and passes=false to create a flag.
- Emit the condition that should HOLD for clean data — not the anomaly condition.
- Do not wrap a validity check in {"op":"not", ...} to "make it flag". That inverts polarity and flags good data.

Rules:
- Output ONLY valid JSON matching the response schema below.
- Use field names exactly as provided in the form schema. Never invent field names.
- Question codes like A10 or D4 refer to form_fields[].name with that exact code. Match by name first, not by label text alone.
- If a referenced code is missing from form_fields, set clarifying_question (do not invent a nearby field).
- Intra-form fields use plain string refs. Inter-form fields use related_field objects only.
- Never invent relationship codes. Use only relationships listed in context.relationships.
- related_field is an operand value for field / field_b — never a sibling key next to field.
- related_field shape: {"type":"related_field","relationship":"<code>","field":"<target_field>"}
- Inter-form example: "T1 A5 must be greater than T2 D3" → {"op":"gt","field":"A5","field_b":{"type":"related_field","relationship":"<code_from_context>","field":"D3"}} (home form = T1).
- If the requirement spans forms and context.relationships is empty, set clarifying_question asking the user to create a study relationship first; do not invent a code.
- For field-to-field comparisons use field_b. Choose the operator that should hold: e.g. "B22 must not exceed B21" → {"op":"lte","field":"B22","field_b":"B21"} (not gt, and not if_then hacks).
- Intra-form consistency / cross-check between two fields (values should match): use equals with field + field_b (passes when equal; flags when they differ). Use not_equals only when values are required to differ.
- For duration bands (min and/or max minutes): use duration_minutes_gte with start_field, end_field, and min/max — alone, without wrapping in not. It already passes inside the band and flags outside.
- If the requirement is ambiguous, set clarifying_question to a single concise question and set rule to null.
- Ask clarifying questions only when necessary. Do not ask which field to use if exactly one field matches the requirement.
- For inter-form rules, ask which relationship to use only when multiple relationships are listed in source_relationships.
- For threshold edits on an existing_rule, preserve the rule id and change only the requested threshold/value.
- If you can compile, set clarifying_question to null and provide rule + explanation.

Response schema:
{
  "clarifying_question": string | null,
  "rule": {
    "severity": "red" | "amber",
    "title": string,
    "message": string,
    "check": { ... operator tree ... }
  } | null,
  "explanation": string | null
}

Do not wrap JSON in markdown fences."""


# Always appended so compile stays reliable even if the editable Prompt row is stale.
COMPILER_CONTRACT = """Compiler contract (always enforce):
- Return one JSON object only — no markdown fences, no prose outside JSON.
- Checks are validity predicates: passes=true means OK; passes=false creates a flag. Emit the condition that should hold.
- Never wrap duration_minutes_gte, equals, required, between, etc. in {"op":"not"} to force flagging.
- Resolve survey codes (A10, D4, …) to form_fields[].name exactly.
- If a code is not present in form_fields, ask a clarifying_question; never invent field names.
- Intra-form consistency between two fields → {"op":"equals","field":"<a>","field_b":"<b>"}.
- Duration band → {"op":"duration_minutes_gte","start_field":"<start>","end_field":"<end>","min":<n>,"max":<n>} (no not wrapper).
- "A must not be greater than B" → {"op":"lte","field":"A","field_b":"B"}.
- Keep checks shallow; prefer a single operator when it is enough.
- A study may have multiple forms. Context includes study_forms (every form and its fields) and relationships.
- A rule may span forms. Evaluate it on one source form's submissions. Fields on another form must use related_field with a relationship whose source_project_id is that source form.
- Inter-form comparison example: {"op":"gt","field":"A5","field_b":{"type":"related_field","relationship":"<code>","field":"D3"}}. Never emit {"related_field":{...}} as a sibling of "field".
- If relationships is empty and the requirement names two forms/tools, ask a clarifying_question — do not invent relationship codes.
- Match question codes in study_forms by name. If the same code exists on more than one form, disambiguate with form name/tool_code or ask a clarifying_question."""


def seed_dqa_compile_prompt(db: Session) -> bool:
    existing = db.get(Prompt, DQA_COMPILE_PROMPT_ID)
    if existing:
        content = (existing.content or "").strip()
        stale = (
            not content
            or "use not_equals with field + field_b" in content
            or '{"op":"not_equals","field":"<a>","field_b":"<b>"}' in content
            or "e.g. gt with field + field_b" in content
            or "Evaluator polarity" not in content
            or "never a sibling key next to field" not in content
        )
        if stale:
            existing.content = DEFAULT_DQA_COMPILE_PROMPT
            existing.category = DQA_COMPILE_CATEGORY
            db.commit()
            return True
        return False
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = Prompt(
        id=DQA_COMPILE_PROMPT_ID,
        name="DQA rule compiler",
        description="System instructions for compiling English DQA rules to JSON checks",
        content=DEFAULT_DQA_COMPILE_PROMPT,
        category=DQA_COMPILE_CATEGORY,
        project_ids=[],
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    return True


def load_compile_prompt(db: Session) -> tuple[str, str | None]:
    row = db.scalars(
        select(Prompt)
        .where(Prompt.category == DQA_COMPILE_CATEGORY)
        .order_by(Prompt.updated_at.desc())
    ).first()
    if row and (row.content or "").strip():
        return row.content.strip(), row.id
    return DEFAULT_DQA_COMPILE_PROMPT, None


def _sanitize_label(label: str) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(label or ""))
    return text.strip()[:MAX_LABEL_LEN]


def compact_form_schema(form_fields: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    compact: list[dict[str, Any]] = []
    warning = None
    fields = form_fields[:MAX_SCHEMA_FIELDS]
    if len(form_fields) > MAX_SCHEMA_FIELDS:
        warning = f"Form schema truncated to {MAX_SCHEMA_FIELDS} fields for compilation"
    for item in fields:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {
            "name": item.get("name"),
            "type": item.get("type"),
            "label": _sanitize_label(str(item.get("label") or item.get("name") or "")),
        }
        choices = item.get("choices") or []
        if isinstance(choices, list) and choices:
            entry["choices"] = [
                {
                    "name": c.get("name"),
                    "label": _sanitize_label(str(c.get("label") or c.get("name") or "")),
                }
                for c in choices[:20]
                if isinstance(c, dict)
            ]
        compact.append(entry)
    return compact, warning


def build_compiler_messages(
    *,
    system_prompt: str,
    form_fields: list[dict[str, Any]],
    pack: dict[str, Any] | None,
    english: str,
    conversation: list[dict[str, str]] | None = None,
    existing_rule: dict[str, Any] | None = None,
    repair_context: dict[str, Any] | None = None,
    relationships: list[dict[str, Any]] | None = None,
    source_relationships: list[str] | None = None,
    study_forms: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    schema, _ = compact_form_schema(form_fields)
    context_payload: dict[str, Any] = {
        "operators": operator_catalog_for_prompt(),
        "form_fields": schema,
        "study_forms": study_forms or [],
        "pack_fields": (pack or {}).get("fields") or {},
        "thresholds": (pack or {}).get("thresholds") or {},
        "relationships": relationships or [],
        "source_relationships": source_relationships or [],
        "related_field_operand": {
            "type": "related_field",
            "relationship": "<relationship_code>",
            "field": "<field_on_target_form>",
        },
    }
    if existing_rule:
        context_payload["existing_rule"] = {
            "id": existing_rule.get("id"),
            "severity": existing_rule.get("severity"),
            "title": existing_rule.get("title"),
            "message": existing_rule.get("message"),
            "check": existing_rule.get("check"),
        }

    system_content = (system_prompt or "").strip()
    if COMPILER_CONTRACT.strip() not in system_content:
        system_content = f"{system_content}\n\n{COMPILER_CONTRACT}".strip()
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    for turn in conversation or []:
        role = str(turn.get("role") or "").strip()
        content = str(turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    if repair_context:
        user_content = (
            "Repair the previous rule proposal. Validation errors:\n"
            + json.dumps(repair_context.get("errors") or [], ensure_ascii=False, indent=2)
            + "\n\nPrevious proposal:\n"
            + json.dumps(repair_context.get("proposal") or {}, ensure_ascii=False, indent=2)
            + "\n\nOriginal requirement:\n"
            + english
        )
    else:
        user_content = english.strip()

    messages.append(
        {
            "role": "user",
            "content": (
                "Compile this DQA requirement.\n\n"
                f"Context JSON:\n{json.dumps(context_payload, ensure_ascii=False, indent=2)}\n\n"
                f"Requirement:\n{user_content}"
            ),
        }
    )
    return messages
