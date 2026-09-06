"""ReportLab PDF rendering of a Report Specification."""

from __future__ import annotations

import html as html_lib
from io import BytesIO
from typing import Any

from app.domain.report_spec.spec import (
    BarChartComponent,
    KpiGroupComponent,
    LineChartComponent,
    MetricComponent,
    NarrativeComponent,
    PieChartComponent,
    ProgressComponent,
    RankingComponent,
    StackedBarChartComponent,
    TableComponent,
    TextComponent,
)
from app.rendering import format as fmt
from app.rendering.spec import charts as spec_charts
from app.rendering.spec.base import RenderPayload, format_value, highlight_matches

_CALLOUT_LABEL = {"insight": "Insight", "warning": "Warning", "action_plan": "Action plan"}


def _styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "SpecTitle",
            parent=base["Heading1"],
            fontSize=15,
            spaceAfter=4,
            textColor=colors.HexColor("#1c1917"),
        ),
        "h2": ParagraphStyle(
            "SpecH2",
            parent=base["Heading2"],
            fontSize=11,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor("#134e4a"),
        ),
        "h3": ParagraphStyle(
            "SpecH3",
            parent=base["Heading3"],
            fontSize=9.5,
            spaceBefore=8,
            spaceAfter=4,
            textColor=colors.HexColor("#0f766e"),
        ),
        "body": ParagraphStyle("SpecBody", parent=base["Normal"], fontSize=9, leading=12),
        "meta": ParagraphStyle(
            "SpecMeta",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#57534e"),
            spaceAfter=6,
        ),
        "caption": ParagraphStyle(
            "SpecCaption",
            parent=base["Normal"],
            fontSize=7.5,
            textColor=colors.HexColor("#78716c"),
            spaceAfter=8,
        ),
    }


def _paras(text: str, style) -> list:
    from reportlab.platypus import Paragraph, Spacer

    out: list = []
    for part in (text or "").split("\n\n"):
        part = part.strip()
        if part:
            out.append(Paragraph(html_lib.escape(part), style))
            out.append(Spacer(1, 3))
    return out


def _image(png: bytes, *, width: float, aspect: float) -> list:
    from reportlab.platypus import Image, Spacer

    if not png:
        return []
    img = Image(BytesIO(png), width=width, height=width * aspect)
    img.hAlign = "CENTER"
    return [img, Spacer(1, 4)]


def _heading(component: Any, styles, level: str = "h3") -> list:
    from reportlab.platypus import Paragraph

    if not component.title:
        return []
    return [Paragraph(html_lib.escape(component.title), styles[level])]


def _unavailable(reason: str, styles) -> list:
    from reportlab.platypus import Paragraph

    return [Paragraph(f"<i>{html_lib.escape(reason)}</i>", styles["caption"])]


