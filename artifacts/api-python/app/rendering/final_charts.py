"""Final DQA chart PNG builders."""

from __future__ import annotations

from typing import Any

from app.domain.reporting.final_stats import (
    _cross_join_views as cross_join_views,
    _tr1_summary as tr1_summary,
)
from app.rendering import charts as report_charts

def final_chart_pngs(stats: dict[str, Any]) -> dict[str, bytes]:
    tools = stats.get("tools") or []
    totals = stats.get("totals") or {}
    flagged = sum(int(t.get("flaggedSubmissions") or 0) for t in tools)
    overall = {
        "submissions": totals.get("cumulative") or 0,
        "red": totals.get("redOpen") or 0,
        "amber": totals.get("amberOpen") or 0,
        "flagged": flagged,
        "flaggedPct": round(100.0 * flagged / totals["cumulative"], 1)
        if totals.get("cumulative")
        else 0.0,
    }
    tr1 = tr1_summary(stats)
    cross = cross_join_views(stats)
    gov_view = cross[0] if cross else (None, {})
    gov_id, tr_gov = gov_view if gov_view[0] else (None, {})
    row_count = int(tr_gov.get("rowCount") or 0)
    mismatch = int(tr_gov.get("mismatchCount") or 0)
    gov_rows = []
    if row_count:
        gov_rows = (
            [{"schoolGovernanceActive": True, "parentAttendedPta": True, "parentCwdIssues": True}]
            * max(0, row_count - mismatch)
            + [{"schoolGovernanceActive": True, "parentAttendedPta": False, "parentCwdIssues": False}]
            * mismatch
        )

    practice_title = tr1.get("title") or tr1.get("viewId") or "Claimed vs observed"
    gov_title = (tr_gov.get("title") or gov_id or "Cross-form concordance")

    return {
        "flagSummary": report_charts.chart_flag_summary_by_tool(tools, overall=overall),
        "topRules": report_charts.chart_top_failing_rules(
            stats.get("topRulesAll") or stats.get("topRulesToday") or [],
            title="Top failing rules (cumulative)",
        ),
        "coverage": report_charts.chart_coverage_vs_plan(tools, title="Coverage vs plan"),
        "tr1": report_charts.chart_tr1_claimed_vs_observed(
            tr1["practices"],
            concordance_pct=tr1["concordance"],
            title=f"{practice_title} · concordance {int(tr1['concordance'])}%"
            if tr1["concordance"] is not None
            else practice_title,
        ),
        "tr3": report_charts.chart_governance_mismatch(
            gov_rows, title=gov_title
        ),
        "trend": report_charts.chart_flag_rate_trend(
            stats.get("flagRateByDay") or [],
            title="Flag rate trend across the study window",
        ),
    }
