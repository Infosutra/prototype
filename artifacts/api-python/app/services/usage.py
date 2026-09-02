"""Usage ledger queries."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import UsageEvent
from app.schemas.audio import UsageEventOut, UsageSummaryItem, UsageSummaryOut


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def list_usage_events(
    db: Session,
    *,
    study_id: str | None = None,
    category: str | None = None,
    limit: int = 500,
) -> list[UsageEventOut]:
    query = select(UsageEvent).order_by(UsageEvent.occurred_at.desc()).limit(limit)
    if study_id:
        query = query.where(UsageEvent.study_id == study_id)
    if category:
        query = query.where(UsageEvent.category == category)
    rows = db.scalars(query).all()
    return [
        UsageEventOut(
            id=row.id,
            occurred_at=_iso(row.occurred_at),
            category=row.category,
            provider=row.provider,
            operation=row.operation,
            quantity=row.quantity,
            unit=row.unit,
            amount=row.amount,
            currency=row.currency,
            study_id=row.study_id,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            metadata=row.metadata_json,
        )
        for row in rows
    ]


def usage_summary(
    db: Session,
    *,
    study_id: str | None = None,
    category: str | None = None,
) -> UsageSummaryOut:
    query = (
        select(
            UsageEvent.category,
            UsageEvent.currency,
            func.sum(UsageEvent.amount).label("total_amount"),
            func.count(UsageEvent.id).label("event_count"),
        )
        .group_by(UsageEvent.category, UsageEvent.currency)
    )
    if study_id:
        query = query.where(UsageEvent.study_id == study_id)
    if category:
        query = query.where(UsageEvent.category == category)

    rows = db.execute(query).all()
    items: list[UsageSummaryItem] = []
    total = 0.0
    currency = "INR"
    for row in rows:
        amount = float(row.total_amount or 0.0)
        currency = row.currency or currency
        total += amount
        items.append(
            UsageSummaryItem(
                category=row.category,
                total_amount=amount,
                currency=row.currency or "INR",
                event_count=int(row.event_count or 0),
            )
        )
    return UsageSummaryOut(items=items, total_amount=total, currency=currency)
