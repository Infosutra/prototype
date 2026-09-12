"""Generic allowlisted aggregate query for free-form report components.

Registered as ``query_aggregate``. Planner prompt wiring lands in a later stage;
param allowlists are enforced in ``validate_spec``.
"""

from __future__ import annotations

from typing import Any

from app.domain.report_spec.catalog import (
    DataField,
    DataSourceDescriptor,
    DataSourceParam,
)
from app.domain.reporting.aggregate import (
    Measure,
    aggregate,
    count,
    count_distinct,
    scalar_aggregate,
    sum_,
)
from app.domain.reporting.date_windows import resolve_query_date_window
from app.domain.reporting.entity_rows import (
    build_flag_entity_rows,
    build_submission_entity_rows,
    derive_entity_day_column,
)
from app.domain.reporting.query_aggregate_catalog import (
    DATE_WINDOW_TOKENS,
    DEFAULT_LIMIT,
    ENTITY_DIMENSIONS,
    ENTITY_IDS,
    ENTITY_MEASURE_FIELDS,
    FILTER_OPS,
    HARD_MAX_LIMIT,
    HIGH_CARDINALITY_GROUP_BY,
    MAX_DISTINCT_DATE_RANGES,
    MAX_GROUP_BY_FIELDS,
    MEASURE_IDS,
    parse_group_by,
)
from app.services.report_tools.context import ReportDataContext, range_key
from app.services.report_tools.registry import register

# Re-export catalog constants and shared helpers for callers/tests that imported them here.
__all__ = [
    "DATE_WINDOW_TOKENS",
    "DEFAULT_LIMIT",
    "ENTITY_DIMENSIONS",
    "ENTITY_IDS",
    "ENTITY_MEASURE_FIELDS",
    "FILTER_OPS",
    "HARD_MAX_LIMIT",
    "HIGH_CARDINALITY_GROUP_BY",
    "MAX_DISTINCT_DATE_RANGES",
    "MAX_GROUP_BY_FIELDS",
    "MEASURE_IDS",
    "QUERY_AGGREGATE",
    "build_flag_entity_rows",
    "build_submission_entity_rows",
    "derive_entity_day_column",
    "query_aggregate",
    "resolve_query_date_window",
]


def _f(name: str, label: str, type_: str, description: str = "") -> DataField:
    return DataField(name=name, label=label, type=type_, description=description)


QUERY_AGGREGATE = DataSourceDescriptor(
    id="query_aggregate",
    title="Custom aggregate query",
    description=(
        "Allowlisted count/sum/median over submissions or flags with optional "
        "group-by, one filter, and a semantic date window. Prefer certified "
        "catalog sources when they already answer the request."
    ),
    kind="table",
    supports_date_window=True,
    business_definition=(
        "Rows are projected from study submissions or DQA flags after resolving "
        "dateWindow to an inclusive calendar range in the study timezone. "
        "Measures are generic aggregates only — never severity coercion, top-N "
        "cuts, thresholds, or narrative templates (those stay on certified "
        "domain_rules tools). Omit dateWindow to use the execution context "
        "range (often the full study bag). Output always includes `value` plus "
        "each groupBy dimension actually requested. The derived `day` dimension is the "
        "submission's submitted_at calendar date in the study timezone (flags use the "
        "joined submission clock, not flag evaluated_at). groupBy including day is "
        "sparse: days with no matching rows are omitted, not zero-filled."
    ),
    fields=[
        _f("value", "Value", "float", "Aggregate measure result"),
        _f("enumerator", "Enumerator", "string"),
        _f("toolCode", "Tool", "string"),
        _f("projectId", "Project id", "string"),
        _f("severity", "Severity", "string"),
        _f("ruleId", "Rule id", "string"),
        _f(
            "day",
            "Day",
            "string",
            "Study-timezone calendar day (YYYY-MM-DD) from submission submitted_at.",
        ),
    ],
    params=[
        DataSourceParam(
            name="entity",
            type="string",
            required=True,
            allowed=sorted(ENTITY_IDS),
            default="submission",
            description="Row bag to aggregate: submission or flag.",
        ),
        DataSourceParam(
            name="measure",
            type="string",
            required=True,
            allowed=sorted(MEASURE_IDS),
            default="count",
            description="Aggregate operation.",
        ),
        DataSourceParam(
            name="measureField",
            type="string",
            required=False,
            description="Required for countDistinct / sum / median; ignored for count.",
        ),
        DataSourceParam(
            name="groupBy",
            type="string",
            required=False,
            default="",
            description="Comma-separated allowlisted dimensions (max 2).",
        ),
        DataSourceParam(
            name="filterField",
            type="string",
            required=False,
            description="Optional single filter field (allowlisted dimension).",
        ),
        DataSourceParam(
            name="filterOp",
            type="string",
            required=False,
            allowed=sorted(FILTER_OPS),
            default="eq",
            description="Filter operator: eq or in.",
        ),
        DataSourceParam(
            name="filterValue",
            type="string",
            required=False,
            description="Filter value; for `in`, comma-separated tokens.",
        ),
        DataSourceParam(
            name="dateWindow",
            type="string",
            required=False,
            allowed=sorted(DATE_WINDOW_TOKENS),
            description=(
                "Semantic window: execution_date | last_7_days | last_14_days | "
                "study_to_date. Omit to use the execution context range."
            ),
        ),
        DataSourceParam(
            name="orderBy",
            type="string",
            required=False,
            description="Optional `{field}:asc` or `{field}:desc`.",
        ),
        DataSourceParam(
            name="limit",
            type="int",
            required=False,
            default=DEFAULT_LIMIT,
            description=f"Row cap (default {DEFAULT_LIMIT}, hard max {HARD_MAX_LIMIT}).",
        ),
    ],
)


