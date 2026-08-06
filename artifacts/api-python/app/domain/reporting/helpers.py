"""Pure helpers for report stats computation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.dqa.values import get_value

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


def day_bounds(date_key: str, tz_name: str) -> tuple[datetime, datetime]:
    """UTC-naive start/end for a calendar day in ``tz_name``."""
    tz = ZoneInfo(tz_name)
    year, month, day = (int(p) for p in date_key.split("-"))
    start_local = datetime(year, month, day, 0, 0, 0, tzinfo=tz)
    end_local = start_local + timedelta(days=1) - timedelta(microseconds=1)
    return start_local.astimezone(timezone.utc).replace(tzinfo=None), end_local.astimezone(
        timezone.utc
    ).replace(tzinfo=None)


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


def udise_for(sub: Any, pack: dict[str, Any] | None) -> str:
    data = sub.data if isinstance(sub.data, dict) else {}
    if pack:
        for alias in ("udise", "UDISE", "udise_code"):
            value = get_value(data, pack, alias)
            if value is not None and str(value).strip():
                return str(value).strip()
    for key, value in data.items():
        if "udise" in str(key).lower() and value is not None and str(value).strip():
            return str(value).strip()
    return "—"


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


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 1)
