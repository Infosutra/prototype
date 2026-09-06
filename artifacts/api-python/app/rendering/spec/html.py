"""HTML rendering of a Report Specification."""

from __future__ import annotations

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
from app.rendering.spec.base import (
    RenderPayload,
    format_value,
    highlight_matches,
)

SPEC_CSS = """
.kpis { display: flex; flex-wrap: wrap; gap: 10px; margin: 10px 0 18px; }
.kpi { flex: 1 1 150px; background: #f8faf9; border-left: 3px solid #0f766e; padding: 10px 14px; }
.kpi .v { font-size: 20px; font-weight: 700; color: #1c1917;
  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; font-variant-numeric: tabular-nums; }
.kpi .l { font-size: 11px; color: #78716c; text-transform: uppercase; letter-spacing: .04em;
  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; }
.rank { list-style: none; padding: 0; margin: 8px 0 16px; }
.rank li { display: flex; justify-content: space-between; gap: 12px; padding: 6px 10px;
  border-bottom: 1px solid #f0efee; font-size: 13px; }
.rank li .n { font-variant-numeric: tabular-nums; font-weight: 600; }
.rank li.flagged { background: #fef2f2; }
.rank li.flagged .n { color: #b91c1c; }
.callout { padding: 12px 16px; margin: 10px 0 18px; border-left: 3px solid #0f766e; background: #f8faf9; }
.callout.warning { border-left-color: #b45309; background: #fffbeb; }
.callout.action { border-left-color: #134e4a; background: #f0fdfa; }
.callout .hd { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #0f766e;
  font-family: 'IBM Plex Sans', 'Segoe UI', sans-serif; margin: 0 0 6px; font-weight: 600; }
.callout.warning .hd { color: #b45309; }
.unavailable { font-size: 12.5px; color: #78716c; font-style: italic; margin: 6px 0 16px; }
"""


def _unavailable(reason: str) -> str:
    return f'<p class="unavailable">{fmt.esc(reason)}</p>'


def _heading(component: Any, level: int = 3) -> str:
    if not component.title:
        return ""
    return f"<h{level}>{fmt.esc(component.title)}</h{level}>"


def _caption(text: str | None) -> str:
    return f'<p class="caption">{fmt.esc(text)}</p>' if text else ""


def _metric(component: MetricComponent, payload: RenderPayload) -> str:
    record, error = payload.record_for(component)
    if error:
        return _heading(component) + _unavailable(error)
    value = format_value(record.get(component.field), component.format, component.unit)
    return (
        f"{_heading(component)}"
        f'<div class="kpis"><div class="kpi"><div class="v">{fmt.esc(value)}</div>'
        f'<div class="l">{fmt.esc(component.label)}</div></div></div>'
        f"{_caption(component.caption)}"
    )


def _kpi_group(component: KpiGroupComponent, payload: RenderPayload) -> str:
    record, error = payload.record_for(component)
    if error:
        return _heading(component) + _unavailable(error)
    cards = "".join(
        f'<div class="kpi"><div class="v">'
        f"{fmt.esc(format_value(record.get(item.field), item.format, item.unit))}</div>"
        f'<div class="l">{fmt.esc(item.label)}</div></div>'
        for item in component.items
    )
    return f'{_heading(component)}<div class="kpis">{cards}</div>'


def _text(component: TextComponent, _payload: RenderPayload) -> str:
    if component.style == "note":
        return f'{_heading(component)}<p class="note">{fmt.esc(component.body)}</p>'
    if component.style == "caption":
        return f"{_heading(component)}{_caption(component.body)}"
    return _heading(component) + fmt.paragraphs_html(component.body)


