"""Semantic dateWindow token → inclusive ISO range resolution."""

from __future__ import annotations

from datetime import date, timedelta

from app.domain.reporting.query_aggregate_catalog import DATE_WINDOW_TOKENS


def intersect_inclusive_iso_dates(
    left_from: str | None,
    left_to: str | None,
    right_from: str | None,
    right_to: str | None,
) -> tuple[str | None, str | None]:
    """Intersect two inclusive ISO date ranges. ``None`` = unbounded on that side.

    When the intersection is empty, ``date_from`` may be greater than ``date_to``;
    loaders treat that as zero rows.
    """
    start = left_from
    end = left_to
    if right_from is not None:
        start = right_from if start is None or right_from > start else start
    if right_to is not None:
        end = right_to if end is None or right_to < end else end
    return start, end


def resolve_query_date_window(
    token: str | None,
    *,
    execution_date: str,
    study_start_date: str | None,
    context_date_from: str | None = None,
    context_date_to: str | None = None,
) -> tuple[str | None, str | None]:
    """Map a dateWindow token (or omit) to inclusive ISO ``(date_from, date_to)``.

    Omitted / empty token → execution context range (may both be None = full bag).
    Named tokens resolve against ``execution_date`` / study start, then are clamped
    to the execution context ``date_from``/``date_to`` when those are set (adhoc
    pre-filter semantics).
    """
    if token is None or (isinstance(token, str) and not token.strip()):
        return context_date_from, context_date_to

    normalized = str(token).strip()
    if normalized not in DATE_WINDOW_TOKENS:
        raise ValueError(f"Unknown dateWindow '{token}'")

    end = date.fromisoformat(execution_date)
    if normalized == "execution_date":
        resolved = (execution_date, execution_date)
    elif normalized == "last_7_days":
        start = end - timedelta(days=6)
        resolved = (start.isoformat(), execution_date)
    elif normalized == "last_14_days":
        start = end - timedelta(days=13)
        resolved = (start.isoformat(), execution_date)
    else:
        # study_to_date
        start_s = study_start_date or execution_date
        resolved = (start_s, execution_date)

    if context_date_from is None and context_date_to is None:
        return resolved
    return intersect_inclusive_iso_dates(
        resolved[0], resolved[1], context_date_from, context_date_to
    )
