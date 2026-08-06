"""Enumerator watchlist / performance aggregation for daily stats (pure)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

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
    """Cumulative enumerator performance (Final §2.5)."""
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
    flags_by_sub_all: dict[str, list[Any]] = defaultdict(list)
    for flag in all_flags:
        flags_by_sub_all[flag.submission_id].append(flag)
    for sub in all_subs:
        name = (sub.enumerator or "Unknown").strip() or "Unknown"
        bucket = enum_all_bucket[name]
        bucket["submissions"] += 1
        project = project_by_id.get(sub.project_id)
        if project and project.tool_code:
            bucket["tools"].add(project.tool_code.upper())
        minutes = duration_minutes(sub)
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
    allmedians = [
        m
        for b in enum_all_bucket.values()
        if (m := median(b["durations"])) is not None
    ]
    groupmedian = median(allmedians) if allmedians else None
    enumerators_all: list[dict[str, Any]] = []
    for name, bucket in enum_all_bucket.items():
        n = bucket["submissions"]
        flag_pct = round(100.0 * len(bucket["flagged_subs"]) / n, 1) if n else 0.0
        med = median(bucket["durations"])
        label = f"{med:g} min" if med is not None else "—"
        if med is not None and groupmedian is not None and med < groupmedian * 0.85:
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
    return enumerators_all[:25]
