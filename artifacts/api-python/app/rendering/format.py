"""Shared HTML/PDF formatting for DQA Daily & Final reports."""

from __future__ import annotations

import html
from typing import Any, Literal, Sequence

from app.domain.reporting.helpers import (
    format_report_date,
    format_report_datetime,
)
from app.rendering import charts as report_charts

Align = Literal["left", "center", "right"]


REPORT_CSS = """
body { font-family: 'Source Serif 4', 'Libre Baskerville', Georgia, serif; color: #1c1917;
  margin: 0; padding: 24px; background: #f4f4f5; line-height: 1.45; }
.wrap { max-width: 940px; margin: 0 auto; background: #fff; padding: 32px 36px 40px;
  border: 1px solid #e4e4e7; box-shadow: 0 1px 2px rgba(28,25,23,.04); }
.brand { margin: 0; font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
  color: #0f766e; font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; }
h1 { font-size: 22px; margin: 6px 0 4px; font-weight: 700; letter-spacing: -0.01em; }
h2 { font-size: 15px; margin: 30px 0 10px; border-bottom: 2px solid #0f766e; padding-bottom: 6px;
  color: #134e4a; font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; font-weight: 600; }
h3 { font-size: 13.5px; margin: 20px 0 8px; color: #0f766e;
  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; font-weight: 600; }
.meta { color: #57534e; font-size: 12.5px; margin: 0 0 16px;
  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; }
.meta-grid { display: grid; grid-template-columns: 140px 1fr; gap: 4px 12px; font-size: 12.5px;
  margin: 12px 0 18px; font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; }
.meta-grid .k { color: #78716c; }
.ai, .prose-box { background: #f8faf9; padding: 14px 16px; border-left: 3px solid #0f766e;
  margin: 10px 0 18px; }
.ai p, .prose-box p { margin: 0 0 10px; }
.ai p:last-child, .prose-box p:last-child { margin-bottom: 0; }
.prose { font-size: 13.5px; margin: 0 0 12px; color: #292524; }
.table-wrap { margin: 10px 0 16px; overflow-x: auto; }
table.rpt { width: 100%; border-collapse: collapse; font-size: 12.5px;
  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; }
table.rpt th, table.rpt td { border: 1px solid #d6d3d1; padding: 8px 10px; vertical-align: top; }
table.rpt thead th { background: #134e4a; color: #fafaf9; font-weight: 600; font-size: 11.5px;
  letter-spacing: .02em; border-color: #0f766e; }
table.rpt tbody tr:nth-child(even) { background: #fafaf9; }
table.rpt tbody tr.total { background: #ecfdf5; font-weight: 600; }
table.rpt td.num, table.rpt th.num { text-align: right; font-variant-numeric: tabular-nums; }
table.rpt td.ctr, table.rpt th.ctr { text-align: center; font-variant-numeric: tabular-nums; }
table.rpt td.left, table.rpt th.left { text-align: left; }
.sev-red { color: #b91c1c; font-weight: 600; }
.sev-amber { color: #b45309; font-weight: 600; }
.sev-clean { color: #15803d; font-weight: 600; }
.mono { font-family: 'IBM Plex Mono', 'Consolas', 'Menlo', monospace;
  font-size: 12px; font-variant-numeric: tabular-nums; }
.uuid { display: block; font-size: 10.5px; color: #78716c; margin-top: 2px;
  font-family: 'IBM Plex Mono', 'Consolas', 'Menlo', monospace; }
.chart { margin: 8px 0 6px; }
.caption { font-size: 11px; color: #78716c; font-style: italic; margin: 0 0 18px;
  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; }
.note { font-size: 11.5px; color: #78716c; margin-top: 28px;
  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; border-top: 1px solid #e7e5e4; padding-top: 12px; }
"""


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def fmt_int(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return esc(value)


def fmt_pct(value: Any, *, digits: int = 1, suffix: str = "%") -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return esc(value)


def _align_class(align: Align) -> str:
    if align == "right":
        return "num"
    if align == "center":
        return "ctr"
    return "left"


def html_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    aligns: Sequence[Align] | None = None,
    total_row: bool = False,
) -> str:
    """Build a styled HTML table. Cell values may be raw HTML (already escaped) or plain."""
    n = len(headers)
    aligns = list(aligns) if aligns else ["left"] * n
    while len(aligns) < n:
        aligns.append("left")

    head = "".join(
        f'<th class="{_align_class(aligns[i])}">{esc(headers[i])}</th>' for i in range(n)
    )
    body_parts: list[str] = []
    for idx, row in enumerate(rows):
        cells = list(row) + [""] * max(0, n - len(row))
        cls = ' class="total"' if total_row and idx == len(rows) - 1 else ""
        tds = []
        for i in range(n):
            cell = cells[i]
            if isinstance(cell, str) and cell.startswith("\x00html:"):
                content = cell[6:]
            else:
                content = esc(cell)
            tds.append(f'<td class="{_align_class(aligns[i])}">{content}</td>')
        body_parts.append(f"<tr{cls}>{''.join(tds)}</tr>")
    if not body_parts:
        body_parts.append(
            f'<tr><td colspan="{n}" class="left">No data.</td></tr>'
        )
    return (
        f'<div class="table-wrap"><table class="rpt"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body_parts)}</tbody></table></div>"
    )


def html_cell(value: Any, *, raw: bool = False) -> str:
    """Return a cell marker that html_table will treat as pre-escaped HTML."""
    if raw:
        return "\x00html:" + str(value)
    return "\x00html:" + esc(value)


def severity_html(sev: str) -> str:
    s = (sev or "").lower()
    cls = "sev-red" if s == "red" else "sev-amber" if s == "amber" else ""
    label = (sev or "—").upper()
    if cls:
        return html_cell(f'<span class="{cls}">{esc(label)}</span>', raw=True)
    return label


def img_tag(png: bytes, alt: str) -> str:
    return (
        f'<div class="chart"><img src="{report_charts.png_data_uri(png)}" '
        f'alt="{esc(alt)}" style="max-width:100%;height:auto;display:block"/></div>'
    )


def paragraphs_html(text: str) -> str:
    parts = [p.strip() for p in (text or "").split("\n\n") if p.strip()]
    if not parts:
        return ""
    return "".join(f'<p class="prose">{esc(p)}</p>' for p in parts)


# --- PDF helpers ---


def pdf_table_style(aligns: Sequence[Align], *, header_bg: str = "#134e4a"):
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    cmds: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d6d3d1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafaf9")]),
    ]
    align_map = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}
    for i, a in enumerate(aligns):
        cmds.append(("ALIGN", (i, 0), (i, -1), align_map.get(a, "LEFT")))
    return TableStyle(cmds)


def make_pdf_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    aligns: Sequence[Align],
    col_widths: Sequence[float] | None = None,
    body_style=None,
):
    from reportlab.platypus import Paragraph, Table

    data: list[list[Any]] = [list(headers)]
    for row in rows:
        cells: list[Any] = []
        for i, cell in enumerate(row):
            if body_style is not None and isinstance(cell, str) and len(cell) > 28:
                cells.append(Paragraph(html.escape(cell), body_style))
            else:
                cells.append("" if cell is None else str(cell))
        while len(cells) < len(headers):
            cells.append("")
        data.append(cells[: len(headers)])
    if len(data) == 1:
        data.append(["—"] * len(headers))
    table = Table(data, colWidths=list(col_widths) if col_widths else None, repeatRows=1)
    table.setStyle(pdf_table_style(aligns))
    return table
