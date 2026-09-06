"""Deterministic rendering of every specification component across all formats."""

from __future__ import annotations

import pytest

from app.domain.report_spec import COMPONENT_TYPES
from app.domain.report_spec.spec import (
    BarChartComponent,
    ChartSeries,
    HighlightRule,
    KpiGroupComponent,
    KpiItem,
    LineChartComponent,
    MetricComponent,
    NarrativeComponent,
    PieChartComponent,
    ProgressComponent,
    RankingComponent,
    ReportSpec,
    Section,
    SortSpec,
    StackedBarChartComponent,
    TableColumn,
    TableComponent,
    TextComponent,
)
from app.rendering.spec import (
    SUPPORTED_COMPONENTS,
    RenderPayload,
    format_value,
    highlight_matches,
    render_spec_docx,
    render_spec_html,
    render_spec_pdf,
    render_spec_plaintext,
)


def _all_components() -> list:
    return [
        MetricComponent(
            id="m", label="Submissions today", data_source="study_totals", field="newToday", format="int"
        ),
        KpiGroupComponent(
            id="k",
            data_source="study_totals",
            items=[
                KpiItem(label="Today", field="newToday", format="int"),
                KpiItem(label="Flagged", field="flaggedPctToday", format="percent"),
            ],
        ),
        TextComponent(id="t", body="Static guidance for the reader."),
        TableComponent(
            id="tb",
            title="Coverage",
            data_source="tool_coverage",
            columns=[
                TableColumn(field="toolCode", label="Tool"),
                TableColumn(field="cumulative", label="Cumulative", align="right", format="int"),
            ],
            sort=SortSpec(field="cumulative", direction="desc"),
        ),
        RankingComponent(
            id="rk",
            data_source="enumerator_performance_today",
            label_field="enumerator",
            value_field="flagRate",
            value_format="percent",
            highlight=HighlightRule(
                field="flagRate", comparison="above_benchmark", benchmark_field="groupFlagRate"
            ),
        ),
        BarChartComponent(
            id="bar",
            data_source="tool_coverage",
            x="toolCode",
            series=[ChartSeries(field="cumulative", label="Cumulative")],
        ),
        StackedBarChartComponent(
            id="stack",
            data_source="tool_coverage",
            x="toolCode",
            series=[
                ChartSeries(field="redToday", label="RED", color="red"),
                ChartSeries(field="amberToday", label="AMBER", color="amber"),
            ],
        ),
        LineChartComponent(
            id="line",
            data_source="flag_rate_trend",
            x="dayLabel",
            series=[ChartSeries(field="flaggedPct", label="% flagged")],
        ),
        PieChartComponent(
            id="pie", data_source="tool_coverage", label_field="toolCode", value_field="cumulative"
        ),
        ProgressComponent(
            id="prog",
            data_source="tool_coverage",
            label_field="toolCode",
            value_field="cumulative",
            target_field="target",
        ),
        NarrativeComponent(id="ins", type="insight", instruction="Summarise"),
        NarrativeComponent(id="warn", type="warning", instruction="Flag risks"),
        NarrativeComponent(id="act", type="action_plan", instruction="Next steps"),
    ]


def _spec() -> ReportSpec:
    return ReportSpec(
        title="Everything report",
        subtitle="One of each component",
        sections=[Section(id="s", title="All components", components=_all_components())],
    )


def _data() -> dict:
    return {
        "study_totals": {"newToday": 128, "flaggedPctToday": 21.9},
        "tool_coverage": [
            {"toolCode": "T1", "cumulative": 45, "target": 100, "redToday": 1, "amberToday": 1},
            {"toolCode": "T2", "cumulative": 75, "target": 80, "redToday": 1, "amberToday": 2},
        ],
        "enumerator_performance_today": [
            {"enumerator": "Ada", "flagRate": 66.7, "groupFlagRate": 21.9},
            {"enumerator": "Bo", "flagRate": 5.0, "groupFlagRate": 21.9},
        ],
        "flag_rate_trend": [
            {"dayLabel": "D1", "flaggedPct": 10.0},
            {"dayLabel": "D2", "flaggedPct": 15.0},
        ],
    }


def _payload(**overrides) -> RenderPayload:
    kwargs = {
        "spec": _spec(),
        "data": _data(),
        "narratives": {"ins": "Volumes held steady.", "warn": "T1 is behind plan.", "act": "Back-check T1."},
        "errors": {},
        "meta": {"organizationName": "Infosutra", "rows": [("Report", "Daily")]},
    }
    kwargs.update(overrides)
    return RenderPayload(**kwargs)


def test_renderer_covers_the_whole_component_vocabulary() -> None:
    assert SUPPORTED_COMPONENTS == set(COMPONENT_TYPES)


