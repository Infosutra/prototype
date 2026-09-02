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

Rules:
- Output ONLY valid JSON matching the response schema below.
- Use field names exactly as provided in the form schema. Never invent field names.
- Intra-form fields use plain string refs. Inter-form fields use related_field objects only.
- Never invent relationship codes. Use only relationships listed in context.relationships.
- related_field shape: {"type":"related_field","relationship":"<code>","field":"<target_field>"}
- For field-to-field comparisons use field_b (e.g. gt with field + field_b or related_field).
- For duration bands use duration_minutes_gte with start_field, end_field, optional min and max.
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


def seed_dqa_compile_prompt(db: Session) -> bool:
    existing = db.get(Prompt, DQA_COMPILE_PROMPT_ID)
    if existing:
        if not (existing.content or "").strip():
            existing.content = DEFAULT_DQA_COMPILE_PROMPT
            existing.category = DQA_COMPILE_CATEGORY
            db.commit()
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
) -> list[dict[str, str]]:
    schema, _ = compact_form_schema(form_fields)
    context_payload: dict[str, Any] = {
        "operators": operator_catalog_for_prompt(),
        "form_fields": schema,
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

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
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
