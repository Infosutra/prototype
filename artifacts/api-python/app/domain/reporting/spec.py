"""ReportSpec models (schema version 1.0).

A component binds to a Query IR (or static text / narrative ``uses``), never to
a named report tool id.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.reporting.query import Query
from app.schemas.common import to_camel

ComponentType = Literal[
    "metric",
    "kpi_group",
    "table",
    "chart",
    "progress",
    "narrative",
    "text",
]
ChartKind = Literal[
    "bar",
    "bar_horizontal",
    "stacked_bar",
    "line",
    "area",
    "pie",
    "donut",
]
NarrativeRole = Literal["insight", "warning", "action"]
TextStyle = Literal["prose", "note"]

SPEC_VERSION = "1.0"


class _ForbidCamel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class MetricDisplay(_ForbidCamel):
    label: str
    field: str
    format: str | None = None


class KpiItem(_ForbidCamel):
    label: str
    field: str
    format: str | None = None


class KpiGroupDisplay(_ForbidCamel):
    items: list[KpiItem]


class TableDisplay(_ForbidCamel):
    columns: list[str]
    sort: str | None = None
    empty_text: str | None = None


class ChartDisplay(_ForbidCamel):
    kind: ChartKind
    x: str
    y: list[str]
    series_field: str | None = None
    stacked: bool | None = None
    limit: int | None = None


class ProgressDisplay(_ForbidCamel):
    label_field: str
    value_field: str
    target_field: str


class NarrativeDisplay(_ForbidCamel):
    role: NarrativeRole
    instruction: str
    max_words: int | None = None


class TextDisplay(_ForbidCamel):
    body: str
    style: TextStyle | None = None


_DISPLAY_BY_TYPE: dict[str, type[BaseModel]] = {
    "metric": MetricDisplay,
    "kpi_group": KpiGroupDisplay,
    "table": TableDisplay,
    "chart": ChartDisplay,
    "progress": ProgressDisplay,
    "narrative": NarrativeDisplay,
    "text": TextDisplay,
}


class Component(_ForbidCamel):
    id: str
    type: ComponentType
    query: Query | None = None
    uses: list[str] | None = None
    display: dict[str, Any]

    @model_validator(mode="after")
    def _rules(self) -> Component:
        display_cls = _DISPLAY_BY_TYPE[self.type]
        # Re-validate display with the type-specific model (extra=forbid).
        parsed = display_cls.model_validate(self.display)
        self.display = parsed.model_dump(by_alias=True, exclude_none=True)

        if self.type == "text":
            if self.query is not None:
                raise ValueError("text components must not have a query")
            if self.uses:
                raise ValueError("text components must not use 'uses'")
            return self

        if self.type == "narrative":
            if self.query is None and not self.uses:
                raise ValueError("narrative requires query or uses")
            return self

        if self.query is None:
            raise ValueError(f"{self.type} component requires a query")
        return self


class Section(_ForbidCamel):
    id: str
    title: str
    description: str | None = None
    components: list[Component] = Field(default_factory=list)


class ReportSpec(_ForbidCamel):
    spec_version: Literal["1.0"] = Field(default=SPEC_VERSION, alias="specVersion")
    title: str
    subtitle: str | None = None
    sections: list[Section] = Field(default_factory=list)

    @model_validator(mode="after")
    def _version(self) -> ReportSpec:
        if self.spec_version != SPEC_VERSION:
            raise ValueError(f'specVersion must be "{SPEC_VERSION}"')
        return self
