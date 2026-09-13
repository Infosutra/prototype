"""Pure helpers for reporting ingest and display."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

# Abbreviated month names matching the requirement-doc sample (e.g. "23 Jul 2026, 18:30 IST").
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def today_in_tz(tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).date().isoformat()


def local_calendar_day(ts: datetime | None, tz_name: str) -> str | None:
    """Calendar date (YYYY-MM-DD) for ``ts`` in ``tz_name``.

    UTC-naive timestamps are treated as UTC, matching how sync times are stored.
    """
    if ts is None:
        return None
    try:
        tz = ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(tz).date().isoformat()


def _parse_display_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_report_datetime(
    value: Any,
    *,
    tz_name: str = "Asia/Kolkata",
    fallback: str = "n/a",
) -> str:
    """Format a UTC/naive timestamp for report headers, e.g. '6 Aug 2026, 12:42 IST'."""
    dt = _parse_display_dt(value)
    if dt is None:
        return fallback
    try:
        tz = ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    if dt.tzinfo is None:
        # Stored sync times are UTC-naive in this app.
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(tz)
    zone_label = "IST" if tz.key in {"Asia/Kolkata", "Asia/Calcutta"} else local.tzname() or tz.key
    return (
        f"{local.day} {_MONTHS[local.month - 1]} {local.year}, "
        f"{local.hour:02d}:{local.minute:02d} {zone_label}"
    )


def format_report_date(
    value: Any,
    *,
    fallback: str = "n/a",
) -> str:
    """Format a calendar date as '6 Aug 2026'."""
    if value is None:
        return fallback
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        text = str(value).strip()
        try:
            d = date.fromisoformat(text[:10])
        except ValueError:
            return fallback
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def parse_meta_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def duration_minutes(sub: Any) -> float | None:
    data = sub.data if isinstance(sub.data, dict) else {}
    start = parse_meta_dt(data.get("start"))
    end = parse_meta_dt(data.get("end"))
    if start is None or end is None:
        return None
    minutes = (end - start).total_seconds() / 60.0
    if minutes < 0 or minutes > 24 * 60:
        return None
    return minutes
