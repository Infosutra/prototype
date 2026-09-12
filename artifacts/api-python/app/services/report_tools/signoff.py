"""Shared sign-off checklist composition for the tool layer and final report."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.reporting.aggregate import aggregate, any_, count, first
from app.domain.reporting.daily_trends import build_signoff_checklist
from app.domain.reporting.domain_rules import (
    apply_red_priority_items,
    apply_top_failing_rules,
    build_udise_index,
)
from app.domain.reporting.helpers import udise_for
from app.services.report_tools.context import ReportDataContext


def compose_signoff_checklist(ctx: ReportDataContext) -> list[dict[str, Any]]:
    """Pre-projector checklist rows (same shape ``compute_daily_dqa_stats`` stored).

    Used by the ``signoff_checklist`` tool and by ``build_final_dqa_stats`` before
    ``enrich_final_checklist``. Explicit windows: execution_date then study_to_date.
    """
    today_from, today_to = ctx.window("execution_date")
    cum_from, cum_to = ctx.window("study_to_date")

    today_red = [
        r
        for r in ctx.entity_rows(today_from, today_to, "flag")
        if r.get("severity") == "red"
    ]
    cum_flags = ctx.entity_rows(cum_from, cum_to, "flag")
    cum_red = [r for r in cum_flags if r.get("severity") == "red"]

    red_measures = {
        "title": first("title"),
        "count": count(),
        "exampleEnumerator": first("enumerator"),
        "exampleSubmissionId": first("submissionId"),
    }
    today_groups = aggregate(
        today_red, group_by=["toolCode", "ruleId"], measures=red_measures
    )
    all_groups = aggregate(cum_red, group_by=["toolCode", "ruleId"], measures=red_measures)

    loaded = ctx.report_inputs(cum_from, cum_to)
    udise_index = build_udise_index(loaded["all_subs"], loaded["pack_cache"])
    red_grouped = apply_red_priority_items(
        today_groups,
        all_groups,
        udise_by_submission_id=udise_index,
    )

    top_rules_all = apply_top_failing_rules(
        aggregate(
            cum_flags,
            group_by=["ruleId"],
            measures={
                "title": first("title"),
                "count": count(),
                "has_red": any_(lambda r: r.get("severity") == "red"),
                "severity_first": first("severity"),
            },
        )
    )

    red_priority: list[dict[str, Any]] = []
    if not red_grouped:
        project_by_id = {p.id: p for p in loaded["projects"]}
        today_ids = {
            str(r["submissionId"])
            for r in ctx.entity_rows(today_from, today_to, "submission")
        }
        today_flag_orm = [
            f for f in loaded["all_flags"] if f.submission_id in today_ids
        ]
        red_today = [f for f in today_flag_orm if f.severity == "red"]
        red_open = [f for f in loaded["all_flags"] if f.severity == "red"]
        red_sorted = sorted(
            red_today or red_open,
            key=lambda f: (
                0 if f in red_today else 1,
                f.rule_id,
                f.evaluated_at or datetime.min,
            ),
        )
        subs_by_id = {s.id: s for s in loaded["all_subs"]}
        pack_cache = loaded["pack_cache"]
        seen_rules: set[str] = set()
        for flag in red_sorted:
            key = f"{flag.rule_id}:{flag.project_id}"
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
                    "toolCode": (project.tool_code if project else None) or "—",
                    "enumerator": sub.enumerator if sub else "—",
                    "udise": udise_for(sub, pack) if sub else "—",
                }
            )
            if len(red_priority) >= 15:
                break

    return build_signoff_checklist(
        red_priority=red_priority,
        red_grouped_today=red_grouped,
        top_rules_all=top_rules_all,
    )
