"""Linear ReportSpec planner (no LangGraph): catalog → LLM → validate → repair → judge."""

from __future__ import annotations

import json
from typing import Any, Callable, Protocol

import structlog
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db.models import AppSettings
from app.domain.reporting.compile import compile_report_spec
from app.domain.reporting.validation import SpecValidationError, validate_report_spec
from app.integrations.llm import (
    chat_completion_detailed,
    llm_plan_config_from_app_settings,
)
from app.integrations.llm.json_object import parse_json_object
from app.integrations.llm.types import ChatMessage, LlmConfig
from app.schemas.common import to_camel
from app.services.reporting.catalog_for_llm import catalog_for_llm
from app.services.reporting.prompt_seeds import (
    DEFAULT_JUDGE_PROMPT,
    DEFAULT_PLANNER_PROMPT,
    DEFAULT_REPAIR_PROMPT,
    REPORT_PLANNER_JUDGE_PROMPT_ID,
    REPORT_PLANNER_PROMPT_ID,
    REPORT_PLANNER_REPAIR_PROMPT_ID,
    resolve_prompt_content,
)
from app.services.settings import get_or_create_settings

logger = structlog.stdlib.get_logger(__name__)

LlmCallable = Callable[..., Any]


class _PlanReply(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    spec: dict[str, Any] = Field(default_factory=dict)
    unmapped: list[dict[str, Any]] = Field(default_factory=list)


class _JudgeReply(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    faithful: bool = True
    issues: list[str] = Field(default_factory=list)


class PlanError(ValueError):
    """Planning failed after validation / repair."""


class LlmInvoker(Protocol):
    def __call__(
        self,
        *,
        system: str,
        user: str,
        purpose: str,
    ) -> dict[str, Any]: ...


def plan_report(
    db: Session,
    *,
    study_id: str,
    instructions: str,
    current_spec: dict[str, Any] | None = None,
    llm: LlmInvoker | None = None,
    settings: AppSettings | None = None,
    judge: bool = True,
    partial_ok: bool = False,
) -> dict[str, Any]:
    """Plan a ReportSpec. Returns ``{spec, unmapped, judgement, partial, issues}``.

    ``llm`` may be injected for tests. Unmapped / faithful=false do not fail.
    Invalid spec after one repair raises :class:`PlanError`, unless
    ``partial_ok`` is True — then a salvaged valid subset is returned with
    ``partial=True`` and user-facing ``issues``.
    Set ``judge=False`` when a human will confirm the spec instead.
    """
    text = (instructions or "").strip()
    if not text:
        raise PlanError("instructions are required")
    if not study_id:
        raise PlanError("study_id is required")

    catalog = catalog_for_llm(db, study_id)
    invoker = llm or _default_llm_invoker(db, settings=settings)

    planner_system = resolve_prompt_content(
        db, REPORT_PLANNER_PROMPT_ID, default=DEFAULT_PLANNER_PROMPT
    )
    if current_spec is not None:
        planner_system = (
            f"{planner_system}\n\n"
            "Patch mode: a currentSpec is provided. Update it to satisfy the new "
            "instructions. Do not drop unrelated existing sections or components."
        )

    user_payload = {
        "instructions": text,
        "catalog": catalog,
        "currentSpec": current_spec,
    }
    plan_raw = invoker(
        system=planner_system,
        user=json.dumps(user_payload, default=str),
        purpose="plan",
    )
    plan = _parse_plan_reply(plan_raw)
    plan.spec = compile_report_spec(plan.spec)
    from app.services.reporting.plan_salvage import autofix_narratives

    plan.spec = autofix_narratives(plan.spec)
    errors = validate_report_spec(plan.spec)

    if errors:
        repair_system = resolve_prompt_content(
            db, REPORT_PLANNER_REPAIR_PROMPT_ID, default=DEFAULT_REPAIR_PROMPT
        )
        repair_payload = {
            "instructions": text,
            "catalog": catalog,
            "invalidSpec": plan.spec,
            "unmapped": plan.unmapped,
            "validationErrors": errors,
            "currentSpec": current_spec,
        }
        repair_raw = invoker(
            system=repair_system,
            user=json.dumps(repair_payload, default=str),
            purpose="repair",
        )
        plan = _parse_plan_reply(repair_raw)
        plan.spec = autofix_narratives(compile_report_spec(plan.spec))
        errors = validate_report_spec(plan.spec)
        if errors:
            if partial_ok:
                return _partial_plan_result(
                    plan.spec,
                    baseline=current_spec,
                    errors=errors,
                    unmapped=plan.unmapped,
                )
            raise PlanError(_format_validation_failure(errors))

    # Re-validate with raise to normalize (and catch edge cases).
    try:
        validate_report_spec(plan.spec, raise_on_error=True)
    except SpecValidationError as exc:
        if partial_ok:
            return _partial_plan_result(
                plan.spec,
                baseline=current_spec,
                errors=list(exc.errors),
                unmapped=plan.unmapped,
            )
        raise PlanError(_format_validation_failure(exc.errors)) from exc

    result = {
        "spec": plan.spec,
        "unmapped": _normalize_unmapped(plan.unmapped),
        "judgement": {"faithful": True, "issues": []},
        "partial": False,
        "issues": [],
    }
    if not judge:
        return result

    judge_system = resolve_prompt_content(
        db, REPORT_PLANNER_JUDGE_PROMPT_ID, default=DEFAULT_JUDGE_PROMPT
    )
    judge_payload = {
        "instructions": text,
        "spec": plan.spec,
        "unmapped": plan.unmapped,
    }
    judge_raw = invoker(
        system=judge_system,
        user=json.dumps(judge_payload, default=str),
        purpose="judge",
    )
    judgement = _parse_judge_reply(judge_raw)
    result["judgement"] = {
        "faithful": bool(judgement.faithful),
        "issues": [str(x) for x in judgement.issues if str(x).strip()],
    }
    return result


def _partial_plan_result(
    candidate: dict[str, Any],
    *,
    baseline: dict[str, Any] | None,
    errors: list[str],
    unmapped: list[dict[str, Any]],
) -> dict[str, Any]:
    from app.services.reporting.plan_salvage import salvage_report_spec

    salvaged = salvage_report_spec(candidate, baseline=baseline, errors=errors)
    spec = salvaged.get("spec")
    issues = list(salvaged.get("issues") or [])
    if spec is None:
        raise PlanError(_format_validation_failure(errors))
    return {
        "spec": spec,
        "unmapped": _normalize_unmapped(unmapped),
        "judgement": {"faithful": True, "issues": []},
        "partial": True,
        "issues": issues,
        "keptFrom": salvaged.get("keptFrom"),
    }


def _format_validation_failure(errors: list[str], *, limit: int = 8) -> str:
    cleaned = [str(e).strip() for e in errors if str(e).strip()]
    if not cleaned:
        return "ReportSpec failed validation after repair"
    head = cleaned[:limit]
    msg = "ReportSpec failed validation after repair: " + "; ".join(head)
    remaining = len(cleaned) - len(head)
    if remaining > 0:
        msg += f" (+{remaining} more)"
    return msg


def _parse_plan_reply(raw: dict[str, Any]) -> _PlanReply:
    if not isinstance(raw, dict):
        raise PlanError("Planner LLM returned a non-object")
    # Allow either {spec, unmapped} or a bare ReportSpec.
    if "spec" not in raw and "specVersion" in raw:
        raw = {"spec": raw, "unmapped": []}
    reply = _PlanReply.model_validate(raw)
    if not isinstance(reply.spec, dict) or not reply.spec:
        raise PlanError("Planner LLM did not return a spec object")
    return reply


def _parse_judge_reply(raw: dict[str, Any]) -> _JudgeReply:
    if not isinstance(raw, dict):
        return _JudgeReply(faithful=True, issues=["Judge returned a non-object"])
    try:
        return _JudgeReply.model_validate(raw)
    except Exception:  # noqa: BLE001
        return _JudgeReply(faithful=True, issues=["Judge reply was malformed"])


def _normalize_unmapped(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        intent = str(
            item.get("userIntent")
            or item.get("user_intent")
            or item.get("intent")
            or ""
        ).strip()
        reason = str(item.get("reason") or "").strip()
        if not intent and not reason:
            continue
        out.append({"userIntent": intent or "(unspecified)", "reason": reason or "unmapped"})
    return out


def _default_llm_invoker(
    db: Session, *, settings: AppSettings | None = None
) -> LlmInvoker:
    app_settings = settings or get_or_create_settings(db)
    config = llm_plan_config_from_app_settings(app_settings)

    def _invoke(*, system: str, user: str, purpose: str) -> dict[str, Any]:
        return _llm_json(config, system=system, user=user, purpose=purpose)

    return _invoke


def _llm_json(
    config: LlmConfig, *, system: str, user: str, purpose: str
) -> dict[str, Any]:
    messages: list[ChatMessage] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    result = chat_completion_detailed(
        config,
        messages,
        temperature=0.1,
        max_tokens=4096,
    )
    parsed = parse_json_object(result.text, log_label=f"report-planner:{purpose}")
    if parsed.data is None:
        raise PlanError(parsed.error or f"Planner {purpose} returned invalid JSON")
    return parsed.data
