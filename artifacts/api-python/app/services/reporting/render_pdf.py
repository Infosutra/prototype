"""PDF renderer: pure function of ExecuteResult (no query_engine, no LLM)."""

from __future__ import annotations

import html as html_lib
from io import BytesIO
from typing import Any


def render_pdf(result: dict[str, Any]) -> bytes:
    """Render an ExecuteResult dict to PDF bytes via ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    styles_base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "ExecTitle",
            parent=styles_base["Heading1"],
            fontSize=14,
            spaceAfter=6,
            textColor=colors.HexColor("#1c1917"),
        ),
        "h2": ParagraphStyle(
            "ExecH2",
            parent=styles_base["Heading2"],
            fontSize=11,
            spaceBefore=10,
            spaceAfter=4,
            textColor=colors.HexColor("#134e4a"),
        ),
        "h3": ParagraphStyle(
            "ExecH3",
            parent=styles_base["Heading3"],
            fontSize=9.5,
            spaceBefore=6,
            spaceAfter=3,
            textColor=colors.HexColor("#0f766e"),
        ),
        "body": ParagraphStyle(
            "ExecBody", parent=styles_base["Normal"], fontSize=9, leading=12
        ),
        "meta": ParagraphStyle(
            "ExecMeta",
            parent=styles_base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#57534e"),
            spaceAfter=8,
        ),
        "error": ParagraphStyle(
            "ExecError",
            parent=styles_base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#b91c1c"),
        ),
    }

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    story: list[Any] = []

    title = str(result.get("title") or "Report")
    story.append(Paragraph(html_lib.escape(title), styles["title"]))

    window = result.get("window") or {}
    meta_bits = []
    if window.get("from") or window.get("to"):
        meta_bits.append(
            f"Window: {window.get('from', '?')} → {window.get('to', '?')}"
        )
    if result.get("reportId"):
        meta_bits.append(f"Report: {result['reportId']}")
    if meta_bits:
        story.append(Paragraph(html_lib.escape(" · ".join(meta_bits)), styles["meta"]))

    for section in result.get("sections") or []:
        story.append(
            Paragraph(html_lib.escape(str(section.get("title") or section.get("id") or "Section")), styles["h2"])
        )
        for comp in section.get("components") or []:
            cid = str(comp.get("id") or "")
            ctype = str(comp.get("type") or "")
            story.append(
                Paragraph(
                    html_lib.escape(f"{cid} ({ctype})" if cid else ctype or "component"),
                    styles["h3"],
                )
            )
            if comp.get("error"):
                story.append(
                    Paragraph(
                        html_lib.escape(f"Error: {comp['error']}"),
                        styles["error"],
                    )
                )
                continue
            data = comp.get("data")
            story.extend(_render_data(ctype, data, styles, Table, TableStyle, colors, Paragraph, Spacer))

    doc.build(story)
    return buf.getvalue()


def _render_data(
    ctype: str,
    data: Any,
    styles: dict,
    Table: Any,
    TableStyle: Any,
    colors: Any,
    Paragraph: Any,
    Spacer: Any,
) -> list[Any]:
    out: list[Any] = []
    if data is None:
        out.append(Paragraph("<i>No data</i>", styles["body"]))
        return out

    if ctype == "metric":
        if isinstance(data, dict) and "value" in data:
            out.append(Paragraph(html_lib.escape(str(data["value"])), styles["body"]))
        else:
            out.append(Paragraph(html_lib.escape(str(data)), styles["body"]))
        out.append(Spacer(1, 4))
        return out

    if ctype == "kpi_group" and isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            rows = [["Metric", "Value"]]
            for item in items:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "")
                if item.get("error"):
                    rows.append([label, f"error: {item.get('error')}"])
                else:
                    rows.append([label, str(item.get("value", ""))])
            out.append(_table(rows, Table, TableStyle, colors))
        else:
            rows = [["Metric", "Value"]] + [
                [str(k), str(v)] for k, v in data.items() if k != "items"
            ]
            out.append(_table(rows, Table, TableStyle, colors))
        out.append(Spacer(1, 4))
        return out

    if ctype in {"narrative", "text"}:
        if isinstance(data, dict):
            text = data.get("text") or data.get("body") or ""
        else:
            text = str(data)
        for part in str(text).split("\n\n"):
            out.append(Paragraph(html_lib.escape(part.strip()), styles["body"]))
        out.append(Spacer(1, 4))
        return out

    # table / chart / progress — list[dict] (charts as simplified tables)
    if isinstance(data, list):
        if not data:
            out.append(Paragraph("<i>Empty</i>", styles["body"]))
            return out
        if isinstance(data[0], dict):
            keys: list[str] = []
            for row in data:
                for k in row.keys():
                    if k not in keys:
                        keys.append(str(k))
            rows = [keys] + [[str(r.get(k, "")) for k in keys] for r in data]
            out.append(_table(rows, Table, TableStyle, colors))
            out.append(Spacer(1, 4))
            return out

    if isinstance(data, dict):
        rows = [["Key", "Value"]] + [[str(k), str(v)] for k, v in data.items()]
        out.append(_table(rows, Table, TableStyle, colors))
        out.append(Spacer(1, 4))
        return out

    out.append(Paragraph(html_lib.escape(str(data)), styles["body"]))
    return out


def _table(rows: list[list[str]], Table: Any, TableStyle: Any, colors: Any) -> Any:
    t = Table(rows, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f5f4")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d6d3d1")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t