def _component_story(
    component: Any, payload: RenderPayload, styles, *, content_width: float
) -> list:
    from reportlab.platypus import Paragraph, Spacer

    story: list = []

    if isinstance(component, NarrativeComponent):
        text = (payload.narratives.get(component.id) or "").strip()
        if not text:
            return []
        label = component.title or _CALLOUT_LABEL[component.type]
        story.append(Paragraph(f"<b>{html_lib.escape(label)}</b>", styles["body"]))
        story.extend(_paras(text, styles["body"]))
        return story

    if isinstance(component, TextComponent):
        story.extend(_heading(component, styles))
        style = styles["caption"] if component.style == "caption" else styles["body"]
        story.extend(_paras(component.body, style))
        return story

    if isinstance(component, MetricComponent):
        record, error = payload.record_for(component)
        story.extend(_heading(component, styles))
        if error:
            return story + _unavailable(error, styles)
        value = format_value(record.get(component.field), component.format, component.unit)
        story.append(
            Paragraph(
                f"<b>{html_lib.escape(component.label)}:</b> {html_lib.escape(value)}",
                styles["body"],
            )
        )
        if component.caption:
            story.append(Paragraph(html_lib.escape(component.caption), styles["caption"]))
        return story

    if isinstance(component, KpiGroupComponent):
        record, error = payload.record_for(component)
        story.extend(_heading(component, styles))
        if error:
            return story + _unavailable(error, styles)
        items = [
            (item.label, format_value(record.get(item.field), item.format, item.unit))
            for item in component.items
        ]
        story.extend(_image(spec_charts.kpi_strip(items), width=content_width, aspect=0.18))
        return story

    if isinstance(component, TableComponent):
        rows, error = payload.rows_for(component)
        story.extend(_heading(component, styles))
        if error:
            return story + _unavailable(error, styles)
        if not rows:
            story.append(Paragraph(html_lib.escape(component.empty_text), styles["body"]))
            return story
        headers = [col.label for col in component.columns]
        aligns = [col.align for col in component.columns]
        body = [
            [format_value(row.get(col.field), col.format) for col in component.columns]
            for row in rows
        ]
        story.append(
            fmt.make_pdf_table(headers, body, aligns=aligns, body_style=styles["body"])
        )
        story.append(Spacer(1, 6))
        return story

    if isinstance(component, RankingComponent):
        rows, error = payload.rows_for(component)
        story.extend(_heading(component, styles))
        if error:
            return story + _unavailable(error, styles)
        ordered = sorted(
            rows,
            key=lambda row: float(row.get(component.value_field) or 0),
            reverse=component.order == "desc",
        )[: component.limit]
        for idx, row in enumerate(ordered, start=1):
            suffix = ""
            if highlight_matches(row, component.highlight) and component.highlight:
                suffix = f" — {component.highlight.label}"
            label = html_lib.escape(str(row.get(component.label_field) or "—"))
            value = html_lib.escape(
                format_value(row.get(component.value_field), component.value_format)
            )
            story.append(
                Paragraph(
                    f"{idx}. {label} — <b>{value}</b>{html_lib.escape(suffix)}", styles["body"]
                )
            )
        story.append(Spacer(1, 6))
        return story

    story.extend(_heading(component, styles))
    rows, error = payload.rows_for(component)
    if error:
        return story + _unavailable(error, styles)

    png: bytes | None = None
    aspect = 0.45
    if isinstance(component, StackedBarChartComponent):
        png = spec_charts.bar_chart(
            rows,
            x=component.x,
            series=component.series,
            title=component.title,
            y_label=component.y_label,
            stacked=True,
        )
    elif isinstance(component, BarChartComponent):
        png = spec_charts.bar_chart(
            rows,
            x=component.x,
            series=component.series,
            title=component.title,
            y_label=component.y_label,
            orientation=component.orientation,
        )
        if component.orientation == "horizontal":
            aspect = 0.55
    elif isinstance(component, LineChartComponent):
        png = spec_charts.line_chart(
            rows,
            x=component.x,
            series=component.series,
            title=component.title,
            y_label=component.y_label,
            area=component.area,
        )
    elif isinstance(component, PieChartComponent):
        png = spec_charts.pie_chart(
            rows[: component.limit],
            label_field=component.label_field,
            value_field=component.value_field,
            title=component.title,
            donut=component.donut,
        )
        aspect = 0.62
    elif isinstance(component, ProgressComponent):
        png = spec_charts.progress_chart(
            rows[: component.limit],
            label_field=component.label_field,
            value_field=component.value_field,
            target_field=component.target_field,
            title=component.title,
        )
        aspect = 0.5

    if png:
        story.extend(_image(png, width=content_width, aspect=aspect))
        caption = getattr(component, "caption", None)
        if caption:
            from reportlab.platypus import Paragraph as P

            story.append(P(html_lib.escape(caption), styles["caption"]))
    return story


def render_spec_pdf(payload: RenderPayload) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    spec = payload.spec
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=spec.title,
    )
    styles = _styles()
    content_width = doc.width

    story: list = [
        Paragraph(
            html_lib.escape(payload.meta.get("organizationName") or "Infosutra"), styles["meta"]
        ),
        Paragraph(html_lib.escape(spec.title), styles["title"]),
    ]
    if spec.subtitle:
        story.append(Paragraph(html_lib.escape(spec.subtitle), styles["meta"]))
    meta_bits = [
        f"{label}: {value}" for label, value in payload.meta.get("rows", []) if value
    ]
    if meta_bits:
        story.append(Paragraph(html_lib.escape(" · ".join(meta_bits)), styles["meta"]))

    for section in spec.sections:
        story.append(Paragraph(html_lib.escape(section.title), styles["h2"]))
        if section.description:
            story.extend(_paras(section.description, styles["body"]))
        for component in section.components:
            story.extend(
                _component_story(component, payload, styles, content_width=content_width)
            )

    footer = payload.meta.get("footer")
    if footer:
        story.append(Paragraph(html_lib.escape(footer), styles["caption"]))

    doc.build(story)
    return buffer.getvalue()
