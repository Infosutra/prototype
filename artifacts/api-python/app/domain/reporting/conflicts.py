"""Deterministic fieldKey × tool clashes in a ReportSpec (no LLM)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.domain.reporting.spec_walk import (
    field_key_values,
    iter_queries,
    query_has_tool_code_filter,
)


def field_key_tool_index(
    study_field_keys: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in study_field_keys or []:
        key = str(row.get("fieldKey") or "").strip()
        if not key:
            continue
        index[key].append(row)
    return dict(index)


def find_field_tool_conflicts(
    spec: dict[str, Any],
    study_field_keys: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Pause questions when an answer query uses a shared fieldKey without toolCode."""
    index = field_key_tool_index(study_field_keys)
    questions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path, query in iter_queries(spec):
        entity = str(query.get("entity") or "")
        if entity != "answer":
            continue
        if query_has_tool_code_filter(query):
            continue
        for key in field_key_values(query):
            tools = index.get(key) or []
            codes = sorted(
                {str(row.get("toolCode") or "").strip() for row in tools if row.get("toolCode")}
            )
            if len(codes) < 2:
                continue
            marker = (path, key)
            if marker in seen:
                continue
            seen.add(marker)
            options = []
            for row in tools:
                code = str(row.get("toolCode") or "").strip()
                if not code:
                    continue
                label = str(row.get("toolLabel") or row.get("label") or code)
                options.append(
                    {
                        "id": code,
                        "label": f"{label} ({code})" if label != code else code,
                        "value": code,
                    }
                )
            tool_list = ", ".join(opt["label"] for opt in options)
            questions.append(
                {
                    "id": f"conflict:{key}:{path}",
                    "kind": "field_tool_conflict",
                    "prompt": (
                        f"{key} is on {tool_list}. Which form should this query use?"
                    ),
                    "options": options,
                    "path": path,
                    "fieldKey": key,
                }
            )
    return questions
