"""Compile planner JSON into a canonical ReportSpec.

The query engine and validator speak Query IR only: required ``entity`` and
``window``, grouping as ``groupBy``. The planner LLM describes the same query in
analytics terms (catalog ``dimensions``, omitted entity/window). This module is
the only translation between those languages. Engine code never sees planner keys.
"""

from __future__ import annotations

from typing import Any

from app.domain.reporting.catalog import (
    ANSWER_FIELDS,
    FLAG_FIELDS,
    SUBMISSION_FIELDS,
)
from app.domain.time_window import WINDOW_PRESETS

MEASURE_FNS = frozenset(
    {"count", "countDistinct", "countWhere", "sum", "avg", "min", "max"}
)
FILTER_OP_ALIASES = {
    "==": "eq",
    "=": "eq",
    "!=": "neq",
    "<>": "neq",
    "equals": "eq",
    "not_equals": "neq",
    "notEquals": "neq",
}
ENTITY_ALIASES = {
    "submission": "submission",
    "submissions": "submission",
    "flag": "flag",
    "flags": "flag",
    "answer": "answer",
    "answers": "answer",
}
DEFAULT_WINDOW = "execution_date"
FLAG_ONLY_FIELDS = FLAG_FIELDS - SUBMISSION_FIELDS
ANSWER_ONLY_FIELDS = ANSWER_FIELDS - SUBMISSION_FIELDS
_GROUPING_KEYS = ("groupBy", "group_by", "dimensions", "dimension", "groups")


