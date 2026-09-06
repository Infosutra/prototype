"""LangGraph Report Planner: natural language to a validated Report Specification.

The graph owns intent and composition. It never touches data: it selects component
types and data source ids from the catalog, and everything it produces is validated
against that catalog before it can be stored or executed.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, TypedDict

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import AppSettings
from app.domain.report_spec.spec import MetricComponent, ReportSpec, Section
from app.domain.report_spec.validation import (
    SpecIssue,
    parse_spec,
    repair_spec,
    validate_spec,
)
from app.integrations.llm import (
    CompletionParams,
    LlmConfig,
    LlmError,
    chat_completion_detailed,
    chat_model,
    llm_report_planner_config_from_app_settings,
    to_lc_messages,
)
from app.services.report_planner_prompts import (
    PATCH_OUTPUT_CONTRACT,
    PLANNER_OUTPUT_CONTRACT,
    resolve_planner_prompt,
)
from app.services.report_planner.prompting import (
    IntentReply,
    PlannerReply,
    build_intent_request,
    build_plan_request,
)
from app.services.report_tools import all_descriptors, descriptors_by_id

logger = logging.getLogger(__name__)

#: Matches the DQA compiler's repair budget.
MAX_LLM_ATTEMPTS = 3

PlanStatus = Literal["ok", "clarification", "unsupported", "invalid", "answer", "error"]

#: Whether a given endpoint+model accepted a structured-output request. Detected once
#: per process and reported on each run.
_STRUCTURED_SUPPORT: dict[str, bool] = {}


@dataclass
class PlanTelemetry:
    attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    model: str | None = None
    provider: str | None = None
    prompt_id: str | None = None
    structured_output: bool = False

    def add(self, *, model: str | None, provider: str | None, prompt_tokens: int,
            completion_tokens: int, latency_ms: float) -> None:
        self.attempts += 1
        self.model = model or self.model
        self.provider = provider or self.provider
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.latency_ms += latency_ms


@dataclass
class PlanResult:
    status: PlanStatus
    spec: ReportSpec | None = None
    question: str | None = None
    reason: str | None = None
    summary: str | None = None
    intent: str = "plan"
    errors: list[SpecIssue] = field(default_factory=list)
    warnings: list[SpecIssue] = field(default_factory=list)
    telemetry: PlanTelemetry = field(default_factory=PlanTelemetry)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.spec is not None

    def error_dicts(self) -> list[dict[str, str]]:
        return [issue.model_dump(by_alias=True) for issue in self.errors]


class PlannerState(TypedDict, total=False):
    instructions: str
    report_kind: str
    conversation: list[dict[str, str]]
    current_spec: ReportSpec | None
    intent: str
    candidate: ReportSpec | None
    errors: list[SpecIssue]
    warnings: list[SpecIssue]
    attempts: int
    status: PlanStatus
    question: str | None
    reason: str | None
    summary: str | None


# --- Model invocation -------------------------------------------------------


def _structured_key(config: LlmConfig) -> str:
    return f"{config.base_url}|{config.model}"


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", stripped).strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", stripped)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _record_raw(telemetry: PlanTelemetry, raw: Any, config: LlmConfig) -> None:
    metadata = getattr(raw, "response_metadata", None) or {}
    usage = getattr(raw, "usage_metadata", None) or {}
    telemetry.add(
        model=str(metadata.get("model_name") or config.model),
        provider=config.provider,
        prompt_tokens=int(usage.get("input_tokens") or 0),
        completion_tokens=int(usage.get("output_tokens") or 0),
        latency_ms=0.0,
    )


class _ModelCaller:
    """Invokes the model with structured output, falling back to JSON-in-prompt.

    Capability is discovered by attempting a structured call once per endpoint and
    model; a provider that rejects the request is remembered so later calls skip it.
    """

    def __init__(
        self,
        config: LlmConfig,
        params: CompletionParams,
        telemetry: PlanTelemetry,
    ) -> None:
        self.config = config
        self.params = params
        self.telemetry = telemetry

    def invoke(
        self,
        reply_model: type[BaseModel],
        build_messages: Callable[[bool], list[dict[str, str]]],
    ) -> tuple[BaseModel | None, str | None, dict[str, Any] | None]:
        """Return (parsed reply, error message, raw payload if parsing failed)."""
        key = _structured_key(self.config)
        if _STRUCTURED_SUPPORT.get(key, True):
            messages = build_messages(False)
            try:
                model = chat_model(self.config, self.params).with_structured_output(
                    reply_model, include_raw=True
                )
                output = model.invoke(to_lc_messages(messages))
            except LlmError:
                raise
            except Exception as exc:  # noqa: BLE001 — provider rejected structured output
                logger.info(
                    "Structured output unavailable for %s (%s); using JSON-in-prompt.",
                    self.config.model,
                    exc,
                )
                _STRUCTURED_SUPPORT[key] = False
            else:
                _STRUCTURED_SUPPORT[key] = True
                self.telemetry.structured_output = True
                raw = output.get("raw") if isinstance(output, dict) else None
                parsed = output.get("parsed") if isinstance(output, dict) else None
                parsing_error = output.get("parsing_error") if isinstance(output, dict) else None
                if raw is not None:
                    _record_raw(self.telemetry, raw, self.config)
                if parsed is not None:
                    return parsed, None, None
                # The model answered but the answer did not fit the schema: that is a
                # content problem for the repair loop, not a capability problem.
                from app.integrations.llm import message_text

                text, _ = message_text(raw) if raw is not None else ("", 0)
                return None, str(parsing_error or "Model output did not match the schema"), (
                    _parse_json_object(text) or None
                )

        messages = build_messages(True)
        result = chat_completion_detailed(
            self.config,
            messages,
            temperature=self.params.temperature,
            max_tokens=self.params.max_tokens,
            timeout_seconds=self.params.timeout_seconds,
        )
        self.telemetry.add(
            model=result.model,
            provider=result.provider,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            latency_ms=result.latency_ms,
        )
        payload = _parse_json_object(result.text)
        if not payload:
            return None, "Model did not return a JSON object", None
        try:
            return reply_model.model_validate(payload), None, None
        except Exception as exc:  # noqa: BLE001 — surfaced to the repair loop
            return None, str(exc), payload


# --- Graph ------------------------------------------------------------------


_NODE_PROGRESS: dict[str, str] = {
    "classify_intent": "Understanding your request…",
    "plan_spec": "Asking the model to draft the report specification…",
    "patch_spec": "Asking the model to update the specification…",
    "validate_spec": "Checking the specification against available data sources…",
    "repair": "Repairing issues the validator found…",
}


def _issues(payload: Any) -> list[SpecIssue]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, SpecIssue)]
    return []


def _stream_progress(phase: str, message: str, **extra: Any) -> None:
    """Emit a progress event mid-node so SSE clients see work before the LLM returns."""
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:  # noqa: BLE001 — streaming is optional outside astream
        return
    if writer is None:
        return
    payload: dict[str, Any] = {"event": "progress", "phase": phase, "message": message}
    payload.update({k: v for k, v in extra.items() if v is not None})
    writer(payload)


def build_graph(
    caller: _ModelCaller,
    *,
    system_prompt: str,
    sources_brief,
    report_kind: str,
):
    from langgraph.graph import END, StateGraph

    sources = sources_brief
    catalog = descriptors_by_id()

    def _messages(
        *,
        instructions: str,
        current_spec: ReportSpec | None,
        conversation: list[dict[str, str]] | None,
        errors: list[SpecIssue] | None,
        contract: str,
    ) -> Callable[[bool], list[dict[str, str]]]:
        def build(include_schema: bool) -> list[dict[str, str]]:
            return [
                {"role": "system", "content": f"{system_prompt}\n\n{contract}"},
                {
                    "role": "user",
                    "content": build_plan_request(
                        instructions=instructions,
                        sources=sources,
                        report_kind=report_kind,
                        include_schema=include_schema,
                        current_spec=current_spec,
                        conversation=conversation,
                        validation_errors=[i.model_dump(by_alias=True) for i in (errors or [])],
                    ),
                },
            ]

        return build

    def _reply_to_state(
        reply: BaseModel | None, error: str | None, payload: dict[str, Any] | None
    ) -> PlannerState:
        if reply is None:
            # Try to salvage a spec from an off-schema reply so repair has something
            # concrete to fix.
            candidate_payload = (payload or {}).get("spec") if payload else None
            if candidate_payload:
                parsed = parse_spec(candidate_payload)
                if parsed.spec is not None:
                    return {"candidate": parsed.spec, "status": "ok", "errors": []}
                return {
                    "candidate": None,
                    "status": "invalid",
                    "errors": parsed.errors,
                }
            return {
                "candidate": None,
                "status": "invalid",
                "errors": [
                    SpecIssue(path="", code="planner_output", message=error or "No planner output")
                ],
            }

        status = str(getattr(reply, "status", "ok") or "ok").strip().lower()
        if status == "clarification":
            return {
                "status": "clarification",
                "question": getattr(reply, "question", None)
                or "Could you say more about what this report should contain?",
            }
        if status == "unsupported":
            return {
                "status": "unsupported",
                "reason": getattr(reply, "reason", None) or "The request is not supported.",
            }
        spec = getattr(reply, "spec", None)
        if spec is None:
            return {
                "status": "invalid",
                "candidate": None,
                "errors": [
                    SpecIssue(
                        path="spec",
                        code="missing_spec",
                        message="Planner reported success but returned no specification.",
                    )
                ],
            }
        return {
            "candidate": spec,
            "status": "ok",
            "summary": getattr(reply, "summary", None),
            "errors": [],
        }

    def classify_intent(state: PlannerState) -> PlannerState:
        current = state.get("current_spec")
        if current is None:
            return {"intent": "plan", "attempts": 0}
        _stream_progress(
            "classify_intent",
            _NODE_PROGRESS["classify_intent"],
        )
        reply, error, _payload = caller.invoke(
            IntentReply,
            lambda _include_schema: [
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt}\n\nOutput contract: respond with a single JSON object "
                        '{"intent": "patch|replace|question", "question": "<answer if question>"}.'
                    ),
                },
                {
                    "role": "user",
                    "content": build_intent_request(
                        instructions=state.get("instructions", ""),
                        current_spec=current,
                        conversation=state.get("conversation"),
                    ),
                },
            ],
        )
        if reply is None:
            logger.info("Intent classification failed (%s); treating turn as a patch.", error)
            return {"intent": "patch", "attempts": 0}
        intent = str(getattr(reply, "intent", "patch") or "patch").strip().lower()
        if intent == "question":
            return {
                "intent": "question",
                "status": "answer",
                "question": getattr(reply, "question", None) or "",
                "attempts": 0,
            }
        return {"intent": intent if intent in {"patch", "replace"} else "patch", "attempts": 0}

    def plan_node(state: PlannerState) -> PlannerState:
        _stream_progress("plan_spec", _NODE_PROGRESS["plan_spec"])
        reply, error, payload = caller.invoke(
            PlannerReply,
            _messages(
                instructions=state.get("instructions", ""),
                current_spec=None,
                conversation=state.get("conversation"),
                errors=None,
                contract=PLANNER_OUTPUT_CONTRACT,
            ),
        )
        return _reply_to_state(reply, error, payload)

    def patch_node(state: PlannerState) -> PlannerState:
        _stream_progress("patch_spec", _NODE_PROGRESS["patch_spec"])
        reply, error, payload = caller.invoke(
            PlannerReply,
            _messages(
                instructions=state.get("instructions", ""),
                current_spec=state.get("current_spec"),
                conversation=state.get("conversation"),
                errors=None,
                contract=PATCH_OUTPUT_CONTRACT,
            ),
        )
        return _reply_to_state(reply, error, payload)

    def validate_node(state: PlannerState) -> PlannerState:
        _stream_progress("validate_spec", _NODE_PROGRESS["validate_spec"])
        candidate = state.get("candidate")
        if candidate is None:
            return {"status": "invalid"}
        result = validate_spec(candidate, catalog)
        if result.valid:
            return {"status": "ok", "errors": [], "warnings": result.warnings}
        # Deterministic kind fix (metric/kpi_group → table on row sources) before LLM repair.
        salvaged, notes = repair_spec(candidate, catalog)
        if any(note.code == "component_coerced_to_table" for note in notes):
            check = validate_spec(salvaged, catalog)
            if check.valid and salvaged.sections:
                return {
                    "status": "ok",
                    "candidate": salvaged,
                    "errors": [],
                    "warnings": [*result.warnings, *notes, *check.warnings],
                }
        return {"status": "invalid", "errors": result.errors, "warnings": result.warnings}

    def repair_node(state: PlannerState) -> PlannerState:
        attempts = int(state.get("attempts") or 0) + 1
        _stream_progress(
            "repair",
            f"Repairing issues the validator found (attempt {attempts}/{MAX_LLM_ATTEMPTS})…",
            attempt=attempts,
        )
        is_patch = state.get("intent") == "patch"
        reply, error, payload = caller.invoke(
            PlannerReply,
            _messages(
                instructions=state.get("instructions", ""),
                current_spec=state.get("current_spec") if is_patch else None,
                conversation=state.get("conversation"),
                errors=_issues(state.get("errors")),
                contract=PATCH_OUTPUT_CONTRACT if is_patch else PLANNER_OUTPUT_CONTRACT,
            ),
        )
        return {**_reply_to_state(reply, error, payload), "attempts": attempts}

    def after_classify(state: PlannerState) -> str:
        intent = state.get("intent")
        if intent == "question":
            return END
        if intent == "patch":
            return "patch_spec"
        return "plan_spec"

    def after_plan(state: PlannerState) -> str:
        return "validate_spec" if state.get("candidate") is not None else END

    def after_validate(state: PlannerState) -> str:
        if state.get("status") == "ok":
            return END
        if int(state.get("attempts") or 0) >= MAX_LLM_ATTEMPTS - 1:
            return END
        return "repair"

    graph = StateGraph(PlannerState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("plan_spec", plan_node)
    graph.add_node("patch_spec", patch_node)
    graph.add_node("validate_spec", validate_node)
    graph.add_node("repair", repair_node)

    graph.set_entry_point("classify_intent")
    graph.add_conditional_edges(
        "classify_intent", after_classify, {"plan_spec": "plan_spec", "patch_spec": "patch_spec", END: END}
    )
    graph.add_conditional_edges("plan_spec", after_plan, {"validate_spec": "validate_spec", END: END})
    graph.add_conditional_edges("patch_spec", after_plan, {"validate_spec": "validate_spec", END: END})
    graph.add_conditional_edges("validate_spec", after_validate, {"repair": "repair", END: END})
    graph.add_edge("repair", "validate_spec")
    return graph.compile()


# --- Public entry points ----------------------------------------------------


def _run(
    db: Session,
    *,
    instructions: str,
    report_kind: str,
    current_spec: ReportSpec | None,
    conversation: list[dict[str, str]] | None,
    settings: AppSettings,
) -> PlanResult:
    if not (instructions or "").strip():
        return PlanResult(
            status="clarification",
            question="What should this report contain?",
        )
    if not settings.ai_enabled:
        return PlanResult(
            status="error",
            reason="AI features are disabled in Settings, so reports cannot be planned.",
        )

    telemetry = PlanTelemetry()
    system_prompt, prompt_id = resolve_planner_prompt(db)
    telemetry.prompt_id = prompt_id
    try:
        config = llm_report_planner_config_from_app_settings(settings)
        params = CompletionParams(
            # Composition should be reproducible, so planning runs colder than prose.
            temperature=min(float(settings.ai_temperature or 0.3), 0.2),
            max_tokens=max(int(settings.ai_max_tokens or 2048), 4096),
            timeout_seconds=float(settings.ai_timeout_seconds or 60),
        )
        caller = _ModelCaller(config, params, telemetry)
        app = build_graph(
            caller,
            system_prompt=system_prompt,
            sources_brief=all_descriptors(),
            report_kind=report_kind,
        )
        final: PlannerState = app.invoke(
            {
                "instructions": instructions.strip(),
                "report_kind": report_kind,
                "conversation": conversation or [],
                "current_spec": current_spec,
                "attempts": 0,
            }
        )
    except LlmError as exc:
        logger.warning("Report planning failed: %s", exc)
        return PlanResult(status="error", reason=str(exc), telemetry=telemetry)
    except Exception as exc:  # noqa: BLE001 — planner must not surface tracebacks
        logger.exception("Report planning failed")
        return PlanResult(status="error", reason=str(exc), telemetry=telemetry)

    return _finalize_plan_state(final, telemetry, instructions=instructions)


_INVALID_PLAN_REASON = (
    "The planner couldn't produce a valid report specification after several attempts. "
    "This is a planner failure, not a problem with your prompt. "
    "Click Plan and save again, or slightly rephrase the request."
)


def _simple_kpi_fallback(instructions: str) -> ReportSpec | None:
    """Last-resort spec when the model describes a simple totals KPI in prose instead of JSON."""
    text = (instructions or "").strip().lower()
    if not text or len(text) > 240:
        return None
    wants_figure = any(
        token in text
        for token in ("kpi", "metric", "total", "submission", "count", "how many", "intake")
    )
    if not wants_figure:
        return None
    use_today = "today" in text or "daily" in text
    field = "newToday" if use_today else "cumulative"
    label = "Submissions today" if use_today else "Total submissions"
    return ReportSpec(
        title=label,
        sections=[
            Section(
                id="summary",
                title="Summary",
                components=[
                    MetricComponent(
                        id="total",
                        label=label,
                        data_source="study_totals",
                        field=field,
                        format="int",
                    )
                ],
            )
        ],
    )


def _finalize_plan_state(
    final: PlannerState,
    telemetry: PlanTelemetry,
    *,
    instructions: str = "",
) -> PlanResult:
    status = final.get("status") or "invalid"
    candidate = final.get("candidate")
    errors = _issues(final.get("errors"))
    warnings = _issues(final.get("warnings"))
    summary = final.get("summary")
    reason = final.get("reason")

    if status == "invalid" and candidate is not None:
        catalog = descriptors_by_id()
        salvaged, notes = repair_spec(candidate, catalog)
        check = validate_spec(salvaged, catalog)
        if check.valid and salvaged.sections:
            status = "ok"
            candidate = salvaged
            errors = []
            warnings = [*warnings, *notes, *check.warnings]
            summary = summary or "Updated the report (dropped invalid components)."
            reason = None
        else:
            warnings = [*warnings, *notes]

    if status == "invalid":
        fallback = _simple_kpi_fallback(instructions)
        if fallback is not None:
            catalog = descriptors_by_id()
            check = validate_spec(fallback, catalog)
            if check.valid:
                status = "ok"
                candidate = fallback
                errors = []
                warnings = [
                    *warnings,
                    SpecIssue(
                        path="sections",
                        code="planner_fallback",
                        message=(
                            "Used a simple study_totals KPI because the model returned "
                            "descriptive text instead of a data-bound component."
                        ),
                    ),
                    *check.warnings,
                ]
                summary = summary or f"Added a {fallback.sections[0].components[0].label} KPI."
                reason = None

    if status == "invalid" and not reason:
        reason = _INVALID_PLAN_REASON

    return PlanResult(
        status=status,  # type: ignore[arg-type]
        spec=candidate if status == "ok" else None,
        question=final.get("question"),
        reason=reason,
        summary=summary,
        intent=str(final.get("intent") or "plan"),
        errors=errors,
        warnings=warnings,
        telemetry=telemetry,
    )


def plan_spec_stream(
    db: Session,
    *,
    instructions: str,
    report_kind: str = "adhoc",
    settings: AppSettings | None = None,
):
    """Yield progress events while planning, then a final PlanResult.

    Event shapes:
    - {"event": "progress", "phase": "<node>", "message": "...", "attempt"?: int}
    - {"event": "result", "result": PlanResult}
    - {"event": "error", "message": "..."}
    """
    from app.services.settings import get_or_create_settings

    settings = settings or get_or_create_settings(db)
    if not (instructions or "").strip():
        yield {
            "event": "result",
            "result": PlanResult(
                status="clarification",
                question="What should this report contain?",
            ),
        }
        return
    if not settings.ai_enabled:
        yield {
            "event": "result",
            "result": PlanResult(
                status="error",
                reason="AI features are disabled in Settings, so reports cannot be planned.",
            ),
        }
        return

    yield {
        "event": "progress",
        "phase": "start",
        "message": "Preparing the report planner…",
    }

    telemetry = PlanTelemetry()
    system_prompt, prompt_id = resolve_planner_prompt(db)
    telemetry.prompt_id = prompt_id
    try:
        config = llm_report_planner_config_from_app_settings(settings)
        params = CompletionParams(
            temperature=min(float(settings.ai_temperature or 0.3), 0.2),
            max_tokens=max(int(settings.ai_max_tokens or 2048), 4096),
            timeout_seconds=float(settings.ai_timeout_seconds or 60),
        )
        caller = _ModelCaller(config, params, telemetry)
        app = build_graph(
            caller,
            system_prompt=system_prompt,
            sources_brief=all_descriptors(),
            report_kind=report_kind,
        )
        inputs: PlannerState = {
            "instructions": instructions.strip(),
            "report_kind": report_kind,
            "conversation": [],
            "current_spec": None,
            "attempts": 0,
        }
        final: PlannerState = dict(inputs)
        for item in app.stream(inputs, stream_mode=["custom", "updates"]):
            mode = "updates"
            chunk: Any = item
            if isinstance(item, tuple) and len(item) == 2:
                mode, chunk = item

            if mode == "custom" and isinstance(chunk, dict):
                # Nodes emit progress at the start of long work (before the LLM returns).
                name = str(chunk.get("event") or "progress")
                data = {k: v for k, v in chunk.items() if k != "event"}
                yield {"event": name, **data}
                continue

            if mode != "updates" or not isinstance(chunk, dict):
                continue

            for node_name, update in chunk.items():
                # Completion notes after each node (status-aware where useful).
                message = None
                attempt = None
                if isinstance(update, dict):
                    final = {**final, **update}
                    status = update.get("status")
                    if node_name == "validate_spec" and status == "ok":
                        message = "Specification looks valid."
                    elif node_name == "validate_spec" and status == "invalid":
                        message = "Found problems — preparing a repair pass…"
                    elif node_name == "plan_spec" and status == "clarification":
                        message = "The model needs a clarifying question…"
                    elif node_name == "plan_spec" and status == "unsupported":
                        message = "The model declined this request…"
                    elif node_name == "repair":
                        attempt = int(update.get("attempts") or 0) or None
                if message:
                    yield {
                        "event": "progress",
                        "phase": node_name,
                        "message": message,
                        **({"attempt": attempt} if attempt is not None else {}),
                    }
        yield {
            "event": "progress",
            "phase": "finalize",
            "message": "Finalising the planned specification…",
        }
        result = _finalize_plan_state(final, telemetry, instructions=instructions.strip())
        yield {"event": "result", "result": result}
    except LlmError as exc:
        logger.warning("Report planning failed: %s", exc)
        yield {
            "event": "result",
            "result": PlanResult(status="error", reason=str(exc), telemetry=telemetry),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Report planning failed")
        yield {
            "event": "error",
            "message": str(exc),
            "code": "plan_stream_error",
        }


def plan_spec(
    db: Session,
    *,
    instructions: str,
    report_kind: str = "adhoc",
    settings: AppSettings | None = None,
) -> PlanResult:
    """Plan a new specification from a natural-language report request."""
    from app.services.settings import get_or_create_settings

    return _run(
        db,
        instructions=instructions,
        report_kind=report_kind,
        current_spec=None,
        conversation=None,
        settings=settings or get_or_create_settings(db),
    )


def patch_spec(
    db: Session,
    *,
    instructions: str,
    current_spec: ReportSpec,
    conversation: list[dict[str, str]] | None = None,
    report_kind: str = "adhoc",
    settings: AppSettings | None = None,
) -> PlanResult:
    """Apply a conversational change to a working specification."""
    from app.services.settings import get_or_create_settings

    return _run(
        db,
        instructions=instructions,
        report_kind=report_kind,
        current_spec=current_spec,
        conversation=conversation,
        settings=settings or get_or_create_settings(db),
    )
