"""Final DQA PDF rendering."""

from __future__ import annotations

import html
from typing import Any

from app.domain.reporting.final_stats import _section_prose as section_prose
from app.rendering import format as fmt
from app.rendering.final_charts import final_chart_pngs

def render_final_pdf(stats: dict[str, Any]) -> bytes:
    """Final DQA PDF with exhaustive summary, findings, enumerators, and figures."""
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

    charts = final_chart_pngs(stats)
    prose = stats.get("sectionProse") or section_prose(stats)
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
