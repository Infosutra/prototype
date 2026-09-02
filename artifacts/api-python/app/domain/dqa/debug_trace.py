"""Deterministic debug trace from evaluation details."""

from __future__ import annotations

from typing import Any


def _trace_node(details: dict[str, Any] | None, *, check: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(details, dict):
        return {"op": "unknown", "passes": True, "operands": {}, "children": []}

    op = str(details.get("op") or (check or {}).get("op") or "")
    node: dict[str, Any] = {
        "op": op,
        "operands": _extract_operands(details),
        "details": {k: v for k, v in details.items() if k not in {"failed", "inner", "if", "then", "checks"}},
        "children": [],
    }

    if op == "all" and isinstance(details.get("failed"), dict):
        node["passes"] = False
        node["children"].append(_trace_node(details["failed"]))
    elif op == "any":
        node["passes"] = True
    elif op == "not" and isinstance(details.get("inner"), dict):
        inner = _trace_node(details["inner"])
        node["passes"] = not inner.get("passes", True)
        node["children"].append(inner)
    elif op == "if_then":
        if_part = details.get("if") if isinstance(details.get("if"), dict) else {}
        then_part = details.get("then") if isinstance(details.get("then"), dict) else {}
        node["children"] = [_trace_node(if_part), _trace_node(then_part)]
        node["passes"] = bool(if_part) and bool(then_part.get("op"))
    else:
        node["passes"] = not details.get("error")

    return node


def _extract_operands(details: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "field",
        "field_b",
        "value",
        "bound",
        "expected",
        "left_relatedField",
        "right_relatedField",
        "left_relatedResolution",
        "right_relatedResolution",
    )
    return {k: details[k] for k in keys if k in details}


def build_debug_trace(
    *,
    check: dict[str, Any] | None,
    details: dict[str, Any] | None,
    passes: bool,
) -> dict[str, Any]:
    trace = _trace_node(details, check=check)
    trace["final_passes"] = passes
    trace["rule_check"] = check
    return trace
