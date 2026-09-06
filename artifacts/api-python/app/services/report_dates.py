"""Parse calendar dates mentioned in report prompts.

Specs keep using "today" data sources; a named day becomes the template's default
execution date so preview/execute resolve to that day.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_MONTHS: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_ISO = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_MONTH_DAY = re.compile(
    r"\b("
    + "|".join(sorted(_MONTHS, key=len, reverse=True))
    + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(20\d{2}))?\b",
    re.IGNORECASE,
)
_DAY_MONTH = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+("
    + "|".join(sorted(_MONTHS, key=len, reverse=True))
    + r")(?:,?\s*(20\d{2}))?\b",
    re.IGNORECASE,
)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_report_date(
    text: str,
    *,
    reference: date | None = None,
    study_start: date | None = None,
) -> str | None:
    """Return an ISO date when the prompt names a calendar day, else None.

    Relative words like "today" / "yesterday" are intentionally ignored — those
    stay unbound so each run uses the current execution day.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    if re.search(r"\b(today|yesterday|tomorrow)\b", lowered) and not (
        _ISO.search(raw) or _MONTH_DAY.search(raw) or _DAY_MONTH.search(raw)
    ):
        return None

    ref = reference or date.today()
    default_year = (study_start or ref).year

    iso = _ISO.search(raw)
    if iso:
        found = _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        if found:
            return found.isoformat()

    match = _MONTH_DAY.search(raw)
    if match:
        month = _MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else default_year
        found = _safe_date(year, month, day)
        if found:
            return found.isoformat()

    match = _DAY_MONTH.search(raw)
    if match:
        day = int(match.group(1))
        month = _MONTHS[match.group(2).lower()]
        year = int(match.group(3)) if match.group(3) else default_year
        found = _safe_date(year, month, day)
        if found:
            return found.isoformat()

    return None


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def study_start_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return parse_iso_date(str(value))
