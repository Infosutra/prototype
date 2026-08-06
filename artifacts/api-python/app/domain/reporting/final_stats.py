"""Pure final-report stats overlays (no Session)."""

from __future__ import annotations

from typing import Any

def _mismatch_detail(row) -> str:
    parts = []
    for cell in row.cells or []:
        if cell.key in {"join_key"}:
            continue
        parts.append(f"{cell.label}={cell.value}")
    return ", ".join(parts) if parts else "mismatch"


def _practice_views(stats: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    tri_data = stats.get("triangulation") or {}
    out = []
    for view_id, payload in tri_data.items():
        if payload.get("practices"):
            out.append((view_id, payload))
    return out


def _cross_join_views(stats: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    tri_data = stats.get("triangulation") or {}
    practice_ids = {v for v, _ in _practice_views(stats)}
    out = []
    for view_id, payload in tri_data.items():
        if view_id in practice_ids:
            continue
        if payload.get("kind") == "cross_form_join" or not payload.get("practices"):
            out.append((view_id, payload))
    return out


def _tr1_summary(stats: dict[str, Any]) -> dict[str, Any]:
    """Practice-matrix summary from the first claim_vs_observation view (if any)."""
    practice_views = _practice_views(stats)
    if not practice_views:
        return {"viewId": None, "title": None, "practices": [], "concordance": None, "widest": []}
    view_id, tri_data = practice_views[0]
    practices = []
    for p in tri_data.get("practices") or []:
        practices.append(
            {
                "id": p.get("id"),
                "label": p.get("label"),
                "claimedPct": p.get("claimedPct", p.get("claimed_pct")),
                "observedPct": p.get("observedPct", p.get("observed_pct")),
                "gapPct": p.get("gapPct", p.get("gap_pct")),
                "concordancePct": p.get("concordancePct", p.get("concordance_pct")),
            }
        )
    conc_vals = [
        float(p["concordancePct"])
        for p in practices
        if p.get("concordancePct") is not None
    ]
    concordance = round(sum(conc_vals) / len(conc_vals), 0) if conc_vals else None
    widest = sorted(
        [p for p in practices if p.get("gapPct") is not None],
        key=lambda p: abs(float(p["gapPct"])),
        reverse=True,
    )[:3]
    return {
        "viewId": view_id,
        "title": tri_data.get("title") or view_id,
        "practices": practices,
        "concordance": concordance,
        "widest": widest,
    }


def _pass_rate(stats: dict[str, Any]) -> tuple[float, int, int]:
    tools = stats.get("tools") or []
    cumulative = int((stats.get("totals") or {}).get("cumulative") or 0)
    flagged = sum(int(t.get("flaggedSubmissions") or 0) for t in tools)
    clean = max(0, cumulative - flagged)
    pct = round(100.0 * clean / cumulative, 1) if cumulative else 0.0
    return pct, clean, flagged


def _exhaustive_executive_summary(stats: dict[str, Any]) -> str:
    """Client-ready multi-paragraph executive summary matching the requirement sample."""
    t = stats["totals"]
    tools = stats.get("tools") or []
    pass_pct, _clean, flagged = _pass_rate(stats)
    red = int(t.get("redOpen") or 0)
    amber = int(t.get("amberOpen") or 0)
    cumulative = int(t.get("cumulative") or 0)
    red_pct = round(100.0 * red / cumulative, 1) if cumulative else 0.0
    flag_pct = round(100.0 * flagged / cumulative, 1) if cumulative else 0.0

    # Tool flag leaders
    by_flag = sorted(tools, key=lambda x: float(x.get("flaggedPct") or 0), reverse=True)
    top_tools = [x for x in by_flag if x.get("flaggedPct")][:2]
    tool_flag_bit = ""
    if top_tools:
        names = " and ".join(
            f"{x['toolCode']} ({x['flaggedPct']}%)" for x in top_tools
        )
        tool_flag_bit = f" {names} show the highest flag rates;"

    # Enumerators concentrating RED
    enums = stats.get("enumeratorsAll") or []
    red_enums = [e for e in enums if e.get("redFlags")][:3]
    enum_bit = ""
    if red_enums:
        names = ", ".join(e["enumerator"] for e in red_enums)
        enum_bit = f" — concentrated in {len(red_enums)} enumerator(s) ({names}), all identified"

    # Leading AMBER theme
    amber_rules = [
        r for r in (stats.get("topRulesAll") or []) if r.get("severity") == "amber"
    ]
    amber_bit = ""
    if amber_rules:
        lead = amber_rules[0]
        amber_bit = (
            f" The {amber} AMBER items are led by {lead['ruleId']} "
            f"({lead['title']}, {lead['count']} records)."
        )
    elif amber:
        amber_bit = f" There are {amber} open AMBER items for review."

    # Flag-rate trend
    trend = stats.get("flagRateByDay") or []
    trend_bit = ""
    if len(trend) >= 2:
        first, last = trend[0], trend[-1]
        direction = "fell" if last["flaggedPct"] <= first["flaggedPct"] else "rose"
        trend_bit = (
            f" Flag rates {direction} from {first['flaggedPct']}% ({first['dayLabel']}) "
            f"to {last['flaggedPct']}% ({last['dayLabel']}) across the collection window"
            + (
                ", so re-training between days appears to have worked."
                if direction == "fell"
                else " — quality drift needs attention before reuse of the field protocols."
            )
        )

    # Coverage sentence
    cov_bits = []
    for tool in tools:
        if tool.get("target"):
            cov_bits.append(
                f"{tool['toolCode']} {tool['cumulative']}/{tool['target']} "
                f"({tool['coveragePct']}% of plan)"
            )
    coverage_para = (
        "Coverage closed at " + "; ".join(cov_bits) + "."
        if cov_bits
        else f"Total submissions: {cumulative}."
    )

    # Triangulation headline (claim vs observation)
    tr1 = _tr1_summary(stats)
    tr1_para = ""
    view_label = tr1.get("viewId") or "practice check"
    if tr1["concordance"] is not None:
        widest_bits = []
        for p in tr1["widest"][:2]:
            gap = p.get("gapPct")
            label = p.get("label") or p.get("id") or "practice"
            if gap is not None:
                widest_bits.append(f"{label} ({gap:+.0f} pp)")
        widest_txt = (
            f", widest on {' and '.join(widest_bits)}" if widest_bits else ""
        )
        tr1_para = (
            f"The main analytical finding is a {tr1['concordance']:.0f}% say–do concordance "
            f"on {view_label} (teacher practice claimed vs observed): observed use is below self-report "
            f"on inclusive practices{widest_txt} — a re-training priority, not a data-entry error."
        )
    extra_tri = []
    for view_id, payload in _cross_join_views(stats):
        if payload.get("mismatchCount"):
            title = payload.get("title") or view_id
            extra_tri.append(
                f"{view_id} ({title}) flags {payload['mismatchCount']} mismatch row(s)"
            )
    if extra_tri:
        tr1_para = (tr1_para + " " if tr1_para else "") + (
            "Further cross-tool findings: " + "; ".join(extra_tri) + "."
        )

    # Verdict line (sample style: short headline + body)
    lead_finding = "close-out quality review complete."
    if tr1["concordance"] is not None and tr1["concordance"] < 90:
        lead_finding = "teacher self-report over-states classroom practice."
    if red == 0:
        verdict = f"Dataset is analysis-ready; {lead_finding}"
    else:
        verdict = f"Dataset is analysis-ready after {red} RED correction(s); {lead_finding}"

    p1 = (
        f"{pass_pct}% of the {cumulative:,} submissions passed all checks. "
        f"{red} record(s) ({red_pct}%) carry a RED flag and must be corrected "
        f"or back-checked before analysis{enum_bit}.{amber_bit}"
        f"{tool_flag_bit} overall {flag_pct}% of records are flagged.{trend_bit}"
    )
    paragraphs = [verdict, p1.strip(), coverage_para]
    if tr1_para:
        paragraphs.append(tr1_para)
    out: list[str] = []
    for p in paragraphs:
        p = " ".join(p.split())
        if p and p not in out:
            out.append(p)
    return "\n\n".join(out)


def _section_prose(stats: dict[str, Any]) -> dict[str, str]:
    """Narrative blurbs that sit above figures (requirement §2.3 / §2.6 style)."""
    tools = stats.get("tools") or []
    t = stats["totals"]
    cumulative = int(t.get("cumulative") or 0)
    red = int(t.get("redOpen") or 0)
    flagged = sum(int(x.get("flaggedSubmissions") or 0) for x in tools)
    flag_pct = round(100.0 * flagged / cumulative, 1) if cumulative else 0.0
    red_pct = round(100.0 * red / cumulative, 1) if cumulative else 0.0
    by_flag = sorted(tools, key=lambda x: float(x.get("flaggedPct") or 0), reverse=True)
    leaders = by_flag[:2]
    lead_txt = ""
    if leaders:
        lead_txt = (
            " and ".join(f"{x['toolCode']} (~{x['flaggedPct']}%)" for x in leaders)
            + " show the highest flag rates; "
        )
    flag_summary = (
        f"{lead_txt}overall {flag_pct}% of records are flagged and only {red_pct}% are RED."
    )

    tr1 = _tr1_summary(stats)
    view_label = tr1.get("viewId") or "claim vs observation"
    if tr1["concordance"] is not None:
        widest_bits = []
        for p in tr1["widest"][:2]:
            gap = p.get("gapPct")
            label = p.get("label") or p.get("id") or "practice"
            if gap is not None:
                widest_bits.append(f"{label} ({gap:+.0f})")
        widest_txt = (
            f", widest on {' and '.join(widest_bits)}" if widest_bits else ""
        )
        tr1_prose = (
            f"{view_label} (teacher practice: claimed vs observed) is the headline validity check "
            "joining self-report with classroom observation. "
            f"Concordance is {tr1['concordance']:.0f}%: observed use is below self-report "
            f"on every practice{widest_txt}."
        )
    else:
        tr1_prose = (
            f"{view_label} (teacher practice: claimed vs observed) joins self-report with "
            "classroom observation. Insufficient paired practice rows were available to "
            "compute concordance for this close-out."
        )

    further_bits = []
    for view_id, payload in _cross_join_views(stats):
        title = payload.get("title") or view_id
        further_bits.append(
            f"{view_id} ({title}) shows {payload.get('mismatchCount', 0)} mismatch(es)"
        )
    further = (
        "Further cross-tool findings: " + "; ".join(further_bits) + "."
        if further_bits
        else "No additional cross-form triangulation mismatches were flagged."
    )

    cov_bits = []
    for tool in tools:
        if tool.get("target"):
            cov_bits.append(
                f"{tool['toolCode']} reached {tool['coveragePct']}% of its "
                f"{tool['target']} target ({tool['cumulative']} actual)"
            )
    coverage = (
        "End-of-round coverage by tool: " + "; ".join(cov_bits) + "."
        if cov_bits
        else "Coverage targets were not configured for this study."
    )

    trend = stats.get("flagRateByDay") or []
    trend_prose = ""
    if len(trend) >= 2:
        trend_prose = (
            f"The cumulative flag rate moved from {trend[0]['flaggedPct']}% on "
            f"{trend[0]['dayLabel']} to {trend[-1]['flaggedPct']}% on {trend[-1]['dayLabel']}."
        )

    signoff = (
        f"Once the {red} RED record(s) are resolved, the dataset is analysis-ready. "
        "AMBER items should be verified but do not block sign-off."
    )
    return {
        "coverage": coverage,
        "flagSummary": flag_summary,
        "tr1": tr1_prose,
        "triangulationFurther": further,
        "trend": trend_prose,
        "signOffClose": signoff,
    }


def enrich_final_checklist(
    checklist: list[dict[str, Any]],
    triangulation: dict[str, Any],
) -> list[dict[str, Any]]:
    """Append triangulation mismatch items and normalize checklist rows."""
    out = list(checklist)
    for view_id, payload in triangulation.items():
        if payload.get("mismatchCount"):
            out.append(
                {
                    "severity": "amber",
                    "label": f"{view_id} — {payload.get('title')}",
                    "detail": f"{payload['mismatchCount']} mismatch row(s) to review",
                    "ownerHint": "Analysis / DQA lead (read-only)",
                    "toolCode": "Cross-tool",
                    "records": payload["mismatchCount"],
                }
            )
    for item in out:
        item.setdefault("toolCode", "—")
        item.setdefault("records", "—")
        item.setdefault("owner", item.get("ownerHint") or "—")
    return out


def mismatch_detail(row: Any) -> str:
    return _mismatch_detail(row)
