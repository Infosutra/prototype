"""DQA Daily report: study-scoped aggregation, AI narrative, HTML + PDF."""

from __future__ import annotations

import html
import json
import logging
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models import AppSettings, DqaFlag, Project, Report, ReportProject, ReportSchedule, Study, StudyTool, Submission
from app.integrations.openrouter import OpenRouterError, chat_completion
from app.integrations.smtp import SmtpError, send_email
from app.services.daily_report import day_bounds, parse_send_time
from app.services.dqa_engine import get_pack_for_project, get_value
from app.services import report_charts
from app.services import report_format
from app.services.settings import (
    get_or_create_settings,
    get_smtp_password,
    smtp_config_from_row,
)
from app.services.studies import SIGHTSAVERS_2030_ID, study_day_number

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_REPORTS_DIR = _REPO_ROOT / "data" / "reports"


def reports_dir() -> Path:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return _REPORTS_DIR


def pdf_path_for(report_id: str) -> Path:
    return reports_dir() / f"{report_id}.pdf"


def docx_path_for(report_id: str) -> Path:
    return reports_dir() / f"{report_id}.docx"


def _today_in_tz(tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).date().isoformat()


def _udise_for(sub: Submission, pack: dict[str, Any] | None) -> str:
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


def _parse_meta_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _duration_minutes(sub: Submission) -> float | None:
    data = sub.data if isinstance(sub.data, dict) else {}
    start = _parse_meta_dt(data.get("start"))
    end = _parse_meta_dt(data.get("end"))
    if start is None or end is None:
        return None
    minutes = (end - start).total_seconds() / 60.0
    if minutes < 0 or minutes > 24 * 60:
        return None
    return minutes


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 1)


