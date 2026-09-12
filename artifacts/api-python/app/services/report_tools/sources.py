"""Semantic report data sources.

Each source speaks business language ("clean submission", "coverage against plan")
and projects a slice of the single authoritative statistics computation. Business
definitions are recorded on the descriptor so the planner, the UI and the docs all
read the same rules.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.domain.report_spec.catalog import (
    DataField,
    DataSourceDescriptor,
    DataSourceParam,
)
from app.domain.reporting.aggregate import (
    aggregate,
    any_,
    collect_list,
    collect_set,
    count,
    count_distinct,
    count_where,
    first,
    scalar_aggregate,
    sum_,
)
from app.domain.reporting.daily_enumerators import (
    build_enumerator_submission_details,
    format_submission_problems,
)
from app.domain.reporting.daily_trends import build_flag_rate_by_day
from app.domain.reporting.domain_rules import (
    apply_enumerator_performance_study,
    apply_findings_by_tool,
    apply_red_priority_items,
    apply_top_failing_rules,
    build_udise_index,
)
from app.domain.reporting.helpers import format_report_date, format_report_datetime, median
from app.domain.reporting.query_aggregate_catalog import DATE_WINDOW_TOKENS
from app.services.report_tools.context import ReportDataContext
from app.services.report_tools.registry import register
from app.services.studies import study_day_number

# Shared LLM-facing dateWindow param for cumulative certified tools (Phase 4).
# Omit → runtime study_to_date (unchanged from Phase 2 hardcode).
_DATE_WINDOW_PARAM = DataSourceParam(
    name="dateWindow",
    type="string",
    required=False,
    allowed=sorted(DATE_WINDOW_TOKENS),
    description=(
        "Semantic window for the cumulative bag: execution_date | last_7_days | "
        "last_14_days | study_to_date. Omit for study_to_date (certified default)."
    ),
)


def _resolve_cumulative_window(
    ctx: ReportDataContext, params: dict[str, Any] | None
) -> tuple[str | None, str | None]:
    """Honor dateWindow when set; otherwise study_to_date (Phase 2 default)."""
    raw = (params or {}).get("dateWindow")
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return ctx.window("study_to_date")
    return ctx.window(str(raw).strip())


# --- Shared business definitions --------------------------------------------

TODAY_DEFINITION = (
    "'Today' is the calendar day of the execution date in the study timezone "
    "(Study.timezone, default Asia/Kolkata)."
)
CLEAN_DEFINITION = (
    "A submission is clean when it carries no DQA flag. It is RED when it carries at "
    "least one red-severity flag, otherwise AMBER when it carries any amber flag."
)
COVERAGE_DEFINITION = (
    "Coverage compares cumulative submissions against the study-configured target for "
    "the tool (StudyTool.target_count). There is no other authoritative target."
)


def _f(name: str, label: str, type_: str, description: str = "") -> DataField:
    return DataField(name=name, label=label, type=type_, description=description)


def _pct(numerator: float, denominator: float) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


# --- study_metadata ---------------------------------------------------------

STUDY_METADATA = DataSourceDescriptor(
    id="study_metadata",
    title="Study and report metadata",
    description=(
        "Identifying details for the report header: study name, organization, the "
        "reporting day and when the data was last synced from KoboToolbox."
    ),
    kind="object",
    business_definition=(
        f"{TODAY_DEFINITION} The study day number counts from Study.start_date, where "
        "the start date itself is day 1."
    ),
    fields=[
        _f("studyName", "Study", "string"),
        _f("organizationName", "Organization", "string"),
        _f("reportDate", "Report date", "string"),
        _f("reportDateDisplay", "Report date (display)", "string"),
        _f("dayNumber", "Study day", "int"),
        _f("timezone", "Timezone", "string"),
        _f("generatedAtDisplay", "Generated at", "string"),
        _f("lastKoboPullDisplay", "Last Kobo pull", "string"),
    ],
)


@register(STUDY_METADATA)
def study_metadata(ctx: ReportDataContext, _params: dict[str, Any]) -> dict[str, Any]:
    """Report header metadata; report day is explicitly ``execution_date``."""
    study = ctx.study
    tz_name = study.timezone or ctx.context.timezone or "Asia/Kolkata"
    # Explicit window token for the reporting day (no stats collapse).
    date_key, _ = ctx.window("execution_date")
    date_key = date_key or ctx.context.execution_date
    day_n = study_day_number(study, on=date.fromisoformat(date_key))

    # Projects are not date-scoped; load the context bag for last_sync only.
    loaded = ctx.report_inputs(*ctx.window(None))
    last_sync = None
    for project in loaded["projects"]:
        if project.last_sync_at and (last_sync is None or project.last_sync_at > last_sync):
            last_sync = project.last_sync_at

    return {
        "studyName": study.name,
        "organizationName": ctx.settings.organization_name or "Infosutra",
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
    }


# --- study_totals -----------------------------------------------------------

STUDY_TOTALS = DataSourceDescriptor(
    id="study_totals",
    title="Study submission and flag totals",
    description=(
        "Headline counts for the study: submissions received today, cumulative "
        "submissions, and open RED/AMBER data-quality flags."
    ),
    kind="object",
    business_definition=f"{TODAY_DEFINITION} {CLEAN_DEFINITION}",
    fields=[
        _f("newToday", "Submissions today", "int"),
        _f("cumulative", "Submissions to date", "int"),
        _f("redToday", "RED flags today", "int"),
        _f("amberToday", "AMBER flags today", "int"),
        _f("redOpen", "RED flags to date", "int"),
        _f("amberOpen", "AMBER flags to date", "int"),
        _f("flaggedToday", "Flagged submissions today", "int"),
        _f("cleanToday", "Clean submissions today", "int"),
        _f("flaggedPctToday", "% submissions flagged today", "percent"),
        _f("flaggedCumulative", "Flagged submissions to date", "int"),
        _f("cleanCumulative", "Clean submissions to date", "int"),
        _f("flaggedPctCumulative", "% submissions flagged to date", "percent"),
    ],
)


@register(STUDY_TOTALS)
def study_totals(ctx: ReportDataContext, _params: dict[str, Any]) -> dict[str, Any]:
    """Headline counts; dual-window recipe (execution_date + study_to_date)."""
    today_from, today_to = ctx.window("execution_date")
    cum_from, cum_to = ctx.window("study_to_date")

    today_subs = ctx.entity_rows(today_from, today_to, "submission")
    today_flags = ctx.entity_rows(today_from, today_to, "flag")
    cum_subs = ctx.entity_rows(cum_from, cum_to, "submission")
    cum_flags = ctx.entity_rows(cum_from, cum_to, "flag")

    today_flag_counts = scalar_aggregate(
        today_flags,
        measures={
            "redToday": count_where(lambda r: r.get("severity") == "red"),
            "amberToday": count_where(lambda r: r.get("severity") == "amber"),
        },
    )
    all_flag_counts = scalar_aggregate(
        cum_flags,
        measures={
            "redOpen": count_where(lambda r: r.get("severity") == "red"),
            "amberOpen": count_where(lambda r: r.get("severity") == "amber"),
        },
    )
    new_today = len(today_subs)
    cumulative = len(cum_subs)
    flagged_today = len({str(f["submissionId"]) for f in today_flags})
    flagged_cumulative = len({str(f["submissionId"]) for f in cum_flags})
    return {
        "newToday": new_today,
        "cumulative": cumulative,
        "redToday": int(today_flag_counts.get("redToday") or 0),
        "amberToday": int(today_flag_counts.get("amberToday") or 0),
        "redOpen": int(all_flag_counts.get("redOpen") or 0),
        "amberOpen": int(all_flag_counts.get("amberOpen") or 0),
        "flaggedToday": flagged_today,
        "cleanToday": max(0, new_today - flagged_today),
        "flaggedPctToday": _pct(flagged_today, new_today),
        "flaggedCumulative": flagged_cumulative,
        "cleanCumulative": max(0, cumulative - flagged_cumulative),
        "flaggedPctCumulative": _pct(flagged_cumulative, cumulative),
    }


# --- tool_coverage ----------------------------------------------------------

TOOL_COVERAGE = DataSourceDescriptor(
    id="tool_coverage",
    title="Intake and coverage by tool",
    description=(
        "One row per study tool (form): submissions today, cumulative submissions, "
        "progress against the configured target, and flag counts."
    ),
    kind="table",
    business_definition=f"{COVERAGE_DEFINITION} {CLEAN_DEFINITION}",
    benchmark_fields=["target"],
    fields=[
        _f("toolCode", "Tool", "string"),
        _f("projectName", "Form", "string"),
        _f("target", "Target", "int", "Authoritative planned sample for the tool."),
        _f("newToday", "New today", "int"),
        _f("cumulative", "Cumulative", "int"),
        _f("remaining", "Remaining to target", "int"),
        _f("coveragePct", "% of target", "percent"),
        _f("redToday", "RED today", "int"),
        _f("amberToday", "AMBER today", "int"),
        _f("flaggedSubmissionsToday", "Flagged submissions today", "int"),
        _f("flaggedPctToday", "% flagged today", "percent"),
        _f("redCumulative", "RED to date", "int"),
        _f("amberCumulative", "AMBER to date", "int"),
        _f("flaggedSubmissions", "Flagged submissions to date", "int"),
        _f("flaggedPct", "% flagged to date", "percent"),
    ],
)

_TOOL_FIELDS = tuple(f.name for f in TOOL_COVERAGE.fields)


@register(TOOL_COVERAGE)
def tool_coverage(ctx: ReportDataContext, _params: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-tool intake: dual-window recipe (execution_date + study_to_date)."""
    today_from, today_to = ctx.window("execution_date")
    cum_from, cum_to = ctx.window("study_to_date")

    today_subs = ctx.entity_rows(today_from, today_to, "submission")
    today_flags = ctx.entity_rows(today_from, today_to, "flag")
    cum_subs = ctx.entity_rows(cum_from, cum_to, "submission")
    cum_flags = ctx.entity_rows(cum_from, cum_to, "flag")

    loaded = ctx.report_inputs(cum_from, cum_to)
    projects = loaded["projects"]
    targets = loaded["targets"]

    today_sub_by = {
        row["projectId"]: row
        for row in aggregate(
            today_subs,
            group_by=["projectId"],
            measures={"newToday": count()},
        )
    }
    cum_sub_by = {
        row["projectId"]: row
        for row in aggregate(
            cum_subs,
            group_by=["projectId"],
            measures={"cumulative": count()},
        )
    }
    today_flag_by = {
        row["projectId"]: row
        for row in aggregate(
            today_flags,
            group_by=["projectId"],
            measures={
                "redToday": count_where(lambda r: r.get("severity") == "red"),
                "amberToday": count_where(lambda r: r.get("severity") == "amber"),
                "flaggedSubmissionsToday": count_distinct("submissionId"),
            },
        )
    }
    cum_flag_by = {
        row["projectId"]: row
        for row in aggregate(
            cum_flags,
            group_by=["projectId"],
            measures={
                "redCumulative": count_where(lambda r: r.get("severity") == "red"),
                "amberCumulative": count_where(lambda r: r.get("severity") == "amber"),
                "flaggedSubmissions": count_distinct("submissionId"),
            },
        )
    }

    rows: list[dict[str, Any]] = []
    for project in projects:
        tool = (project.tool_code or "—").upper()
        s_today = today_sub_by.get(project.id) or {}
        s_cum = cum_sub_by.get(project.id) or {}
        f_today = today_flag_by.get(project.id) or {}
        f_cum = cum_flag_by.get(project.id) or {}
        target = int(targets.get(tool) or targets.get(tool.lower()) or 0)
        cumulative = int(s_cum.get("cumulative") or 0)
        new_today = int(s_today.get("newToday") or 0)
        flagged_today = int(f_today.get("flaggedSubmissionsToday") or 0)
        flagged_all = int(f_cum.get("flaggedSubmissions") or 0)
        tool_row = {
            "toolCode": tool,
            "projectName": project.name,
            "target": target,
            "newToday": new_today,
            "cumulative": cumulative,
            "remaining": max(0, target - cumulative) if target else None,
            "coveragePct": round(100.0 * cumulative / target, 1) if target else None,
            "redToday": int(f_today.get("redToday") or 0),
            "amberToday": int(f_today.get("amberToday") or 0),
            "flaggedSubmissionsToday": flagged_today,
            "flaggedPctToday": round(100.0 * flagged_today / new_today, 1)
            if new_today
            else 0.0,
            "redCumulative": int(f_cum.get("redCumulative") or 0),
            "amberCumulative": int(f_cum.get("amberCumulative") or 0),
            "flaggedSubmissions": flagged_all,
            "flaggedPct": round(100.0 * flagged_all / cumulative, 1) if cumulative else 0.0,
        }
        rows.append({name: tool_row.get(name) for name in _TOOL_FIELDS})
    return rows


