"""LLM-backed DQA rule compiler with deterministic validation."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AppSettings, Project
from app.domain.dqa.form_fields import list_form_fields
from app.domain.dqa.operands import collect_relationship_codes, is_related_field_operand
from app.domain.dqa.catalog import FIELD_LIST_KEYS, FIELD_REF_KEYS
from app.domain.dqa.rule_audit import attach_compile_audit, sanitize_english
from app.domain.dqa.rule_diff import compute_rule_diff
from app.domain.dqa.validate import ValidationResult, validate_rule
from app.integrations.llm import (
    LlmError,
    StreamDone,
    chat_completion_detailed,
    chat_completion_stream,
    llm_compile_config_from_app_settings,
)
from app.integrations.llm.json_object import parse_json_object
from app.schemas.common import to_camel
from app.services.dqa_compile_audit import CompileSessionRecorder
from app.services.dqa_compile_prompt import build_compiler_messages, load_compile_prompt
from app.services.dqa_preview import preview_rule
from app.services.dqa_test import run_rule_test
from app.services.dqa_relationships import (
    build_relationship_schema,
    relationships_for_source_project,
)
from app.services.dqa_rule_packs import get_pack_for_project

MAX_LLM_ATTEMPTS = 3
COMPILE_TEMPERATURE = 0.1
REPAIR_TEMPERATURE = 0.0

# Rule/check trees must stay in evaluator snake_case (field_b, start_field, …).
_CAMELIZE_PRESERVE_VALUE_KEYS = frozenset(
    {"rule", "check", "last_proposal", "existing_rule"}
)

def camelize(obj: Any) -> Any:
    """Recursively convert dict keys to camelCase for JSON responses.

    Nested DQA rule/check objects are left unchanged so compiled rules remain
    valid for validate/save/eval (which expect snake_case operands).
    """
    if isinstance(obj, list):
        return [camelize(item) for item in obj]
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for key, value in obj.items():
            camel_key = to_camel(str(key)) if isinstance(key, str) else key
            if isinstance(key, str) and key in _CAMELIZE_PRESERVE_VALUE_KEYS:
                out[camel_key] = value
            else:
                out[camel_key] = camelize(value)
        return out
    return obj

class CompileError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "compile_error"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code

def _parse_compiler_payload(text: str) -> dict[str, Any]:
    """Best-effort JSON object from model output; logs empty vs malformed distinctly."""
    return parse_json_object(text, log_label="DQA compiler").data or {}

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
        "english": sanitize_english(english),
        "check": proposal.get("check"),
    }

def _meta_from_recorder(recorder: CompileSessionRecorder, *, prompt_id: str | None) -> dict[str, Any]:
    return {
        "session_id": recorder.session_id,
        "model": recorder.model,
        "provider": recorder.provider,
        "attempts": recorder.attempts,
        "prompt_id": prompt_id,
        "latency_ms": int(round(recorder.latency_ms_total)),
        "prompt_tokens": recorder.prompt_tokens,
        "completion_tokens": recorder.completion_tokens,
    }

def _field_label(fields: list[dict[str, Any]], name: str) -> str:
    for row in fields:
        if str(row.get("name") or "") == name:
            return str(row.get("label") or name)
    return name

def _walk_field_operands(node: Any, out: list[tuple[str, str, str | None]]) -> None:
    """Collect (kind, field_code, relationship_or_none) from a check tree."""
    if not isinstance(node, dict):
        return
    for key in FIELD_REF_KEYS:
        operand = node.get(key)
        if is_related_field_operand(operand):
            out.append(
                (
                    "related",
                    str(operand.get("field") or "").strip(),
                    str(operand.get("relationship") or "").strip(),
                )
            )
        elif isinstance(operand, str) and operand.strip():
            out.append(("local", operand.strip(), None))
    for key in FIELD_LIST_KEYS:
        for item in node.get(key) or []:
            if is_related_field_operand(item):
                out.append(
                    (
                        "related",
                        str(item.get("field") or "").strip(),
                        str(item.get("relationship") or "").strip(),
                    )
                )
            elif isinstance(item, str) and item.strip():
                out.append(("local", item.strip(), None))
    for nested in ("check", "if", "then", "failed", "inner"):
        if nested in node:
            _walk_field_operands(node[nested], out)
    for child in node.get("checks") or []:
        _walk_field_operands(child, out)

def build_resolved_fields(
    db: Session,
    project: Project,
    check: dict[str, Any] | None,
    *,
    source_fields: list[dict[str, Any]],
    rel_catalog: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Human-readable field resolution table for the compile confirmation step."""
    if not isinstance(check, dict):
        return []

    operands: list[tuple[str, str, str | None]] = []
    _walk_field_operands(check, operands)

    rel_by_code = {str(r.get("code") or ""): r for r in rel_catalog}
    target_fields_cache: dict[str, list[dict[str, Any]]] = {}
    target_name_cache: dict[str, str] = {}

    def target_fields(rel_code: str) -> list[dict[str, Any]]:
        if rel_code in target_fields_cache:
            return target_fields_cache[rel_code]
        meta = rel_by_code.get(rel_code) or {}
        target_id = str(meta.get("target_project_id") or "")
        target = db.get(Project, target_id) if target_id else None
        fields = list_form_fields(
            target.form_definition if target and isinstance(target.form_definition, dict) else None
        )
        target_fields_cache[rel_code] = fields
        target_name_cache[rel_code] = (
            (target.name if target else "") or str(meta.get("title") or rel_code)
        )
        return fields

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    source_name = project.name or "This form"

    for kind, field, rel_code in operands:
        if not field:
            continue
        key = (kind, f"{rel_code or ''}:{field}")
        if key in seen:
            continue
        seen.add(key)
        if kind == "related" and rel_code:
            fields = target_fields(rel_code)
            rows.append(
                {
                    "code": field,
                    "form": target_name_cache.get(rel_code) or rel_code,
                    "label": _field_label(fields, field),
                }
            )
        else:
            rows.append(
                {
                    "code": field,
                    "form": source_name,
                    "label": _field_label(source_fields, field),
                }
            )

    for rel_code in sorted(collect_relationship_codes(check)):
        meta = rel_by_code.get(rel_code) or {}
        join_field = str(meta.get("source_join_field") or meta.get("target_join_field") or "").strip()
        if not join_field:
            continue
        key = ("join", join_field)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "code": "join",
                "form": "Study",
                "label": join_field,
            }
        )

    return rows

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
    text = sanitize_english(english)
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
    recorder = CompileSessionRecorder(
        db,
        project_id=project.id,
        study_id=study_id,
        english=text,
        conversation_turns=len(conversation or []),
        provider=llm.provider,
        model=llm.model,
        prompt_id=prompt_id,
    )
    recorder.metadata = {
        "relationship_count": len(rel_catalog),
        "source_relationships": source_relationships,
        "form_field_count": len(form_fields),
    }

    last_proposal: dict[str, Any] | None = None
    repair_context: dict[str, Any] | None = None
    attempts = 0
    last_validation: ValidationResult | None = None

    while attempts < MAX_LLM_ATTEMPTS:
        attempts += 1
        temperature = REPAIR_TEMPERATURE if repair_context else COMPILE_TEMPERATURE
        phase = "repair" if repair_context else "compile"
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
            completion = chat_completion_detailed(
                llm,
                messages,
                temperature=temperature,
                max_tokens=int(settings.ai_max_tokens or 2048),
                timeout_seconds=float(settings.ai_timeout_seconds or 60),
            )
            recorder.record_llm_call(
                latency_ms=completion.latency_ms,
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                attempt=attempts,
                phase=phase,
            )
            raw = completion.text
        except LlmError as exc:
            recorder.finalize(
                status="error",
                error_code="provider_error",
                error_message=str(exc),
            )
            raise CompileError(str(exc), status_code=502, code="provider_error") from exc

        payload = _parse_compiler_payload(raw)
        if not payload and attempts < MAX_LLM_ATTEMPTS and not repair_context:
            repair_context = {
                "errors": [{"path": "", "code": "invalid_json", "message": "Response was not JSON"}],
                "proposal": {"raw": raw[:2000]},
            }
            continue
        if not payload:
            session = recorder.finalize(
                status="invalid",
                validation_valid=False,
                error_code="invalid_json",
                error_message="Compiler returned unparseable output",
                extra_metadata={"last_proposal": last_proposal},
            )
            return _invalid_response(
                message="Compiler returned unparseable output",
                validation=ValidationResult(valid=False, errors=[], warnings=[]),
                last_proposal=last_proposal,
                attempts=attempts,
                recorder=recorder,
                prompt_id=prompt_id,
                session=session,
            )

        question = payload.get("clarifying_question")
        if isinstance(question, str) and question.strip():
            session = recorder.finalize(
                status="needs_clarification",
                extra_metadata={"question": question.strip()},
            )
            return {
                "status": "needs_clarification",
                "question": question.strip(),
                "partial_explanation": payload.get("explanation"),
                "meta": _meta_from_recorder(recorder, prompt_id=prompt_id),
                "session_id": session.id,
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
            session = recorder.finalize(
                status="invalid",
                validation_valid=False,
                error_code="missing_rule",
                error_message="Compiler did not return a valid rule",
            )
            return _invalid_response(
                message="Compiler did not return a valid rule",
                validation=ValidationResult(valid=False, errors=[], warnings=[]),
                last_proposal=payload,
                attempts=attempts,
                recorder=recorder,
                prompt_id=prompt_id,
                session=session,
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
            audited_rule = attach_compile_audit(
                rule,
                english=text,
                compile_session_id=recorder.session_id,
                model=recorder.model,
                provider=recorder.provider,
                prompt_id=prompt_id,
            )
            session = recorder.finalize(
                status="success",
                validation_valid=True,
                rule=audited_rule,
                preview=preview,
            )
            body: dict[str, Any] = {
                "status": "success",
                "rule": audited_rule,
                "explanation": str(payload.get("explanation") or rule["message"]),
                "validation": validation.to_dict(),
                "preview": preview,
                "resolved_fields": build_resolved_fields(
                    db,
                    project,
                    audited_rule.get("check") if isinstance(audited_rule.get("check"), dict) else None,
                    source_fields=form_fields,
                    rel_catalog=rel_catalog,
                ),
                "meta": _meta_from_recorder(recorder, prompt_id=prompt_id),
                "session_id": session.id,
                "warnings": preview.get("warnings") if isinstance(preview, dict) else [],
            }
            if existing_rule:
                body["diff"] = compute_rule_diff(existing_rule, audited_rule)
            return body

        if attempts < MAX_LLM_ATTEMPTS:
            repair_context = {
                "errors": validation.to_dict()["errors"],
                "proposal": proposal,
            }
            continue

    session = recorder.finalize(
        status="invalid",
        validation_valid=False,
        validation_errors=(last_validation.to_dict()["errors"] if last_validation else []),
        rule=last_proposal if isinstance(last_proposal, dict) else None,
        error_code="validation_exhausted",
        error_message="Could not compile a valid rule after repair attempts",
    )
    return _invalid_response(
        message="Could not compile a valid rule after repair attempts",
        validation=last_validation or ValidationResult(valid=False, errors=[], warnings=[]),
        last_proposal=last_proposal,
        attempts=attempts,
        recorder=recorder,
        prompt_id=prompt_id,
        session=session,
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
        body["test"] = run_rule_test(db, project.id, rule, limit=preview_limit)
        body["warnings"] = body["test"].get("warnings") or []
    else:
        body["message"] = "Rule failed validation"
    return body

def _invalid_response(
    *,
    message: str,
    validation: ValidationResult,
    last_proposal: dict[str, Any] | None,
    attempts: int,
    recorder: CompileSessionRecorder,
    prompt_id: str | None = None,
    session: Any = None,
) -> dict[str, Any]:
    return {
        "status": "invalid",
        "message": message,
        "validation": validation.to_dict(),
        "last_proposal": last_proposal,
        "meta": _meta_from_recorder(recorder, prompt_id=prompt_id),
        "session_id": getattr(session, "id", recorder.session_id),
    }

def compile_dqa_rule_stream(
    db: Session,
    project: Project,
    *,
    english: str,
    conversation: list[dict[str, str]] | None = None,
    existing_rule: dict[str, Any] | None = None,
    preview_limit: int = 50,
    settings: AppSettings,
):
    """Yield SSE-friendly event dicts while compiling (progress / token / result / error)."""
    text = sanitize_english(english)
    if not text:
        yield {"event": "error", "message": "english is required", "code": "compile_error"}
        return

    if not settings.ai_enabled:
        yield {
            "event": "error",
            "message": "AI is disabled. Enable it under Settings → General.",
            "code": "ai_disabled",
        }
        return
    llm = llm_compile_config_from_app_settings(settings)
    if not llm.api_key:
        yield {
            "event": "error",
            "message": "AI API key is not configured.",
            "code": "ai_not_configured",
        }
        return

    yield {"event": "progress", "phase": "schema", "message": "Loading form schema and relationships…"}

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
        yield {
            "event": "error",
            "message": "Form schema is too large to compile",
            "code": "schema_too_large",
        }
        return

    system_prompt, prompt_id = load_compile_prompt(db)
    recorder = CompileSessionRecorder(
        db,
        project_id=project.id,
        study_id=study_id,
        english=text,
        conversation_turns=len(conversation or []),
        provider=llm.provider,
        model=llm.model,
        prompt_id=prompt_id,
    )
    recorder.metadata = {
        "relationship_count": len(rel_catalog),
        "source_relationships": source_relationships,
        "form_field_count": len(form_fields),
    }

    last_proposal: dict[str, Any] | None = None
    repair_context: dict[str, Any] | None = None
    attempts = 0
    last_validation: ValidationResult | None = None
    timeout = float(settings.ai_timeout_seconds or 60)
    max_tokens = int(settings.ai_max_tokens or 2048)

    while attempts < MAX_LLM_ATTEMPTS:
        attempts += 1
        temperature = REPAIR_TEMPERATURE if repair_context else COMPILE_TEMPERATURE
        phase = "repair" if repair_context else "compile"
        yield {
            "event": "progress",
            "phase": phase,
            "attempt": attempts,
            "message": (
                f"Repairing rule (attempt {attempts}/{MAX_LLM_ATTEMPTS})…"
                if repair_context
                else f"Calling model (attempt {attempts}/{MAX_LLM_ATTEMPTS})…"
            ),
        }
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
            completion = None
            for item in chat_completion_stream(
                llm,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout,
            ):
                if isinstance(item, StreamDone):
                    completion = item.result
                else:
                    yield {"event": "token", "text": item}
            if completion is None:
                raise LlmError("LLM returned an empty completion")
            recorder.record_llm_call(
                latency_ms=completion.latency_ms,
                prompt_tokens=completion.usage.prompt_tokens,
                completion_tokens=completion.usage.completion_tokens,
                attempt=attempts,
                phase=phase,
            )
            raw = completion.text
        except LlmError as exc:
            recorder.finalize(
                status="error",
                error_code="provider_error",
                error_message=str(exc),
            )
            yield {"event": "error", "message": str(exc), "code": "provider_error"}
            return

        yield {"event": "progress", "phase": "parse", "message": "Parsing model response…"}
        payload = _parse_compiler_payload(raw)
        if not payload and attempts < MAX_LLM_ATTEMPTS and not repair_context:
            repair_context = {
                "errors": [{"path": "", "code": "invalid_json", "message": "Response was not JSON"}],
                "proposal": {"raw": raw[:2000]},
            }
            yield {
                "event": "progress",
                "phase": "repair",
                "message": "Model output was not valid JSON — retrying…",
            }
            continue
        if not payload:
            session = recorder.finalize(
                status="invalid",
                validation_valid=False,
                error_code="invalid_json",
                error_message="Compiler returned unparseable output",
                extra_metadata={"last_proposal": last_proposal},
            )
            body = _invalid_response(
                message="Compiler returned unparseable output",
                validation=ValidationResult(valid=False, errors=[], warnings=[]),
                last_proposal=last_proposal,
                attempts=attempts,
                recorder=recorder,
                prompt_id=prompt_id,
                session=session,
            )
            yield {"event": "result", "data": camelize(body)}
            return

        question = payload.get("clarifying_question")
        if isinstance(question, str) and question.strip():
            session = recorder.finalize(
                status="needs_clarification",
                extra_metadata={"question": question.strip()},
            )
            body = {
                "status": "needs_clarification",
                "question": question.strip(),
                "partial_explanation": payload.get("explanation"),
                "meta": _meta_from_recorder(recorder, prompt_id=prompt_id),
                "session_id": session.id,
            }
            yield {"event": "result", "data": camelize(body)}
            return

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
            session = recorder.finalize(
                status="invalid",
                validation_valid=False,
                error_code="missing_rule",
                error_message="Compiler did not return a valid rule",
            )
            body = _invalid_response(
                message="Compiler did not return a valid rule",
                validation=ValidationResult(valid=False, errors=[], warnings=[]),
                last_proposal=payload,
                attempts=attempts,
                recorder=recorder,
                prompt_id=prompt_id,
                session=session,
            )
            yield {"event": "result", "data": camelize(body)}
            return

        last_proposal = proposal
        rule = _finalize_rule(proposal, english=text, existing_rule=existing_rule)
        yield {"event": "progress", "phase": "validate", "message": "Validating compiled check…"}
        validation = validate_rule(
            rule,
            form_fields=form_fields,
            pack=pack,
            for_compile=True,
            related_fields=related_field_map,
        )
        last_validation = validation
        if validation.valid:
            yield {"event": "progress", "phase": "preview", "message": "Running preview on submissions…"}
            preview = preview_rule(db, project.id, rule, limit=preview_limit)
            audited_rule = attach_compile_audit(
                rule,
                english=text,
                compile_session_id=recorder.session_id,
                model=recorder.model,
                provider=recorder.provider,
                prompt_id=prompt_id,
            )
            session = recorder.finalize(
                status="success",
                validation_valid=True,
                rule=audited_rule,
                preview=preview,
            )
            body: dict[str, Any] = {
                "status": "success",
                "rule": audited_rule,
                "explanation": str(payload.get("explanation") or rule["message"]),
                "validation": validation.to_dict(),
                "preview": preview,
                "resolved_fields": build_resolved_fields(
                    db,
                    project,
                    audited_rule.get("check") if isinstance(audited_rule.get("check"), dict) else None,
                    source_fields=form_fields,
                    rel_catalog=rel_catalog,
                ),
                "meta": _meta_from_recorder(recorder, prompt_id=prompt_id),
                "session_id": session.id,
                "warnings": preview.get("warnings") if isinstance(preview, dict) else [],
            }
            if existing_rule:
                body["diff"] = compute_rule_diff(existing_rule, audited_rule)
            yield {"event": "result", "data": camelize(body)}
            return

        if attempts < MAX_LLM_ATTEMPTS:
            repair_context = {
                "errors": validation.to_dict()["errors"],
                "proposal": proposal,
            }
            yield {
                "event": "progress",
                "phase": "repair",
                "message": "Validation failed — asking model to repair…",
            }
            continue

    session = recorder.finalize(
        status="invalid",
        validation_valid=False,
        validation_errors=(last_validation.to_dict()["errors"] if last_validation else []),
        rule=last_proposal if isinstance(last_proposal, dict) else None,
        error_code="validation_exhausted",
        error_message="Could not compile a valid rule after repair attempts",
    )
    body = _invalid_response(
        message="Could not compile a valid rule after repair attempts",
        validation=last_validation or ValidationResult(valid=False, errors=[], warnings=[]),
        last_proposal=last_proposal,
        attempts=attempts,
        recorder=recorder,
        prompt_id=prompt_id,
        session=session,
    )
    yield {"event": "result", "data": camelize(body)}

