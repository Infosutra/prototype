"""Validation and safe repair for Report Specifications.

Nothing produced by an LLM reaches execution without passing through here: unknown
components, unknown data sources, unknown fields, bad params, oversized requests
and frozen literal dates are all rejected.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from app.domain.report_spec import limits
from app.domain.report_spec.base import SpecModel
from app.domain.report_spec.catalog import DataSourceDescriptor
from app.domain.report_spec.spec import (
    SPEC_VERSION,
    CategoryChartComponent,
    DataBound,
    KpiGroupComponent,
    MetricComponent,
    NarrativeComponent,
    PieChartComponent,
    ProgressComponent,
    RankingComponent,
    ReportSpec,
    Section,
    TableColumn,
    TableComponent,
    TextComponent,
)
from app.domain.reporting.query_aggregate_catalog import (
    DEFAULT_RANGE_TOKEN,
    ENTITY_DIMENSIONS,
    ENTITY_MEASURE_FIELDS,
    HARD_MAX_LIMIT,
    HIGH_CARDINALITY_GROUP_BY,
    MAX_DISTINCT_DATE_RANGES,
    MAX_GROUP_BY_FIELDS,
    MEASURES_REQUIRING_FIELD,
    parse_group_by,
    semantic_date_range_token,
)

_LITERAL_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_UNSAFE_MARKUP = re.compile(
    r"<\s*(script|style|iframe|object|link|meta)\b|javascript:|onerror\s*=|onload\s*=",
    re.IGNORECASE,
)
_UNSAFE_SQL = re.compile(
    r"\b(select\s+.+\s+from|drop\s+table|insert\s+into|union\s+select|delete\s+from)\b",
    re.IGNORECASE,
)
# LLMs sometimes invent mustache/template syntax in text bodies; the renderer never
# interpolates these — figures must come from metric / kpi_group / table / charts.
_TEMPLATE_PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}|\$\{[^{}]+\}")
# LLMs sometimes emit a text caption that describes a table/KPI instead of the
# real data-bound component (ids like "kpi-group", bodies like "This table shows…").
_TEXT_STANDS_IN_FOR_DATA = re.compile(
    r"(^|[-_\s])(kpi|kpis|table|chart|metric|ranking|progress|heatmap)([-_\s]|$)",
    re.IGNORECASE,
)
_TEXT_DESCRIBES_DATA = re.compile(
    r"\b(this (table|section|chart|kpi)|headline numbers|lists each|shows,? for each)\b",
    re.IGNORECASE,
)

# Common planner synonyms mapped onto supported component types. Applied before
# parsing so a near-miss becomes a warning instead of a hard failure.
TYPE_ALIASES: dict[str, str] = {
    "kpi": "metric",
    "card": "metric",
    "number": "metric",
    "kpi_cards": "kpi_group",
    "kpis": "kpi_group",
    "paragraph": "text",
    "markdown": "text",
    "column_chart": "bar_chart",
    "horizontal_bar_chart": "bar_chart",
    "histogram": "bar_chart",
    "grouped_bar_chart": "bar_chart",
    "area_chart": "line_chart",
    "trend_chart": "line_chart",
    "donut_chart": "pie_chart",
    "doughnut_chart": "pie_chart",
    "gauge": "progress",
    "progress_bar": "progress",
    "leaderboard": "ranking",
    "top_list": "ranking",
    "summary": "insight",
    "narrative": "insight",
    "alert": "warning",
    "risk": "warning",
    "recommendation": "action_plan",
    "recommendations": "action_plan",
    "actions": "action_plan",
}

_OBJECT_COMPONENTS = ("metric", "kpi_group")


class SpecIssue(SpecModel):
    path: str
    code: str
    message: str


class SpecValidationResult(SpecModel):
    valid: bool
    errors: list[SpecIssue] = []
    warnings: list[SpecIssue] = []

    def error_dicts(self) -> list[dict[str, str]]:
        return [issue.model_dump(by_alias=False) for issue in self.errors]


class SpecParseResult(SpecModel):
    spec: ReportSpec | None = None
    errors: list[SpecIssue] = []
    warnings: list[SpecIssue] = []


def normalize_payload(payload: Any) -> tuple[Any, list[SpecIssue]]:
    """Map component-type synonyms onto supported types before parsing."""
    warnings: list[SpecIssue] = []

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, dict):
            out = {}
            for key, value in node.items():
                if key == "type" and isinstance(value, str):
                    lowered = value.strip().lower()
                    mapped = TYPE_ALIASES.get(lowered, lowered)
                    if mapped != lowered:
                        warnings.append(
                            SpecIssue(
                                path=path,
                                code="type_aliased",
                                message=f"Mapped unsupported component '{value}' to '{mapped}'.",
                            )
                        )
                    out[key] = mapped
                else:
                    out[key] = walk(value, f"{path}.{key}" if path else key)
            return out
        if isinstance(node, list):
            return [walk(item, f"{path}[{idx}]") for idx, item in enumerate(node)]
        return node

    return walk(payload, ""), warnings


def parse_spec(payload: Any) -> SpecParseResult:
    """Parse untrusted JSON into a ReportSpec, collecting structured errors."""
    normalized, warnings = normalize_payload(payload)
    if not isinstance(normalized, dict):
        return SpecParseResult(
            errors=[SpecIssue(path="", code="not_an_object", message="Specification must be a JSON object.")],
            warnings=warnings,
        )
    try:
        spec = ReportSpec.model_validate(normalized)
    except ValidationError as exc:
        errors = [
            SpecIssue(
                path=".".join(str(part) for part in err.get("loc", ())),
                code=str(err.get("type") or "invalid"),
                message=str(err.get("msg") or "Invalid value"),
            )
            for err in exc.errors()
        ]
        return SpecParseResult(errors=errors, warnings=warnings)
    return SpecParseResult(spec=spec, warnings=warnings)


def _check_literal_dates(spec: ReportSpec) -> list[SpecIssue]:
    issues: list[SpecIssue] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, str):
            if _LITERAL_DATE.search(node):
                issues.append(
                    SpecIssue(
                        path=path,
                        code="literal_date",
                        message=(
                            "Specifications must not contain literal dates; the execution "
                            "context supplies the reporting period."
                        ),
                    )
                )
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                walk(item, f"{path}[{idx}]")

    walk(spec.model_dump(by_alias=True), "")
    return issues


def _presentation_text_issues(component: Any, path: str) -> list[SpecIssue]:
    """Reject markup, SQL, or invented template placeholders in presentation text."""
    issues: list[SpecIssue] = []
    texts: list[tuple[str, str]] = []
    if isinstance(component, NarrativeComponent):
        texts.append((f"{path}.instruction", component.instruction or ""))
        if component.fallback:
            texts.append((f"{path}.fallback", component.fallback))
    body = getattr(component, "body", None)
    if isinstance(body, str):
        texts.append((f"{path}.body", body))
    for field_path, text in texts:
        if _TEMPLATE_PLACEHOLDER.search(text):
            issues.append(
                SpecIssue(
                    path=field_path,
                    code="template_placeholder",
                    message=(
                        "Component text cannot contain {{placeholders}} or ${...}; "
                        "use metric, kpi_group, table or chart components with a dataSource "
                        "and field names from the catalog."
                    ),
                )
            )
        elif _UNSAFE_MARKUP.search(text) or _UNSAFE_SQL.search(text):
            issues.append(
                SpecIssue(
                    path=field_path,
                    code="unsafe_content",
                    message=(
                        "Component text cannot contain markup, scripts or SQL; "
                        "the renderer owns presentation."
                    ),
                )
            )
    return issues


def _check_unsafe_content(spec: ReportSpec) -> list[SpecIssue]:
    """Reject markup, SQL, or template placeholders smuggled into presentation text."""
    issues: list[SpecIssue] = []
    for s_idx, section in enumerate(spec.sections):
        for c_idx, component in enumerate(section.components):
            path = f"sections[{s_idx}].components[{c_idx}]"
            issues.extend(_presentation_text_issues(component, path))
    return issues


def _check_text_standing_in_for_data(spec: ReportSpec) -> list[SpecIssue]:
    """Reject text components that are captions for missing tables/KPIs."""
    issues: list[SpecIssue] = []
    for s_idx, section in enumerate(spec.sections):
        for c_idx, component in enumerate(section.components):
            if not isinstance(component, TextComponent):
                continue
            path = f"sections[{s_idx}].components[{c_idx}]"
            identity = " ".join(
                part for part in (component.id or "", component.title or "") if part
            )
            body = component.body or ""
            if _TEXT_STANDS_IN_FOR_DATA.search(identity) or _TEXT_DESCRIBES_DATA.search(body):
                issues.append(
                    SpecIssue(
                        path=path,
                        code="text_standing_in_for_data",
                        message=(
                            "Do not use a text component to describe a KPI, table or chart. "
                            "Emit the actual metric, kpi_group, table, ranking, progress or "
                            "chart component with a dataSource and catalog field names."
                        ),
                    )
                )
    return issues


def _check_has_retrievable_content(spec: ReportSpec) -> list[SpecIssue]:
    """A report must retrieve data somehow — not only static text captions."""
    for section in spec.sections:
        for component in section.components:
            if isinstance(component, DataBound):
                return []
            if isinstance(component, NarrativeComponent) and component.data_sources:
                return []
    if not any(section.components for section in spec.sections):
        return []
    return [
        SpecIssue(
            path="sections",
            code="no_data_bound_content",
            message=(
                "The specification has no data-bound components. Add at least one metric, "
                "kpi_group, table, ranking, chart, progress, or narrative with dataSources."
            ),
        )
    ]


def _check_params(
    component: DataBound, source: DataSourceDescriptor, path: str
) -> list[SpecIssue]:
    issues: list[SpecIssue] = []
    for name, value in (component.params or {}).items():
        param = source.param(name)
        if param is None:
            issues.append(
                SpecIssue(
                    path=f"{path}.params.{name}",
                    code="unknown_param",
                    message=f"'{source.id}' does not accept parameter '{name}'.",
                )
            )
            continue
        if param.allowed is not None and str(value) not in param.allowed:
            issues.append(
                SpecIssue(
                    path=f"{path}.params.{name}",
                    code="param_not_allowed",
                    message=(
                        f"'{value}' is not valid for '{name}'. Allowed: {', '.join(param.allowed)}."
                    ),
                )
            )
        if param.type == "int" and not isinstance(value, int):
            issues.append(
                SpecIssue(
                    path=f"{path}.params.{name}",
                    code="param_type",
                    message=f"Parameter '{name}' must be an integer.",
                )
            )
        if param.type == "bool" and not isinstance(value, bool):
            issues.append(
                SpecIssue(
                    path=f"{path}.params.{name}",
                    code="param_type",
                    message=f"Parameter '{name}' must be a boolean.",
                )
            )
    for param in source.params:
        if param.required and param.name not in (component.params or {}):
            issues.append(
                SpecIssue(
                    path=f"{path}.params.{param.name}",
                    code="param_required",
                    message=f"'{source.id}' requires parameter '{param.name}'.",
                )
            )
    if source.id == "query_aggregate":
        issues.extend(_check_query_aggregate_params(component, path))
    return issues


def _check_query_aggregate_params(component: DataBound, path: str) -> list[SpecIssue]:
    """Cross-field allowlists for query_aggregate beyond generic param checks."""
    issues: list[SpecIssue] = []
    params = component.params or {}
    entity = str(params["entity"]).strip() if "entity" in params else None
    measure = str(params["measure"]).strip() if "measure" in params else None
    dimensions = ENTITY_DIMENSIONS.get(entity or "", frozenset())
    measure_fields = ENTITY_MEASURE_FIELDS.get(entity or "", frozenset())

    group_by = parse_group_by(params.get("groupBy"))
    if len(group_by) > MAX_GROUP_BY_FIELDS:
        issues.append(
            SpecIssue(
                path=f"{path}.params.groupBy",
                code="query_aggregate_group_by_too_many",
                message=(
                    f"groupBy may list at most {MAX_GROUP_BY_FIELDS} fields; "
                    f"got {len(group_by)}."
                ),
            )
        )
    for field in group_by:
        if field in HIGH_CARDINALITY_GROUP_BY:
            issues.append(
                SpecIssue(
                    path=f"{path}.params.groupBy",
                    code="query_aggregate_group_by_high_cardinality",
                    message=(
                        f"'{field}' is not allowed as a groupBy target "
                        "(high-cardinality identifiers are rejected)."
                    ),
                )
            )
        elif entity is not None and field not in dimensions:
            allowed = ", ".join(sorted(dimensions)) or "none"
            issues.append(
                SpecIssue(
                    path=f"{path}.params.groupBy",
                    code="query_aggregate_group_by_unknown",
                    message=(
                        f"'{field}' is not an allowlisted dimension for entity "
                        f"'{entity}'. Allowed: {allowed}."
                    ),
                )
            )

    measure_field_raw = params.get("measureField")
    measure_field = (
        str(measure_field_raw).strip()
        if measure_field_raw not in (None, "")
        else None
    )
    if measure in MEASURES_REQUIRING_FIELD:
        if not measure_field:
            issues.append(
                SpecIssue(
                    path=f"{path}.params.measureField",
                    code="query_aggregate_measure_field_required",
                    message=f"measure '{measure}' requires measureField.",
                )
            )
        elif entity is not None and measure_field not in measure_fields:
            allowed = ", ".join(sorted(measure_fields)) or "none"
            issues.append(
                SpecIssue(
                    path=f"{path}.params.measureField",
                    code="query_aggregate_measure_field_unknown",
                    message=(
                        f"'{measure_field}' is not an allowlisted measureField for "
                        f"entity '{entity}'. Allowed: {allowed}."
                    ),
                )
            )

    filter_field_raw = params.get("filterField")
    filter_field = (
        str(filter_field_raw).strip()
        if filter_field_raw not in (None, "")
        else None
    )
    filter_value = params.get("filterValue")
    has_filter_value = filter_value not in (None, "")
    if filter_field:
        if entity is not None and filter_field not in dimensions:
            allowed = ", ".join(sorted(dimensions)) or "none"
            issues.append(
                SpecIssue(
                    path=f"{path}.params.filterField",
                    code="query_aggregate_filter_field_unknown",
                    message=(
                        f"'{filter_field}' is not an allowlisted filterField for "
                        f"entity '{entity}'. Allowed: {allowed}."
                    ),
                )
            )
        if not has_filter_value:
            issues.append(
                SpecIssue(
                    path=f"{path}.params.filterValue",
                    code="query_aggregate_filter_incomplete",
                    message="filterField requires filterValue.",
                )
            )
    elif has_filter_value:
        issues.append(
            SpecIssue(
                path=f"{path}.params.filterField",
                code="query_aggregate_filter_incomplete",
                message="filterValue requires filterField.",
            )
        )

    if "limit" in params:
        limit = params["limit"]
        if isinstance(limit, int) and limit > HARD_MAX_LIMIT:
            issues.append(
                SpecIssue(
                    path=f"{path}.params.limit",
                    code="query_aggregate_limit_too_high",
                    message=(
                        f"limit {limit} exceeds the hard maximum of {HARD_MAX_LIMIT}."
                    ),
                )
            )
        elif isinstance(limit, int) and limit < 0:
            issues.append(
                SpecIssue(
                    path=f"{path}.params.limit",
                    code="query_aggregate_limit_invalid",
                    message="limit must be a non-negative integer.",
                )
            )

    return issues


def _iter_data_bound_components(spec: ReportSpec) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for s_idx, section in enumerate(spec.sections):
        for c_idx, component in enumerate(section.components):
            path = f"sections[{s_idx}].components[{c_idx}]"
            out.append((path, component))
    return out


def _check_distinct_date_ranges(spec: ReportSpec) -> list[SpecIssue]:
    """Option A: at most MAX_DISTINCT_DATE_RANGES distinct resolved ranges per spec.

    Certified tools always use the default/context bag. ``query_aggregate``
    contributes ``default`` when dateWindow is omitted, otherwise its token.
    """
    tokens: set[str] = set()
    for _path, component in _iter_data_bound_components(spec):
        if isinstance(component, NarrativeComponent):
            for source_id in component.data_sources:
                # Narratives cannot pass per-source dateWindow params.
                if source_id:
                    tokens.add(DEFAULT_RANGE_TOKEN)
            continue
        if not isinstance(component, DataBound):
            continue
        if component.data_source == "query_aggregate":
            tokens.add(semantic_date_range_token((component.params or {}).get("dateWindow")))
        else:
            tokens.add(DEFAULT_RANGE_TOKEN)

    if len(tokens) <= MAX_DISTINCT_DATE_RANGES:
        return []
    listed = ", ".join(sorted(tokens))
    return [
        SpecIssue(
            path="sections",
            code="too_many_date_ranges",
            message=(
                "too many distinct date ranges requested — max "
                f"{MAX_DISTINCT_DATE_RANGES} per report (found {len(tokens)}: {listed}). "
                "Use at most one non-default dateWindow alongside certified tools, "
                "or at most two dateWindow tokens with no certified default sources."
            ),
        )
    ]

def _check_fields(
    source: DataSourceDescriptor, names: list[tuple[str, str]], path: str
) -> list[SpecIssue]:
    known = source.field_names()
    issues: list[SpecIssue] = []
    for label, name in names:
        if name not in known:
            issues.append(
                SpecIssue(
                    path=f"{path}.{label}",
                    code="unknown_field",
                    message=(
                        f"'{source.id}' has no field '{name}'. "
                        f"Available: {', '.join(sorted(known))}."
                    ),
                )
            )
    return issues


def _component_issues(
    component: Any,
    sources: dict[str, DataSourceDescriptor],
    path: str,
) -> list[SpecIssue]:
    issues: list[SpecIssue] = []

    if isinstance(component, NarrativeComponent):
        for idx, source_id in enumerate(component.data_sources):
            if source_id not in sources:
                issues.append(
                    SpecIssue(
                        path=f"{path}.dataSources[{idx}]",
                        code="unknown_data_source",
                        message=f"Unknown data source '{source_id}'.",
                    )
                )
        return issues

    if not isinstance(component, DataBound):
        return issues

    source = sources.get(component.data_source)
    if source is None:
        return [
            SpecIssue(
                path=f"{path}.dataSource",
                code="unknown_data_source",
                message=f"Unknown data source '{component.data_source}'.",
            )
        ]

    expects_object = component.type in _OBJECT_COMPONENTS
    if expects_object and source.kind != "object":
        issues.append(
            SpecIssue(
                path=f"{path}.dataSource",
                code="source_kind_mismatch",
                message=f"'{component.type}' needs a single-record source; '{source.id}' returns rows.",
            )
        )
    if not expects_object and source.kind != "table":
        issues.append(
            SpecIssue(
                path=f"{path}.dataSource",
                code="source_kind_mismatch",
                message=f"'{component.type}' needs a row source; '{source.id}' returns a single record.",
            )
        )

    issues.extend(_check_params(component, source, path))

    if isinstance(component, MetricComponent):
        issues.extend(_check_fields(source, [("field", component.field)], path))
    elif isinstance(component, KpiGroupComponent):
        issues.extend(
            _check_fields(
                source,
                [(f"items[{i}].field", item.field) for i, item in enumerate(component.items)],
                path,
            )
        )
    elif isinstance(component, TableComponent):
        issues.extend(
            _check_fields(
                source,
                [(f"columns[{i}].field", col.field) for i, col in enumerate(component.columns)],
                path,
            )
        )
        if component.sort:
            issues.extend(_check_fields(source, [("sort.field", component.sort.field)], path))
    elif isinstance(component, RankingComponent):
        issues.extend(
            _check_fields(
                source,
                [("labelField", component.label_field), ("valueField", component.value_field)],
                path,
            )
        )
        if component.highlight:
            issues.extend(
                _check_fields(
                    source,
                    [
                        ("highlight.field", component.highlight.field),
                        ("highlight.benchmarkField", component.highlight.benchmark_field),
                    ],
                    path,
                )
            )
            if component.highlight.benchmark_field not in source.benchmark_fields:
                issues.append(
                    SpecIssue(
                        path=f"{path}.highlight.benchmarkField",
                        code="not_a_benchmark",
                        message=(
                            f"'{component.highlight.benchmark_field}' is not an authoritative "
                            f"benchmark for '{source.id}'. Allowed: "
                            f"{', '.join(source.benchmark_fields) or 'none'}."
                        ),
                    )
                )
    elif isinstance(component, CategoryChartComponent):
        names = [("x", component.x)]
        names += [(f"series[{i}].field", s.field) for i, s in enumerate(component.series)]
        if component.sort:
            names.append(("sort.field", component.sort.field))
        issues.extend(_check_fields(source, names, path))
    elif isinstance(component, PieChartComponent):
        issues.extend(
            _check_fields(
                source,
                [("labelField", component.label_field), ("valueField", component.value_field)],
                path,
            )
        )
    elif isinstance(component, ProgressComponent):
        issues.extend(
            _check_fields(
                source,
                [
                    ("labelField", component.label_field),
                    ("valueField", component.value_field),
                    ("targetField", component.target_field),
                ],
                path,
            )
        )
    return issues


def validate_spec(
    spec: ReportSpec, sources: dict[str, DataSourceDescriptor]
) -> SpecValidationResult:
    errors: list[SpecIssue] = []
    warnings: list[SpecIssue] = []

    if spec.spec_version != SPEC_VERSION:
        errors.append(
            SpecIssue(
                path="specVersion",
                code="unsupported_version",
                message=f"Unsupported spec version '{spec.spec_version}'; expected '{SPEC_VERSION}'.",
            )
        )
    if not spec.sections:
        errors.append(
            SpecIssue(path="sections", code="empty", message="A report needs at least one section.")
        )

    total = spec.component_count()
    if total > limits.MAX_COMPONENTS_TOTAL:
        errors.append(
            SpecIssue(
                path="sections",
                code="too_many_components",
                message=f"{total} components exceeds the limit of {limits.MAX_COMPONENTS_TOTAL}.",
            )
        )
    used_sources = spec.data_source_ids()
    if len(used_sources) > limits.MAX_DATA_SOURCES_PER_SPEC:
        errors.append(
            SpecIssue(
                path="sections",
                code="too_many_data_sources",
                message=(
                    f"{len(used_sources)} data sources exceeds the limit of "
                    f"{limits.MAX_DATA_SOURCES_PER_SPEC}."
                ),
            )
        )

    for s_idx, section in enumerate(spec.sections):
        if not section.components:
            warnings.append(
                SpecIssue(
                    path=f"sections[{s_idx}]",
                    code="empty_section",
                    message=f"Section '{section.title}' has no components.",
                )
            )
        for c_idx, component in enumerate(section.components):
            path = f"sections[{s_idx}].components[{c_idx}]"
            errors.extend(_component_issues(component, sources, path))

    errors.extend(_check_literal_dates(spec))
    errors.extend(_check_distinct_date_ranges(spec))
    errors.extend(_check_unsafe_content(spec))
    errors.extend(_check_text_standing_in_for_data(spec))
    errors.extend(_check_has_retrievable_content(spec))

    return SpecValidationResult(valid=not errors, errors=errors, warnings=warnings)


def _table_columns_for_source(
    source: DataSourceDescriptor, params: dict[str, Any] | None
) -> list[TableColumn]:
    """Best-effort columns when coercing a metric/kpi_group onto a row source."""
    params = params or {}
    if source.id == "query_aggregate":
        columns = [
            TableColumn(field=name, label=name)
            for name in parse_group_by(params.get("groupBy"))
        ]
        columns.append(TableColumn(field="value", label="Value", format="int"))
        return columns
    if source.id == "top_failing_rules":
        return [
            TableColumn(field="ruleId", label="Rule"),
            TableColumn(field="title", label="Check"),
            TableColumn(field="severity", label="Severity", format="severity"),
            TableColumn(field="count", label="Records", format="int", align="right"),
        ]
    columns: list[TableColumn] = []
    for field in source.fields[:6]:
        fmt = field.type if field.type in {"int", "float", "percent", "text", "date", "datetime", "severity"} else "text"
        columns.append(
            TableColumn(
                field=field.name,
                label=field.label or field.name,
                format=fmt,  # type: ignore[arg-type]
            )
        )
    return columns or [TableColumn(field=source.fields[0].name, label=source.fields[0].label)]


def _coerce_object_component_to_table(
    component: Any, sources: dict[str, DataSourceDescriptor]
) -> TableComponent | None:
    """If metric/kpi_group was bound to a table source, rewrite as a table.

    Reduces planner flakiness where models pick the right dataSource but the wrong
    component kind (especially query_aggregate).
    """
    if not isinstance(component, (MetricComponent, KpiGroupComponent)):
        return None
    source = sources.get(component.data_source)
    if source is None or source.kind != "table":
        return None
    columns = _table_columns_for_source(source, component.params)
    if not columns:
        return None
    return TableComponent(
        id=component.id or "",
        title=component.title,
        data_source=component.data_source,
        params=dict(component.params or {}),
        columns=columns,
    )


def repair_spec(
    spec: ReportSpec, sources: dict[str, DataSourceDescriptor]
) -> tuple[ReportSpec, list[SpecIssue]]:
    """Drop components that cannot execute, keeping the rest of the report usable.

    Used when a planner has exhausted its repair attempts but produced a mostly
    sound specification, and when a data source is retired from the catalog.
    """
    notes: list[SpecIssue] = []
    sections: list[Section] = []
    for s_idx, section in enumerate(spec.sections):
        kept = []
        for c_idx, component in enumerate(section.components):
            path = f"sections[{s_idx}].components[{c_idx}]"
            issues = _component_issues(component, sources, path)
            issues.extend(_presentation_text_issues(component, path))
            if isinstance(component, TextComponent):
                identity = " ".join(
                    part for part in (component.id or "", component.title or "") if part
                )
                body = component.body or ""
                if _TEXT_STANDS_IN_FOR_DATA.search(identity) or _TEXT_DESCRIBES_DATA.search(
                    body
                ):
                    issues.append(
                        SpecIssue(
                            path=path,
                            code="text_standing_in_for_data",
                            message=(
                                "Do not use a text component to describe a KPI, table or chart. "
                                "Emit the actual metric, kpi_group, table, ranking, progress or "
                                "chart component with a dataSource and catalog field names."
                            ),
                        )
                    )
            if issues and all(i.code == "source_kind_mismatch" for i in issues):
                coerced = _coerce_object_component_to_table(component, sources)
                if coerced is not None:
                    coerced_issues = _component_issues(coerced, sources, path)
                    if not coerced_issues:
                        kept.append(coerced)
                        notes.append(
                            SpecIssue(
                                path=path,
                                code="component_coerced_to_table",
                                message=(
                                    f"Rewrote {component.type} as table for row source "
                                    f"'{component.data_source}'."
                                ),
                            )
                        )
                        continue
            if issues:
                notes.append(
                    SpecIssue(
                        path=path,
                        code="component_dropped",
                        message=(
                            f"Removed {component.type} component: {issues[0].message}"
                        ),
                    )
                )
                continue
            kept.append(component)
        if kept:
            sections.append(section.model_copy(update={"components": kept}))
        else:
            notes.append(
                SpecIssue(
                    path=f"sections[{s_idx}]",
                    code="section_dropped",
                    message=f"Removed empty section '{section.title}'.",
                )
            )
    repaired = spec.model_copy(update={"sections": sections})
    return repaired, notes