# --- enumerator_performance_today -------------------------------------------

ENUMERATOR_PERFORMANCE_TODAY = DataSourceDescriptor(
    id="enumerator_performance_today",
    title="Enumerator performance today",
    description=(
        "One row per enumerator who submitted today: volume, flag counts, flag rate, "
        "median interview length and why their records were flagged. Includes the "
        "group benchmarks so performance can be compared without inventing a threshold."
    ),
    kind="table",
    execution_day_scoped=True,
    business_definition=(
        f"{TODAY_DEFINITION} {CLEAN_DEFINITION} Flag rate is the share of an "
        "enumerator's submissions today carrying at least one flag. groupFlagRate and "
        "groupMedianMinutes are the study-wide values for the same day and are the only "
        "authoritative benchmarks for 'below expectation'."
    ),
    benchmark_fields=["groupFlagRate", "groupMedianMinutes"],
    fields=[
        _f("enumerator", "Enumerator", "string"),
        _f("tools", "Tool(s)", "string"),
        _f("submissionsToday", "Records today", "int"),
        _f("redFlags", "RED flags", "int"),
        _f("amberFlags", "AMBER flags", "int"),
        _f("flagRate", "Flag %", "percent"),
        _f("medianMinutes", "Median minutes", "float"),
        _f("medianTimeLabel", "Median time", "string"),
        _f("whyFlagged", "Why flagged", "string"),
        _f("groupFlagRate", "Study flag % today", "percent", "Benchmark: all enumerators today."),
        _f("groupMedianMinutes", "Study median minutes", "float", "Benchmark: all enumerators today."),
    ],
)


