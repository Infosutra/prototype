"""Collect related-field operands from check trees."""

from __future__ import annotations

from typing import Any

from app.domain.dqa.catalog import FIELD_LIST_KEYS, FIELD_REF_KEYS


def is_related_field_operand(operand: Any) -> bool:
    return (
        isinstance(operand, dict)
        and str(operand.get("type") or "").strip() == "related_field"
        and str(operand.get("relationship") or "").strip()
    )


def collect_relationship_codes(node: Any, out: set[str] | None = None) -> set[str]:
    if out is None:
        out = set()
    if not isinstance(node, dict):
        return out
    for key in FIELD_REF_KEYS:
        operand = node.get(key)
        if is_related_field_operand(operand):
            out.add(str(operand["relationship"]).strip())
    for key in FIELD_LIST_KEYS:
        for item in node.get(key) or []:
            if is_related_field_operand(item):
                out.add(str(item["relationship"]).strip())
    for nested in ("check", "if", "then", "failed", "inner"):
        if nested in node:
            collect_relationship_codes(node[nested], out)
    for child in node.get("checks") or []:
        collect_relationship_codes(child, out)
    return out


def related_field_ref(relationship: str, field: str) -> dict[str, str]:
    return {
        "type": "related_field",
        "relationship": relationship,
        "field": field,
    }
