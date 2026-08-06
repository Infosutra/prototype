"""Daily report trend series and sign-off checklist builders (pure)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.domain.reporting.helpers import day_bounds


def build_flag_rate_by_day(
    *,
    study_start_date: str | None,
    date_key: str,
    tz_name: str,
    all_subs: list[Any],
    all_flags: list[Any],
) -> list[dict[str, Any]]:
    """Day-by-day cumulative flag-rate trend (Section 1.4)."""
    flag_rate_by_day: list[dict[str, Any]] = []
    if not study_start_date:
        return flag_rate_by_day
    try:
        start_d = date.fromisoformat(study_start_date)
        end_d = date.fromisoformat(date_key)
        if end_d < start_d:
            return flag_rate_by_day
        day = start_d
        while day <= end_d and len(flag_rate_by_day) < 45:
            _s, day_end = day_bounds(day.isoformat(), tz_name)
            subs_to_date = [
                s for s in all_subs if s.submitted_at and s.submitted_at <= day_end
            ]
            ids = {s.id for s in subs_to_date}
            flagged_ids = {f.submission_id for f in all_flags if f.submission_id in ids}
            n = len(subs_to_date)
            flag_rate_by_day.append(
                {
                    "date": day.isoformat(),
                    "dayLabel": f"D{(day - start_d).days + 1}",
                    "flaggedPct": round(100.0 * len(flagged_ids) / n, 1) if n else 0.0,
                    "submissions": n,
                }
            )
            day += timedelta(days=1)
    except ValueError:
        return []
    return flag_rate_by_day


def build_signoff_checklist(
    *,
    red_priority: list[dict[str, Any]],
    red_grouped_today: list[dict[str, Any]],
    top_rules_all: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Read-only sign-off checklist from open RED rules + top AMBER themes."""
    checklist: list[dict[str, Any]] = []
    for item in red_priority[:8]:
        checklist.append(
            {
                "severity": "red",
                "label": f"{item['ruleId']} — {item['title']}",
                "detail": f"{item['toolCode']} · enumerator {item['enumerator']} · UDISE {item['udise']}",
                "ownerHint": "Field coordinator / DQA lead",
                "toolCode": item["toolCode"],
                "records": 1,
                "owner": "Field supervisor",
            }
        )
    # Prefer grouped RED counts when available for sign-off table
    if red_grouped_today:
        checklist = []
        for item in red_grouped_today[:8]:
            checklist.append(
                {
                    "severity": "red",
                    "label": f"Correct/back-check {item['ruleId']} — {item['title']}",
                    "detail": f"{item['count']} record(s) · e.g. {item['exampleEnumerator']}",
                    "ownerHint": "Field supervisor",
                    "toolCode": item["toolCode"],
                    "records": item["count"],
                    "owner": "Field supervisor",
                }
            )
    amber_themes = [r for r in top_rules_all if r["severity"] == "amber"][:5]
    for rule in amber_themes:
        checklist.append(
            {
                "severity": "amber",
                "label": f"Verify {rule['ruleId']} — {rule['title']}",
                "detail": f"{rule['count']} flag(s) cumulative",
                "ownerHint": "M&E officer",
                "toolCode": "—",
                "records": rule["count"],
                "owner": "M&E officer",
            }
        )
    return checklist
