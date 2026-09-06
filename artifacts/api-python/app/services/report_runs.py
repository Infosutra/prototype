"""Observability for report planning and execution runs."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ReportRun
from app.services.usage_ledger import record_usage_event

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_run(
    db: Session,
    *,
    mode: str,
    status: str = "ok",
    study_id: str | None = None,
    template_id: str | None = None,
    template_version_id: str | None = None,
    conversation_id: str | None = None,
    report_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    prompt_id: str | None = None,
    attempts: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: float = 0.0,
    structured_output: bool = False,
    tool_calls: list[dict[str, Any]] | None = None,
    validation_errors: list[dict[str, Any]] | None = None,
    error: str | None = None,
    commit: bool = True,
) -> ReportRun:
    """Persist one trace row and, when tokens were spent, a usage ledger entry.

    Never raises: observability must not break report generation.
    """
    run = ReportRun(
        id=str(uuid.uuid4()),
        mode=mode,
        status=status,
        study_id=study_id,
        template_id=template_id,
        template_version_id=template_version_id,
        conversation_id=conversation_id,
        report_id=report_id,
        provider=provider,
        model=model,
        prompt_id=prompt_id,
        attempts=attempts,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        structured_output=structured_output,
        tool_calls_json=tool_calls or [],
        validation_errors_json=validation_errors or [],
        error=error,
        created_at=_now(),
    )
    try:
        db.add(run)
        total_tokens = int(prompt_tokens) + int(completion_tokens)
        if total_tokens > 0:
            record_usage_event(
                db,
                category="llm",
                provider=provider or "unknown",
                operation=f"report_{mode}",
                quantity=float(total_tokens),
                unit="tokens",
                study_id=study_id,
                resource_type="report_run",
                resource_id=run.id,
                metadata={
                    "model": model,
                    "promptTokens": prompt_tokens,
                    "completionTokens": completion_tokens,
                    "latencyMs": round(latency_ms, 1),
                },
                commit=False,
            )
        if commit:
            db.commit()
    except Exception:
        logger.exception("Failed to record report run (mode=%s)", mode)
    return run