@register(ENUMERATOR_PERFORMANCE_TODAY)
def enumerator_performance_today(
    ctx: ReportDataContext, _params: dict[str, Any]
) -> list[dict[str, Any]]:
    """Enumerator watchlist for today; window is explicitly ``execution_date``."""
    date_from, date_to = ctx.window("execution_date")
    today_subs = ctx.entity_rows(date_from, date_to, "submission")
    today_flags = ctx.entity_rows(date_from, date_to, "flag")

    flags_by_sub: dict[str, list[dict[str, Any]]] = {}
    for flag in today_flags:
        flags_by_sub.setdefault(str(flag["submissionId"]), []).append(flag)

    flat: list[dict[str, Any]] = []
    for sub in today_subs:
        sub_flags = flags_by_sub.get(str(sub["submissionId"]), [])
        red = sum(1 for f in sub_flags if f.get("severity") == "red")
        amber = sum(1 for f in sub_flags if f.get("severity") == "amber")
        tool = sub.get("toolCode")
        flat.append(
            {
                "enumerator": sub["enumerator"],
                "tool_code": tool if tool and tool != "—" else None,
                "duration_minutes": sub.get("durationMinutes"),
                "red_count": red,
                "amber_count": amber,
            }
        )

    grouped = aggregate(
        flat,
        group_by=["enumerator"],
        measures={
            "submissionsToday": count(),
            "redFlags": sum_("red_count"),
            "amberFlags": sum_("amber_count"),
            "tools": collect_set("tool_code", where=lambda r: r.get("tool_code") is not None),
            "durations": collect_list(
                "duration_minutes", where=lambda r: r.get("duration_minutes") is not None
            ),
        },
    )

    rows: list[dict[str, Any]] = []
    for group in grouped:
        submissions = int(group.get("submissionsToday") or 0)
        red = int(group.get("redFlags") or 0)
        amber = int(group.get("amberFlags") or 0)
        flagged = red + amber
        med = median(group.get("durations") or [])
        why_bits: list[str] = []
        if red:
            why_bits.append(f"RED ×{red}")
        if amber:
            why_bits.append(f"AMBER ×{amber}")
        rows.append(
            {
                "enumerator": group.get("enumerator"),
                "submissionsToday": submissions,
                "redFlags": red,
                "amberFlags": amber,
                "flagRate": round(100.0 * flagged / max(1, submissions), 1),
                "tools": list(group.get("tools") or []),
                "medianMinutes": med,
                "whyFlagged": "; ".join(why_bits) if why_bits else "—",
                "medianTimeLabel": f"{med:g} min" if med is not None else "—",
            }
        )

    rows.sort(
        key=lambda r: (-r["redFlags"], -r["amberFlags"], -r["submissionsToday"])
    )
    rows = rows[:20]

    new_today = len(today_subs)
    flagged_today = len({str(f["submissionId"]) for f in today_flags})
    group_flag_rate = _pct(flagged_today, new_today)
    minutes = [r.get("medianMinutes") for r in rows if r.get("medianMinutes") is not None]
    group_median = round(sum(minutes) / len(minutes), 1) if minutes else None

    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "enumerator": row.get("enumerator"),
                "tools": ", ".join(row.get("tools") or []) or "—",
                "submissionsToday": row.get("submissionsToday"),
                "redFlags": row.get("redFlags"),
                "amberFlags": row.get("amberFlags"),
                "flagRate": row.get("flagRate"),
                "medianMinutes": row.get("medianMinutes"),
                "medianTimeLabel": row.get("medianTimeLabel") or "—",
                "whyFlagged": row.get("whyFlagged") or "—",
                "groupFlagRate": group_flag_rate,
                "groupMedianMinutes": group_median,
            }
        )
    return out


