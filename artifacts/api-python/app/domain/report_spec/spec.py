"""Strongly typed, versionable Report Specification.

The specification says WHAT a report contains. It never carries concrete dates,
data values, SQL, or presentation markup — those come from the execution context,
the semantic tool layer, and the deterministic renderer respectively.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from app.domain.report_spec import limits
from app.domain.report_spec.base import SpecModel

SPEC_VERSION = "1.0"

ValueFormat = Literal["int", "float", "percent", "text", "date", "datetime", "severity"]
Align = Literal["left", "center", "right"]
SeriesColor = Literal["teal", "red", "amber", "steel", "muted"]

ParamValue = Union[str, int, float, bool]


class SortSpec(SpecModel):
    field: str
    direction: Literal["asc", "desc"] = "desc"


class DataBound(SpecModel):
    """Mixin-ish base for components that read from a registered data source."""

    data_source: str
    params: dict[str, ParamValue] = Field(default_factory=dict)


class ComponentBase(SpecModel):
    id: str = ""
    title: str | None = Field(default=None, max_length=limits.MAX_TITLE_CHARS)


# --- Value components -------------------------------------------------------


class MetricComponent(ComponentBase, DataBound):
    type: Literal["metric"] = "metric"
    label: str
    field: str
    format: ValueFormat = "text"
    unit: str | None = None
    caption: str | None = None


class KpiItem(SpecModel):
    label: str
    field: str
    format: ValueFormat = "int"
    unit: str | None = None


class KpiGroupComponent(ComponentBase, DataBound):
    type: Literal["kpi_group"] = "kpi_group"
    items: list[KpiItem] = Field(min_length=1, max_length=limits.MAX_KPI_ITEMS)


class TextComponent(ComponentBase):
    """Static author-provided prose. Not generated at execution time."""

    type: Literal["text"] = "text"
    body: str = Field(max_length=limits.MAX_TEXT_CHARS)
    style: Literal["prose", "note", "caption"] = "prose"


# --- Tabular ----------------------------------------------------------------


class TableColumn(SpecModel):
    field: str
    label: str
    align: Align = "left"
    format: ValueFormat = "text"


class TableComponent(ComponentBase, DataBound):
    type: Literal["table"] = "table"
    columns: list[TableColumn] = Field(min_length=1, max_length=limits.MAX_TABLE_COLUMNS)
    sort: SortSpec | None = None
    limit: int = Field(default=25, ge=1, le=limits.MAX_TABLE_ROWS)
    total_row: bool = False
    empty_text: str = "No data."


class RankingComponent(ComponentBase, DataBound):
    type: Literal["ranking"] = "ranking"
    label_field: str
    value_field: str
    value_format: ValueFormat = "int"
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=5, ge=1, le=25)
    highlight: HighlightRule | None = None


# --- Charts -----------------------------------------------------------------


class ChartSeries(SpecModel):
    field: str
    label: str
    color: SeriesColor | None = None


class CategoryChartComponent(ComponentBase, DataBound):
    """Shared shape for bar / stacked bar / line charts."""

    x: str
    series: list[ChartSeries] = Field(min_length=1, max_length=limits.MAX_CHART_SERIES)
    y_label: str | None = None
    sort: SortSpec | None = None
    limit: int = Field(default=20, ge=1, le=limits.MAX_CHART_POINTS)
    caption: str | None = None


class BarChartComponent(CategoryChartComponent):
    type: Literal["bar_chart"] = "bar_chart"
    orientation: Literal["vertical", "horizontal"] = "vertical"


class StackedBarChartComponent(CategoryChartComponent):
    type: Literal["stacked_bar_chart"] = "stacked_bar_chart"


class LineChartComponent(CategoryChartComponent):
    type: Literal["line_chart"] = "line_chart"
    area: bool = True


class PieChartComponent(ComponentBase, DataBound):
    type: Literal["pie_chart"] = "pie_chart"
    label_field: str
    value_field: str
    donut: bool = False
    limit: int = Field(default=8, ge=2, le=12)
    caption: str | None = None


class ProgressComponent(ComponentBase, DataBound):
    type: Literal["progress"] = "progress"
    label_field: str
    value_field: str
    target_field: str
    limit: int = Field(default=10, ge=1, le=25)
    caption: str | None = None


# --- Narrative (LLM-authored prose, never numbers) --------------------------


class HighlightRule(SpecModel):
    """Comparison against an authoritative benchmark carried by the data itself.

    A spec may not invent a numeric threshold: `benchmark_field` must name a field
    the data source actually returns (a configured target, plan value, or group
    median). Only `comparison` and the two field names are author-controlled.
    """

    field: str
    comparison: Literal["below_benchmark", "above_benchmark"]
    benchmark_field: str
    label: str = "Below expectation"


class NarrativeComponent(ComponentBase):
    type: Literal["insight", "warning", "action_plan"]
    instruction: str = Field(max_length=limits.MAX_INSTRUCTION_CHARS)
    data_sources: list[str] = Field(default_factory=list, max_length=6)
    fallback: str | None = None
    max_words: int = Field(default=180, ge=20, le=limits.MAX_NARRATIVE_WORDS)


Component = Annotated[
    Union[
        MetricComponent,
        KpiGroupComponent,
        TextComponent,
        TableComponent,
        RankingComponent,
        BarChartComponent,
        StackedBarChartComponent,
        LineChartComponent,
        PieChartComponent,
        ProgressComponent,
        NarrativeComponent,
    ],
    Field(discriminator="type"),
]

COMPONENT_TYPES: tuple[str, ...] = (
    "metric",
    "kpi_group",
    "text",
    "table",
    "ranking",
    "bar_chart",
    "stacked_bar_chart",
    "line_chart",
    "pie_chart",
    "progress",
    "insight",
    "warning",
    "action_plan",
)

NARRATIVE_TYPES: frozenset[str] = frozenset({"insight", "warning", "action_plan"})

#: Component type to its model, used to derive the planner's vocabulary so the
#: prompt cannot drift from the schema.
COMPONENT_MODELS: dict[str, type[SpecModel]] = {
    "metric": MetricComponent,
    "kpi_group": KpiGroupComponent,
    "text": TextComponent,
    "table": TableComponent,
    "ranking": RankingComponent,
    "bar_chart": BarChartComponent,
    "stacked_bar_chart": StackedBarChartComponent,
    "line_chart": LineChartComponent,
    "pie_chart": PieChartComponent,
    "progress": ProgressComponent,
    "insight": NarrativeComponent,
    "warning": NarrativeComponent,
    "action_plan": NarrativeComponent,
}


class Section(SpecModel):
    id: str = ""
    title: str = Field(max_length=limits.MAX_TITLE_CHARS)
    description: str | None = Field(default=None, max_length=limits.MAX_TEXT_CHARS)
    components: list[Component] = Field(
        default_factory=list, max_length=limits.MAX_COMPONENTS_PER_SECTION
    )


class ReportSpec(SpecModel):
    spec_version: str = SPEC_VERSION
    title: str = Field(max_length=limits.MAX_TITLE_CHARS)
    subtitle: str | None = Field(default=None, max_length=limits.MAX_TITLE_CHARS)
    sections: list[Section] = Field(default_factory=list, max_length=limits.MAX_SECTIONS)

    @model_validator(mode="after")
    def _assign_ids(self) -> ReportSpec:
        """Stable ids let conversational patches target sections and components."""
        seen: set[str] = set()
        for s_idx, section in enumerate(self.sections, start=1):
            if not section.id:
                section.id = f"s{s_idx}"
            while section.id in seen:
                section.id = f"{section.id}x"
            seen.add(section.id)
            for c_idx, component in enumerate(section.components, start=1):
                if not component.id:
                    component.id = f"{section.id}c{c_idx}"
                while component.id in seen:
                    component.id = f"{component.id}x"
                seen.add(component.id)
        return self

    def iter_components(self):
        for section in self.sections:
            for component in section.components:
                yield section, component

    def component_count(self) -> int:
        return sum(len(section.components) for section in self.sections)

    def data_source_ids(self) -> list[str]:
        ids: list[str] = []
        for _section, component in self.iter_components():
            if isinstance(component, NarrativeComponent):
                ids.extend(component.data_sources)
            elif isinstance(component, DataBound):
                ids.append(component.data_source)
        seen: set[str] = set()
        unique: list[str] = []
        for value in ids:
            if value not in seen:
                seen.add(value)
                unique.append(value)
        return unique


RankingComponent.model_rebuild()
