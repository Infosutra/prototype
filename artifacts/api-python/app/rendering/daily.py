"""Daily DQA HTML / PDF / plaintext rendering."""

from __future__ import annotations

import html
from typing import Any

from app.rendering import charts as report_charts
from app.rendering import format as fmt

def daily_chart_pngs(stats: dict[str, Any]) -> dict[str, bytes]:
    """Build chart PNGs for Daily report sections."""
    return {
        "flagsToday": report_charts.chart_today_flags_by_tool(stats.get("tools") or []),
        "coverage": report_charts.chart_coverage_vs_plan(
            stats.get("tools") or [], title="Coverage vs plan (cumulative)"
        ),
        "trend": report_charts.chart_flag_rate_trend(
            stats.get("flagRateByDay") or [],
            title="Cumulative flag rate by study day",
        ),
        "topRules": report_charts.chart_top_failing_rules(
            stats.get("topRulesToday") or [], title="Top failing rules today"
        ),
    }
def render_html(stats: dict[str, Any]) -> str:
    org = fmt.esc(stats.get("organizationName") or "Infosutra")
    study = fmt.esc(stats["studyName"])
    day = stats.get("dayNumber")
    day_label = f"Day {day}" if day is not None else "Study day n/a"
    charts = daily_chart_pngs(stats)
    tot = stats["totals"]

    tool_rows = [
        [
            t["toolCode"],
            fmt.fmt_int(t["newToday"]),
            fmt.fmt_int(t["cumulative"]),
            fmt.fmt_int(t["redToday"]),
            fmt.fmt_int(t["amberToday"]),
            fmt.fmt_pct(t["flaggedPctToday"]),
        ]
        for t in stats["tools"]
    ]
    flagged_today = sum(int(t.get("flaggedSubmissionsToday") or 0) for t in stats["tools"])
    flagged_pct_today = (
        round(100.0 * flagged_today / tot["newToday"], 1) if tot["newToday"] else 0.0
    )
    tool_rows.append(
        [
            "Total",
            fmt.fmt_int(tot["newToday"]),
            fmt.fmt_int(tot["cumulative"]),
            fmt.fmt_int(tot["redToday"]),
            fmt.fmt_int(tot["amberToday"]),
            fmt.fmt_pct(flagged_pct_today),
        ]
    )
    tools_table = fmt.html_table(
        ["Tool", "New today", "Cumulative", "RED today", "AMBER today", "% flagged (today)"],
        tool_rows,
        aligns=["left", "right", "right", "right", "right", "right"],
        total_row=True,
    )

    red_src = stats.get("redGrouped") or []
    red_rows = [
        [
            r["toolCode"],
            r["ruleId"],
            r["title"],
            fmt.fmt_int(r["count"]),
            f"{r['exampleEnumerator']} · UDISE {r['exampleUdise']}",
        ]
        for r in red_src
    ]
    red_table = fmt.html_table(
        ["Tool", "Rule", "Check", "Records", "Example"],
        red_rows,
        aligns=["left", "left", "left", "right", "left"],
    )

    enum_rows = [
        [
            e["enumerator"],
            ", ".join(e["tools"]) or "—",
            fmt.fmt_int(e["submissionsToday"]),
            fmt.fmt_pct(e["flagRate"]),
            e.get("medianTimeLabel") or "—",
            e.get("whyFlagged") or "—",
        ]
        for e in stats["enumerators"][:12]
    ]
    enum_table = fmt.html_table(
        ["Enumerator", "Tool(s)", "Records today", "Flag %", "Median time", "Why flagged"],
        enum_rows,
        aligns=["left", "left", "right", "right", "right", "left"],
    )

    checklist = "".join(
        f"<li><strong>[{fmt.esc(c['severity'].upper())}]</strong> {fmt.esc(c['label'])} — "
        f"{fmt.esc(c['detail'])} <em>({fmt.esc(c['ownerHint'])})</em></li>"
        for c in stats["signOffChecklist"]
    ) or "<li>No open checklist items.</li>"

    coverage_prose = stats.get("aiCoverageNote") or ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>DQA Daily — {study}</title>
