"""DOCX export for Final DQA reports."""

from __future__ import annotations

from typing import Any

from docx import Document
from docx.shared import Cm

from app.domain.reporting.final_stats import _section_prose
from app.rendering.docx_helpers import (
    CAPTION,
    MUTED,
    TEAL,
    _add_chart,
    _add_heading,
    _add_paragraph,
    _add_paras,
    _add_table,
    _save,
)
from app.rendering.final import final_chart_pngs

def render_final_docx(stats: dict[str, Any]) -> bytes:
    charts = final_chart_pngs(stats)
    prose = stats.get("sectionProse") or _section_prose(stats)
    tot = stats["totals"]
    tools = stats.get("tools") or []

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(1.5)
    section.bottom_margin = Cm(1.5)
    section.left_margin = Cm(1.8)
    section.right_margin = Cm(1.8)

    _add_paragraph(
        doc,
        stats.get("organizationName") or "Infosutra",
        size_pt=9,
        color=MUTED,
        space_after=2,
    )
    _add_heading(doc, stats.get("title") or "Final DQA", level=1)
    _add_paragraph(
        doc,
        (
            f"Final DQA — end of round · "
            f"{stats.get('reportDateDisplay') or stats['reportDate']} · "
            f"KoBo pull {stats.get('lastKoboPullDisplay') or 'n/a'} · "
            f"Generated {stats.get('generatedAtDisplay') or 'n/a'} · "
            f"Total submissions {tot['cumulative']}"
        ),
        size_pt=8,
        color=MUTED,
        space_after=10,
    )

    _add_heading(doc, "2.1 Executive summary", level=2)
    _add_paras(doc, stats.get("aiHeadline") or "")

    _add_heading(doc, "2.2 Coverage — by tool", level=2)
    _add_paras(doc, prose.get("coverage") or "")
    _add_table(
        doc,
        ["Tool", "Target", "Actual", "% of plan"],
        [
            [
                t["toolCode"],
                t["target"] if t.get("target") is not None else "—",
                t["cumulative"],
                f"{t['coveragePct']}%" if t.get("coveragePct") is not None else "—",
            ]
            for t in tools
        ],
    )
    _add_chart(doc, charts.get("coverage"), "Figure — Actual vs plan by tool.")
    _add_paras(doc, prose.get("trend") or "")
    _add_chart(doc, charts.get("trend"), "Figure — Cumulative flag rate across the study window.")

    _add_heading(doc, "2.3 Data-quality flag summary — by tool", level=2)
    _add_paras(doc, prose.get("flagSummary") or "")
    flagged_total = sum(int(t.get("flaggedSubmissions") or 0) for t in tools)
    flag_rows = [
        [
            t["toolCode"],
            t["cumulative"],
            t["redCumulative"],
            t["amberCumulative"],
            f"{t['flaggedPct']}%",
        ]
        for t in tools
    ]
    flag_rows.append(
        [
            "Overall",
            tot["cumulative"],
            tot["redOpen"],
            tot["amberOpen"],
            f"{round(100.0 * flagged_total / tot['cumulative'], 1) if tot.get('cumulative') else 0}%",
        ]
    )
    _add_table(doc, ["Tool", "Submissions", "RED", "AMBER", "% flagged"], flag_rows)
    _add_chart(
        doc,
        charts.get("flagSummary"),
        "Figure 1 — DQA flag summary by tool. Submissions, RED/AMBER counts and % flagged.",
    )
    _add_chart(doc, charts.get("topRules"), "Figure — Top failing rules (cumulative).", width_in=5.6)

    _add_heading(doc, "2.4 Findings by tool", level=2)
    for block in stats.get("findingsByTool") or []:
        _add_heading(doc, f"{block.get('toolCode')} — {block.get('projectName')}", level=3)
        _add_paragraph(doc, block.get("summary") or "", size_pt=10, space_after=4)
        _add_table(
            doc,
            ["Rule", "Check", "Records", "Sev"],
            [
                [
                    r.get("ruleId"),
                    (r.get("title") or "")[:70],
                    r.get("count"),
                    (r.get("severity") or "").upper(),
                ]
                for r in block.get("rules") or []
            ],
        )

    _add_heading(doc, "2.5 Enumerator performance", level=2)
    _add_paragraph(
        doc,
        "Enumerators ranked by RED volume and flag rate. Median time marked “(below)” when under the group median.",
        size_pt=9,
        color=MUTED,
    )
    _add_table(
        doc,
        ["Enumerator", "Tool(s)", "Records", "Flag %", "Median", "Action"],
        [
            [
                e["enumerator"],
                ", ".join(e.get("tools") or []) or "—",
                e["submissions"],
                f"{e['flagRate']}%",
                e.get("medianTimeLabel") or "—",
                e.get("action") or "—",
            ]
            for e in (stats.get("enumeratorsAll") or [])[:12]
        ],
    )

    _add_heading(doc, "2.6 Triangulation across tools", level=2)
    _add_paras(doc, prose.get("tr1") or "")
    _add_chart(
        doc,
        charts.get("tr1"),
        "Figure 2 — TR-1 teacher practice, claimed vs observed. Say–do gap per practice.",
    )
    _add_paras(doc, prose.get("triangulationFurther") or "")
    _add_chart(doc, charts.get("tr3"), "Figure — TR-3 governance concordance.")

    _add_heading(doc, "2.7 What remains before sign-off", level=2)
    _add_table(
        doc,
        ["Action", "Tool", "Records", "Owner", "Sev"],
        [
            [
                (c.get("label") or "")[:60],
                c.get("toolCode") or "—",
                c.get("records") if c.get("records") is not None else "—",
                c.get("owner") or c.get("ownerHint") or "—",
                (c.get("severity") or "").upper(),
            ]
            for c in stats.get("signOffChecklist") or []
        ],
    )
    _add_paras(doc, prose.get("signOffClose") or "")
    _add_paragraph(
        doc,
        "Infosutra Final DQA · Kobo is source of truth (read-only) · Checklist is informational.",
        size_pt=8,
        color=MUTED,
        space_before=10,
    )
    return _save(doc)
