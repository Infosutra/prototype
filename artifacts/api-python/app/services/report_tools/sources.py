"""Semantic report data sources.

Each source speaks business language ("clean submission", "coverage against plan")
and projects a slice of the single authoritative statistics computation. Business
definitions are recorded on the descriptor so the planner, the UI and the docs all
read the same rules.
"""

from __future__ import annotations

from typing import Any

from app.domain.report_spec.catalog import (
    DataField,
    DataSourceDescriptor,
    DataSourceParam,
)
from app.domain.reporting.daily_enumerators import format_submission_problems
from app.services.report_tools.context import ReportDataContext
from app.services.report_tools.registry import register

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
    stats = ctx.stats()
    return {
        "studyName": stats.get("studyName"),
        "organizationName": stats.get("organizationName") or "Infosutra",
        "reportDate": stats.get("reportDate"),
        "reportDateDisplay": stats.get("reportDateDisplay"),
        "dayNumber": stats.get("dayNumber"),
        "timezone": stats.get("timezone"),
        "generatedAtDisplay": stats.get("generatedAtDisplay"),
        "lastKoboPullDisplay": stats.get("lastKoboPullDisplay"),
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
    stats = ctx.stats()
    totals = stats.get("totals") or {}
    tools = stats.get("tools") or []
    new_today = int(totals.get("newToday") or 0)
    cumulative = int(totals.get("cumulative") or 0)
    flagged_today = sum(int(t.get("flaggedSubmissionsToday") or 0) for t in tools)
    flagged_cumulative = sum(int(t.get("flaggedSubmissions") or 0) for t in tools)
    return {
        "newToday": new_today,
        "cumulative": cumulative,
        "redToday": int(totals.get("redToday") or 0),
        "amberToday": int(totals.get("amberToday") or 0),
        "redOpen": int(totals.get("redOpen") or 0),
        "amberOpen": int(totals.get("amberOpen") or 0),
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
    return [
        {name: tool.get(name) for name in _TOOL_FIELDS}
        for tool in (ctx.stats().get("tools") or [])
    ]


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
    stats = ctx.stats()
    rows = stats.get("enumerators") or []
    totals = stats.get("totals") or {}
    tools = stats.get("tools") or []
    flagged_today = sum(int(t.get("flaggedSubmissionsToday") or 0) for t in tools)
    group_flag_rate = _pct(flagged_today, int(totals.get("newToday") or 0))
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
    details = ctx.stats().get("enumeratorSubmissionDetails") or []
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
    business_definition=(
        f"{TODAY_DEFINITION} scope=today counts flags raised on today's submissions; "
        "scope=cumulative counts all flags raised in the study so far."
    ),
    params=[
        DataSourceParam(
            name="scope",
            type="string",
            allowed=["today", "cumulative"],
            default="today",
            description="Whether to count today's flags or all flags to date.",
        )
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
    stats = ctx.stats()
    key = "topRulesAll" if params.get("scope") == "cumulative" else "topRulesToday"
    return [
        {
            "ruleId": rule.get("ruleId"),
            "title": rule.get("title"),
            "severity": rule.get("severity"),
            "count": rule.get("count"),
        }
        for rule in (stats.get(key) or [])
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
    rows = ctx.stats().get("redGrouped") or []
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
    return [
        {
            "date": row.get("date"),
            "dayLabel": row.get("dayLabel"),
            "flaggedPct": row.get("flaggedPct"),
            "submissions": row.get("submissions"),
        }
        for row in (ctx.stats().get("flagRateByDay") or [])
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
    return [
        {
            "severity": row.get("severity"),
            "label": row.get("label"),
            "detail": row.get("detail"),
            "owner": row.get("owner") or row.get("ownerHint"),
            "toolCode": row.get("toolCode"),
            "records": row.get("records"),
        }
        for row in (ctx.stats().get("signOffChecklist") or [])
    ]


# --- enumerator_performance_study -------------------------------------------

ENUMERATOR_PERFORMANCE_STUDY = DataSourceDescriptor(
    id="enumerator_performance_study",
    title="Enumerator performance across the study",
    description=(
        "One row per enumerator for the full study window, ranked for close-out review."
    ),
    kind="table",
    business_definition=(
        f"{CLEAN_DEFINITION} Flag rate and RED volume are cumulative for the study, "
        "not limited to the execution date."
    ),
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
        _f("groupFlagRate", "Study flag %", "percent", "Benchmark: all enumerators in the study."),
    ],
)


@register(ENUMERATOR_PERFORMANCE_STUDY)
def enumerator_performance_study(
    ctx: ReportDataContext, _params: dict[str, Any]
) -> list[dict[str, Any]]:
    stats = ctx.stats()
    rows = stats.get("enumeratorsAll") or []
    totals = stats.get("totals") or {}
    tools = stats.get("tools") or []
    flagged = sum(int(t.get("flaggedSubmissions") or 0) for t in tools)
    group_flag_rate = _pct(flagged, int(totals.get("cumulative") or 0))
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
    description="Per-tool summary of the rules that flagged the most records over the study.",
    kind="table",
    business_definition=(
        "Counts are cumulative. Severity is the rule pack's classification, not a new threshold."
    ),
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
def findings_by_tool(ctx: ReportDataContext, _params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for block in ctx.stats().get("findingsByTool") or []:
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
