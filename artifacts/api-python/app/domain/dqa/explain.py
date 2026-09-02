"""Deterministic human-readable explanations from evaluation details."""

from __future__ import annotations

from typing import Any

from app.domain.dqa.operands import is_related_field_operand


def _format_operand(operand: Any) -> str:
    if is_related_field_operand(operand):
        return f"related({operand.get('relationship')}.{operand.get('field')})"
    return str(operand or "")


def _explain_compare(details: dict[str, Any], *, op: str) -> list[str]:
    lines: list[str] = []
    field = details.get("field")
    field_b = details.get("field_b")
    value = details.get("value")
    bound = details.get("bound")
    expected = details.get("expected")

    left_label = _format_operand(field) if field else "left"
    if field_b is not None:
        right_label = _format_operand(field_b)
        right_val = bound if bound is not None else expected
    else:
        right_label = "threshold"
        right_val = bound if bound is not None else expected

    if value is not None:
        lines.append(f"{left_label} = {value!r}")
    if right_val is not None:
        lines.append(f"{right_label} = {right_val!r}")

    op_text = {
        "gt": ">",
        "lt": "<",
        "gte": ">=",
        "lte": "<=",
        "equals": "==",
        "not_equals": "!=",
    }.get(op, op)
    if value is not None and right_val is not None:
        lines.append(f"condition {left_label} {op_text} {right_label} was evaluated")
    return lines


def _explain_related(details: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, val in details.items():
        if key.startswith("left_related") or key.startswith("right_related"):
            continue
        if key == "relatedSubmissions" and isinstance(val, list):
            for item in val:
                if not isinstance(item, dict):
                    continue
                rel = item.get("relationship") or "related"
                lines.append(
                    f"Related form submission via {rel}: "
                    f"{item.get('projectName') or item.get('submissionId')} "
                    f"(join key {item.get('joinKey')!r})"
                )
    left_res = details.get("left_relatedResolution") or details.get("right_relatedResolution")
    if left_res == "none":
        lines.append("No related submission matched the join key")
    elif left_res == "missing_key":
        lines.append("Join key missing on current submission")
    elif left_res == "ambiguous":
        lines.append("Multiple related submissions matched (ambiguous)")
    return lines


def explain_evaluation(
    *,
    check: dict[str, Any] | None,
    details: dict[str, Any] | None,
    passes: bool,
    flag_when: str = "fail",
) -> dict[str, Any]:
    """Build explainable finding text from deterministic eval output."""
    details = details if isinstance(details, dict) else {}
    check = check if isinstance(check, dict) else {}
    op = str(details.get("op") or check.get("op") or "")

    would_flag = (not passes) if str(flag_when or "fail").lower() == "fail" else passes
    lines: list[str] = []

    if op == "all" and details.get("failed"):
        lines.append("Composite rule (all) failed because a child check failed:")
        nested = explain_evaluation(
            check=check.get("checks", [{}])[0] if check.get("checks") else None,
            details=details.get("failed") if isinstance(details.get("failed"), dict) else {},
            passes=False,
            flag_when=flag_when,
        )
        lines.extend(nested.get("lines") or [])
    elif op == "if_then":
        if details.get("if") and details.get("then"):
            lines.append("Conditional rule: when-clause and then-clause were evaluated")
        elif not details.get("if") and not details.get("then"):
            lines.append("Conditional rule did not apply (when-clause was false)")
    elif op in {"gt", "lt", "gte", "lte", "equals", "not_equals"}:
        lines.extend(_explain_compare(details, op=op))
        lines.extend(_explain_related(details))
    elif op == "required":
        lines.append(f"Field {details.get('field')!r} value = {details.get('value')!r}")
        lines.append("Required field check")
    else:
        if details.get("value") is not None:
            lines.append(f"value = {details.get('value')!r}")
        if details.get("field"):
            lines.append(f"field = {details.get('field')!r}")

    lines.extend(_explain_related(details))

    if would_flag:
        summary = "Flagged because:"
    elif op == "if_then" and not details.get("then"):
        summary = "Not applicable:"
    else:
        summary = "Passed because:"

    return {
        "summary": summary,
        "lines": [line for line in lines if line],
        "would_flag": would_flag,
        "op": op,
    }
