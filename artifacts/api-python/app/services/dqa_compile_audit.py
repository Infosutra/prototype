"""Persist DQA compile session audit records."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DqaCompileSession
from app.domain.dqa.rule_audit import sanitize_english
from app.services.usage_ledger import record_usage_event

logger = logging.getLogger(__name__)


class CompileSessionRecorder:
    """Accumulates compile telemetry across LLM attempts."""

    def __init__(
        self,
        db: Session,
        *,
        project_id: str,
        study_id: str | None,
        english: str,
        conversation_turns: int,
        provider: str,
        model: str,
        prompt_id: str | None,
    ):
        self.db = db
        self.session_id = str(uuid.uuid4())
        self.project_id = project_id
        self.study_id = study_id
        self.english = sanitize_english(english)
        self.conversation_turns = conversation_turns
        self.provider = provider
        self.model = model
        self.prompt_id = prompt_id
        self.attempts = 0
        self.latency_ms_total = 0.0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.metadata: dict[str, Any] = {}

    def record_llm_call(
        self,
        *,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        attempt: int,
        phase: str,
    ) -> None:
        self.attempts = max(self.attempts, attempt)
        self.latency_ms_total += latency_ms
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        record_usage_event(
            self.db,
            category="llm",
            provider=self.provider,
            operation=f"dqa_compile_{phase}",
            quantity=float(prompt_tokens + completion_tokens),
            unit="tokens",
            study_id=self.study_id,
            resource_type="dqa_compile_session",
            resource_id=self.session_id,
            metadata={
                "project_id": self.project_id,
                "attempt": attempt,
                "phase": phase,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": round(latency_ms, 2),
                "model": self.model,
            },
            commit=False,
        )

    def finalize(
        self,
        *,
        status: str,
        validation_valid: bool | None = None,
        validation_errors: list[dict[str, Any]] | None = None,
        rule: dict[str, Any] | None = None,
        preview: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> DqaCompileSession:
        row = DqaCompileSession(
            id=self.session_id,
            project_id=self.project_id,
            study_id=self.study_id,
            status=status,
            english=self.english,
            conversation_turns=self.conversation_turns,
            provider=self.provider,
            model=self.model,
            prompt_id=self.prompt_id,
            attempts=self.attempts,
            latency_ms_total=int(round(self.latency_ms_total)),
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            validation_valid=(1 if validation_valid else 0 if validation_valid is False else None),
            validation_errors={"errors": validation_errors} if validation_errors else None,
            rule_id=str(rule.get("id")) if isinstance(rule, dict) and rule.get("id") else None,
            rule_snapshot=rule,
            preview_summary=_preview_summary(preview),
            error_code=error_code,
            error_message=(error_message or "")[:2000] or None,
            metadata_json={**(self.metadata or {}), **(extra_metadata or {})} or None,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        logger.info(
            "DQA compile session project_id=%s session_id=%s status=%s attempts=%s latency_ms=%s tokens=%s",
            self.project_id,
            self.session_id,
            status,
            self.attempts,
            row.latency_ms_total,
            row.prompt_tokens + row.completion_tokens,
        )
        return row


def get_compile_session(db: Session, session_id: str) -> DqaCompileSession | None:
    return db.get(DqaCompileSession, session_id)


def list_compile_sessions(
    db: Session, project_id: str, *, limit: int = 50
) -> list[DqaCompileSession]:
    limit = max(1, min(int(limit or 50), 200))
    return list(
        db.scalars(
            select(DqaCompileSession)
            .where(DqaCompileSession.project_id == project_id)
            .order_by(DqaCompileSession.created_at.desc())
            .limit(limit)
        ).all()
    )


def _preview_summary(preview: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(preview, dict):
        return None
    return {
        "submissions_checked": preview.get("submissions_checked"),
        "flag_count": preview.get("flag_count"),
        "pass_count": preview.get("pass_count"),
        "not_applicable_count": preview.get("not_applicable_count"),
    }