def compile_report_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Return engine ReportSpec JSON. Unknown planner-only query keys are dropped."""
    if not isinstance(spec, dict):
        return spec
    out = dict(spec)
    if not out.get("specVersion"):
        out["specVersion"] = "1.0"
    sections = out.get("sections")
    if not isinstance(sections, list):
        return out
    out["sections"] = [
        _compile_section(section) if isinstance(section, dict) else section
        for section in sections
    ]
    return out


def _compile_section(section: dict[str, Any]) -> dict[str, Any]:
    out = dict(section)
    components = out.get("components")
    if not isinstance(components, list):
        return out
    out["components"] = [
        _compile_component(component) if isinstance(component, dict) else component
        for component in components
    ]
    return out


def _compile_component(component: dict[str, Any]) -> dict[str, Any]:
    out = dict(component)
    comp_type = str(out.get("type") or "")
    uses = out.get("uses")
    query = out.get("query")

    if comp_type == "text":
        out.pop("query", None)
        out.pop("uses", None)
    elif isinstance(query, dict):
        compiled = _compile_query(query)
        if (
            comp_type == "narrative"
            and uses
            and not _query_has_bindings(compiled)
        ):
            out.pop("query", None)
        elif compiled is None:
            out.pop("query", None)
        else:
            out["query"] = compiled
    elif query is not None and not isinstance(query, dict):
        out.pop("query", None)

    display = out.get("display")
    if display is not None:
        out["display"] = _compile_display(comp_type, display)

    if comp_type == "kpi_group":
        out = _finalize_kpi_group(out)
    return out


def _finalize_kpi_group(component: dict[str, Any]) -> dict[str, Any]:
    """If any KPI item has a query, prefer per-item mode and drop component query."""
    display = component.get("display")
    if not isinstance(display, dict):
        return component
    items = display.get("items")
    if not isinstance(items, list):
        return component
    compiled_items: list[Any] = []
    any_item_query = False
    for item in items:
        if not isinstance(item, dict):
            compiled_items.append(item)
            continue
        item_out = dict(item)
        raw_q = item_out.get("query")
        if isinstance(raw_q, dict):
            cq = _compile_query(raw_q)
            if cq is not None:
                item_out["query"] = cq
                any_item_query = True
            else:
                item_out.pop("query", None)
        compiled_items.append(item_out)
    display_out = dict(display)
    display_out["items"] = compiled_items
    component = dict(component)
    component["display"] = display_out
    if any_item_query:
        component.pop("query", None)
    return component


def _query_has_bindings(query: dict[str, Any] | None) -> bool:
    if not query:
        return False
    return bool(query.get("groupBy") or query.get("measures") or query.get("filters"))


def _compile_query(raw: dict[str, Any]) -> dict[str, Any] | None:
    grouping = _first_list(raw, _GROUPING_KEYS)
    measures_in = raw.get("measures")
    if measures_in is None:
        measures_in = raw.get("metrics") or raw.get("aggregations")
    measures = (
        [_compile_measure(item) for item in measures_in if isinstance(item, dict)]
        if isinstance(measures_in, list)
        else None
    )
    filters_in = raw.get("filters")
    filters = (
        [_compile_filter(item) for item in filters_in if isinstance(item, dict)]
        if isinstance(filters_in, list)
        else []
    )
    sort = _compile_sort(raw.get("sort") if isinstance(raw.get("sort"), dict) else None)

    mentioned = list(grouping)
    if measures:
        for item in measures:
            field = item.get("field")
            if isinstance(field, str) and field.strip():
                mentioned.append(field.strip())
    for item in filters:
        field = item.get("field")
        if isinstance(field, str) and field.strip():
            mentioned.append(field.strip())
    if sort:
        field = sort.get("field")
        if isinstance(field, str) and field.strip():
            mentioned.append(field.strip())

    entity = _compile_entity(raw.get("entity"), mentioned)
    window = _compile_window(raw.get("window", raw.get("timeWindow", raw.get("preset"))))
    if entity is None and window is None and not _query_has_bindings(
        {"groupBy": grouping, "measures": measures, "filters": filters}
    ):
        return None

    query: dict[str, Any] = {
        "entity": entity or _infer_entity(mentioned) or "submission",
        "window": window or DEFAULT_WINDOW,
    }
    if grouping:
        query["groupBy"] = grouping
    if measures:
        query["measures"] = measures
    if filters:
        query["filters"] = filters
    limit = raw.get("limit")
    if isinstance(limit, int) and limit > 0:
        query["limit"] = limit
    if sort:
        query["sort"] = sort
    return query


def _first_list(raw: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    for key in keys:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    return []


def _compile_entity(value: Any, fields: list[str]) -> str | None:
    if isinstance(value, str) and value.strip():
        key = value.strip().lower()
        if key in ENTITY_ALIASES:
            return ENTITY_ALIASES[key]
        return value.strip()
    return _infer_entity(fields)


def _infer_entity(fields: list[str]) -> str | None:
    names = {name for name in fields if name}
    has_flag = bool(names & FLAG_ONLY_FIELDS)
    has_answer = bool(names & ANSWER_ONLY_FIELDS)
    if has_flag and not has_answer:
        return "flag"
    if has_answer and not has_flag:
        return "answer"
    if has_flag and has_answer:
        return "flag"
    return None


def _compile_window(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("preset") or value.get("window")
    if isinstance(value, str) and value.strip():
        window = value.strip()
        if window in WINDOW_PRESETS:
            return window
        return window
    return None


def _compile_measure(measure: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    fn = measure.get("fn") or measure.get("function") or measure.get("aggregation")
    raw_measure = measure.get("measure")
    if isinstance(raw_measure, str) and raw_measure.strip():
        if fn is None and raw_measure in MEASURE_FNS:
            fn = raw_measure
        elif not measure.get("id"):
            out["id"] = raw_measure
    if isinstance(fn, str) and fn.strip():
        out["fn"] = fn.strip()
    measure_id = measure.get("id") or out.get("id")
    field = measure.get("field")
    if isinstance(field, str) and field.strip():
        out["field"] = field.strip()
    if measure.get("eq") is not None:
        out["eq"] = measure["eq"]
    if isinstance(measure_id, str) and measure_id.strip():
        out["id"] = measure_id.strip()
    else:
        fn_s = str(out.get("fn") or "m")
        out["id"] = f"{fn_s}_{out['field']}" if out.get("field") else fn_s
    return out


def _compile_filter(filt: dict[str, Any]) -> dict[str, Any]:
    op = filt.get("op", filt.get("operator"))
    if isinstance(op, str):
        key = op.strip()
        op = FILTER_OP_ALIASES.get(key, FILTER_OP_ALIASES.get(key.lower(), key))
    out: dict[str, Any] = {"field": filt.get("field"), "op": op}
    if filt.get("value") is not None:
        out["value"] = filt["value"]
    return out


def _compile_sort(sort: dict[str, Any] | None) -> dict[str, Any] | None:
    if not sort:
        return None
    direction = sort.get("dir", sort.get("order", sort.get("direction")))
    if isinstance(direction, str):
        lowered = direction.strip().lower()
        if lowered in {"asc", "ascending"}:
            direction = "asc"
        elif lowered in {"desc", "descending"}:
            direction = "desc"
    field = sort.get("field")
    if not isinstance(field, str) or not field.strip():
        return None
    out: dict[str, Any] = {"field": field.strip()}
    if isinstance(direction, str) and direction.strip():
        out["dir"] = direction.strip()
    return out


def _compile_display(comp_type: str, display: Any) -> Any:
    if isinstance(display, dict):
        if comp_type == "kpi_group":
            items = display.get("items")
            if isinstance(items, list):
                out = dict(display)
                out["items"] = [
                    _compile_kpi_item_display(item) if isinstance(item, dict) else item
                    for item in items
                ]
                return out
        return display
    if not isinstance(display, str):
        return display
    text = display.strip()
    if not text:
        return {}
    if comp_type == "text":
        return {"body": text}
    if comp_type == "narrative":
        return {"role": "insight", "instruction": text}
    if comp_type == "metric":
        return {"label": text, "field": "value"}
    if comp_type == "kpi_group":
        return {
            "items": [
                {
                    "label": text,
                    "query": {
                        "entity": "submission",
                        "window": DEFAULT_WINDOW,
                        "measures": [{"id": "value", "fn": "count"}],
                    },
                }
            ]
        }
    if comp_type == "table":
        return {"columns": ["value"], "emptyText": text}
    if comp_type == "chart":
        return {"kind": "bar", "x": "label", "y": ["value"]}
    if comp_type == "progress":
        return {
            "labelField": "label",
            "valueField": "value",
            "targetField": "target",
        }
    return display


def _compile_kpi_item_display(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    raw_q = out.get("query")
    if isinstance(raw_q, dict):
        cq = _compile_query(raw_q)
        if cq is not None:
            out["query"] = cq
        else:
            out.pop("query", None)
    return out
