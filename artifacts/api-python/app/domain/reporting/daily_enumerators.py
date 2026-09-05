"""Enumerator watchlist / performance aggregation for daily stats (pure)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from app.domain.reporting.aggregate import (
    aggregate,
    collect_list,
    collect_set,
    count,
    sum_,
)
from app.domain.reporting.domain_rules import apply_enumerator_performance_study
from app.domain.reporting.helpers import duration_minutes, median


def build_enumerators_today(
    *,
    today_subs: list[Any],
    today_flags: list[Any],
    project_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    """Enumerator watchlist for today (Daily §1.3)."""
    enum_bucket: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"submissions": 0, "red": 0, "amber": 0, "tools": set()}
    )
    flags_by_sub: dict[str, list[Any]] = defaultdict(list)
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
    today_durations: dict[str, list[float]] = defaultdict(list)
    for sub in today_subs:
        name = (sub.enumerator or "Unknown").strip() or "Unknown"
        minutes = duration_minutes(sub)
        if minutes is not None:
            today_durations[name].append(minutes)
    for row in enumerators:
        med = median(today_durations.get(row["enumerator"], []))
        row["medianMinutes"] = med
        why_bits = []
        if row["redFlags"]:
            why_bits.append(f"RED ×{row['redFlags']}")
        if row["amberFlags"]:
            why_bits.append(f"AMBER ×{row['amberFlags']}")
        row["whyFlagged"] = "; ".join(why_bits) if why_bits else "—"
        row["medianTimeLabel"] = f"{med:g} min" if med is not None else "—"
    enumerators.sort(key=lambda r: (-r["redFlags"], -r["amberFlags"], -r["submissionsToday"]))
    return enumerators[:20]


def build_enumerators_all(
    *,
    all_subs: list[Any],
    all_flags: list[Any],
    project_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    """Cumulative enumerator performance (Final §2.5).

    Aggregation is generic; (below) / action thresholds / top-25 live in
    ``apply_enumerator_performance_study``.
    """
    flags_by_sub_all: dict[str, list[Any]] = defaultdict(list)
    for flag in all_flags:
        flags_by_sub_all[flag.submission_id].append(flag)

    flat: list[dict[str, Any]] = []
    for sub in all_subs:
        name = (sub.enumerator or "Unknown").strip() or "Unknown"
        project = project_by_id.get(sub.project_id)
        tool = project.tool_code.upper() if project and project.tool_code else None
        minutes = duration_minutes(sub)
        sub_flags = flags_by_sub_all.get(sub.id, [])
        red = sum(1 for f in sub_flags if f.severity == "red")
        amber = sum(1 for f in sub_flags if f.severity == "amber")
        flat.append(
            {
                "enumerator": name,
                "tool_code": tool,
                "duration_minutes": minutes,
                "submission_id": sub.id,
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
    return apply_enumerator_performance_study(rows, group_median=group_median)


def _submission_status(flags: list[Any]) -> str:
    if any(getattr(f, "severity", None) == "red" for f in flags):
        return "red"
    if any(getattr(f, "severity", None) == "amber" for f in flags):
        return "amber"
    return "clean"


def _flag_payload(flag: Any) -> dict[str, Any]:
    return {
        "ruleId": flag.rule_id,
        "severity": flag.severity,
        "title": flag.title or "",
        "message": flag.message or "",
    }


def format_submission_problems(flags: list[dict[str, Any]]) -> str:
    """Human-readable problem list for report tables."""
    if not flags:
        return "—"
    parts: list[str] = []
    for flag in flags:
        sev = str(flag.get("severity") or "").upper() or "?"
        rule = flag.get("ruleId") or "—"
        title = (flag.get("title") or "").strip() or "—"
        message = (flag.get("message") or "").strip()
        bit = f"{sev} {rule}: {title}"
        if message:
            bit = f"{bit} — {message}"
        parts.append(bit)
    return "; ".join(parts)


def build_enumerator_submission_details(
    *,
    today_subs: list[Any],
    today_flags: list[Any],
    project_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    """Per-enumerator submission detail for Daily §1.5 (all enumerators today)."""
    flags_by_sub: dict[str, list[Any]] = defaultdict(list)
    for flag in today_flags:
        flags_by_sub[flag.submission_id].append(flag)

    by_enum: dict[str, list[Any]] = defaultdict(list)
    for sub in today_subs:
        name = (sub.enumerator or "Unknown").strip() or "Unknown"
        by_enum[name].append(sub)

    details: list[dict[str, Any]] = []
    for name, subs in by_enum.items():
        ordered = sorted(
            subs,
            key=lambda s: s.submitted_at or datetime.min,
            reverse=True,
        )
        submissions: list[dict[str, Any]] = []
        red_subs = 0
        amber_subs = 0
        for sub in ordered:
            sub_flags = flags_by_sub.get(sub.id, [])
            status = _submission_status(sub_flags)
            if status == "red":
                red_subs += 1
            elif status == "amber":
                amber_subs += 1
            project = project_by_id.get(sub.project_id)
            tool = (project.tool_code if project and project.tool_code else None) or "—"
            uuid_val = getattr(sub, "uuid", None)
            submissions.append(
                {
                    "koboId": str(sub.kobo_id) if sub.kobo_id is not None else "",
                    "uuid": str(uuid_val).strip() if uuid_val else None,
                    "toolCode": tool.upper() if tool != "—" else "—",
                    "projectName": project.name if project else (sub.form_name or sub.project_id),
                    "status": status,
                    "flags": [_flag_payload(f) for f in sorted(
                        sub_flags,
                        key=lambda f: (0 if f.severity == "red" else 1, f.rule_id or ""),
                    )],
                }
            )
        details.append(
            {
                "enumerator": name,
                "submissionsToday": len(submissions),
                "redSubmissions": red_subs,
                "amberSubmissions": amber_subs,
                "submissions": submissions,
            }
        )

    details.sort(
        key=lambda r: (
            -r["redSubmissions"],
            -r["amberSubmissions"],
            -r["submissionsToday"],
            r["enumerator"],
        )
    )
    return details
