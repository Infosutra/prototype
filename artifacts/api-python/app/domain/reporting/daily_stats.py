"""Pure daily DQA stats computation (no Session).

Phase 3: certified tools and narrative fallbacks no longer consume this collapse.
The function remains as a thin compatibility stub for callers that still invoke
``build_daily_dqa_stats`` (golden inject, rare ``stats()`` paths). Heavy
enumerator / findings / red-priority / trend / checklist slices were removed —
those live on Phase 2 tool recipes and ``compose_signoff_checklist``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.domain.reporting.aggregate import count_where, project_fields, scalar_aggregate
from app.domain.reporting.helpers import format_report_date, format_report_datetime


def compute_daily_dqa_stats(
    *,
    study_id: str,
    study_name: str,
    study_start_date: str | None,
    tz_name: str,
    date_key: str,
    day_n: int | None,
    organization_name: str | None,
    projects: list[Any],
    targets: dict[str, Any],
    all_subs: list[Any],
    all_flags: list[Any],
    pack_cache: dict[str, dict | None],
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, Any]:
    """Minimal daily stats stub (metadata + cheap totals only)."""
    _ = study_start_date, targets, pack_cache

    today_subs = [
        s
        for s in all_subs
        if s.submitted_at and start_utc <= s.submitted_at <= end_utc
    ]
    today_ids = {s.id for s in today_subs}
    today_flags = [f for f in all_flags if f.submission_id in today_ids]

    last_sync = None
    for project in projects:
        if project.last_sync_at and (last_sync is None or project.last_sync_at > last_sync):
            last_sync = project.last_sync_at

    metadata = project_fields(
        {
            "studyName": study_name,
            "organizationName": organization_name,
            "reportDate": date_key,
            "reportDateDisplay": format_report_date(date_key),
            "dayNumber": day_n,
            "timezone": tz_name,
            "generatedAtDisplay": format_report_datetime(
                datetime.now(timezone.utc), tz_name=tz_name
            ),
            "lastKoboPullDisplay": (
                format_report_datetime(last_sync, tz_name=tz_name, fallback="never")
                if last_sync
                else "never"
            ),
        },
        [
            "studyName",
            "organizationName",
            "reportDate",
            "reportDateDisplay",
            "dayNumber",
            "timezone",
            "generatedAtDisplay",
            "lastKoboPullDisplay",
        ],
    )

    today_flag_counts = scalar_aggregate(
        [{"severity": f.severity} for f in today_flags],
        measures={
            "redToday": count_where(lambda r: r.get("severity") == "red"),
            "amberToday": count_where(lambda r: r.get("severity") == "amber"),
        },
    )
    all_flag_counts = scalar_aggregate(
        [{"severity": f.severity} for f in all_flags],
        measures={
            "redOpen": count_where(lambda r: r.get("severity") == "red"),
            "amberOpen": count_where(lambda r: r.get("severity") == "amber"),
        },
    )
    totals = {
        "newToday": len(today_subs),
        "cumulative": len(all_subs),
        **today_flag_counts,
        **all_flag_counts,
    }

    return {
        "studyId": study_id,
        **metadata,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "lastKoboPullAt": last_sync.isoformat() if last_sync else None,
        "totals": totals,
        # Empty placeholders — former slices moved to Phase 2 tools / final overlay.
        "tools": [],
        "redPriority": [],
        "redGrouped": [],
        "enumerators": [],
        "enumeratorSubmissionDetails": [],
        "enumeratorsAll": [],
        "findingsByTool": [],
        "topRulesToday": [],
        "topRulesAll": [],
        "flagRateByDay": [],
        "signOffChecklist": [],
        "aiHeadline": None,
        "aiCoverageNote": None,
    }