<style>{fmt.REPORT_CSS}</style></head><body><div class="wrap">
<p class="brand">{org}</p>
<h1>DQA Daily Report — {study}</h1>
<div class="meta-grid">
<span class="k">Report</span><span>Daily DQA — {fmt.esc(day_label)}</span>
<span class="k">Data window</span><span>{fmt.esc(stats.get('reportDateDisplay') or fmt.format_report_date(stats['reportDate']))} ({fmt.esc(stats['timezone'])})</span>
<span class="k">KoBo pull</span><span>{fmt.esc(stats.get('lastKoboPullDisplay') or fmt.format_report_datetime(stats.get('lastKoboPullAt'), tz_name=stats.get('timezone') or 'Asia/Kolkata', fallback='never'))}</span>
<span class="k">Generated</span><span>{fmt.esc(stats.get('generatedAtDisplay') or fmt.format_report_datetime(stats.get('generatedAt'), tz_name=stats.get('timezone') or 'Asia/Kolkata'))}</span>
<span class="k">Today's intake</span><span>{fmt.fmt_int(tot['newToday'])} new · cumulative {fmt.fmt_int(tot['cumulative'])}</span>
</div>
<div class="ai"><p><strong>Today's headline</strong></p>
{fmt.paragraphs_html(stats.get('aiHeadline') or '')}</div>
<h2>1.1 Today's intake &amp; flags — by tool</h2>
{tools_table}
<p class="prose">Note: today's flag rate is inflated by same-day records not yet back-checked;
the cumulative trend (Section 1.4) is the truer picture.</p>
{fmt.img_tag(charts['flagsToday'], "Today RED and AMBER flags by tool")}
<p class="caption">Figure — Today's RED / AMBER flag counts by tool.</p>
{fmt.img_tag(charts['topRules'], "Top failing rules today")}
<p class="caption">Figure — Top failing rules today (RED in crimson, AMBER in orange).</p>
<h2>1.2 RED items to correct or back-check (priority)</h2>
{red_table}
<h2>1.3 Enumerators to back-check tomorrow</h2>
{enum_table}
<h2>1.4 Coverage &amp; trend</h2>
{fmt.paragraphs_html(coverage_prose)}
{fmt.img_tag(charts['coverage'], "Coverage vs plan")}
<p class="caption">Figure — Cumulative submissions vs study targets by tool.</p>
{fmt.img_tag(charts['trend'], "Flag rate trend")}
<p class="caption">Figure — Cumulative flag rate across study days.</p>
<h2>Sign-off checklist (read-only)</h2>
<ul>{checklist}</ul>
<p class="note">Generated by Infosutra · KoboToolbox is source of truth (read-only sync) ·
This checklist is informational; resolutions are not tracked in-app.</p>
</div></body></html>"""
def render_plaintext(stats: dict[str, Any]) -> str:
    lines = [
        f"DQA Daily — {stats['studyName']}",
        f"Date: {stats['reportDate']}  Day: {stats.get('dayNumber')}",
        "",
        stats.get("aiHeadline") or "",
        stats.get("aiCoverageNote") or "",
        "",
        "Tools:",
    ]
    for t in stats["tools"]:
        lines.append(
            f"  {t['toolCode']}: +{t['newToday']} today, {t['cumulative']}/{t['target'] or '—'} "
            f"RED {t['redToday']} AMBER {t['amberToday']}"
        )
    lines.append("")
    lines.append("RED priority:")
    for r in (stats.get("redGrouped") or stats["redPriority"])[:10]:
        if "count" in r:
            lines.append(
                f"  {r['ruleId']} {r['title']} ×{r['count']} · {r.get('exampleEnumerator')}"
            )
        else:
            lines.append(f"  {r['ruleId']} {r['title']} · {r['enumerator']} · UDISE {r['udise']}")
    return "\n".join(lines)
def render_pdf(stats: dict[str, Any]) -> bytes:
    """Build multi-page PDF with embedded charts and aligned tables."""
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

    charts = daily_chart_pngs(stats)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"DQA Daily — {stats['studyName']}",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "DqaTitle", parent=styles["Heading1"], fontSize=15, spaceAfter=4, textColor=colors.HexColor("#1c1917")
    )
    h2 = ParagraphStyle(
        "DqaH2",
        parent=styles["Heading2"],
        fontSize=11,
        spaceBefore=12,
        spaceAfter=6,
        textColor=colors.HexColor("#134e4a"),
    )
    body = ParagraphStyle("DqaBody", parent=styles["Normal"], fontSize=9, leading=12)
    meta = ParagraphStyle(
        "DqaMeta", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#57534e"), spaceAfter=6
    )
    caption = ParagraphStyle(
        "Cap", parent=styles["Normal"], fontSize=7.5, textColor=colors.HexColor("#78716c"), spaceAfter=8
    )

    def _chart(key: str, width: float = 170 * mm, aspect: float = 0.45) -> list:
        png = charts.get(key)
        if not png:
            return []
        img = Image(BytesIO(png), width=width, height=width * aspect)
        img.hAlign = "CENTER"
        return [img, Spacer(1, 4)]

    def _paras(text: str) -> list:
        out = []
        for part in (text or "").split("\n\n"):
            part = part.strip()
            if part:
                out.append(Paragraph(html.escape(part), body))
                out.append(Spacer(1, 3))
        return out

    story: list[Any] = []
    day = stats.get("dayNumber")
    day_label = f"Day {day}" if day is not None else "Day n/a"
    tot = stats["totals"]
    story.append(Paragraph(html.escape(stats.get("organizationName") or "Infosutra"), meta))
    story.append(Paragraph(f"DQA Daily Report — {html.escape(stats['studyName'])}", title))
    story.append(
        Paragraph(
            f"Report: Daily DQA — {day_label} · "
            f"{html.escape(stats.get('reportDateDisplay') or stats['reportDate'])} "
            f"({html.escape(stats['timezone'])}) · "
            f"KoBo pull {html.escape(stats.get('lastKoboPullDisplay') or 'never')} · "
            f"New {tot['newToday']} · Cumulative {tot['cumulative']}",
            meta,
        )
    )
    story.append(Paragraph("<b>Today's headline</b>", body))
    story.extend(_paras(stats.get("aiHeadline") or ""))

    story.append(Paragraph("1.1 Today's intake &amp; flags — by tool", h2))
    tool_rows = [
        [
            t["toolCode"],
            str(t["newToday"]),
            str(t["cumulative"]),
            str(t["redToday"]),
            str(t["amberToday"]),
            f"{t['flaggedPctToday']}%",
        ]
        for t in stats["tools"]
    ]
    story.append(
        fmt.make_pdf_table(
            ["Tool", "New today", "Cumulative", "RED", "AMBER", "% flagged"],
            tool_rows,
            aligns=["left", "right", "right", "right", "right", "right"],
            col_widths=[55, 55, 60, 45, 50, 55],
        )
    )
    story.append(Spacer(1, 6))
    story.extend(_chart("flagsToday"))
    story.append(Paragraph("Figure — Today's RED / AMBER by tool.", caption))
    story.extend(_chart("topRules", width=150 * mm, aspect=0.55))
    story.append(Paragraph("Figure — Top failing rules today.", caption))

    story.append(Paragraph("1.2 RED items to correct or back-check (priority)", h2))
    red_rows = [
        [
            r["toolCode"],
            r["ruleId"],
            r["title"][:48],
            str(r["count"]),
            f"{r['exampleEnumerator'][:18]} · {r['exampleUdise']}",
        ]
        for r in (stats.get("redGrouped") or [])[:12]
    ]
    story.append(
        fmt.make_pdf_table(
            ["Tool", "Rule", "Check", "Records", "Example"],
            red_rows,
            aligns=["left", "left", "left", "right", "left"],
            col_widths=[35, 45, 145, 45, 110],
            body_style=body,
        )
    )

    story.append(Paragraph("1.3 Enumerators to back-check tomorrow", h2))
    enum_rows = [
        [
            e["enumerator"][:28],
            ", ".join(e["tools"]) or "—",
            str(e["submissionsToday"]),
            f"{e['flagRate']}%",
            e.get("medianTimeLabel") or "—",
            (e.get("whyFlagged") or "—")[:36],
        ]
        for e in stats["enumerators"][:12]
    ]
    story.append(
        fmt.make_pdf_table(
            ["Enumerator", "Tool(s)", "Records", "Flag %", "Median", "Why flagged"],
            enum_rows,
            aligns=["left", "left", "right", "right", "right", "left"],
            col_widths=[95, 45, 45, 40, 55, 100],
            body_style=body,
        )
    )

    story.append(Paragraph("1.4 Coverage &amp; trend", h2))
    story.extend(_paras(stats.get("aiCoverageNote") or ""))
    story.extend(_chart("coverage"))
    story.append(Paragraph("Figure — Cumulative submissions vs study targets.", caption))
    story.extend(_chart("trend"))
    story.append(Paragraph("Figure — Cumulative flag rate by study day.", caption))

    story.append(Paragraph("Sign-off checklist (read-only)", h2))
    for item in stats["signOffChecklist"]:
        story.append(
            Paragraph(
                f"[{html.escape(item['severity'].upper())}] "
                f"<b>{html.escape(item['label'])}</b> — {html.escape(item['detail'])}",
                body,
            )
        )
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "Infosutra · Kobo is source of truth (read-only) · Checklist is informational.",
            meta,
        )
    )
    doc.build(story)
    return buffer.getvalue()