# --- enumerator_submission_quality ------------------------------------------

ENUMERATOR_SUBMISSION_QUALITY = DataSourceDescriptor(
    id="enumerator_submission_quality",
    title="Submission quality by enumerator",
    description=(
        "One row per enumerator submitting today with clean versus flagged counts and "
        "the exact DQA issues raised against their records."
    ),
    kind="table",
    execution_day_scoped=True,
    business_definition=f"{TODAY_DEFINITION} {CLEAN_DEFINITION}",
    fields=[
        _f("enumerator", "Enumerator", "string"),
        _f("submissionsToday", "Forms submitted", "int"),
        _f("cleanSubmissions", "Clean forms", "int"),
        _f("flaggedSubmissions", "Flagged forms", "int"),
        _f("redSubmissions", "RED forms", "int"),
        _f("amberSubmissions", "AMBER forms", "int"),
        _f("issues", "DQA issues", "string"),
    ],
)

_MAX_ISSUE_CHARS = 600


@register(ENUMERATOR_SUBMISSION_QUALITY)
def enumerator_submission_quality(
    ctx: ReportDataContext, _params: dict[str, Any]
) -> list[dict[str, Any]]:
    """Submission quality today; window is explicitly ``execution_date``."""
    date_from, date_to = ctx.window("execution_date")
    # Warm shared entity-row memo; detail builder still needs ORM flag payloads.
    _ = ctx.entity_rows(date_from, date_to, "submission")
    _ = ctx.entity_rows(date_from, date_to, "flag")
    loaded = ctx.report_inputs(date_from, date_to)
    details = build_enumerator_submission_details(
        today_subs=loaded["all_subs"],
        today_flags=loaded["all_flags"],
        project_by_id={p.id: p for p in loaded["projects"]},
    )
    rows: list[dict[str, Any]] = []
    for entry in details:
        total = int(entry.get("submissionsToday") or 0)
        red = int(entry.get("redSubmissions") or 0)
        amber = int(entry.get("amberSubmissions") or 0)
        seen: list[str] = []
        for sub in entry.get("submissions") or []:
            problems = format_submission_problems(sub.get("flags") or [])
            if problems and problems != "—" and problems not in seen:
                seen.append(problems)
        issues = "; ".join(seen) or "—"
        if len(issues) > _MAX_ISSUE_CHARS:
            issues = issues[: _MAX_ISSUE_CHARS - 1].rstrip() + "…"
        rows.append(
            {
                "enumerator": entry.get("enumerator") or "Unknown",
                "submissionsToday": total,
                "cleanSubmissions": max(0, total - red - amber),
                "flaggedSubmissions": red + amber,
                "redSubmissions": red,
                "amberSubmissions": amber,
                "issues": issues,
            }
        )
    return rows


