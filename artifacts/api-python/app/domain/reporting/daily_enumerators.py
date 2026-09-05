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
    count_where,
    sum_,
    with_derived_columns,
)
from app.domain.reporting.domain_rules import apply_enumerator_performance_study
from app.domain.reporting.helpers import duration_minutes, median


def build_enumerators_today(
    *,
    today_subs: list[Any],
    today_flags: list[Any],
    project_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    """Enumerator watchlist for today (Daily §1.3) via generic aggregate."""
    flags_by_sub: dict[str, list[Any]] = defaultdict(list)
    for flag in today_flags:
        flags_by_sub[flag.submission_id].append(flag)

    flat: list[dict[str, Any]] = []
    for sub in today_subs:
        name = (sub.enumerator or "Unknown").strip() or "Unknown"
        project = project_by_id.get(sub.project_id)
        tool = project.tool_code.upper() if project and project.tool_code else None
        sub_flags = flags_by_sub.get(sub.id, [])
        red = sum(1 for f in sub_flags if f.severity == "red")
        amber = sum(1 for f in sub_flags if f.severity == "amber")
        flat.append(
            {
                "enumerator": name,
                "tool_code": tool,
                "duration_minutes": duration_minutes(sub),
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
    return rows[:20]


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

    flat: list[dict[str, Any]] = []
    for sub in today_subs:
        name = (sub.enumerator or "Unknown").strip() or "Unknown"
        sub_flags = flags_by_sub.get(sub.id, [])
        project = project_by_id.get(sub.project_id)
        tool = (project.tool_code if project and project.tool_code else None) or "—"
        uuid_val = getattr(sub, "uuid", None)
        base = {
            "enumerator": name,
            "submitted_at": sub.submitted_at,
            "sub_flags": sub_flags,
            "project": project,
            "tool": tool,
            "sub": sub,
            "uuid_val": uuid_val,
        }
        flat.append(base)

    flat = with_derived_columns(
        flat,
        {"status": lambda r: _submission_status(r.get("sub_flags") or [])},
    )

    # Preserve first-seen enumerator order from today_subs, then attach
    # submissions sorted by submitted_at desc (same as the prior hand loop).
    counts = aggregate(
        flat,
        group_by=["enumerator"],
        measures={
            "submissionsToday": count(),
            "redSubmissions": count_where(lambda r: r.get("status") == "red"),
            "amberSubmissions": count_where(lambda r: r.get("status") == "amber"),
        },
    )

    by_enum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in flat:
        by_enum[str(row["enumerator"])].append(row)

    details: list[dict[str, Any]] = []
    for group in counts:
        name = str(group.get("enumerator"))
        ordered = sorted(
            by_enum.get(name) or [],
            key=lambda r: r.get("submitted_at") or datetime.min,
            reverse=True,
        )
        submissions: list[dict[str, Any]] = []
        for row in ordered:
            sub = row["sub"]
            project = row["project"]
            tool = row["tool"]
            sub_flags = row.get("sub_flags") or []
            uuid_val = row.get("uuid_val")
            submissions.append(
                {
                    "koboId": str(sub.kobo_id) if sub.kobo_id is not None else "",
                    "uuid": str(uuid_val).strip() if uuid_val else None,
                    "toolCode": tool.upper() if tool != "—" else "—",
                    "projectName": project.name if project else (sub.form_name or sub.project_id),
                    "status": row["status"],
                    "flags": [
                        _flag_payload(f)
                        for f in sorted(
                            sub_flags,
                            key=lambda f: (0 if f.severity == "red" else 1, f.rule_id or ""),
                        )
                    ],
                }
            )
        details.append(
            {
                "enumerator": name,
                "submissionsToday": int(group.get("submissionsToday") or 0),
                "redSubmissions": int(group.get("redSubmissions") or 0),
                "amberSubmissions": int(group.get("amberSubmissions") or 0),
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
