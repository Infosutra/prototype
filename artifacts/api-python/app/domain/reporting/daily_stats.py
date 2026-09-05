"""Pure daily DQA stats computation (no Session)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.domain.reporting.aggregate import any_, aggregate, count, first
from app.domain.reporting.daily_enumerators import (
    build_enumerator_submission_details,
    build_enumerators_all,
    build_enumerators_today,
)
from app.domain.reporting.daily_trends import (
    build_flag_rate_by_day,
    build_signoff_checklist,
)
from app.domain.reporting.domain_rules import (
    apply_findings_by_tool,
    apply_red_priority_items,
    apply_top_failing_rules,
    build_udise_index,
)
from app.domain.reporting.helpers import (
    format_report_date,
    format_report_datetime,
    udise_for,
)


def _flag_rows(flags: list[Any]) -> list[dict[str, Any]]:
    """Flatten DQA flag ORM rows for generic aggregation (encounter order preserved)."""
    return [
        {
            "ruleId": flag.rule_id,
            "title": flag.title,
            "severity": flag.severity,
            "submission_id": flag.submission_id,
            "project_id": flag.project_id,
        }
        for flag in flags
    ]


def _red_flag_rows(
    flags: list[Any],
    *,
    project_by_id: dict[str, Any],
    subs_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for flag in flags:
        if flag.severity != "red":
            continue
        project = project_by_id.get(flag.project_id)
        tool = (project.tool_code if project else None) or "—"
        tool_code = tool.upper() if tool != "—" else "—"
        sub = subs_by_id.get(flag.submission_id)
        rows.append(
            {
                "toolCode": tool_code,
                "ruleId": flag.rule_id,
                "title": flag.title,
                "enumerator": (sub.enumerator or "—") if sub else None,
                "submission_id": flag.submission_id if sub else None,
            }
        )
    return rows


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
    """Aggregate today + cumulative DQA stats from preloaded rows."""
    project_by_id = {p.id: p for p in projects}
    today_subs = [
        s
        for s in all_subs
        if s.submitted_at and start_utc <= s.submitted_at <= end_utc
    ]
    today_ids = {s.id for s in today_subs}
    today_flags = [f for f in all_flags if f.submission_id in today_ids]

    # Per-tool intake
    tools: list[dict[str, Any]] = []
    for project in projects:
        tool = (project.tool_code or "—").upper()
        p_all = [s for s in all_subs if s.project_id == project.id]
        p_today = [s for s in today_subs if s.project_id == project.id]
        p_today_ids = {s.id for s in p_today}
        p_flags = [f for f in all_flags if f.project_id == project.id]
        p_today_flags = [f for f in p_flags if f.submission_id in p_today_ids]
        flagged_today = {f.submission_id for f in p_today_flags}
        flagged_all = {f.submission_id for f in p_flags}
        target = int(targets.get(tool) or targets.get(tool.lower()) or 0)
        cumulative = len(p_all)
        tools.append(
            {
                "toolCode": tool,
                "projectId": project.id,
                "projectName": project.name,
                "target": target,
                "newToday": len(p_today),
                "cumulative": cumulative,
                "remaining": max(0, target - cumulative) if target else None,
                "coveragePct": round(100.0 * cumulative / target, 1) if target else None,
                "redToday": sum(1 for f in p_today_flags if f.severity == "red"),
                "amberToday": sum(1 for f in p_today_flags if f.severity == "amber"),
                "flaggedSubmissionsToday": len(flagged_today),
                "flaggedPctToday": round(100.0 * len(flagged_today) / len(p_today), 1)
                if p_today
                else 0.0,
                "redCumulative": sum(1 for f in p_flags if f.severity == "red"),
                "amberCumulative": sum(1 for f in p_flags if f.severity == "amber"),
                "flaggedSubmissions": len(flagged_all),
                "flaggedPct": round(100.0 * len(flagged_all) / cumulative, 1) if cumulative else 0.0,
            }
        )

    # RED priority examples (sign-off input; not one of the four mixed tool splits)
    red_today = [f for f in today_flags if f.severity == "red"]
    red_open = [f for f in all_flags if f.severity == "red"]
    red_sorted = sorted(
        red_today or red_open,
        key=lambda f: (0 if f in red_today else 1, f.rule_id, f.evaluated_at or datetime.min),
    )
    subs_by_id = {s.id: s for s in all_subs}
    red_priority: list[dict[str, Any]] = []
    seen_rules: set[str] = set()
    for flag in red_sorted:
        key = f"{flag.rule_id}:{flag.project_id}"
        if key in seen_rules and len(red_priority) >= 12:
            continue
        if key in seen_rules:
            continue
        seen_rules.add(key)
        sub = subs_by_id.get(flag.submission_id)
        project = project_by_id.get(flag.project_id)
        pack = pack_cache.get(flag.project_id)
        red_priority.append(
            {
                "ruleId": flag.rule_id,
                "title": flag.title,
                "message": flag.message,
                "toolCode": (project.tool_code if project else None) or "—",
                "projectName": project.name if project else flag.project_id,
                "enumerator": sub.enumerator if sub else "—",
                "udise": udise_for(sub, pack) if sub else "—",
                "koboId": sub.kobo_id if sub else None,
                "submittedAt": sub.submitted_at.isoformat() if sub and sub.submitted_at else None,
                "isToday": flag.submission_id in today_ids,
            }
        )
        if len(red_priority) >= 15:
            break

    enumerators = build_enumerators_today(
        today_subs=today_subs,
        today_flags=today_flags,
        project_by_id=project_by_id,
    )
    enumerator_submission_details = build_enumerator_submission_details(
        today_subs=today_subs,
        today_flags=today_flags,
        project_by_id=project_by_id,
    )
    enumerators_all = build_enumerators_all(
        all_subs=all_subs,
        all_flags=all_flags,
        project_by_id=project_by_id,
    )

    # --- Mixed (C): top failing rules ---------------------------------------
    top_rules = apply_top_failing_rules(
        aggregate(
            _flag_rows(today_flags),
            group_by=["ruleId"],
            measures={
                "title": first("title"),
                "count": count(),
                "has_red": any_(lambda r: r.get("severity") == "red"),
                "severity_first": first("severity"),
            },
        )
    )
    top_rules_all = apply_top_failing_rules(
        aggregate(
            _flag_rows(all_flags),
            group_by=["ruleId"],
            measures={
                "title": first("title"),
                "count": count(),
                "has_red": any_(lambda r: r.get("severity") == "red"),
                "severity_first": first("severity"),
            },
        )
    )

    # --- Mixed (C): red priority items (redGrouped) -------------------------
    udise_index = build_udise_index(all_subs, pack_cache)
    today_red_groups = aggregate(
        _red_flag_rows(today_flags, project_by_id=project_by_id, subs_by_id=subs_by_id),
        group_by=["toolCode", "ruleId"],
        measures={
            "title": first("title"),
            "count": count(),
            "exampleEnumerator": first("enumerator"),
            "exampleSubmissionId": first("submission_id"),
        },
    )
    all_red_groups = aggregate(
        _red_flag_rows(all_flags, project_by_id=project_by_id, subs_by_id=subs_by_id),
        group_by=["toolCode", "ruleId"],
        measures={
            "title": first("title"),
            "count": count(),
            "exampleEnumerator": first("enumerator"),
            "exampleSubmissionId": first("submission_id"),
        },
    )
    red_grouped_today = apply_red_priority_items(
        today_red_groups,
        all_red_groups,
        udise_by_submission_id=udise_index,
    )

    # --- Mixed (C): findings by tool ----------------------------------------
    findings_input: list[dict[str, Any]] = []
    for project in projects:
        tool = (project.tool_code or "—").upper()
        p_flags = [f for f in all_flags if f.project_id == project.id]
        rules_raw = aggregate(
            _flag_rows(p_flags),
            group_by=["ruleId"],
            measures={
                "title": first("title"),
                "count": count(),
                "has_red": any_(lambda r: r.get("severity") == "red"),
                "severity_first": first("severity"),
            },
        )
        tool_row = next((t for t in tools if t["projectId"] == project.id), None)
        findings_input.append(
            {
                "toolCode": tool,
                "projectName": project.name,
                "rules_raw": rules_raw,
                "redCumulative": tool_row["redCumulative"] if tool_row else 0,
                "amberCumulative": tool_row["amberCumulative"] if tool_row else 0,
                "flaggedPct": tool_row["flaggedPct"] if tool_row else 0.0,
            }
        )
    findings_by_tool = apply_findings_by_tool(findings_input)

    flag_rate_by_day = build_flag_rate_by_day(
        study_start_date=study_start_date,
        date_key=date_key,
        tz_name=tz_name,
        all_subs=all_subs,
        all_flags=all_flags,
    )
    checklist = build_signoff_checklist(
        red_priority=red_priority,
        red_grouped_today=red_grouped_today,
        top_rules_all=top_rules_all,
    )

    last_sync = None
    for project in projects:
        if project.last_sync_at and (last_sync is None or project.last_sync_at > last_sync):
            last_sync = project.last_sync_at

    return {
        "studyId": study_id,
        "studyName": study_name,
        "reportDate": date_key,
        "timezone": tz_name,
        "dayNumber": day_n,
        "organizationName": organization_name,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "lastKoboPullAt": last_sync.isoformat() if last_sync else None,
        "lastKoboPullDisplay": format_report_datetime(
            last_sync, tz_name=tz_name, fallback="never"
        )
        if last_sync
        else "never",
        "generatedAtDisplay": format_report_datetime(
            datetime.now(timezone.utc), tz_name=tz_name
        ),
        "reportDateDisplay": format_report_date(date_key),
        "totals": {
            "newToday": len(today_subs),
            "cumulative": len(all_subs),
            "redToday": sum(1 for f in today_flags if f.severity == "red"),
            "amberToday": sum(1 for f in today_flags if f.severity == "amber"),
            "redOpen": sum(1 for f in all_flags if f.severity == "red"),
            "amberOpen": sum(1 for f in all_flags if f.severity == "amber"),
        },
        "tools": tools,
        "redPriority": red_priority,
        "redGrouped": red_grouped_today,
        "enumerators": enumerators,
        "enumeratorSubmissionDetails": enumerator_submission_details,
        "enumeratorsAll": enumerators_all,
        "findingsByTool": findings_by_tool,
        "topRulesToday": top_rules,
        "topRulesAll": top_rules_all,
        "flagRateByDay": flag_rate_by_day,
        "signOffChecklist": checklist,
        "aiHeadline": None,
        "aiCoverageNote": None,
    }
