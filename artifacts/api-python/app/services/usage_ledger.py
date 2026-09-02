"""Install-wide usage event recording (transcription, LLM, etc.)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import UsageEvent


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_usage_event(
    db: Session,
    *,
    category: str,
    provider: str,
    operation: str,
    quantity: float,
    unit: str,
    amount: float = 0.0,
    currency: str = "INR",
    study_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> UsageEvent:
    event = UsageEvent(
        id=str(uuid.uuid4()),
        occurred_at=_utcnow(),
        category=category,
        provider=provider,
        operation=operation,
        quantity=quantity,
        unit=unit,
        amount=amount,
        currency=currency,
        study_id=study_id,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_json=metadata or {},
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    return event
