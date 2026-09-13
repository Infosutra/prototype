"""Shared study-local time window resolver (reports, dashboard, DQA, submissions).

Resolve presets and absolute ``{from, to}`` in Python with ``ZoneInfo``.
Do **not** use SQLite IANA timezone functions.

``utc_end`` is **exclusive** (start of the calendar day after ``to_date`` in the
study timezone, converted to UTC-naive). Prefer filtering with
``calendar_day`` inclusive ``[from_date, to_date]`` for day-group consistency;
``submitted_at`` filters use ``[utc_start, utc_end)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import to_camel

WindowPreset = Literal[
    "execution_date",
    "last_7_days",
    "last_14_days",
    "study_to_date",
]

WINDOW_PRESETS: frozenset[str] = frozenset(
    {"execution_date", "last_7_days", "last_14_days", "study_to_date"}
)


class TimeWindowInput(BaseModel):
    """Exactly one mode: preset (+ optional executionDate) OR absolute from/to."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    preset: WindowPreset | None = None
    execution_date: str | None = Field(default=None, alias="executionDate")
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> TimeWindowInput:
        has_preset = self.preset is not None
        has_from = self.from_ is not None
        has_to = self.to is not None
        if has_from != has_to:
            raise ValueError("Absolute range requires both 'from' and 'to'")
        has_range = has_from and has_to
        if has_preset and has_range:
            raise ValueError("Provide either preset or absolute from/to, not both")
        if not has_preset and not has_range:
            raise ValueError("Provide either preset or absolute from/to")
        return self


@dataclass(frozen=True)
class ResolvedTimeWindow:
    from_date: date
    to_date: date
    utc_start: datetime  # inclusive; UTC-naive
    utc_end: datetime  # exclusive; UTC-naive
    timezone: str
    source: Literal["preset", "range"]


class TimeWindowError(ValueError):
    """Invalid time window input or resolution failure."""


def _parse_iso_date(value: str, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise TimeWindowError(f"Invalid {label} date '{value}'") from exc


def _today_in_tz(tz_name: str, *, now: datetime | None) -> date:
    tz = ZoneInfo(tz_name)
    if now is None:
        return datetime.now(tz).date()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(tz).date()


def day_utc_bounds(
    day: date,
    tz_name: str,
) -> tuple[datetime, datetime]:
    """UTC-naive ``[start, end)`` for one study-local calendar day.

    ``end`` is exclusive (start of the next local day) for clean
    ``submitted_at`` range filters.
    """
    tz = ZoneInfo(tz_name)
    start_local = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    utc_start = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    utc_end = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return utc_start, utc_end


def range_utc_bounds(
    from_date: date,
    to_date: date,
    tz_name: str,
) -> tuple[datetime, datetime]:
    """UTC-naive ``[utc_start, utc_end)`` covering inclusive local days."""
    utc_start, _ = day_utc_bounds(from_date, tz_name)
    _, utc_end = day_utc_bounds(to_date, tz_name)
    return utc_start, utc_end


def _resolve_preset_dates(
    preset: str,
    *,
    execution_day: date,
    study_start_date: str | None,
) -> tuple[date, date]:
    if preset == "execution_date":
        return execution_day, execution_day
    if preset == "last_7_days":
        return execution_day - timedelta(days=6), execution_day
    if preset == "last_14_days":
        return execution_day - timedelta(days=13), execution_day
    if preset == "study_to_date":
        start = (
            _parse_iso_date(study_start_date, label="study_start_date")
            if study_start_date
            else execution_day
        )
        return start, execution_day
    raise TimeWindowError(f"Unknown preset '{preset}'")


def resolve_time_window(
    input: TimeWindowInput | dict[str, Any],
    *,
    timezone: str,
    study_start_date: str | None = None,
    max_range_days: int = 366,
    now: datetime | None = None,
) -> ResolvedTimeWindow:
    """Resolve preset or absolute range into study-local dates + UTC bounds."""
    if isinstance(input, dict):
        tw = TimeWindowInput.model_validate(input)
    else:
        tw = input

    tz_name = (timezone or "").strip() or "UTC"
    try:
        ZoneInfo(tz_name)
    except Exception as exc:
        raise TimeWindowError(f"Invalid timezone '{tz_name}'") from exc

    if tw.preset is not None:
        if tw.execution_date:
            execution_day = _parse_iso_date(tw.execution_date, label="executionDate")
        else:
            execution_day = _today_in_tz(tz_name, now=now)
        from_date, to_date = _resolve_preset_dates(
            tw.preset,
            execution_day=execution_day,
            study_start_date=study_start_date,
        )
        source: Literal["preset", "range"] = "preset"
    else:
        assert tw.from_ is not None and tw.to is not None
        from_date = _parse_iso_date(tw.from_, label="from")
        to_date = _parse_iso_date(tw.to, label="to")
        source = "range"

    if from_date > to_date:
        raise TimeWindowError(f"from ({from_date}) is after to ({to_date})")

    # Inclusive day count: from==to → 1 day.
    span_days = (to_date - from_date).days + 1
    if span_days > max_range_days:
        raise TimeWindowError(
            f"Range spans {span_days} days; max_range_days is {max_range_days}"
        )

    utc_start, utc_end = range_utc_bounds(from_date, to_date, tz_name)
    return ResolvedTimeWindow(
        from_date=from_date,
        to_date=to_date,
        utc_start=utc_start,
        utc_end=utc_end,
        timezone=tz_name,
        source=source,
    )


def resolve_optional_submitted_at_bounds(
    date_from: str | None,
    date_to: str | None,
    *,
    timezone: str,
) -> tuple[datetime | None, datetime | None]:
    """Optional inclusive local dates → UTC-naive ``[start, end)`` for submitted_at.

    One-sided filters are allowed (open start or open end). Prefer passing both
    dates so study TZ day boundaries stay consistent with report execute.
    """
    has_from = bool(date_from and str(date_from).strip())
    has_to = bool(date_to and str(date_to).strip())
    if not has_from and not has_to:
        return None, None

    tz_name = (timezone or "").strip() or "UTC"
    if has_from and has_to:
        resolved = resolve_time_window(
            {"from": str(date_from).strip()[:10], "to": str(date_to).strip()[:10]},
            timezone=tz_name,
        )
        return resolved.utc_start, resolved.utc_end

    if has_from:
        day = _parse_iso_date(str(date_from).strip()[:10], label="from")
        utc_start, _ = day_utc_bounds(day, tz_name)
        return utc_start, None

    day = _parse_iso_date(str(date_to).strip()[:10], label="to")
    _, utc_end = day_utc_bounds(day, tz_name)
    return None, utc_end
