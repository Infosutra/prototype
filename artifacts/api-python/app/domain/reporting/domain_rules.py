"""Pure domain post-processors for mixed (C) report stats slices.

Each function takes aggregated rows (no Session/SQL) and applies only the fixed
business rules: severity coercion, thresholds, fallbacks, top-N cuts, narratives.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domain.reporting.helpers import udise_for


def build_udise_index(
    subs: list[Any], pack_cache: Mapping[str, dict | None]
) -> dict[str, str]:
    """Map submission id → UDISE string using the same rules as ``udise_for``."""
    index: dict[str, str] = {}
    for sub in subs:
        pack = pack_cache.get(sub.project_id)
        index[sub.id] = udise_for(sub, pack)
    return index


def apply_top_failing_rules(
    groups: list[dict[str, Any]], *, limit: int = 12
) -> list[dict[str, Any]]:
    """Red-wins severity coercion, then sort by (-count, ruleId) and take ``limit``."""
    out: list[dict[str, Any]] = []
    for group in groups:
        severity = (
            "red"
            if group.get("has_red")
            else group.get("severity_first")
        )
        out.append(
            {
                "ruleId": group.get("ruleId"),
                "title": group.get("title"),
                "severity": severity,
                "count": group.get("count") or 0,
            }
        )
    out.sort(key=lambda r: (-int(r["count"]), str(r.get("ruleId") or "")))
    return out[:limit]


def apply_red_priority_items(
    today_groups: list[dict[str, Any]],
    all_groups: list[dict[str, Any]],
    *,
    udise_by_submission_id: Mapping[str, str],
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Prefer today's red groups; else cumulative. Resolve UDISE; sort; top ``limit``.

    Intermediate ``exampleSubmissionId`` is consumed here and not emitted.
    """
    chosen = today_groups if today_groups else all_groups
    out: list[dict[str, Any]] = []
    for group in chosen:
        sub_id = group.get("exampleSubmissionId")
        udise = "—"
        if sub_id is not None:
            udise = udise_by_submission_id.get(str(sub_id), "—")
        out.append(
            {
                "toolCode": group.get("toolCode"),
                "ruleId": group.get("ruleId"),
                "title": group.get("title"),
                "count": group.get("count") or 0,
                "exampleEnumerator": group.get("exampleEnumerator") or "—",
                "exampleUdise": udise,
            }
        )
    out.sort(key=lambda r: (-int(r["count"]), str(r.get("ruleId") or "")))
    return out[:limit]


def apply_enumerator_performance_study(
    rows: list[dict[str, Any]],
    *,
    group_median: float | None,
    below_ratio: float = 0.85,
    flag_pct_threshold: float = 12.0,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Apply (below) label, action thresholds, then sort and take ``limit``."""
    out: list[dict[str, Any]] = []
    for row in rows:
        med = row.get("medianMinutes")
        label = row.get("medianTimeLabel") or "—"
        if (
            med is not None
            and group_median is not None
            and med < group_median * below_ratio
        ):
            label = f"{med:g} min (below)"
        red = int(row.get("redFlags") or 0)
        flag_pct = float(row.get("flagRate") or 0.0)
        action = "None"
        if red > 0:
            action = "Back-check RED first"
        elif flag_pct >= flag_pct_threshold:
            action = "Verify flagged records"
        out.append(
            {
                "enumerator": row.get("enumerator"),
                "tools": list(row.get("tools") or []),
                "submissions": row.get("submissions"),
                "flagRate": flag_pct,
                "redFlags": red,
                "amberFlags": row.get("amberFlags"),
                "medianMinutes": med,
                "medianTimeLabel": label,
                "action": action,
            }
        )
    out.sort(
        key=lambda r: (
            -int(r.get("redFlags") or 0),
            -float(r.get("flagRate") or 0.0),
            -int(r.get("submissions") or 0),
        )
    )
    return out[:limit]


def apply_findings_by_tool(
    per_tool: list[dict[str, Any]], *, rules_limit: int = 5
) -> list[dict[str, Any]]:
    """Coerce rule severity (red-wins), take top rules, build English summaries."""
    findings: list[dict[str, Any]] = []
    for block in per_tool:
        raw_rules = list(block.get("rules_raw") or [])
        coerced: list[dict[str, Any]] = []
        for rule in raw_rules:
            severity = (
                "red" if rule.get("has_red") else rule.get("severity_first")
            )
            coerced.append(
                {
                    "ruleId": rule.get("ruleId"),
                    "title": rule.get("title"),
                    "severity": severity,
                    "count": rule.get("count") or 0,
                }
            )
        coerced.sort(key=lambda r: (-int(r["count"]), str(r.get("ruleId") or "")))
        top = coerced[:rules_limit]

        narrative_bits: list[str] = []
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

        findings.append(
            {
                "toolCode": block.get("toolCode"),
                "projectName": block.get("projectName"),
                "summary": ". ".join(narrative_bits) + ".",
                "rules": top,
                "redCumulative": block.get("redCumulative") or 0,
                "amberCumulative": block.get("amberCumulative") or 0,
                "flaggedPct": block.get("flaggedPct") or 0.0,
            }
        )
    return findings
