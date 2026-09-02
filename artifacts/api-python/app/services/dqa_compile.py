"""LLM-backed DQA rule compiler with deterministic validation."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AppSettings, Project
from app.domain.dqa.form_fields import list_form_fields
from app.domain.dqa.validate import ValidationResult, validate_rule
from app.integrations.llm import LlmError, chat_completion, llm_compile_config_from_app_settings
from app.services.dqa_compile_prompt import build_compiler_messages, load_compile_prompt
from app.services.dqa_preview import preview_rule
from app.services.dqa_relationships import build_relationship_schema, relationships_for_source_project
from app.services.dqa_rule_packs import get_pack_for_project

MAX_LLM_ATTEMPTS = 3
COMPILE_TEMPERATURE = 0.1
REPAIR_TEMPERATURE = 0.0


class CompileError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "compile_error"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _parse_compiler_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", stripped)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}


def _finalize_rule(
    proposal: dict[str, Any],
    *,
    english: str,
    existing_rule: dict[str, Any] | None,
) -> dict[str, Any]:
    rule_id = str((existing_rule or {}).get("id") or f"R-{uuid.uuid4().hex[:12]}")
    return {
        "id": rule_id,
        "severity": str(proposal.get("severity") or "amber").lower(),
        "title": str(proposal.get("title") or english[:80] or "DQA rule"),
        "message": str(proposal.get("message") or english),
        "english": english,
        "check": proposal.get("check"),
    }


def compile_dqa_rule(
    db: Session,
    project: Project,
    *,
    english: str,
    conversation: list[dict[str, str]] | None = None,
    existing_rule: dict[str, Any] | None = None,
    preview_limit: int = 50,
    settings: AppSettings,
) -> dict[str, Any]:
    text = (english or "").strip()
    if not text:
        raise CompileError("english is required", status_code=400)

    if not settings.ai_enabled:
        raise CompileError(
            "AI is disabled. Enable it under Settings → General.",
            status_code=400,
            code="ai_disabled",
        )
    llm = llm_compile_config_from_app_settings(settings)
    if not llm.api_key:
        raise CompileError(
            "AI API key is not configured.",
            status_code=400,
            code="ai_not_configured",
        )

    pack = get_pack_for_project(db, project.id) or {}
    form_fields = list_form_fields(
        project.form_definition if isinstance(project.form_definition, dict) else None
    )
    study_id = project.study_id
    rel_catalog, related_field_map = (
        build_relationship_schema(db, study_id) if study_id else ([], {})
    )
    source_relationships = [
        row.code
        for row in (
            relationships_for_source_project(db, study_id, project.id) if study_id else []
        )
    ]
    if len(form_fields) > 500:
        raise CompileError(
            "Form schema is too large to compile",
            status_code=413,
            code="schema_too_large",
        )

    system_prompt, prompt_id = load_compile_prompt(db)
    last_proposal: dict[str, Any] | None = None
    repair_context: dict[str, Any] | None = None
    attempts = 0
    last_validation: ValidationResult | None = None

    while attempts < MAX_LLM_ATTEMPTS:
        attempts += 1
        temperature = REPAIR_TEMPERATURE if repair_context else COMPILE_TEMPERATURE
        messages = build_compiler_messages(
            system_prompt=system_prompt,
            form_fields=form_fields,
            pack=pack,
            english=text,
            conversation=conversation,
            existing_rule=existing_rule,
            repair_context=repair_context,
            relationships=rel_catalog,
            source_relationships=source_relationships,
        )
        try:
            raw = chat_completion(
                llm,
                messages,
                temperature=temperature,
                max_tokens=int(settings.ai_max_tokens or 2048),
                timeout_seconds=float(settings.ai_timeout_seconds or 60),
            )
        except LlmError as exc:
            raise CompileError(str(exc), status_code=502, code="provider_error") from exc

        payload = _parse_compiler_payload(raw)
        if not payload and attempts < MAX_LLM_ATTEMPTS and not repair_context:
            repair_context = {
                "errors": [{"path": "", "code": "invalid_json", "message": "Response was not JSON"}],
                "proposal": {"raw": raw[:2000]},
            }
            continue
        if not payload:
            return _invalid_response(
                message="Compiler returned unparseable output",
                validation=ValidationResult(
                    valid=False,
                    errors=[],
                    warnings=[],
                ),
                last_proposal=last_proposal,
                attempts=attempts,
                model=llm.model,
            )

        question = payload.get("clarifying_question")
        if isinstance(question, str) and question.strip():
            return {
                "status": "needs_clarification",
                "question": question.strip(),
                "partial_explanation": payload.get("explanation"),
                "meta": {"model": llm.model, "attempts": attempts, "prompt_id": prompt_id},
            }

        proposal = payload.get("rule")
        if not isinstance(proposal, dict) or not isinstance(proposal.get("check"), dict):
            if attempts < MAX_LLM_ATTEMPTS:
                repair_context = {
                    "errors": [
                        {
                            "path": "rule",
                            "code": "missing_rule",
                            "message": "Expected rule.check object when clarifying_question is null",
                        }
                    ],
                    "proposal": payload,
                }
                continue
            return _invalid_response(
                message="Compiler did not return a valid rule",
                validation=ValidationResult(valid=False, errors=[], warnings=[]),
                last_proposal=payload,
                attempts=attempts,
                model=llm.model,
            )

        last_proposal = proposal
        rule = _finalize_rule(proposal, english=text, existing_rule=existing_rule)
        validation = validate_rule(
            rule,
            form_fields=form_fields,
            pack=pack,
            for_compile=True,
            related_fields=related_field_map,
        )
        last_validation = validation
        if validation.valid:
            preview = preview_rule(db, project.id, rule, limit=preview_limit)
            return {
                "status": "success",
                "rule": rule,
                "explanation": str(payload.get("explanation") or rule["message"]),
                "validation": validation.to_dict(),
                "preview": preview,
                "meta": {
                    "model": llm.model,
                    "attempts": attempts,
                    "promptId": prompt_id,
                },
            }

        if attempts < MAX_LLM_ATTEMPTS:
            repair_context = {
                "errors": validation.to_dict()["errors"],
                "proposal": proposal,
            }
            continue

    return _invalid_response(
        message="Could not compile a valid rule after repair attempts",
        validation=last_validation or ValidationResult(valid=False, errors=[], warnings=[]),
        last_proposal=last_proposal,
        attempts=attempts,
        model=llm.model,
        prompt_id=prompt_id,
    )


def validate_dqa_rule_for_project(
    db: Session,
    project: Project,
    rule: dict[str, Any],
    *,
    preview_limit: int = 50,
) -> dict[str, Any]:
    pack = get_pack_for_project(db, project.id) or {}
    form_fields = list_form_fields(
        project.form_definition if isinstance(project.form_definition, dict) else None
    )
    related_field_map: dict[str, set[str]] = {}
    if project.study_id:
        _, related_field_map = build_relationship_schema(db, project.study_id)
    validation = validate_rule(
        rule,
        form_fields=form_fields,
        pack=pack,
        related_fields=related_field_map,
    )
    body: dict[str, Any] = {
        "status": "success" if validation.valid else "invalid",
        "validation": validation.to_dict(),
    }
    if validation.valid:
        body["preview"] = preview_rule(db, project.id, rule, limit=preview_limit)
    else:
        body["message"] = "Rule failed validation"
    return body


def _invalid_response(
    *,
    message: str,
    validation: ValidationResult,
    last_proposal: dict[str, Any] | None,
    attempts: int,
    model: str,
    prompt_id: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "invalid",
        "message": message,
        "validation": validation.to_dict(),
        "last_proposal": last_proposal,
        "meta": {"model": model, "attempts": attempts, "prompt_id": prompt_id},
    }