# --- top_failing_rules ------------------------------------------------------

TOP_FAILING_RULES = DataSourceDescriptor(
    id="top_failing_rules",
    title="Most frequently failing DQA rules",
    description="DQA rules ordered by how many records they flagged.",
    kind="table",
    supports_date_window=True,
    business_definition=(
        f"{TODAY_DEFINITION} scope=today counts flags raised on today's submissions; "
        "scope=cumulative counts flags over the selected window (default: study to date). "
        "dateWindow is valid only with scope=cumulative."
    ),
    params=[
        DataSourceParam(
            name="scope",
            type="string",
            allowed=["today", "cumulative"],
            default="today",
            description="Whether to count today's flags or flags in the cumulative window.",
        ),
        _DATE_WINDOW_PARAM,
    ],
    fields=[
        _f("ruleId", "Rule", "string"),
        _f("title", "Check", "string"),
        _f("severity", "Severity", "string"),
        _f("count", "Records", "int"),
    ],
)


@register(TOP_FAILING_RULES)
def top_failing_rules(ctx: ReportDataContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Top failing rules; scope=today → execution_date; cumulative → dateWindow/study_to_date."""
    if params.get("scope") == "cumulative":
        date_from, date_to = _resolve_cumulative_window(ctx, params)
    else:
        date_from, date_to = ctx.window("execution_date")

    flag_rows = ctx.entity_rows(date_from, date_to, "flag")
    groups = aggregate(
        flag_rows,
        group_by=["ruleId"],
        measures={
            "title": first("title"),
            "count": count(),
            "has_red": any_(lambda r: r.get("severity") == "red"),
            "severity_first": first("severity"),
        },
    )
    return [
        {
            "ruleId": rule.get("ruleId"),
            "title": rule.get("title"),
            "severity": rule.get("severity"),
            "count": rule.get("count"),
        }
        for rule in apply_top_failing_rules(groups)
    ]


# --- red_priority_items -----------------------------------------------------

RED_PRIORITY_ITEMS = DataSourceDescriptor(
    id="red_priority_items",
    title="RED items to correct or back-check",
    description=(
        "RED findings grouped by tool and rule, with a worked example so field teams "
        "can locate the records in KoboToolbox."
    ),
    kind="table",
    business_definition=(
        "RED flags are must-fix data quality failures as defined by the study's DQA "
        "rule pack. Rows are grouped by tool and rule."
    ),
    fields=[
        _f("toolCode", "Tool", "string"),
        _f("ruleId", "Rule", "string"),
        _f("title", "Check", "string"),
        _f("count", "Records", "int"),
        _f("exampleEnumerator", "Example enumerator", "string"),
        _f("exampleUdise", "Example UDISE", "string"),
        _f("example", "Example", "string"),
    ],
)


@register(RED_PRIORITY_ITEMS)
def red_priority_items(ctx: ReportDataContext, _params: dict[str, Any]) -> list[dict[str, Any]]:
    """RED groups: try ``execution_date`` first, fall back to ``study_to_date``."""
    today_from, today_to = ctx.window("execution_date")
    cum_from, cum_to = ctx.window("study_to_date")

    today_red = [
        r
        for r in ctx.entity_rows(today_from, today_to, "flag")
        if r.get("severity") == "red"
    ]
    cum_red = [
        r
        for r in ctx.entity_rows(cum_from, cum_to, "flag")
        if r.get("severity") == "red"
    ]

    measures = {
        "title": first("title"),
        "count": count(),
        "exampleEnumerator": first("enumerator"),
        "exampleSubmissionId": first("submissionId"),
    }
    today_groups = aggregate(today_red, group_by=["toolCode", "ruleId"], measures=measures)
    all_groups = aggregate(cum_red, group_by=["toolCode", "ruleId"], measures=measures)

    loaded = ctx.report_inputs(cum_from, cum_to)
    udise_index = build_udise_index(loaded["all_subs"], loaded["pack_cache"])
    rows = apply_red_priority_items(
        today_groups,
        all_groups,
        udise_by_submission_id=udise_index,
    )
    return [
        {
            "toolCode": row.get("toolCode"),
            "ruleId": row.get("ruleId"),
            "title": row.get("title"),
            "count": row.get("count"),
            "exampleEnumerator": row.get("exampleEnumerator"),
            "exampleUdise": row.get("exampleUdise"),
            "example": f"{row.get('exampleEnumerator')} · UDISE {row.get('exampleUdise')}",
        }
        for row in rows
    ]


# --- flag_rate_trend --------------------------------------------------------

FLAG_RATE_TREND = DataSourceDescriptor(
    id="flag_rate_trend",
    title="Flag rate by study day",
    description="Cumulative share of submissions carrying at least one flag, by study day.",
    kind="table",
    business_definition=(
        "flaggedPct is cumulative through that study day, not the rate for that day "
        "alone, so the series is not distorted by low-volume days."
    ),
    fields=[
        _f("date", "Date", "string"),
        _f("dayLabel", "Study day", "string"),
        _f("flaggedPct", "% flagged (cumulative)", "percent"),
        _f("submissions", "Submissions", "int"),
    ],
)


@register(FLAG_RATE_TREND)
def flag_rate_trend(ctx: ReportDataContext, _params: dict[str, Any]) -> list[dict[str, Any]]:
    """Cumulative flag-rate series; window is explicitly ``study_to_date``."""
    date_from, date_to = ctx.window("study_to_date")
    _ = ctx.entity_rows(date_from, date_to, "submission")
    _ = ctx.entity_rows(date_from, date_to, "flag")
    loaded = ctx.report_inputs(date_from, date_to)
    tz_name = ctx.study.timezone or ctx.context.timezone or "Asia/Kolkata"
    series = build_flag_rate_by_day(
        study_start_date=ctx.study.start_date,
        date_key=ctx.context.execution_date,
        tz_name=tz_name,
        all_subs=loaded["all_subs"],
        all_flags=loaded["all_flags"],
    )
    return [
        {
            "date": row.get("date"),
            "dayLabel": row.get("dayLabel"),
            "flaggedPct": row.get("flaggedPct"),
            "submissions": row.get("submissions"),
        }
        for row in series
    ]


# --- signoff_checklist ------------------------------------------------------

SIGNOFF_CHECKLIST = DataSourceDescriptor(
    id="signoff_checklist",
    title="Data quality sign-off checklist",
    description="Open RED and AMBER items a reviewer should resolve before sign-off.",
    kind="table",
    business_definition=(
        "Informational only: the application does not track resolution state for "
        "checklist items."
    ),
    fields=[
        _f("severity", "Severity", "string"),
        _f("label", "Item", "string"),
        _f("detail", "Detail", "string"),
        _f("owner", "Owner", "string"),
        _f("toolCode", "Tool", "string"),
        _f("records", "Records", "int"),
    ],
)


@register(SIGNOFF_CHECKLIST)
def signoff_checklist(ctx: ReportDataContext, _params: dict[str, Any]) -> list[dict[str, Any]]:
    """Compose from red-priority + cumulative top rules (explicit windows)."""
    from app.services.report_tools.signoff import compose_signoff_checklist

    checklist = compose_signoff_checklist(ctx)
    return [
        {
            "severity": row.get("severity"),
            "label": row.get("label"),
            "detail": row.get("detail"),
            "owner": row.get("owner") or row.get("ownerHint"),
            "toolCode": row.get("toolCode"),
            "records": row.get("records"),
        }
        for row in checklist
    ]


# --- enumerator_performance_study -------------------------------------------

ENUMERATOR_PERFORMANCE_STUDY = DataSourceDescriptor(
    id="enumerator_performance_study",
    title="Enumerator performance across the study",
    description=(
        "One row per enumerator for the selected cumulative window (default: study to date), "
        "ranked for close-out review."
    ),
    kind="table",
    supports_date_window=True,
    business_definition=(
        f"{CLEAN_DEFINITION} Flag rate and RED volume are over the selected window "
        "(default: study to date), not limited to the execution date alone."
    ),
    params=[_DATE_WINDOW_PARAM],
    benchmark_fields=["groupFlagRate"],
    fields=[
        _f("enumerator", "Enumerator", "string"),
        _f("tools", "Tool(s)", "string"),
        _f("submissions", "Records", "int"),
        _f("redFlags", "RED flags", "int"),
        _f("amberFlags", "AMBER flags", "int"),
        _f("flagRate", "Flag %", "percent"),
        _f("medianTimeLabel", "Median time", "string"),
        _f("action", "Action", "string"),
        _f(
            "groupFlagRate",
            "Window flag %",
            "percent",
            "Benchmark: all enumerators in the selected window.",
        ),
    ],
)


@register(ENUMERATOR_PERFORMANCE_STUDY)
def enumerator_performance_study(
    ctx: ReportDataContext, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """Cumulative enumerator performance; dateWindow or study_to_date default."""
    date_from, date_to = _resolve_cumulative_window(ctx, params)
    all_subs = ctx.entity_rows(date_from, date_to, "submission")
    all_flags = ctx.entity_rows(date_from, date_to, "flag")

    flags_by_sub: dict[str, list[dict[str, Any]]] = {}
    for flag in all_flags:
        flags_by_sub.setdefault(str(flag["submissionId"]), []).append(flag)

    flat: list[dict[str, Any]] = []
    for sub in all_subs:
        sub_flags = flags_by_sub.get(str(sub["submissionId"]), [])
        red = sum(1 for f in sub_flags if f.get("severity") == "red")
        amber = sum(1 for f in sub_flags if f.get("severity") == "amber")
        tool = sub.get("toolCode")
        flat.append(
            {
                "enumerator": sub["enumerator"],
                "tool_code": tool if tool and tool != "—" else None,
                "duration_minutes": sub.get("durationMinutes"),
                "submission_id": sub["submissionId"],
                "red_count": red,
                "amber_count": amber,
                "is_flagged": bool(sub_flags),
            }
        )

    grouped = aggregate(
        flat,
        group_by=["enumerator"],
        measures={
            "submissions": count(),
            "redFlags": sum_("red_count"),
            "amberFlags": sum_("amber_count"),
            "flagged_subs": collect_set(
                "submission_id", where=lambda r: bool(r.get("is_flagged"))
            ),
            "tools": collect_set("tool_code", where=lambda r: r.get("tool_code") is not None),
            "durations": collect_list(
                "duration_minutes", where=lambda r: r.get("duration_minutes") is not None
            ),
        },
    )

    rows: list[dict[str, Any]] = []
    medians_for_group: list[float] = []
    for group in grouped:
        n = int(group.get("submissions") or 0)
        flagged = group.get("flagged_subs") or []
        flag_pct = round(100.0 * len(flagged) / n, 1) if n else 0.0
        med = median(group.get("durations") or [])
        if med is not None:
            medians_for_group.append(med)
        label = f"{med:g} min" if med is not None else "—"
        rows.append(
            {
                "enumerator": group.get("enumerator"),
                "tools": list(group.get("tools") or []),
                "submissions": n,
                "flagRate": flag_pct,
                "redFlags": int(group.get("redFlags") or 0),
                "amberFlags": int(group.get("amberFlags") or 0),
                "medianMinutes": med,
                "medianTimeLabel": label,
            }
        )

    group_median = median(medians_for_group) if medians_for_group else None
    rows = apply_enumerator_performance_study(rows, group_median=group_median)

    flagged_total = len({str(f["submissionId"]) for f in all_flags})
    group_flag_rate = _pct(flagged_total, len(all_subs))
    return [
        {
            "enumerator": row.get("enumerator"),
            "tools": ", ".join(row.get("tools") or [])
            if isinstance(row.get("tools"), list)
            else (row.get("tools") or "—"),
            "submissions": row.get("submissions"),
            "redFlags": row.get("redFlags"),
            "amberFlags": row.get("amberFlags"),
            "flagRate": row.get("flagRate"),
            "medianTimeLabel": row.get("medianTimeLabel") or "—",
            "action": row.get("action") or "—",
            "groupFlagRate": group_flag_rate,
        }
        for row in rows
    ]


# --- findings_by_tool -------------------------------------------------------

FINDINGS_BY_TOOL = DataSourceDescriptor(
    id="findings_by_tool",
    title="Data-quality findings by tool",
    description=(
        "Per-tool summary of the rules that flagged the most records over the selected "
        "window (default: study to date)."
    ),
    kind="table",
    supports_date_window=True,
    business_definition=(
        "Counts are over the selected window (default: study to date). Severity is the "
        "rule pack's classification, not a new threshold."
    ),
    params=[_DATE_WINDOW_PARAM],
    fields=[
        _f("toolCode", "Tool", "string"),
        _f("projectName", "Form", "string"),
        _f("summary", "Summary", "string"),
        _f("redCumulative", "RED", "int"),
        _f("amberCumulative", "AMBER", "int"),
        _f("flaggedPct", "% flagged", "percent"),
        _f("topRule", "Leading rule", "string"),
    ],
)


@register(FINDINGS_BY_TOOL)
def findings_by_tool(ctx: ReportDataContext, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-tool findings; dateWindow or study_to_date default."""
    date_from, date_to = _resolve_cumulative_window(ctx, params)
    all_subs = ctx.entity_rows(date_from, date_to, "submission")
    all_flags = ctx.entity_rows(date_from, date_to, "flag")
    loaded = ctx.report_inputs(date_from, date_to)
    projects = loaded["projects"]

    sub_by_project = {
        row["projectId"]: row
        for row in aggregate(
            all_subs,
            group_by=["projectId"],
            measures={"cumulative": count()},
        )
    }
    flag_by_project = {
        row["projectId"]: row
        for row in aggregate(
            all_flags,
            group_by=["projectId"],
            measures={
                "redCumulative": count_where(lambda r: r.get("severity") == "red"),
                "amberCumulative": count_where(lambda r: r.get("severity") == "amber"),
                "flaggedSubmissions": count_distinct("submissionId"),
            },
        )
    }

    findings_input: list[dict[str, Any]] = []
    for project in projects:
        tool = (project.tool_code or "—").upper()
        p_flags = [f for f in all_flags if f.get("projectId") == project.id]
        rules_raw = aggregate(
            p_flags,
            group_by=["ruleId"],
            measures={
                "title": first("title"),
                "count": count(),
                "has_red": any_(lambda r: r.get("severity") == "red"),
                "severity_first": first("severity"),
            },
        )
        srow = sub_by_project.get(project.id) or {}
        frow = flag_by_project.get(project.id) or {}
        cumulative = int(srow.get("cumulative") or 0)
        flagged_all = int(frow.get("flaggedSubmissions") or 0)
        findings_input.append(
            {
                "toolCode": tool,
                "projectName": project.name,
                "rules_raw": rules_raw,
                "redCumulative": int(frow.get("redCumulative") or 0),
                "amberCumulative": int(frow.get("amberCumulative") or 0),
                "flaggedPct": round(100.0 * flagged_all / cumulative, 1) if cumulative else 0.0,
            }
        )

    rows: list[dict[str, Any]] = []
    for block in apply_findings_by_tool(findings_input):
        rules = block.get("rules") or []
        lead = rules[0] if rules else {}
        rows.append(
            {
                "toolCode": block.get("toolCode"),
                "projectName": block.get("projectName"),
                "summary": block.get("summary"),
                "redCumulative": block.get("redCumulative"),
                "amberCumulative": block.get("amberCumulative"),
                "flaggedPct": block.get("flaggedPct"),
                "topRule": (
                    f"{lead.get('ruleId')} ({lead.get('title')})" if lead.get("ruleId") else "—"
                ),
            }
        )
    return rows


# --- triangulation_summary --------------------------------------------------

TRIANGULATION_SUMMARY = DataSourceDescriptor(
    id="triangulation_summary",
    title="Triangulation across tools",
    description="Study-defined triangulation views with mismatch counts and concordance.",
    kind="table",
    business_definition=(
        "Mismatch and concordance come from the study's triangulation view definitions. "
        "No additional agreement threshold is invented here."
    ),
    fields=[
        _f("viewId", "View", "string"),
        _f("title", "Title", "string"),
        _f("kind", "Kind", "string"),
        _f("mismatchCount", "Mismatches", "int"),
        _f("rowCount", "Rows", "int"),
        _f("concordance", "Concordance", "percent"),
    ],
)


@register(TRIANGULATION_SUMMARY)
def triangulation_summary(
    ctx: ReportDataContext, _params: dict[str, Any]
) -> list[dict[str, Any]]:
    triangulation = ctx.stats().get("triangulation") or {}
    rows: list[dict[str, Any]] = []
    if isinstance(triangulation, dict):
        items = triangulation.items()
    else:
        items = []
    for view_id, view in items:
        if not isinstance(view, dict):
            continue
        practices = view.get("practices") or []
        concordances = [
            p.get("concordance")
            for p in practices
            if isinstance(p, dict) and p.get("concordance") is not None
        ]
        concordance = (
            round(sum(concordances) / len(concordances), 1) if concordances else None
        )
        if concordance is None and view.get("concordance") is not None:
            concordance = view.get("concordance")
        rows.append(
            {
                "viewId": view.get("id") or view_id,
                "title": view.get("title") or view_id,
                "kind": view.get("kind") or "—",
                "mismatchCount": view.get("mismatchCount") or 0,
                "rowCount": view.get("rowCount") or 0,
                "concordance": concordance,
            }
        )
    return rows
