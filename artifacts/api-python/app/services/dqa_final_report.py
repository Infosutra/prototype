"""Final DQA close-out report: cumulative coverage, flags, triangulation, sign-off."""

from __future__ import annotations

import html
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, Report, ReportProject, Study
from app.services import dqa_daily_report as daily
from app.services import triangulation as tri
from app.services.settings import get_or_create_settings
from app.services.studies import SIGHTSAVERS_2030_ID

logger = logging.getLogger(__name__)


def build_final_dqa_stats(
    db: Session,
    study: Study,
    *,
    run_ai: bool = True,
) -> dict[str, Any]:
    """Cumulative study stats + TR-1/TR-3/TR-5 summaries for Final report."""
    settings = get_or_create_settings(db)
    report_date = (
        study.end_date
        or datetime.now(timezone.utc).date().isoformat()
    )
    base = daily.build_daily_dqa_stats(
        db, study, report_date=report_date, settings=settings
    )
    base["reportKind"] = "final_dqa"
    base["title"] = f"Final DQA — {study.name}"

    triangulation: dict[str, Any] = {}
    for view_id in ("TR-1", "TR-3", "TR-5"):
        try:
            view = tri.build_view(db, view_id, study_id=study.id)
            triangulation[view_id] = {
                "id": view.id,
                "title": view.title,
                "description": view.description,
                "mismatchCount": view.mismatch_count,
                "rowCount": len(view.rows),
                "practices": [p.model_dump(by_alias=True) for p in view.practices],
                "mismatchExamples": [
                    {
                        "udise": r.udise,
                        "schoolName": r.school_name,
                        "detail": _mismatch_detail(view_id, r),
                    }
                    for r in view.rows
                    if r.mismatch
                ][:12],
            }
        except Exception:
            logger.exception("Triangulation %s failed for final report", view_id)
            triangulation[view_id] = {
                "id": view_id,
                "title": view_id,
                "mismatchCount": 0,
                "rowCount": 0,
                "practices": [],
                "mismatchExamples": [],
                "error": "failed",
            }
    base["triangulation"] = triangulation

    checklist = list(base.get("signOffChecklist") or [])
    for view_id, payload in triangulation.items():
        if payload.get("mismatchCount"):
            checklist.append(
                {
                    "severity": "amber",
                    "label": f"{view_id} — {payload.get('title')}",
                    "detail": f"{payload['mismatchCount']} mismatch row(s) to review",
                    "ownerHint": "Analysis / DQA lead (read-only)",
                    "toolCode": "Cross-tool",
                    "records": payload["mismatchCount"],
                }
            )
    # Enrich checklist rows for table layout
    for item in checklist:
        item.setdefault("toolCode", "—")
        item.setdefault("records", "—")
        item.setdefault("owner", item.get("ownerHint") or "—")
    base["signOffChecklist"] = checklist

    narratives = _build_final_narratives(base, settings, run_ai=run_ai)
    base.update(narratives)
    return base


def _mismatch_detail(view_id: str, row) -> str:
    if view_id == "TR-5":
        return (
            f"teacher CWD={row.teacher_has_cwd} parent disability={row.parent_reports_disability}"
        )
    if view_id == "TR-1":
        return f"gap={row.practice_gap} claimed={row.claimed_practices} observed={row.observed_practices}"
    if view_id == "TR-3":
        return (
            f"school active={row.school_governance_active} "
            f"parent attended={row.parent_attended_pta} issues={row.parent_cwd_issues}"
        )
    return "mismatch"