def build_daily_dqa_stats(
    db: Session,
    study: Study,
    *,
    report_date: str | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    """Aggregate today + cumulative DQA stats for one study. Local DB only."""
    settings = settings or get_or_create_settings(db)
    tz_name = study.timezone or "Asia/Kolkata"
    date_key = report_date or _today_in_tz(tz_name)
    start_utc, end_utc = day_bounds(date_key, tz_name)
    day_n = study_day_number(study, on=date.fromisoformat(date_key))

    projects = list(
        db.scalars(
            select(Project)
            .where(Project.study_id == study.id)
            .order_by(Project.name)
        ).all()
    )
    tools_by_code = {
        (t.code or "").upper(): t
        for t in db.scalars(select(StudyTool).where(StudyTool.study_id == study.id)).all()
    }
    targets = {code: t.target_count for code, t in tools_by_code.items()}
    project_ids = [p.id for p in projects]
    project_by_id = {p.id: p for p in projects}

    all_subs: list[Submission] = []
    today_subs: list[Submission] = []
    if project_ids:
        all_subs = list(
            db.scalars(select(Submission).where(Submission.project_id.in_(project_ids))).all()
        )
        today_subs = [
            s
            for s in all_subs
            if s.submitted_at and start_utc <= s.submitted_at <= end_utc
        ]

    today_ids = {s.id for s in today_subs}
    all_flags: list[DqaFlag] = []
    if project_ids:
        all_flags = list(
            db.scalars(select(DqaFlag).where(DqaFlag.project_id.in_(project_ids))).all()
        )
    today_flags = [f for f in all_flags if f.submission_id in today_ids]

    pack_cache: dict[str, dict | None] = {}
    for pid in project_ids:
        pack_cache[pid] = get_pack_for_project(db, pid)

    # Per-tool intake
    tools: list[dict[str, Any]] = []
    for project in projects:
        tool = (project.tool_code or "—").upper()
        p_all = [s for s in all_subs if s.project_id == project.id]
        p_today = [s for s in today_subs if s.project_id == project.id]
        p_all_ids = {s.id for s in p_all}
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

    # RED priority (today first, then open cumulative REDs)
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
                "udise": _udise_for(sub, pack) if sub else "—",
                "koboId": sub.kobo_id if sub else None,
                "submittedAt": sub.submitted_at.isoformat() if sub and sub.submitted_at else None,
                "isToday": flag.submission_id in today_ids,
            }
        )
        if len(red_priority) >= 15:
            break

    # Enumerator watchlist for today
    enum_bucket: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"submissions": 0, "red": 0, "amber": 0, "tools": set()}
    )
    flags_by_sub: dict[str, list[DqaFlag]] = defaultdict(list)
    for flag in today_flags:
        flags_by_sub[flag.submission_id].append(flag)
    for sub in today_subs:
        name = (sub.enumerator or "Unknown").strip() or "Unknown"
        bucket = enum_bucket[name]
        bucket["submissions"] += 1
        project = project_by_id.get(sub.project_id)
        if project and project.tool_code:
            bucket["tools"].add(project.tool_code.upper())
        for flag in flags_by_sub.get(sub.id, []):
            if flag.severity == "red":
                bucket["red"] += 1
            elif flag.severity == "amber":
                bucket["amber"] += 1
    enumerators: list[dict[str, Any]] = []
    for name, bucket in enum_bucket.items():
        flagged = bucket["red"] + bucket["amber"]
        enumerators.append(
            {
                "enumerator": name,
                "submissionsToday": bucket["submissions"],
                "redFlags": bucket["red"],
                "amberFlags": bucket["amber"],
                "flagRate": round(100.0 * flagged / max(1, bucket["submissions"]), 1),
                "tools": sorted(bucket["tools"]),
            }
        )
    # Attach median interview duration for today's enumerators
    today_durations: dict[str, list[float]] = defaultdict(list)
    for sub in today_subs:
        name = (sub.enumerator or "Unknown").strip() or "Unknown"
        minutes = _duration_minutes(sub)
        if minutes is not None:
            today_durations[name].append(minutes)
    for row in enumerators:
        med = _median(today_durations.get(row["enumerator"], []))
        row["medianMinutes"] = med
        why_bits = []
        if row["redFlags"]:
            why_bits.append(f"RED ×{row['redFlags']}")
        if row["amberFlags"]:
            why_bits.append(f"AMBER ×{row['amberFlags']}")
        row["whyFlagged"] = "; ".join(why_bits) if why_bits else "—"
        if med is not None:
            row["medianTimeLabel"] = f"{med:g} min"
        else:
            row["medianTimeLabel"] = "—"
    enumerators.sort(key=lambda r: (-r["redFlags"], -r["amberFlags"], -r["submissionsToday"]))
    enumerators = enumerators[:20]

    # Cumulative enumerator performance (Final §2.5)
    enum_all_bucket: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "submissions": 0,
            "flagged_subs": set(),
            "red": 0,
            "amber": 0,
            "tools": set(),
            "durations": [],
        }
    )
    flags_by_sub_all: dict[str, list[DqaFlag]] = defaultdict(list)
    for flag in all_flags:
        flags_by_sub_all[flag.submission_id].append(flag)
    for sub in all_subs:
        name = (sub.enumerator or "Unknown").strip() or "Unknown"
        bucket = enum_all_bucket[name]
        bucket["submissions"] += 1
        project = project_by_id.get(sub.project_id)
        if project and project.tool_code:
            bucket["tools"].add(project.tool_code.upper())
        minutes = _duration_minutes(sub)
        if minutes is not None:
            bucket["durations"].append(minutes)
        sub_flags = flags_by_sub_all.get(sub.id, [])
        if sub_flags:
            bucket["flagged_subs"].add(sub.id)
        for flag in sub_flags:
            if flag.severity == "red":
                bucket["red"] += 1
            elif flag.severity == "amber":
                bucket["amber"] += 1
    # Group median for "below" annotation
    all_medians = [
        m
        for b in enum_all_bucket.values()
        if (m := _median(b["durations"])) is not None
    ]
    group_median = _median(all_medians) if all_medians else None
    enumerators_all: list[dict[str, Any]] = []
    for name, bucket in enum_all_bucket.items():
        n = bucket["submissions"]
        flag_pct = round(100.0 * len(bucket["flagged_subs"]) / n, 1) if n else 0.0
        med = _median(bucket["durations"])
        label = f"{med:g} min" if med is not None else "—"
        if med is not None and group_median is not None and med < group_median * 0.85:
            label = f"{med:g} min (below)"
        action = "None"
        if bucket["red"] > 0:
            action = "Back-check RED first"
        elif flag_pct >= 12:
            action = "Verify flagged records"
        enumerators_all.append(
            {
                "enumerator": name,
                "tools": sorted(bucket["tools"]),
                "submissions": n,
                "flagRate": flag_pct,
                "redFlags": bucket["red"],
                "amberFlags": bucket["amber"],
                "medianMinutes": med,
                "medianTimeLabel": label,
                "action": action,
            }
        )
    enumerators_all.sort(key=lambda r: (-r["redFlags"], -r["flagRate"], -r["submissions"]))
    enumerators_all = enumerators_all[:25]

    # Top rules today
    rule_counts: dict[str, dict[str, Any]] = {}
    for flag in today_flags:
        entry = rule_counts.setdefault(
            flag.rule_id,
            {"ruleId": flag.rule_id, "title": flag.title, "severity": flag.severity, "count": 0},
        )
        entry["count"] += 1
        if flag.severity == "red":
            entry["severity"] = "red"
    top_rules = sorted(rule_counts.values(), key=lambda r: (-r["count"], r["ruleId"]))[:12]

    # Cumulative top rules (for Final / summary charts)
    rule_all: dict[str, dict[str, Any]] = {}
    for flag in all_flags:
        entry = rule_all.setdefault(
            flag.rule_id,
            {"ruleId": flag.rule_id, "title": flag.title, "severity": flag.severity, "count": 0},
        )
        entry["count"] += 1
        if flag.severity == "red":
            entry["severity"] = "red"
    top_rules_all = sorted(rule_all.values(), key=lambda r: (-r["count"], r["ruleId"]))[:12]

    # RED items grouped by rule (Daily §1.2 / Final style)
    def _group_red_flags(flags: list[DqaFlag]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for flag in flags:
            if flag.severity != "red":
                continue
            project = project_by_id.get(flag.project_id)
            tool = (project.tool_code if project else None) or "—"
            key = f"{tool}:{flag.rule_id}"
            entry = grouped.setdefault(
                key,
                {
                    "toolCode": tool.upper() if tool != "—" else "—",
                    "ruleId": flag.rule_id,
                    "title": flag.title,
                    "count": 0,
                    "exampleEnumerator": "—",
                    "exampleUdise": "—",
                },
            )
            entry["count"] += 1
            if entry["exampleEnumerator"] == "—":
                sub = subs_by_id.get(flag.submission_id)
                pack = pack_cache.get(flag.project_id)
                if sub:
                    entry["exampleEnumerator"] = sub.enumerator or "—"
                    entry["exampleUdise"] = _udise_for(sub, pack)
        return sorted(grouped.values(), key=lambda r: (-r["count"], r["ruleId"]))[:15]

    red_grouped_today = _group_red_flags(today_flags) or _group_red_flags(all_flags)

    # Findings by tool — top rules per tool (Final §2.4)
    findings_by_tool: list[dict[str, Any]] = []
    for project in projects:
        tool = (project.tool_code or "—").upper()
        p_flags = [f for f in all_flags if f.project_id == project.id]
        by_rule: dict[str, dict[str, Any]] = {}
        for flag in p_flags:
            entry = by_rule.setdefault(
                flag.rule_id,
                {
                    "ruleId": flag.rule_id,
                    "title": flag.title,
                    "severity": flag.severity,
                    "count": 0,
                },
            )
            entry["count"] += 1
            if flag.severity == "red":
                entry["severity"] = "red"
        top = sorted(by_rule.values(), key=lambda r: (-r["count"], r["ruleId"]))[:5]
        tool_row = next((t for t in tools if t["projectId"] == project.id), None)
        narrative_bits = []
        reds = [r for r in top if r["severity"] == "red"]
        ambers = [r for r in top if r["severity"] != "red"]
        if ambers:
            lead = ambers[0]
            narrative_bits.append(
                f"Led by AMBER {lead['ruleId']} ({lead['count']} records)"
            )
        if reds:
            lead = reds[0]
            narrative_bits.append(
                f"RED cluster on {lead['ruleId']} ({lead['count']} records)"
            )
        if not narrative_bits:
            narrative_bits.append("No material DQA flags for this tool.")
        findings_by_tool.append(
            {
                "toolCode": tool,
                "projectName": project.name,
                "summary": ". ".join(narrative_bits) + ".",
                "rules": top,
                "redCumulative": tool_row["redCumulative"] if tool_row else 0,
                "amberCumulative": tool_row["amberCumulative"] if tool_row else 0,
                "flaggedPct": tool_row["flaggedPct"] if tool_row else 0.0,
            }
        )

    # Day-by-day cumulative flag-rate trend (Section 1.4)
    flag_rate_by_day: list[dict[str, Any]] = []
    if study.start_date:
        try:
            start_d = date.fromisoformat(study.start_date)
            end_d = date.fromisoformat(date_key)
            if end_d >= start_d:
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
            flag_rate_by_day = []

    # Read-only sign-off checklist from open RED rules + top AMBER themes
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

    last_sync = None
    for project in projects:
        if project.last_sync_at and (last_sync is None or project.last_sync_at > last_sync):
            last_sync = project.last_sync_at

    return {
        "studyId": study.id,
        "studyName": study.name,
        "reportDate": date_key,
        "timezone": tz_name,
        "dayNumber": day_n,
        "organizationName": settings.organization_name,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "lastKoboPullAt": last_sync.isoformat() if last_sync else None,
        "lastKoboPullDisplay": report_format.format_report_datetime(
            last_sync, tz_name=tz_name, fallback="never"
        )
        if last_sync
        else "never",
        "generatedAtDisplay": report_format.format_report_datetime(
            datetime.now(timezone.utc), tz_name=tz_name
        ),
        "reportDateDisplay": report_format.format_report_date(date_key),
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
        "enumeratorsAll": enumerators_all,
        "findingsByTool": findings_by_tool,
        "topRulesToday": top_rules,
        "topRulesAll": top_rules_all,
        "flagRateByDay": flag_rate_by_day,
        "signOffChecklist": checklist,
        "aiHeadline": None,
        "aiCoverageNote": None,
    }


def generate_ai_narratives(stats: dict[str, Any], settings: AppSettings) -> dict[str, str]:
    """Call OpenRouter with structured stats. Returns headline + coverage note."""
    if not settings.ai_enabled:
        return {
            "aiHeadline": _fallback_headline(stats),
            "aiCoverageNote": _fallback_coverage(stats),
            "aiSource": "fallback",
        }
    api_key = (settings.ai_api_key or "").strip()
    if not api_key:
        return {
            "aiHeadline": _fallback_headline(stats),
            "aiCoverageNote": _fallback_coverage(stats),
            "aiSource": "fallback-no-key",
        }

    compact = {
        "study": stats["studyName"],
        "dayNumber": stats["dayNumber"],
        "reportDate": stats["reportDate"],
        "totals": stats["totals"],
        "tools": [
            {
                "tool": t["toolCode"],
                "newToday": t["newToday"],
                "cumulative": t["cumulative"],
                "target": t["target"],
                "coveragePct": t["coveragePct"],
                "redToday": t["redToday"],
                "amberToday": t["amberToday"],
                "flaggedPctToday": t["flaggedPctToday"],
            }
            for t in stats["tools"]
        ],
        "topRulesToday": stats["topRulesToday"][:8],
        "redGrouped": (stats.get("redGrouped") or [])[:8],
        "enumeratorWatch": stats["enumerators"][:5],
        "flagRateByDay": (stats.get("flagRateByDay") or [])[-5:],
    }
    system = (
        "You are a field data quality analyst for an NGO education baseline study. "
        "Write concise, factual prose for a daily DQA email used to drive same-day back-checks. "
        "No markdown. No speculation beyond the numbers. "
        "Respond with exactly two paragraphs separated by a blank line: "
        "(1) Today's headline — 1–3 sentences naming new submissions, RED count to back-check tomorrow, "
        "and the leading AMBER theme by tool; "
        "(2) Coverage & trend — coverage vs plan (call out any lagging tool), how the cumulative flag rate "
        "has moved across study days, and the concrete action for tomorrow."
    )
    user = (
        "Produce the two paragraphs from this JSON stats payload only:\n"
        + json.dumps(compact, ensure_ascii=False)
    )
    try:
        text = chat_completion(
            api_key=api_key,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=settings.ai_model or "nvidia/nemotron-3-super-120b-a12b:free",
            base_url=settings.ai_base_url or "https://openrouter.ai/api/v1",
            temperature=float(settings.ai_temperature or 0.3),
            max_tokens=int(settings.ai_max_tokens or 2048),
            timeout_seconds=float(settings.ai_timeout_seconds or 60),
        )
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        headline = parts[0] if parts else _fallback_headline(stats)
        coverage = parts[1] if len(parts) > 1 else _fallback_coverage(stats)
        return {"aiHeadline": headline, "aiCoverageNote": coverage, "aiSource": "openrouter"}
    except OpenRouterError:
        logger.exception("OpenRouter narrative failed; using fallback")
        return {
            "aiHeadline": _fallback_headline(stats),
            "aiCoverageNote": _fallback_coverage(stats),
            "aiSource": "fallback-error",
        }


def _fallback_headline(stats: dict[str, Any]) -> str:
    t = stats["totals"]
    day = stats.get("dayNumber")
    day_bit = f"Day {day}: " if day is not None else ""
    lead_amber = next(
        (r for r in (stats.get("topRulesToday") or []) if r.get("severity") == "amber"),
        None,
    )
    amber_bit = ""
    if lead_amber:
        amber_bit = (
            f" AMBER is led by {lead_amber['ruleId']} "
            f"({lead_amber['title']}, {lead_amber['count']} today)."
        )
    return (
        f"{day_bit}{t['newToday']} new submission(s), {t['redToday']} RED to back-check tomorrow."
        f"{amber_bit}"
    )


def _fallback_coverage(stats: dict[str, Any]) -> str:
    bits = []
    lagging = None
    for tool in stats["tools"]:
        if tool["target"]:
            bits.append(
                f"{tool['toolCode']} {tool['cumulative']}/{tool['target']} "
                f"({tool['coveragePct']}%)"
            )
            if tool["coveragePct"] is not None and (
                lagging is None or tool["coveragePct"] < lagging["coveragePct"]
            ):
                lagging = tool
        else:
            bits.append(f"{tool['toolCode']} {tool['cumulative']} cumulative")
    trend = stats.get("flagRateByDay") or []
    trend_bit = ""
    if len(trend) >= 2:
        first, last = trend[0], trend[-1]
        trend_bit = (
            f" Cumulative flag rate moved from {first['flaggedPct']}% ({first['dayLabel']}) "
            f"to {last['flaggedPct']}% ({last['dayLabel']})."
        )
    lag_bit = ""
    if lagging and lagging.get("coveragePct") is not None and lagging["coveragePct"] < 90:
        lag_bit = (
            f" {lagging['toolCode']} lags at {lagging['coveragePct']}% of plan and needs attention."
        )
    action = (
        f" Action for tomorrow: complete the {stats['totals']['redToday']} RED back-check(s) "
        "and verify leading AMBER patterns before the next sync."
    )
    return "Coverage — " + "; ".join(bits) + "." + lag_bit + trend_bit + action


def _daily_chart_pngs(stats: dict[str, Any]) -> dict[str, bytes]:
    """Build chart PNGs for Daily report sections."""
    return {
        "flagsToday": report_charts.chart_today_flags_by_tool(stats.get("tools") or []),
        "coverage": report_charts.chart_coverage_vs_plan(
            stats.get("tools") or [], title="Coverage vs plan (cumulative)"
        ),
        "trend": report_charts.chart_flag_rate_trend(
            stats.get("flagRateByDay") or [],
            title="Cumulative flag rate by study day",
        ),
        "topRules": report_charts.chart_top_failing_rules(
            stats.get("topRulesToday") or [], title="Top failing rules today"
        ),
    }


def render_html(stats: dict[str, Any]) -> str:
    from app.services import report_format as fmt

    org = fmt.esc(stats.get("organizationName") or "Infosutra")
    study = fmt.esc(stats["studyName"])
    day = stats.get("dayNumber")
    day_label = f"Day {day}" if day is not None else "Study day n/a"
    charts = _daily_chart_pngs(stats)
    tot = stats["totals"]

    tool_rows = [
        [
            t["toolCode"],
            fmt.fmt_int(t["newToday"]),
            fmt.fmt_int(t["cumulative"]),
            fmt.fmt_int(t["redToday"]),
            fmt.fmt_int(t["amberToday"]),
            fmt.fmt_pct(t["flaggedPctToday"]),
        ]
        for t in stats["tools"]
    ]
    flagged_today = sum(int(t.get("flaggedSubmissionsToday") or 0) for t in stats["tools"])
    flagged_pct_today = (
        round(100.0 * flagged_today / tot["newToday"], 1) if tot["newToday"] else 0.0
    )
    tool_rows.append(
        [
            "Total",
            fmt.fmt_int(tot["newToday"]),
            fmt.fmt_int(tot["cumulative"]),
            fmt.fmt_int(tot["redToday"]),
            fmt.fmt_int(tot["amberToday"]),
            fmt.fmt_pct(flagged_pct_today),
        ]
    )
    tools_table = fmt.html_table(
        ["Tool", "New today", "Cumulative", "RED today", "AMBER today", "% flagged (today)"],
        tool_rows,
        aligns=["left", "right", "right", "right", "right", "right"],
        total_row=True,
    )

    red_src = stats.get("redGrouped") or []
    red_rows = [
        [
            r["toolCode"],
            r["ruleId"],
            r["title"],
            fmt.fmt_int(r["count"]),
            f"{r['exampleEnumerator']} · UDISE {r['exampleUdise']}",
        ]
        for r in red_src
    ]
    red_table = fmt.html_table(
        ["Tool", "Rule", "Check", "Records", "Example"],
        red_rows,
        aligns=["left", "left", "left", "right", "left"],
    )

    enum_rows = [
        [
            e["enumerator"],
            ", ".join(e["tools"]) or "—",
            fmt.fmt_int(e["submissionsToday"]),
            fmt.fmt_pct(e["flagRate"]),
            e.get("medianTimeLabel") or "—",
            e.get("whyFlagged") or "—",
        ]
        for e in stats["enumerators"][:12]
    ]
    enum_table = fmt.html_table(
        ["Enumerator", "Tool(s)", "Records today", "Flag %", "Median time", "Why flagged"],
        enum_rows,
        aligns=["left", "left", "right", "right", "right", "left"],
    )

    checklist = "".join(
        f"<li><strong>[{fmt.esc(c['severity'].upper())}]</strong> {fmt.esc(c['label'])} — "
        f"{fmt.esc(c['detail'])} <em>({fmt.esc(c['ownerHint'])})</em></li>"
        for c in stats["signOffChecklist"]
    ) or "<li>No open checklist items.</li>"

    coverage_prose = stats.get("aiCoverageNote") or ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>DQA Daily — {study}</title>
<style>{fmt.REPORT_CSS}</style></head><body><div class="wrap">
<p class="brand">{org}</p>
<h1>DQA Daily Report — {study}</h1>
<div class="meta-grid">
<span class="k">Report</span><span>Daily DQA — {fmt.esc(day_label)}</span>
<span class="k">Data window</span><span>{fmt.esc(stats.get('reportDateDisplay') or fmt.format_report_date(stats['reportDate']))} ({fmt.esc(stats['timezone'])})</span>
<span class="k">KoBo pull</span><span>{fmt.esc(stats.get('lastKoboPullDisplay') or fmt.format_report_datetime(stats.get('lastKoboPullAt'), tz_name=stats.get('timezone') or 'Asia/Kolkata', fallback='never'))}</span>
<span class="k">Generated</span><span>{fmt.esc(stats.get('generatedAtDisplay') or fmt.format_report_datetime(stats.get('generatedAt'), tz_name=stats.get('timezone') or 'Asia/Kolkata'))}</span>
<span class="k">Today's intake</span><span>{fmt.fmt_int(tot['newToday'])} new · cumulative {fmt.fmt_int(tot['cumulative'])}</span>
</div>
<div class="ai"><p><strong>Today's headline</strong></p>
{fmt.paragraphs_html(stats.get('aiHeadline') or '')}</div>
<h2>1.1 Today's intake &amp; flags — by tool</h2>
{tools_table}
<p class="prose">Note: today's flag rate is inflated by same-day records not yet back-checked;
the cumulative trend (Section 1.4) is the truer picture.</p>
{fmt.img_tag(charts['flagsToday'], "Today RED and AMBER flags by tool")}
<p class="caption">Figure — Today's RED / AMBER flag counts by tool.</p>
{fmt.img_tag(charts['topRules'], "Top failing rules today")}
<p class="caption">Figure — Top failing rules today (RED in crimson, AMBER in orange).</p>
<h2>1.2 RED items to correct or back-check (priority)</h2>
{red_table}
<h2>1.3 Enumerators to back-check tomorrow</h2>
{enum_table}
<h2>1.4 Coverage &amp; trend</h2>
{fmt.paragraphs_html(coverage_prose)}
{fmt.img_tag(charts['coverage'], "Coverage vs plan")}
<p class="caption">Figure — Cumulative submissions vs study targets by tool.</p>
{fmt.img_tag(charts['trend'], "Flag rate trend")}
<p class="caption">Figure — Cumulative flag rate across study days.</p>
<h2>Sign-off checklist (read-only)</h2>
<ul>{checklist}</ul>
<p class="note">Generated by Infosutra · KoboToolbox is source of truth (read-only sync) ·
This checklist is informational; resolutions are not tracked in-app.</p>
</div></body></html>"""


def render_plaintext(stats: dict[str, Any]) -> str:
    lines = [
        f"DQA Daily — {stats['studyName']}",
        f"Date: {stats['reportDate']}  Day: {stats.get('dayNumber')}",
        "",
        stats.get("aiHeadline") or "",
        stats.get("aiCoverageNote") or "",
        "",
        "Tools:",
    ]
    for t in stats["tools"]:
        lines.append(
            f"  {t['toolCode']}: +{t['newToday']} today, {t['cumulative']}/{t['target'] or '—'} "
            f"RED {t['redToday']} AMBER {t['amberToday']}"
        )
    lines.append("")
    lines.append("RED priority:")
    for r in (stats.get("redGrouped") or stats["redPriority"])[:10]:
        if "count" in r:
            lines.append(
                f"  {r['ruleId']} {r['title']} ×{r['count']} · {r.get('exampleEnumerator')}"
            )
        else:
            lines.append(f"  {r['ruleId']} {r['title']} · {r['enumerator']} · UDISE {r['udise']}")
    return "\n".join(lines)


def render_pdf(stats: dict[str, Any]) -> bytes:
    """Build multi-page PDF with embedded charts and aligned tables."""
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

    from app.services import report_format as fmt

    charts = _daily_chart_pngs(stats)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"DQA Daily — {stats['studyName']}",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "DqaTitle", parent=styles["Heading1"], fontSize=15, spaceAfter=4, textColor=colors.HexColor("#1c1917")
    )
    h2 = ParagraphStyle(
        "DqaH2",
        parent=styles["Heading2"],
        fontSize=11,
        spaceBefore=12,
        spaceAfter=6,
        textColor=colors.HexColor("#134e4a"),
    )
    body = ParagraphStyle("DqaBody", parent=styles["Normal"], fontSize=9, leading=12)
    meta = ParagraphStyle(
        "DqaMeta", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#57534e"), spaceAfter=6
    )
    caption = ParagraphStyle(
        "Cap", parent=styles["Normal"], fontSize=7.5, textColor=colors.HexColor("#78716c"), spaceAfter=8
    )

    def _chart(key: str, width: float = 170 * mm, aspect: float = 0.45) -> list:
        png = charts.get(key)
        if not png:
            return []
        img = Image(BytesIO(png), width=width, height=width * aspect)
        img.hAlign = "CENTER"
        return [img, Spacer(1, 4)]

    def _paras(text: str) -> list:
        out = []
        for part in (text or "").split("\n\n"):
            part = part.strip()
            if part:
                out.append(Paragraph(html.escape(part), body))
                out.append(Spacer(1, 3))
        return out

    story: list[Any] = []
    day = stats.get("dayNumber")
    day_label = f"Day {day}" if day is not None else "Day n/a"
    tot = stats["totals"]
    story.append(Paragraph(html.escape(stats.get("organizationName") or "Infosutra"), meta))
    story.append(Paragraph(f"DQA Daily Report — {html.escape(stats['studyName'])}", title))
    story.append(
        Paragraph(
            f"Report: Daily DQA — {day_label} · "
            f"{html.escape(stats.get('reportDateDisplay') or stats['reportDate'])} "
            f"({html.escape(stats['timezone'])}) · "
            f"KoBo pull {html.escape(stats.get('lastKoboPullDisplay') or 'never')} · "
            f"New {tot['newToday']} · Cumulative {tot['cumulative']}",
            meta,
        )
    )
    story.append(Paragraph("<b>Today's headline</b>", body))
    story.extend(_paras(stats.get("aiHeadline") or ""))

    story.append(Paragraph("1.1 Today's intake &amp; flags — by tool", h2))
    tool_rows = [
        [
            t["toolCode"],
            str(t["newToday"]),
            str(t["cumulative"]),
            str(t["redToday"]),
            str(t["amberToday"]),
            f"{t['flaggedPctToday']}%",
        ]
        for t in stats["tools"]
    ]
    story.append(
        fmt.make_pdf_table(
            ["Tool", "New today", "Cumulative", "RED", "AMBER", "% flagged"],
            tool_rows,
            aligns=["left", "right", "right", "right", "right", "right"],
            col_widths=[55, 55, 60, 45, 50, 55],
        )
    )
    story.append(Spacer(1, 6))
    story.extend(_chart("flagsToday"))
    story.append(Paragraph("Figure — Today's RED / AMBER by tool.", caption))
    story.extend(_chart("topRules", width=150 * mm, aspect=0.55))
    story.append(Paragraph("Figure — Top failing rules today.", caption))

    story.append(Paragraph("1.2 RED items to correct or back-check (priority)", h2))
    red_rows = [
        [
            r["toolCode"],
            r["ruleId"],
            r["title"][:48],
            str(r["count"]),
            f"{r['exampleEnumerator'][:18]} · {r['exampleUdise']}",
        ]
        for r in (stats.get("redGrouped") or [])[:12]
    ]
    story.append(
        fmt.make_pdf_table(
            ["Tool", "Rule", "Check", "Records", "Example"],
            red_rows,
            aligns=["left", "left", "left", "right", "left"],
            col_widths=[35, 45, 145, 45, 110],
            body_style=body,
        )
    )

    story.append(Paragraph("1.3 Enumerators to back-check tomorrow", h2))
    enum_rows = [
        [
            e["enumerator"][:28],
            ", ".join(e["tools"]) or "—",
            str(e["submissionsToday"]),
            f"{e['flagRate']}%",
            e.get("medianTimeLabel") or "—",
            (e.get("whyFlagged") or "—")[:36],
        ]
        for e in stats["enumerators"][:12]
    ]
    story.append(
        fmt.make_pdf_table(
            ["Enumerator", "Tool(s)", "Records", "Flag %", "Median", "Why flagged"],
            enum_rows,
            aligns=["left", "left", "right", "right", "right", "left"],
            col_widths=[95, 45, 45, 40, 55, 100],
            body_style=body,
        )
    )

    story.append(Paragraph("1.4 Coverage &amp; trend", h2))
    story.extend(_paras(stats.get("aiCoverageNote") or ""))
    story.extend(_chart("coverage"))
    story.append(Paragraph("Figure — Cumulative submissions vs study targets.", caption))
    story.extend(_chart("trend"))
    story.append(Paragraph("Figure — Cumulative flag rate by study day.", caption))

    story.append(Paragraph("Sign-off checklist (read-only)", h2))
    for item in stats["signOffChecklist"]:
        story.append(
            Paragraph(
                f"[{html.escape(item['severity'].upper())}] "
                f"<b>{html.escape(item['label'])}</b> — {html.escape(item['detail'])}",
                body,
            )
        )
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "Infosutra · Kobo is source of truth (read-only) · Checklist is informational.",
            meta,
        )
    )
    doc.build(story)
    return buffer.getvalue()


def _set_report_projects(db: Session, report: Report, projects: list[Project]) -> None:
    report.report_projects.clear()
    db.flush()
    for project in projects:
        report.report_projects.append(
            ReportProject(project_id=project.id, project_name=project.name)
        )


def _daily_schedule_for_study(db: Session, study_id: str) -> ReportSchedule | None:
    return db.scalars(
        select(ReportSchedule).where(
            ReportSchedule.study_id == study_id,
            ReportSchedule.report_type == "daily_dqa",
        )
    ).first()


def generate_daily_dqa_report(
    db: Session,
    *,
    study_id: str | None = None,
    report_date: str | None = None,
    run_ai: bool = True,
) -> Report:
    settings = get_or_create_settings(db)
    sid = study_id or SIGHTSAVERS_2030_ID
    study = db.get(Study, sid)
    if not study:
        raise ValueError(f"Study not found: {sid}")

    stats = build_daily_dqa_stats(db, study, report_date=report_date, settings=settings)
    if run_ai:
        narratives = generate_ai_narratives(stats, settings)
        stats["aiHeadline"] = narratives["aiHeadline"]
        stats["aiCoverageNote"] = narratives["aiCoverageNote"]
        stats["aiSource"] = narratives["aiSource"]
    else:
        stats["aiHeadline"] = _fallback_headline(stats)
        stats["aiCoverageNote"] = _fallback_coverage(stats)
        stats["aiSource"] = "skipped"

    html_body = render_html(stats)
    plain = render_plaintext(stats)
    pdf_bytes = render_pdf(stats)
    from app.services import report_docx

    docx_bytes = report_docx.render_daily_docx(stats)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    report_id = str(uuid.uuid4())
    path = pdf_path_for(report_id)
    path.write_bytes(pdf_bytes)
    docx_path_for(report_id).write_bytes(docx_bytes)

    projects = list(db.scalars(select(Project).where(Project.study_id == study.id)).all())
    payload = {
        "stats": stats,
        "html": html_body,
        "plainText": plain,
        "aiSource": stats.get("aiSource"),
    }
    row = Report(
        id=report_id,
        title=f"DQA Daily — {study.name} — {stats['reportDate']}",
        description=f"Day {stats.get('dayNumber')} study DQA daily report",
        status="ready",
        format="pdf",
        report_type="daily_dqa",
        study_id=study.id,
        report_date=stats["reportDate"],
        prompt_id=None,
        prompt_name="DQA Daily",
        generated_content=json.dumps(payload),
        download_url=f"/api/reports/{report_id}/download",
        page_count=max(1, 2 + len(stats["redPriority"]) // 20),
        file_size_kb=round(len(pdf_bytes) / 1024, 1),
        generated_at=now,
        created_at=now,
    )
    db.add(row)
    db.flush()
    _set_report_projects(db, row, projects)
    db.commit()
    db.refresh(row)
    return row


def send_dqa_daily_email(
    db: Session,
    report: Report,
    *,
    recipients: list[str] | None = None,
) -> tuple[Report, list[str]]:
    settings = get_or_create_settings(db)
    if recipients is not None:
        to = list(recipients)
    else:
        schedule = _daily_schedule_for_study(db, report.study_id) if report.study_id else None
        to = list(schedule.recipients or []) if schedule else []
    to = [e.strip() for e in to if e and e.strip()]
    if not to:
        raise SmtpError("No DQA Daily recipients configured")

    password = get_smtp_password(settings)
    if not password:
        raise SmtpError("SMTP password is not configured")

    payload: dict[str, Any] = {}
    if report.generated_content:
        try:
            payload = json.loads(report.generated_content)
        except json.JSONDecodeError:
            payload = {}
    html_body = payload.get("html") or f"<p>{html.escape(report.title)}</p>"
    plain = payload.get("plainText") or report.title
    pdf_file = pdf_path_for(report.id)
    attachments = []
    if pdf_file.is_file():
        attachments.append(
            (f"{report.title.replace(' ', '_')[:80]}.pdf", pdf_file.read_bytes(), "application/pdf")
        )

    send_email(
        smtp_config_from_row(settings, password),
        to=to,
        subject=report.title,
        text=plain,
        html=html_body,
        attachments=attachments,
    )
    return report, to


def send_dqa_daily_now(
    db: Session,
    *,
    study_id: str | None = None,
    report_date: str | None = None,
) -> tuple[Report, list[str]]:
    report = generate_daily_dqa_report(
        db, study_id=study_id, report_date=report_date, run_ai=True
    )
    return send_dqa_daily_email(db, report)


def maybe_send_scheduled_dqa_daily(db: Session) -> bool:
    """Scheduler tick for DQA Daily via ReportSchedule rows."""
    sent_any = False
    schedules = list(
        db.scalars(
            select(ReportSchedule).where(
                ReportSchedule.enabled.is_(True),
                ReportSchedule.report_type == "daily_dqa",
            )
        ).all()
    )
    for schedule in schedules:
        parsed = parse_send_time(schedule.time or "21:30")
        if not parsed:
            continue
        hour, minute = parsed
        tz_name = schedule.timezone or "Asia/Kolkata"
        now_local = datetime.now(ZoneInfo(tz_name))
        if now_local.hour != hour or now_local.minute != minute:
            continue
        date_key = now_local.date().isoformat()
        if schedule.last_sent_on == date_key:
            continue
        try:
            send_dqa_daily_now(db, study_id=schedule.study_id, report_date=date_key)
            schedule.last_sent_on = date_key
            db.commit()
            logger.info("Scheduled DQA Daily sent for study %s on %s", schedule.study_id, date_key)
            sent_any = True
        except Exception:
            logger.exception("Scheduled DQA Daily failed for study %s", schedule.study_id)
    return sent_any
