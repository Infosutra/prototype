"""Fallback narrative text for DQA reports."""

from __future__ import annotations

from typing import Any


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


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def fallback_stats_from_resolved_data(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build the daily-subset dict fallbacks read from resolved tool ``data``.

    Phase 3 adapter: keep ``_fallback_*`` prose byte-stable by mapping Phase 2
    tool outputs into the same shape ``compute_daily_dqa_stats`` used to provide.
    Returns ``None`` when ``study_totals`` is missing.
    """
    if not data:
        return None

    totals_src = _first_present(data, "study_totals")
    if not isinstance(totals_src, dict):
        return None

    meta = _first_present(data, "study_metadata")
    meta = meta if isinstance(meta, dict) else {}

    top = _first_present(
        data,
        "top_failing_rules",
        "top_failing_rules?scope=today",
    )
    if top is None:
        top = []
    if not isinstance(top, list):
        return None

    tools = _first_present(data, "tool_coverage")
    if tools is None:
        tools = []
    if not isinstance(tools, list):
        return None

    trend = _first_present(data, "flag_rate_trend")
    if trend is None:
        trend = []
    if not isinstance(trend, list):
        return None

    return {
        "dayNumber": meta.get("dayNumber"),
        "totals": {
            "newToday": totals_src.get("newToday"),
            "redToday": totals_src.get("redToday"),
            "cumulative": totals_src.get("cumulative"),
            "amberToday": totals_src.get("amberToday"),
            "redOpen": totals_src.get("redOpen"),
            "amberOpen": totals_src.get("amberOpen"),
        },
        "topRulesToday": top,
        "tools": tools,
        "flagRateByDay": trend,
    }
