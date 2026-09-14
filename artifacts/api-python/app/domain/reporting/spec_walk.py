"""Walk Query objects inside a ReportSpec dict (no ORM)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def iter_queries(spec: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    sections = spec.get("sections") if isinstance(spec, dict) else None
    if not isinstance(sections, list):
        return
    for si, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        components = section.get("components")
        if not isinstance(components, list):
            continue
        for ci, component in enumerate(components):
            if not isinstance(component, dict):
                continue
            query = component.get("query")
            if isinstance(query, dict):
                yield f"sections[{si}].components[{ci}].query", query
            display = component.get("display")
            items = display.get("items") if isinstance(display, dict) else None
            if not isinstance(items, list):
                continue
            for ii, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                item_query = item.get("query")
                if isinstance(item_query, dict):
                    yield (
                        f"sections[{si}].components[{ci}].display.items[{ii}].query",
                        item_query,
                    )


def query_has_tool_code_filter(query: dict[str, Any]) -> bool:
    for item in query.get("filters") or []:
        if isinstance(item, dict) and item.get("field") == "toolCode":
            return True
    return False


def field_key_values(query: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for item in query.get("filters") or []:
        if not isinstance(item, dict) or item.get("field") != "fieldKey":
            continue
        value = item.get("value")
        if isinstance(value, list):
            keys.extend(str(v) for v in value if v is not None and str(v).strip())
        elif value is not None and str(value).strip():
            keys.append(str(value))
    return keys


def query_field_names(query: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in query.get("groupBy") or query.get("group_by") or []:
        if item:
            names.append(str(item))
    for item in query.get("filters") or []:
        if isinstance(item, dict) and item.get("field"):
            names.append(str(item["field"]))
    for item in query.get("measures") or []:
        if isinstance(item, dict) and item.get("field"):
            names.append(str(item["field"]))
    return names


def rename_query_field(query: dict[str, Any], old: str, new: str) -> None:
    group = query.get("groupBy")
    if isinstance(group, list):
        query["groupBy"] = [new if str(item) == old else item for item in group]
    group_snake = query.get("group_by")
    if isinstance(group_snake, list):
        query["group_by"] = [new if str(item) == old else item for item in group_snake]
    for item in query.get("filters") or []:
        if isinstance(item, dict) and item.get("field") == old:
            item["field"] = new
    for item in query.get("measures") or []:
        if isinstance(item, dict) and item.get("field") == old:
            item["field"] = new


def set_query_at_path(spec: dict[str, Any], path: str, query: dict[str, Any]) -> None:
    """Replace the query dict at an ``iter_queries`` path."""
    for existing_path, existing in iter_queries(spec):
        if existing_path == path:
            existing.clear()
            existing.update(query)
            return