def test_html_renders_every_component() -> None:
    html = render_spec_html(_payload())
    assert "Everything report" in html
    assert "Submissions today" in html
    assert "128" in html
    assert "Coverage" in html
    assert "Volumes held steady." in html
    assert "T1 is behind plan." in html
    assert "Back-check T1." in html
    # Charts are embedded images produced by the application, not model output.
    assert html.count("data:image/png;base64,") == 5


def test_pdf_and_docx_render_every_component() -> None:
    payload = _payload()
    pdf = render_spec_pdf(payload)
    docx = render_spec_docx(payload)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000
    assert docx.startswith(b"PK")
    assert len(docx) > 5000


def test_plaintext_carries_values_and_prose() -> None:
    text = render_spec_plaintext(_payload())
    assert "Everything report" in text
    assert "Submissions today: 128" in text
    assert "Volumes held steady." in text
    assert "Tool=T1" in text


def test_rendering_is_reproducible() -> None:
    assert render_spec_html(_payload()) == render_spec_html(_payload())


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"study_totals": {}, "tool_coverage": [], "enumerator_performance_today": [], "flag_rate_trend": []},
        {
            "study_totals": {"newToday": None},
            "tool_coverage": [{"toolCode": None, "cumulative": None, "target": None}],
            "enumerator_performance_today": [{}],
            "flag_rate_trend": [{"dayLabel": "D1"}],
        },
        {
            "study_totals": [{"wrong": "shape"}],
            "tool_coverage": {"wrong": "shape"},
            "enumerator_performance_today": "nonsense",
            "flag_rate_trend": None,
        },
    ],
    ids=["missing", "empty", "null-values", "wrong-shapes"],
)
def test_degenerate_data_still_renders(data: dict) -> None:
    payload = _payload(data=data)
    html = render_spec_html(payload)
    assert "Everything report" in html
    assert render_spec_pdf(payload).startswith(b"%PDF")
    assert render_spec_docx(payload).startswith(b"PK")


def test_failed_data_source_renders_an_explicit_unavailable_state() -> None:
    payload = _payload(data={}, errors={"study_totals": "Study totals are not available."})
    html = render_spec_html(payload)
    assert "Study totals are not available." in html
    assert 'class="unavailable"' in html


def test_narrative_without_prose_renders_nothing() -> None:
    html = render_spec_html(_payload(narratives={}))
    assert '<div class="callout' not in html
    assert "Volumes held steady." not in html


def test_highlight_only_fires_against_a_benchmark() -> None:
    html = render_spec_html(_payload())
    # Ada (66.7%) is above the 21.9% study average; Bo (5.0%) is not.
    assert 'class="rank-item flagged"' in html
    assert html.count('class="rank-item flagged"') == 1


def test_highlight_is_inert_when_the_benchmark_is_missing() -> None:
    rule = HighlightRule(field="flagRate", comparison="below_benchmark", benchmark_field="groupFlagRate")
    assert highlight_matches({"flagRate": 5.0}, rule) is False
    assert highlight_matches({"groupFlagRate": 5.0}, rule) is False
    assert highlight_matches({"flagRate": 1.0, "groupFlagRate": 5.0}, rule) is True
    assert highlight_matches({"flagRate": 5.0, "groupFlagRate": 5.0}, rule) is False


@pytest.mark.parametrize(
    "value,fmt,expected",
    [
        (1234, "int", "1,234"),
        (12.5, "percent", "12.5%"),
        (12.5, "float", "12.5"),
        ("red", "severity", "RED"),
        (None, "int", "—"),
        ("", "text", "—"),
        ("n/a", "int", "n/a"),
    ],
)
def test_value_formatting(value, fmt, expected) -> None:
    assert format_value(value, fmt) == expected


def test_table_sort_and_limit_are_applied() -> None:
    spec = ReportSpec(
        title="T",
        sections=[
            Section(
                title="S",
                components=[
                    TableComponent(
                        id="tb",
                        data_source="tool_coverage",
                        columns=[TableColumn(field="toolCode", label="Tool")],
                        sort=SortSpec(field="cumulative", direction="desc"),
                        limit=1,
                    )
                ],
            )
        ],
    )
    text = render_spec_plaintext(RenderPayload(spec=spec, data=_data()))
    assert "Tool=T2" in text
    assert "Tool=T1" not in text


def test_severity_column_is_styled_not_recomputed() -> None:
    spec = ReportSpec(
        title="T",
        sections=[
            Section(
                title="S",
                components=[
                    TableComponent(
                        id="tb",
                        data_source="signoff_checklist",
                        columns=[TableColumn(field="severity", label="Severity", format="severity")],
                    )
                ],
            )
        ],
    )
    html = render_spec_html(
        RenderPayload(spec=spec, data={"signoff_checklist": [{"severity": "red"}]})
    )
    assert "sev-red" in html
    assert ">RED<" in html
