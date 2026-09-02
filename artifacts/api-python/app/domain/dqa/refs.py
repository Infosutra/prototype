"""Intra-form value resolution and comparison helpers for DQA evaluation."""

from __future__ import annotations

from typing import Any

from app.domain.dqa.context import EvaluationContext
from app.domain.dqa.values import _as_number, _as_str, _threshold, get_value


def resolve_field_value(ctx: EvaluationContext, field_ref: str | None) -> Any:
    """Resolve a pack field alias against the current submission only."""
    if not field_ref:
        return None
    ref = str(field_ref).strip()
    if not ref:
        return None
    if "." in ref:
        # Phase 2 scoped refs (e.g. register.A10) are not supported in Phase 0.
        return None
    return get_value(ctx.data, ctx.pack, ref)


def _constant_bound(ctx: EvaluationContext, check: dict[str, Any]) -> float | None:
    bound = check.get("value")
    if bound is None and check.get("threshold"):
        bound = _threshold(ctx.pack, str(check["threshold"]))
    if bound is None:
        return None
    if isinstance(bound, (int, float)):
        return float(bound)
    return _as_number(bound)


def resolve_numeric_operands(
    ctx: EvaluationContext,
    check: dict[str, Any],
) -> tuple[float | None, float | None, dict[str, Any]]:
    """Return (left, right, details) for numeric comparison ops."""
    left = _as_number(resolve_field_value(ctx, check.get("field")))
    field_b = check.get("field_b")
    has_value = check.get("value") is not None or check.get("threshold") is not None
    details: dict[str, Any] = {
        "field": check.get("field"),
        "value": left,
    }

    if field_b and has_value:
        details["error"] = "field_b and value/threshold are mutually exclusive"
        return None, None, details

    if field_b:
        right = _as_number(resolve_field_value(ctx, field_b))
        details["field_b"] = field_b
        details["bound"] = right
        return left, right, details

    right = _constant_bound(ctx, check)
    details["bound"] = right
    return left, right, details


def eval_numeric_relation(
    left: float | None,
    right: float | None,
    op: str,
) -> bool:
    if left is None or right is None:
        return False
    if op == "gt":
        return left > right
    if op == "lt":
        return left < right
    if op == "gte":
        return left >= right
    if op == "lte":
        return left <= right
    return False


def resolve_string_operands(
    ctx: EvaluationContext,
    check: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Return normalized (left, right, details) for string equality ops."""
    left = _as_str(resolve_field_value(ctx, check.get("field"))).lower()
    field_b = check.get("field_b")
    has_value = check.get("value") is not None
    details: dict[str, Any] = {"value": left}

    if field_b and has_value:
        details["error"] = "field_b and value are mutually exclusive"
        return left, "", details

    if field_b:
        right = _as_str(resolve_field_value(ctx, field_b)).lower()
        details["field_b"] = field_b
        details["expected"] = right
        return left, right, details

    right = _as_str(check.get("value")).lower()
    details["expected"] = right
    return left, right, details