def _table(component: TableComponent, payload: RenderPayload) -> str:
    rows, error = payload.rows_for(component)
    if error:
        return _heading(component) + _unavailable(error)
    if not rows:
        return f"{_heading(component)}<p class=\"prose\">{fmt.esc(component.empty_text)}</p>"
    headers = [col.label for col in component.columns]
    aligns = [col.align for col in component.columns]
    body: list[list[Any]] = []
    for row in rows:
        cells: list[Any] = []
        for col in component.columns:
            if col.format == "severity":
                cells.append(fmt.severity_html(str(row.get(col.field) or "")))
            else:
                cells.append(format_value(row.get(col.field), col.format))
        body.append(cells)
    return _heading(component) + fmt.html_table(
        headers, body, aligns=aligns, total_row=component.total_row
    )


def _ranking(component: RankingComponent, payload: RenderPayload) -> str:
    rows, error = payload.rows_for(component)
    if error:
        return _heading(component) + _unavailable(error)
    ordered = sorted(
        rows,
        key=lambda row: float(row.get(component.value_field) or 0),
        reverse=component.order == "desc",
    )[: component.limit]
    if not ordered:
        return f'{_heading(component)}<p class="prose">No data.</p>'
    items = []
    for row in ordered:
        flagged = " flagged" if highlight_matches(row, component.highlight) else ""
        note = (
            f' <em>({fmt.esc(component.highlight.label)})</em>'
            if flagged and component.highlight
            else ""
        )
        items.append(
            f'<li class="rank-item{flagged}"><span>{fmt.esc(row.get(component.label_field))}{note}</span>'
            f'<span class="n">'
            f"{fmt.esc(format_value(row.get(component.value_field), component.value_format))}"
            f"</span></li>"
        )
    return f'{_heading(component)}<ul class="rank">{"".join(items)}</ul>'


def _chart_html(component: Any, payload: RenderPayload, png_builder) -> str:
    rows, error = payload.rows_for(component)
    if error:
        return _heading(component) + _unavailable(error)
    png = png_builder(rows)
    alt = component.title or component.type
    return (
        f"{_heading(component)}{fmt.img_tag(png, alt)}"
        f"{_caption(getattr(component, 'caption', None))}"
    )


def _bar(component: BarChartComponent, payload: RenderPayload) -> str:
    return _chart_html(
        component,
        payload,
        lambda rows: spec_charts.bar_chart(
            rows,
            x=component.x,
            series=component.series,
            title=component.title,
            y_label=component.y_label,
            orientation=component.orientation,
        ),
    )


def _stacked_bar(component: StackedBarChartComponent, payload: RenderPayload) -> str:
    return _chart_html(
        component,
        payload,
        lambda rows: spec_charts.bar_chart(
            rows,
            x=component.x,
            series=component.series,
            title=component.title,
            y_label=component.y_label,
            stacked=True,
        ),
    )


def _line(component: LineChartComponent, payload: RenderPayload) -> str:
    return _chart_html(
        component,
        payload,
        lambda rows: spec_charts.line_chart(
            rows,
            x=component.x,
            series=component.series,
            title=component.title,
            y_label=component.y_label,
            area=component.area,
        ),
    )


def _pie(component: PieChartComponent, payload: RenderPayload) -> str:
    return _chart_html(
        component,
        payload,
        lambda rows: spec_charts.pie_chart(
            rows[: component.limit],
            label_field=component.label_field,
            value_field=component.value_field,
            title=component.title,
            donut=component.donut,
        ),
    )


def _progress(component: ProgressComponent, payload: RenderPayload) -> str:
    return _chart_html(
        component,
        payload,
        lambda rows: spec_charts.progress_chart(
            rows[: component.limit],
            label_field=component.label_field,
            value_field=component.value_field,
            target_field=component.target_field,
            title=component.title,
        ),
    )


_CALLOUT_CLASS = {"insight": "", "warning": " warning", "action_plan": " action"}
_CALLOUT_LABEL = {"insight": "Insight", "warning": "Warning", "action_plan": "Action plan"}


def _narrative(component: NarrativeComponent, payload: RenderPayload) -> str:
    text = (payload.narratives.get(component.id) or "").strip()
    if not text:
        return ""
    label = component.title or _CALLOUT_LABEL[component.type]
    css = _CALLOUT_CLASS[component.type]
    return (
        f'<div class="callout{css}"><p class="hd">{fmt.esc(label)}</p>'
        f"{fmt.paragraphs_html(text)}</div>"
    )