def _parse_group_by(raw: Any) -> list[str]:
    return parse_group_by(raw)


def _parse_order_by(raw: Any) -> list[tuple[str, str]] | None:
    if raw is None or raw == "":
        return None
    text = str(raw).strip()
    if ":" in text:
        field, direction = text.rsplit(":", 1)
        return [(field.strip(), direction.strip().lower())]
    return [(text, "asc")]


def _build_measure(measure: str, measure_field: str | None) -> Measure:
    if measure == "count":
        return count()
    if measure == "countDistinct":
        if not measure_field:
            raise ValueError("measureField is required for countDistinct")
        return count_distinct(measure_field)
    if measure == "sum":
        if not measure_field:
            raise ValueError("measureField is required for sum")
        return sum_(measure_field)
    if measure == "median":
        if not measure_field:
            raise ValueError("measureField is required for median")
        return Measure(op="median", field=measure_field)
    raise ValueError(f"Unknown measure '{measure}'")


def _filter_pred(
    field: str | None, op: str | None, value: Any
) -> list[Any] | None:
    if not field:
        return None
    op_norm = (op or "eq").strip()
    if op_norm == "eq":
        target = str(value) if value is not None else ""
        return [lambda row, f=field, t=target: str(row.get(f) or "") == t]
    if op_norm == "in":
        tokens = {
            part.strip()
            for part in str(value or "").split(",")
            if part.strip()
        }
        return [lambda row, f=field, allowed=tokens: str(row.get(f) or "") in allowed]
    raise ValueError(f"Unknown filterOp '{op}'")


@register(QUERY_AGGREGATE)
def query_aggregate(
    ctx: ReportDataContext, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """Execute one allowlisted aggregate over submission or flag entity rows."""
    entity = str(params.get("entity") or "submission").strip()
    measure = str(params.get("measure") or "count").strip()
    measure_field = params.get("measureField")
    measure_field_s = (
        str(measure_field).strip() if measure_field not in (None, "") else None
    )
    group_by = _parse_group_by(params.get("groupBy"))
    filter_field = params.get("filterField")
    filter_field_s = (
        str(filter_field).strip() if filter_field not in (None, "") else None
    )
    filter_op = params.get("filterOp") or "eq"
    filter_value = params.get("filterValue")
    date_window = params.get("dateWindow")
    order_by = _parse_order_by(params.get("orderBy"))
    limit_raw = params.get("limit", DEFAULT_LIMIT)
    try:
        limit = int(limit_raw) if limit_raw is not None else DEFAULT_LIMIT
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid limit '{limit_raw}'") from exc
    # Soft cap at execution; Stage 2 validation rejects oversized limits before run.
    limit = max(0, min(limit, HARD_MAX_LIMIT))

    date_from, date_to = ctx.window(
        None if date_window in (None, "") else str(date_window)
    )
    # Touch the range key so memo sharing is obvious to callers / tests.
    _ = range_key(date_from, date_to)

    rows = ctx.entity_rows(date_from, date_to, entity)

    tz_name = ctx.study.timezone or ctx.context.timezone or "Asia/Kolkata"
    rows = derive_entity_day_column(rows, tz_name=tz_name)

    measures = {"value": _build_measure(measure, measure_field_s)}
    filters = _filter_pred(filter_field_s, str(filter_op), filter_value)

    if not group_by:
        scalar = scalar_aggregate(rows, measures=measures, filters=filters)
        return [scalar]

    return aggregate(
        rows,
        group_by=group_by,
        measures=measures,
        filters=filters,
        order_by=order_by,
        limit=limit,
    )
