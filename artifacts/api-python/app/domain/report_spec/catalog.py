"""Catalog types describing what a specification may reference.

The catalog is the only surface the planner sees: business data sources and their
fields, plus the component vocabulary. The database schema is never exposed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.domain.report_spec.base import SpecModel
from app.domain.report_spec.spec import COMPONENT_MODELS, COMPONENT_TYPES, ReportSpec

FieldType = Literal["string", "int", "float", "percent", "datetime", "bool"]
SourceKind = Literal["object", "table"]
ParamType = Literal["string", "int", "bool"]


class DataField(SpecModel):
    name: str
    label: str
    type: FieldType
    description: str = ""


class DataSourceParam(SpecModel):
    name: str
    type: ParamType = "string"
    required: bool = False
    allowed: list[str] | None = None
    default: Any = None
    description: str = ""


class DataSourceDescriptor(SpecModel):
    """Business-language description of one semantic tool."""

    id: str
    title: str
    description: str
    kind: SourceKind
    fields: list[DataField] = Field(default_factory=list)
    params: list[DataSourceParam] = Field(default_factory=list)
    # How the underlying business terms are defined, surfaced to planner and docs.
    business_definition: str = ""
    # Fields that may legitimately act as a benchmark in a HighlightRule.
    benchmark_fields: list[str] = Field(default_factory=list)
    # True when the tool accepts semantic dateWindow tokens (or equivalent) and can
    # honor an arbitrary reporting window. False = pinned to the execution default bag.
    supports_date_window: bool = False
    # True when the tool's meaningful output is the execution calendar day only
    # (even if the default bag also holds cumulative slices elsewhere).
    execution_day_scoped: bool = False

    def field_names(self) -> set[str]:
        return {f.name for f in self.fields}

    def param(self, name: str) -> DataSourceParam | None:
        for item in self.params:
            if item.name == name:
                return item
        return None


class ComponentDescriptor(SpecModel):
    type: str
    required: list[str]
    optional: list[str]
    #: "object" for single-record sources, "table" for row sources, None if not data-bound.
    source_kind: SourceKind | None = None


class SpecCatalog(SpecModel):
    spec_version: str
    component_types: list[str]
    components: list[ComponentDescriptor]
    data_sources: list[DataSourceDescriptor]
    spec_schema: dict[str, Any] = Field(default_factory=dict)


_OBJECT_COMPONENTS = frozenset({"metric", "kpi_group"})
_UNBOUND_COMPONENTS = frozenset({"text", "insight", "warning", "action_plan"})


def component_catalog() -> list[ComponentDescriptor]:
    """Per-component key lists derived from the models themselves."""
    out: list[ComponentDescriptor] = []
    for type_name in COMPONENT_TYPES:
        model = COMPONENT_MODELS[type_name]
        required: list[str] = []
        optional: list[str] = []
        for name, info in model.model_fields.items():
            if name in {"id", "type"}:
                continue
            alias = info.alias or name
            (required if info.is_required() else optional).append(alias)
        kind: SourceKind | None = None
        if type_name not in _UNBOUND_COMPONENTS:
            kind = "object" if type_name in _OBJECT_COMPONENTS else "table"
        out.append(
            ComponentDescriptor(
                type=type_name,
                required=sorted(required),
                optional=sorted(optional),
                source_kind=kind,
            )
        )
    return out


def build_catalog(
    sources: list[DataSourceDescriptor], *, include_schema: bool = False
) -> SpecCatalog:
    from app.domain.report_spec.spec import SPEC_VERSION

    return SpecCatalog(
        spec_version=SPEC_VERSION,
        component_types=list(COMPONENT_TYPES),
        components=component_catalog(),
        data_sources=sources,
        spec_schema=ReportSpec.model_json_schema() if include_schema else {},
    )


def sources_by_id(
    sources: list[DataSourceDescriptor],
) -> dict[str, DataSourceDescriptor]:
    return {source.id: source for source in sources}
