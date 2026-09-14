"""Validate ReportSpec against catalog allowlists and config knobs."""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from app.domain.reporting.catalog import ENTITY_FIELDS, resolve_field
from app.domain.reporting.spec import ReportSpec
from app.domain.time_window import WINDOW_PRESETS
from app.services.reporting.config import ReportingConfig, get_reporting_config

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_PLACEHOLDER_RE = re.compile(r"\{\{")

# Legacy certified-tool / recipe identifiers — never legal on a ReportSpec.
_LEGACY_TOOL_IDS = frozenset(
    {
        "enumerator" + "_performance_today",
        "study" + "_totals",
        "signoff" + "_checklist",
        "top_failing_rules",
        "triangulation_table",
        "daily_dqa_stats",
        "final_dqa_stats",
    }
)

_ALLOWED_MEASURE_FNS: frozenset[str] = frozenset(
    {"count", "countDistinct", "countWhere", "sum", "avg", "min", "max"}
)
_ALLOWED_FILTER_OPS: frozenset[str] = frozenset(
    {"eq", "neq", "in", "isTrue", "isFalse", "gt", "gte", "lt", "lte"}
)


class SpecValidationError(ValueError):
    """ReportSpec failed validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors) if self.errors else "Invalid ReportSpec")


def validate_report_spec(
    spec: ReportSpec | dict[str, Any],
    config: ReportingConfig | None = None,
    *,
    raise_on_error: bool = False,
) -> list[str]:
    """Return validation error strings (empty if valid).

    When ``raise_on_error`` is True, raises :class:`SpecValidationError` if any
    errors are found.
    """
    cfg = config or get_reporting_config()
    errors: list[str] = []

    raw: dict[str, Any] | None = None
    if isinstance(spec, dict):
        raw = spec
        errors.extend(_forbidden_keys(raw))
        errors.extend(_legacy_tool_mentions(raw))
        try:
            parsed = ReportSpec.model_validate(spec)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(x) for x in err.get("loc", ()))
                msg = err.get("msg", "invalid")
                errors.append(f"{loc}: {msg}" if loc else msg)
            if raise_on_error and errors:
                raise SpecValidationError(errors) from exc
            return errors
    else:
        parsed = spec
        dumped = parsed.model_dump(by_alias=True)
        errors.extend(_forbidden_keys(dumped))
        errors.extend(_legacy_tool_mentions(dumped))

    if parsed.spec_version != "1.0":
        errors.append('specVersion must be "1.0"')

    if len(parsed.sections) > cfg.spec_sections_max:
        errors.append(
            f"sections has {len(parsed.sections)}; max is {cfg.spec_sections_max}"
        )

    component_ids: set[str] = set()
    for section in parsed.sections:
        if len(section.components) > cfg.spec_components_per_section_max:
            errors.append(
                f"section '{section.id}' has {len(section.components)} components; "
                f"max is {cfg.spec_components_per_section_max}"
            )
        for comp in section.components:
            if comp.id in component_ids:
                errors.append(f"Duplicate component id '{comp.id}'")
            component_ids.add(comp.id)
            errors.extend(_validate_component(comp, path=f"{section.id}.{comp.id}"))

    # uses references (second pass once all ids known)
    for section in parsed.sections:
        for comp in section.components:
            if not comp.uses:
                continue
            for ref in comp.uses:
                if ref not in component_ids:
                    errors.append(
                        f"Component '{comp.id}' uses unknown id '{ref}'"
                    )
                elif ref == comp.id:
                    errors.append(f"Component '{comp.id}' cannot use itself")

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            unique.append(e)

    if raise_on_error and unique:
        raise SpecValidationError(unique)
    return unique


def _forbidden_keys(raw: dict[str, Any], path: str = "") -> list[str]:
    errors: list[str] = []
    forbidden = {"data_source", "dataSource", "report_kind", "reportKind"}
    for key, val in raw.items():
        here = f"{path}.{key}" if path else key
        if key in forbidden:
            errors.append(f"Forbidden field '{here}'")
        if isinstance(val, dict):
            errors.extend(_forbidden_keys(val, here))
        elif isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, dict):
                    errors.extend(_forbidden_keys(item, f"{here}[{i}]"))
    return errors


def _legacy_tool_mentions(obj: Any) -> list[str]:
    errors: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            if node in _LEGACY_TOOL_IDS:
                errors.append(f"Legacy tool id '{node}' is not allowed on ReportSpec")
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(obj)
    return errors


def _validate_component(comp: Any, *, path: str) -> list[str]:
    errors: list[str] = []
    display = comp.display or {}

    if comp.type == "text":
        body = display.get("body", "")
        if isinstance(body, str) and _PLACEHOLDER_RE.search(body):
            errors.append(f"{path}: text body must not contain {{{{placeholders}}}}")
        return errors

    if comp.type == "narrative":
        instruction = display.get("instruction", "")
        if isinstance(instruction, str) and _PLACEHOLDER_RE.search(instruction):
            errors.append(
                f"{path}: narrative instruction must not contain {{{{placeholders}}}}"
            )

    if comp.type == "kpi_group":
        errors.extend(_validate_kpi_group(comp, path=path))
        return errors

    if comp.query is not None:
        errors.extend(_validate_query(comp.query, path=f"{path}.query"))

    return errors


def _validate_kpi_group(comp: Any, *, path: str) -> list[str]:
    errors: list[str] = []
    items = (comp.display or {}).get("items") or []
    if not items:
        errors.append(f"{path}: kpi_group needs at least one display item")
        return errors

    per_item = False
    for item in items:
        q = item.get("query") if isinstance(item, dict) else getattr(item, "query", None)
        if q is not None:
            per_item = True
            break

    if per_item:
        for i, item in enumerate(items):
            item_path = f"{path}.display.items[{i}]"
            if not isinstance(item, dict):
                q = getattr(item, "query", None)
                label = getattr(item, "label", "")
            else:
                q = item.get("query")
                label = item.get("label") or ""
            if not str(label).strip():
                errors.append(f"{item_path}: label is required")
            if q is None:
                errors.append(f"{item_path}: query is required in per-item mode")
                continue
            # Display dumps Query as dict; accept both.
            if isinstance(q, dict):
                from app.domain.reporting.query import Query

                try:
                    parsed_q = Query.model_validate(q)
                except ValidationError as exc:
                    for err in exc.errors():
                        loc = ".".join(str(x) for x in err.get("loc", ()))
                        msg = err.get("msg", "invalid")
                        errors.append(
                            f"{item_path}.query.{loc}: {msg}"
                            if loc
                            else f"{item_path}.query: {msg}"
                        )
                    continue
            else:
                parsed_q = q
            if parsed_q.group_by:
                errors.append(
                    f"{item_path}.query: glance KPI queries must not use groupBy"
                )
            if not parsed_q.measures:
                errors.append(f"{item_path}.query: glance KPI queries need measures")
            errors.extend(_validate_query(parsed_q, path=f"{item_path}.query"))
        return errors

    if comp.query is not None:
        errors.extend(_validate_query(comp.query, path=f"{path}.query"))
    for i, item in enumerate(items):
        item_path = f"{path}.display.items[{i}]"
        if isinstance(item, dict):
            field = item.get("field")
            label = item.get("label")
        else:
            field = getattr(item, "field", None)
            label = getattr(item, "label", None)
        if not str(label or "").strip():
            errors.append(f"{item_path}: label is required")
        if not str(field or "").strip():
            errors.append(f"{item_path}: field is required in shared-query mode")
    return errors


def _validate_query(query: Any, *, path: str) -> list[str]:
    errors: list[str] = []
    window = query.window
    if isinstance(window, str):
        if _ISO_DATE_RE.match(window) or window not in WINDOW_PRESETS:
            if _ISO_DATE_RE.match(window):
                errors.append(
                    f"{path}.window: ISO dates are not allowed; use a preset enum"
                )
            elif window not in WINDOW_PRESETS:
                errors.append(f"{path}.window: unknown preset '{window}'")

    entity = query.entity
    if entity not in ENTITY_FIELDS:
        errors.append(f"{path}.entity: unknown entity '{entity}'")
        return errors

    for name in query.group_by or []:
        try:
            resolve_field(entity, name)
        except ValueError as exc:
            errors.append(f"{path}.groupBy: {exc}")

    if query.measures:
        for m in query.measures:
            fn = m.fn if isinstance(m.fn, str) else str(m.fn)
            if fn not in _ALLOWED_MEASURE_FNS:
                errors.append(f"{path}.measures: unknown fn '{fn}'")
            if m.field:
                try:
                    resolve_field(entity, m.field)
                except ValueError as exc:
                    errors.append(f"{path}.measures: {exc}")

    for f in query.filters or []:
        op = f.op if isinstance(f.op, str) else str(f.op)
        if op not in _ALLOWED_FILTER_OPS:
            errors.append(f"{path}.filters: unknown op '{op}'")
        try:
            resolve_field(entity, f.field)
        except ValueError as exc:
            errors.append(f"{path}.filters: {exc}")

    if query.sort is not None:
        try:
            resolve_field(entity, query.sort.field)
        except ValueError as exc:
            # sort may also target measure ids; only flag unknown catalog dims/facts
            # when the field looks like a catalog miss and is not a measure id.
            measure_ids = {m.id for m in (query.measures or [])}
            if query.sort.field not in measure_ids:
                errors.append(f"{path}.sort: {exc}")

    return errors