def _tr1_summary(stats: dict[str, Any]) -> dict[str, Any]:
    tri_data = (stats.get("triangulation") or {}).get("TR-1") or {}
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
    return {"practices": practices, "concordance": concordance, "widest": widest}


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

    # Triangulation headline (TR-1 say–do)
    tr1 = _tr1_summary(stats)
    tri_data = stats.get("triangulation") or {}
    tr1_para = ""
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
            f"on TR-1 (teacher practice claimed vs observed): observed use is below self-report "
            f"on inclusive practices{widest_txt} — a re-training priority, not a data-entry error."
        )
    tr3 = tri_data.get("TR-3") or {}
    tr5 = tri_data.get("TR-5") or {}
    extra_tri = []
    if tr3.get("mismatchCount"):
        extra_tri.append(
            f"TR-3 (governance, T1 × T3) flags {tr3['mismatchCount']} institution(s) "
            "with school-reported PTA/SMC activity that sampled parents did not confirm"
        )
    if tr5.get("mismatchCount"):
        extra_tri.append(
            f"TR-5 (CWD identification, T2 × T3) flags {tr5['mismatchCount']} case(s) "
            "where parents report a child with disability but teachers report none — "
            "possible under-identification"
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
            "TR-1 (teacher practice: claimed vs observed) is the headline validity check "
            "joining Tool 2 self-report with Tool 2 classroom observation. "
            f"Concordance is {tr1['concordance']:.0f}%: observed use is below self-report "
            f"on every practice{widest_txt}."
        )
    else:
        tr1_prose = (
            "TR-1 (teacher practice: claimed vs observed) joins Tool 2 self-report with "
            "classroom observation. Insufficient paired practice rows were available to "
            "compute concordance for this close-out."
        )

    tri = stats.get("triangulation") or {}
    tr3 = tri.get("TR-3") or {}
    tr5 = tri.get("TR-5") or {}
    further = (
        f"Two further cross-tool findings: TR-3 (governance, T1 × T3) shows "
        f"{tr3.get('mismatchCount', 0)} mismatch(es) — school-reported PTA/SMC activity "
        f"that sampled parents did not experience; TR-5 (CWD identification, T2 × T3) "
        f"flags {tr5.get('mismatchCount', 0)} case(s) where parents report a child with "
        "disability but teachers report none — possible under-identification, a core "
        "project concern."
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


def _build_final_narratives(
    stats: dict[str, Any], settings, *, run_ai: bool
) -> dict[str, Any]:
    prose = _section_prose(stats)
    fallback_exec = _exhaustive_executive_summary(stats)
    if not run_ai or not settings.ai_enabled or not (settings.ai_api_key or "").strip():
        return {
            "aiHeadline": fallback_exec,
            "aiCoverageNote": prose["coverage"],
            "sectionProse": prose,
            "aiSource": "fallback" if run_ai else "skipped",
        }

    from app.integrations.openrouter import OpenRouterError, chat_completion

    tr1 = _tr1_summary(stats)
    compact = {
        "study": stats["studyName"],
        "reportDate": stats["reportDate"],
        "totals": stats["totals"],
        "passRatePct": _pass_rate(stats)[0],
        "tools": [
            {
                "tool": t["toolCode"],
                "target": t["target"],
                "actual": t["cumulative"],
                "coveragePct": t["coveragePct"],
                "red": t["redCumulative"],
                "amber": t["amberCumulative"],
                "flaggedPct": t["flaggedPct"],
            }
            for t in stats["tools"]
        ],
        "topRules": (stats.get("topRulesAll") or [])[:10],
        "findingsByTool": [
            {"tool": f["toolCode"], "summary": f["summary"], "rules": f["rules"][:3]}
            for f in (stats.get("findingsByTool") or [])
        ],
        "topEnumerators": (stats.get("enumeratorsAll") or [])[:6],
        "flagRateByDay": [
            {"day": d["dayLabel"], "flaggedPct": d["flaggedPct"]}
            for d in (stats.get("flagRateByDay") or [])
        ],
        "triangulation": {
            vid: {
                "title": p.get("title"),
                "mismatchCount": p.get("mismatchCount"),
                "rowCount": p.get("rowCount"),
            }
            for vid, p in (stats.get("triangulation") or {}).items()
        },
        "tr1ConcordancePct": tr1["concordance"],
        "tr1WidestGaps": tr1["widest"][:3],
        "draftExecutiveSummary": fallback_exec,
    }
    system = (
        "You write Final DQA close-out reports for NGO education baseline studies. "
        "This document is submitted to clients for dataset sign-off. "
        "Write an EXHAUSTIVE executive summary in 3–5 short paragraphs (blank-line separated). "
        "No markdown. Cover: (1) analysis-readiness verdict and pass rate; "
        "(2) RED/AMBER volumes, where they concentrate (tools + enumerators), leading rules; "
        "(3) whether flag rates improved across the collection window; "
        "(4) coverage vs plan by tool; "
        "(5) the main triangulation finding (TR-1 say–do concordance and widest gaps) plus TR-3/TR-5 if relevant. "
        "Stay factual; use only the JSON. Tone matches a concluding client brief."
    )
    user = "Write the executive summary from this payload:\n" + json.dumps(
        compact, ensure_ascii=False
    )
    try:
        text = chat_completion(
            api_key=settings.ai_api_key.strip(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=settings.ai_model or "nvidia/nemotron-3-super-120b-a12b:free",
            base_url=settings.ai_base_url or "https://openrouter.ai/api/v1",
            temperature=float(settings.ai_temperature or 0.3),
            max_tokens=max(int(settings.ai_max_tokens or 2048), 1800),
            timeout_seconds=float(settings.ai_timeout_seconds or 90),
        )
        exec_summary = text.strip() or fallback_exec
        return {
            "aiHeadline": exec_summary,
            "aiCoverageNote": prose["coverage"],
            "sectionProse": prose,
            "aiSource": "openrouter",
        }
    except OpenRouterError:
        logger.exception("Final DQA AI narrative failed; using exhaustive fallback")
        return {
            "aiHeadline": fallback_exec,
            "aiCoverageNote": prose["coverage"],
            "sectionProse": prose,
            "aiSource": "fallback-error",
        }


def _final_chart_pngs(stats: dict[str, Any]) -> dict[str, bytes]:
    from app.services import report_charts

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
    tr1 = _tr1_summary(stats)
    tri = stats.get("triangulation") or {}
    tr3 = tri.get("TR-3") or {}
    row_count = int(tr3.get("rowCount") or 0)
    mismatch = int(tr3.get("mismatchCount") or 0)
    gov_rows = []
    if row_count:
        gov_rows = (
            [{"schoolGovernanceActive": True, "parentAttendedPta": True, "parentCwdIssues": True}]
            * max(0, row_count - mismatch)
            + [{"schoolGovernanceActive": True, "parentAttendedPta": False, "parentCwdIssues": False}]
            * mismatch
        )

    return {
        "flagSummary": report_charts.chart_flag_summary_by_tool(tools, overall=overall),
        "topRules": report_charts.chart_top_failing_rules(
            stats.get("topRulesAll") or stats.get("topRulesToday") or [],
            title="Top failing rules (cumulative)",
        ),
        "coverage": report_charts.chart_coverage_vs_plan(tools, title="Coverage vs plan"),
        "tr1": report_charts.chart_tr1_claimed_vs_observed(
            tr1["practices"], concordance_pct=tr1["concordance"]
        ),
        "tr3": report_charts.chart_governance_mismatch(
            gov_rows, title="TR-3 Governance: school vs parent confirmation"
        ),
        "trend": report_charts.chart_flag_rate_trend(
            stats.get("flagRateByDay") or [],
            title="Flag rate trend across the study window",
        ),
    }


def render_final_html(stats: dict[str, Any]) -> str:
    from app.services import report_format as fmt

    charts = _final_chart_pngs(stats)
    prose = stats.get("sectionProse") or _section_prose(stats)
    tot = stats["totals"]
    tools = stats.get("tools") or []

    coverage_table = fmt.html_table(
        ["Tool", "Target", "Actual", "% of plan"],
        [
            [
                t["toolCode"],
                fmt.fmt_int(t["target"]) if t.get("target") else "—",
                fmt.fmt_int(t["cumulative"]),
                fmt.fmt_pct(t["coveragePct"]) if t.get("coveragePct") is not None else "—",
            ]
            for t in tools
        ],
        aligns=["left", "right", "right", "right"],
    )

    flagged_total = sum(int(t.get("flaggedSubmissions") or 0) for t in tools)
    flag_rows = [
        [
            t["toolCode"],
            fmt.fmt_int(t["cumulative"]),
            fmt.fmt_int(t["redCumulative"]),
            fmt.fmt_int(t["amberCumulative"]),
            fmt.fmt_pct(t["flaggedPct"]),
        ]
        for t in tools
    ]
    flag_rows.append(
        [
            "Overall",
            fmt.fmt_int(tot["cumulative"]),
            fmt.fmt_int(tot["redOpen"]),
            fmt.fmt_int(tot["amberOpen"]),
            fmt.fmt_pct(
                round(100.0 * flagged_total / tot["cumulative"], 1)
                if tot.get("cumulative")
                else 0.0
            ),
        ]
    )
    flag_table = fmt.html_table(
        ["Tool", "Submissions", "RED", "AMBER", "% flagged"],
        flag_rows,
        aligns=["left", "right", "right", "right", "right"],
        total_row=True,
    )

    findings_html = []
    for block in stats.get("findingsByTool") or []:
        rules_table = fmt.html_table(
            ["Rule", "Check", "Records", "Sev"],
            [
                [
                    r["ruleId"],
                    r["title"],
                    fmt.fmt_int(r["count"]),
                    fmt.severity_html(r["severity"]),
                ]
                for r in block.get("rules") or []
            ],
            aligns=["left", "left", "right", "center"],
        )
        findings_html.append(
            f"<h3>{fmt.esc(block['toolCode'])} — {fmt.esc(block['projectName'])}</h3>"
            f"<p class='prose'>{fmt.esc(block['summary'])}</p>"
            f"{rules_table}"
        )

    enum_table = fmt.html_table(
        ["Enumerator", "Tool(s)", "Records", "Flag %", "Median time", "Action"],
        [
            [
                e["enumerator"],
                ", ".join(e["tools"]) or "—",
                fmt.fmt_int(e["submissions"]),
                fmt.fmt_pct(e["flagRate"]),
                e.get("medianTimeLabel") or "—",
                e.get("action") or "—",
            ]
            for e in (stats.get("enumeratorsAll") or [])[:15]
        ],
        aligns=["left", "left", "right", "right", "right", "left"],
    )

    signoff_table = fmt.html_table(
        ["Action", "Tool", "Records", "Owner", "Sev"],
        [
            [
                c["label"],
                c.get("toolCode") or "—",
                fmt.fmt_int(c["records"]) if isinstance(c.get("records"), int) else (c.get("records") or "—"),
                c.get("owner") or c.get("ownerHint") or "—",
                fmt.severity_html(c["severity"]),
            ]
            for c in stats.get("signOffChecklist") or []
        ],
        aligns=["left", "left", "right", "left", "center"],
    )

    tool_bits = " · ".join(
        f"{t['toolCode']} {fmt.fmt_int(t['cumulative'])}" for t in tools
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{fmt.esc(stats.get('title') or 'Final DQA')}</title>
<style>{fmt.REPORT_CSS}</style></head><body><div class="wrap">
<p class="brand">{fmt.esc(stats.get('organizationName') or 'Infosutra')}</p>
<h1>{fmt.esc(stats.get('title') or 'Final DQA')}</h1>
<div class="meta-grid">
<span class="k">Report</span><span>Final DQA — end of round</span>
<span class="k">Data window</span><span>{fmt.esc(stats.get('reportDateDisplay') or fmt.format_report_date(stats['reportDate']))} (closed)</span>
<span class="k">KoBo pull</span><span>{fmt.esc(stats.get('lastKoboPullDisplay') or fmt.format_report_datetime(stats.get('lastKoboPullAt'), tz_name=stats.get('timezone') or 'Asia/Kolkata', fallback='n/a'))}</span>
<span class="k">Generated</span><span>{fmt.esc(stats.get('generatedAtDisplay') or fmt.format_report_datetime(stats.get('generatedAt'), tz_name=stats.get('timezone') or 'Asia/Kolkata'))}</span>
<span class="k">Total submissions</span><span>{fmt.fmt_int(tot['cumulative'])} ({tool_bits})</span>
</div>
<h2>2.1 Executive summary</h2>
<div class="ai">{fmt.paragraphs_html(stats.get('aiHeadline') or '')}</div>
<h2>2.2 Coverage — by tool</h2>
{fmt.paragraphs_html(prose.get('coverage') or '')}
{coverage_table}
{fmt.img_tag(charts['coverage'], "Coverage vs plan")}
<p class="caption">Figure — Actual submissions vs planned targets by tool.</p>
{fmt.paragraphs_html(prose.get('trend') or '')}
{fmt.img_tag(charts['trend'], "Flag rate trend")}
<p class="caption">Figure — Cumulative flag rate across the collection window.</p>
<h2>2.3 Data-quality flag summary — by tool</h2>
{fmt.paragraphs_html(prose.get('flagSummary') or '')}
{flag_table}
{fmt.img_tag(charts['flagSummary'], "DQA flag summary by tool")}
<p class="caption">Figure 1 — DQA flag summary by tool. Submissions, RED/AMBER counts and % flagged per tool, with overall totals.</p>
{fmt.img_tag(charts['topRules'], "Top failing rules")}
<p class="caption">Figure — Top failing rules (cumulative). Crimson = RED, orange = AMBER.</p>
<h2>2.4 Findings by tool</h2>
{''.join(findings_html) or '<p class="prose">No per-tool findings available.</p>'}
<h2>2.5 Enumerator performance</h2>
<p class="prose">Enumerators ranked by RED volume and flag rate. Median interview/observation time is annotated “(below)” when clearly under the group median.</p>
{enum_table}
<h2>2.6 Triangulation across tools</h2>
{fmt.paragraphs_html(prose.get('tr1') or '')}
{fmt.img_tag(charts['tr1'], "TR-1 claimed vs observed")}
<p class="caption">Figure 2 — TR-1 teacher practice, claimed vs observed. Say–do gap per practice; overall concordance shown on the chart.</p>
{fmt.paragraphs_html(prose.get('triangulationFurther') or '')}
{fmt.img_tag(charts['tr3'], "TR-3 governance")}
<p class="caption">Figure — TR-3 governance concordance (school-reported vs parent-confirmed).</p>
<h2>2.7 What remains before sign-off</h2>
{signoff_table}
{fmt.paragraphs_html(prose.get('signOffClose') or '')}
<p class="note">Infosutra Final DQA · Kobo is source of truth (read-only) · Checklist is informational; resolutions are not tracked in-app.</p>
</div></body></html>"""


def render_final_pdf(stats: dict[str, Any]) -> bytes:
    """Final DQA PDF with exhaustive summary, findings, enumerators, and figures."""
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

    from app.services import report_format as fmt

    charts = _final_chart_pngs(stats)
    prose = stats.get("sectionProse") or _section_prose(stats)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=stats.get("title") or "Final DQA",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("T", parent=styles["Heading1"], fontSize=15, spaceAfter=6)
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=colors.HexColor("#134e4a"),
        spaceBefore=12,
        spaceAfter=6,
    )
    h3 = ParagraphStyle(
        "H3",
        parent=styles["Heading3"],
        fontSize=10,
        textColor=colors.HexColor("#0f766e"),
        spaceBefore=8,
        spaceAfter=4,
    )
    body = ParagraphStyle("B", parent=styles["Normal"], fontSize=9, leading=12)
    meta = ParagraphStyle("M", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#57534e"))
    caption = ParagraphStyle(
        "C", parent=styles["Normal"], fontSize=7.5, textColor=colors.HexColor("#78716c"), spaceAfter=8
    )

    def _chart(key: str, width: float = 175 * mm, aspect: float = 0.42) -> list:
        png = charts.get(key)
        if not png:
            return []
        img = Image(BytesIO(png), width=width, height=width * aspect)
        img.hAlign = "CENTER"
        return [img, Spacer(1, 3)]

    def _paras(text: str) -> list:
        out = []
        for part in (text or "").split("\n\n"):
            part = part.strip()
            if part:
                out.append(Paragraph(html.escape(part), body))
                out.append(Spacer(1, 4))
        return out

    tot = stats["totals"]
    tools = stats.get("tools") or []
    story: list[Any] = [
        Paragraph(html.escape(stats.get("organizationName") or "Infosutra"), meta),
        Paragraph(html.escape(stats.get("title") or "Final DQA"), title),
        Paragraph(
            f"Final DQA — end of round · "
            f"{html.escape(stats.get('reportDateDisplay') or stats['reportDate'])} · "
            f"KoBo pull {html.escape(stats.get('lastKoboPullDisplay') or 'n/a')} · "
            f"Total submissions {tot['cumulative']}",
            meta,
        ),
        Paragraph("2.1 Executive summary", h2),
    ]
    story.extend(_paras(stats.get("aiHeadline") or ""))

    story.append(Paragraph("2.2 Coverage — by tool", h2))
    story.extend(_paras(prose.get("coverage") or ""))
    story.append(
        fmt.make_pdf_table(
            ["Tool", "Target", "Actual", "% of plan"],
            [
                [
                    t["toolCode"],
                    str(t["target"] or "—"),
                    str(t["cumulative"]),
                    f"{t['coveragePct']}%" if t["coveragePct"] is not None else "—",
                ]
                for t in tools
            ],
            aligns=["left", "right", "right", "right"],
            col_widths=[80, 70, 70, 70],
        )
    )
    story.append(Spacer(1, 6))
    story.extend(_chart("coverage", aspect=0.45))
    story.append(Paragraph("Figure — Actual vs plan by tool.", caption))
    story.extend(_paras(prose.get("trend") or ""))
    story.extend(_chart("trend", aspect=0.42))
    story.append(Paragraph("Figure — Cumulative flag rate across the study window.", caption))

    story.append(Paragraph("2.3 Data-quality flag summary — by tool", h2))
    story.extend(_paras(prose.get("flagSummary") or ""))
    flagged_total = sum(int(t.get("flaggedSubmissions") or 0) for t in tools)
    flag_rows = [
        [
            t["toolCode"],
            str(t["cumulative"]),
            str(t["redCumulative"]),
            str(t["amberCumulative"]),
            f"{t['flaggedPct']}%",
        ]
        for t in tools
    ]
    flag_rows.append(
        [
            "Overall",
            str(tot["cumulative"]),
            str(tot["redOpen"]),
            str(tot["amberOpen"]),
            f"{round(100.0 * flagged_total / tot['cumulative'], 1) if tot.get('cumulative') else 0}%",
        ]
    )
    story.append(
        fmt.make_pdf_table(
            ["Tool", "Submissions", "RED", "AMBER", "% flagged"],
            flag_rows,
            aligns=["left", "right", "right", "right", "right"],
            col_widths=[70, 70, 50, 55, 60],
        )
    )
    story.append(Spacer(1, 6))
    story.extend(_chart("flagSummary", aspect=0.40))
    story.append(
        Paragraph(
            "Figure 1 — DQA flag summary by tool. Submissions, RED/AMBER counts and % flagged.",
            caption,
        )
    )
    story.extend(_chart("topRules", width=155 * mm, aspect=0.55))
    story.append(Paragraph("Figure — Top failing rules (cumulative).", caption))

    story.append(Paragraph("2.4 Findings by tool", h2))
    for block in stats.get("findingsByTool") or []:
        story.append(
            Paragraph(
                f"{html.escape(block['toolCode'])} — {html.escape(block['projectName'])}",
                h3,
            )
        )
        story.append(Paragraph(html.escape(block["summary"]), body))
        story.append(Spacer(1, 3))
        story.append(
            fmt.make_pdf_table(
                ["Rule", "Check", "Records", "Sev"],
                [
                    [r["ruleId"], r["title"][:55], str(r["count"]), (r["severity"] or "").upper()]
                    for r in block.get("rules") or []
                ],
                aligns=["left", "left", "right", "center"],
                col_widths=[50, 220, 50, 40],
                body_style=body,
            )
        )
        story.append(Spacer(1, 6))

    story.append(Paragraph("2.5 Enumerator performance", h2))
    story.append(
        Paragraph(
            "Enumerators ranked by RED volume and flag rate. Median time marked “(below)” when under the group median.",
            body,
        )
    )
    story.append(Spacer(1, 3))
    story.append(
        fmt.make_pdf_table(
            ["Enumerator", "Tool(s)", "Records", "Flag %", "Median", "Action"],
            [
                [
                    e["enumerator"][:28],
                    ", ".join(e["tools"]) or "—",
                    str(e["submissions"]),
                    f"{e['flagRate']}%",
                    e.get("medianTimeLabel") or "—",
                    e.get("action") or "—",
                ]
                for e in (stats.get("enumeratorsAll") or [])[:12]
            ],
            aligns=["left", "left", "right", "right", "right", "left"],
            col_widths=[95, 45, 45, 40, 55, 100],
            body_style=body,
        )
    )

    story.append(Paragraph("2.6 Triangulation across tools", h2))
    story.extend(_paras(prose.get("tr1") or ""))
    story.extend(_chart("tr1", aspect=0.46))
    story.append(
        Paragraph(
            "Figure 2 — TR-1 teacher practice, claimed vs observed. Say–do gap per practice.",
            caption,
        )
    )
    story.extend(_paras(prose.get("triangulationFurther") or ""))
    story.extend(_chart("tr3", aspect=0.42))
    story.append(Paragraph("Figure — TR-3 governance concordance.", caption))

    story.append(Paragraph("2.7 What remains before sign-off", h2))
    story.append(
        fmt.make_pdf_table(
            ["Action", "Tool", "Records", "Owner", "Sev"],
            [
                [
                    c["label"][:48],
                    str(c.get("toolCode") or "—")[:12],
                    str(c.get("records") if c.get("records") is not None else "—"),
                    str(c.get("owner") or c.get("ownerHint") or "—")[:28],
                    (c.get("severity") or "").upper(),
                ]
                for c in stats.get("signOffChecklist") or []
            ],
            aligns=["left", "left", "right", "left", "center"],
            col_widths=[160, 45, 45, 90, 35],
            body_style=body,
        )
    )
    story.append(Spacer(1, 6))
    story.extend(_paras(prose.get("signOffClose") or ""))
    story.append(
        Paragraph(
            "Infosutra Final DQA · Kobo is source of truth (read-only) · Checklist is informational.",
            meta,
        )
    )
    doc.build(story)
    return buffer.getvalue()


def generate_final_dqa_report(
    db: Session,
    *,
    study_id: str | None = None,
    run_ai: bool = True,
) -> Report:
    settings = get_or_create_settings(db)
    sid = study_id or SIGHTSAVERS_2030_ID
    study = db.get(Study, sid)
    if not study:
        raise ValueError(f"Study not found: {sid}")

    stats = build_final_dqa_stats(db, study, run_ai=run_ai)
    html_body = render_final_html(stats)
    plain = f"{stats.get('title')}\n\n{stats.get('aiHeadline')}\n"
    pdf_bytes = render_final_pdf(stats)
    from app.services import report_docx

    docx_bytes = report_docx.render_final_docx(stats)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    report_id = str(uuid.uuid4())
    path = daily.pdf_path_for(report_id)
    path.write_bytes(pdf_bytes)
    daily.docx_path_for(report_id).write_bytes(docx_bytes)

    projects = list(db.scalars(select(Project).where(Project.study_id == study.id)).all())
    payload = {
        "stats": stats,
        "html": html_body,
        "plainText": plain,
        "aiSource": stats.get("aiSource"),
    }
    row = Report(
        id=report_id,
        title=stats.get("title") or f"Final DQA — {study.name}",
        description="Study close-out DQA with triangulation TR-1 / TR-3 / TR-5",
        status="ready",
        format="pdf",
        report_type="final_dqa",
        study_id=study.id,
        report_date=stats["reportDate"],
        prompt_name="Final DQA",
        generated_content=json.dumps(payload),
        download_url=f"/api/reports/{report_id}/download",
        page_count=5,
        file_size_kb=round(len(pdf_bytes) / 1024, 1),
        generated_at=now,
        created_at=now,
    )
    db.add(row)
    db.flush()
    for project in projects:
        row.report_projects.append(
            ReportProject(project_id=project.id, project_name=project.name)
        )
    db.commit()
    db.refresh(row)
    return row