HTML_RENDERERS = {
    "metric": _metric,
    "kpi_group": _kpi_group,
    "text": _text,
    "table": _table,
    "ranking": _ranking,
    "bar_chart": _bar,
    "stacked_bar_chart": _stacked_bar,
    "line_chart": _line,
    "pie_chart": _pie,
    "progress": _progress,
    "insight": _narrative,
    "warning": _narrative,
    "action_plan": _narrative,
}


def _meta_grid(meta: dict[str, Any]) -> str:
    rows = [(label, value) for label, value in meta.get("rows", []) if value]
    if not rows:
        return ""
    cells = "".join(
        f'<span class="k">{fmt.esc(label)}</span><span>{fmt.esc(value)}</span>'
        for label, value in rows
    )
    return f'<div class="meta-grid">{cells}</div>'


def render_spec_html(payload: RenderPayload) -> str:
    spec = payload.spec
    org = payload.meta.get("organizationName") or "Infosutra"
    parts: list[str] = [
        f'<p class="brand">{fmt.esc(org)}</p>',
        f"<h1>{fmt.esc(spec.title)}</h1>",
    ]
    if spec.subtitle:
        parts.append(f'<p class="meta">{fmt.esc(spec.subtitle)}</p>')
    parts.append(_meta_grid(payload.meta))

    for section in spec.sections:
        parts.append(f"<h2>{fmt.esc(section.title)}</h2>")
        if section.description:
            parts.append(f'<p class="prose">{fmt.esc(section.description)}</p>')
        for component in section.components:
            renderer = HTML_RENDERERS.get(component.type)
            if renderer is None:
                continue
            parts.append(renderer(component, payload))

    footer = payload.meta.get("footer") or (
        "Generated by Infosutra · KoboToolbox is source of truth (read-only sync)."
    )
    parts.append(f'<p class="note">{fmt.esc(footer)}</p>')

    return (
        "<!DOCTYPE html>\n"
        f'<html><head><meta charset="utf-8"><title>{fmt.esc(spec.title)}</title>\n'
        f"<style>{fmt.REPORT_CSS}{SPEC_CSS}</style></head><body><div class=\"wrap\">\n"
        + "\n".join(part for part in parts if part)
        + "\n</div></body></html>"
    )


def render_spec_plaintext(payload: RenderPayload) -> str:
    spec = payload.spec
    lines: list[str] = [spec.title]
    if spec.subtitle:
        lines.append(spec.subtitle)
    for label, value in payload.meta.get("rows", []):
        if value:
            lines.append(f"{label}: {value}")
    lines.append("")

    for section in spec.sections:
        lines.append(section.title)
        lines.append("-" * len(section.title))
        for component in section.components:
            if isinstance(component, NarrativeComponent):
                text = (payload.narratives.get(component.id) or "").strip()
                if text:
                    lines.append(text)
                    lines.append("")
                continue
            if isinstance(component, TextComponent):
                lines.append(component.body)
                lines.append("")
                continue
            if isinstance(component, MetricComponent):
                record, error = payload.record_for(component)
                value = error or format_value(
                    record.get(component.field), component.format, component.unit
                )
                lines.append(f"{component.label}: {value}")
                continue
            if isinstance(component, KpiGroupComponent):
                record, error = payload.record_for(component)
                for item in component.items:
                    value = error or format_value(record.get(item.field), item.format, item.unit)
                    lines.append(f"{item.label}: {value}")
                continue
            if isinstance(component, TableComponent):
                rows, error = payload.rows_for(component)
                if component.title:
                    lines.append(component.title)
                if error:
                    lines.append(f"  {error}")
                    continue
                for row in rows:
                    cells = [
                        f"{col.label}={format_value(row.get(col.field), col.format)}"
                        for col in component.columns
                    ]
                    lines.append("  " + " · ".join(cells))
                continue
            if component.title:
                lines.append(component.title)
        lines.append("")
    return "\n".join(lines).strip() + "\n"
