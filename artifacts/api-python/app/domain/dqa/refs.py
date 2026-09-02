"""Intra-form and inter-form value resolution for DQA evaluation."""

from __future__ import annotations

from typing import Any

from app.domain.dqa.context import EvaluationContext, RelatedResolution
from app.domain.dqa.operands import is_related_field_operand
from app.domain.dqa.values import _as_number, _as_str, _parse_dt, _threshold, get_value

# Resolution statuses that make a related operand not evaluable (pass check).
_NA_STATUSES = frozenset({"none", "missing_key"})
# Ambiguous related match fails comparisons using that operand.
_FAIL_STATUSES = frozenset({"ambiguous"})


def resolve_operand(ctx: EvaluationContext, operand: Any) -> tuple[Any, dict[str, Any]]:
    """Resolve a field operand (string or related_field object)."""
    meta: dict[str, Any] = {}
    if is_related_field_operand(operand):
        code = str(operand.get("relationship") or "").strip()
        field = str(operand.get("field") or "").strip()
        meta["relatedField"] = {"relationship": code, "field": field}
        resolution = ctx.related.get(code) if ctx.related else None
        if not resolution:
            meta["relatedResolution"] = "missing_relationship"
            return None, meta
        meta["relatedResolution"] = resolution.status
        if resolution.status in _FAIL_STATUSES:
            meta["relatedResolutionFailed"] = True
            return None, meta
        if resolution.status in _NA_STATUSES:
            return None, meta
        if resolution.status != "resolved":
            return None, meta
        value = get_value(resolution.data, resolution.pack, field)
        meta["relatedSubmissionId"] = (
            resolution.submission.id if resolution.submission is not None else None
        )
        return value, meta

    if isinstance(operand, str):
        ref = operand.strip()
        if not ref:
            return None, meta
        if "." in ref and not is_related_field_operand(operand):
            return None, meta
        return get_value(ctx.data, ctx.pack, ref), meta

    return None, meta


def resolve_field_value(ctx: EvaluationContext, field_ref: str | None) -> Any:
    """Backward-compatible string field resolution on current submission."""
    value, _ = resolve_operand(ctx, field_ref)
    return value


def operand_is_not_applicable(meta: dict[str, Any]) -> bool:
    if meta.get("relatedResolutionFailed"):
        return False
    status = str(meta.get("relatedResolution") or "")
    return status in _NA_STATUSES or status == "missing_relationship"


def operand_is_ambiguous_failure(meta: dict[str, Any]) -> bool:
    return bool(meta.get("relatedResolutionFailed"))


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
) -> tuple[float | None, float | None, dict[str, Any], bool | None]:
    """Return (left, right, details, not_applicable).

    not_applicable True → caller should pass check (N/A).
    not_applicable False with None operands → fail compare.
    """
    left_raw, left_meta = resolve_operand(ctx, check.get("field"))
    details: dict[str, Any] = {"field": check.get("field"), "value": left_raw}
    details.update({f"left_{k}": v for k, v in left_meta.items()})

    if operand_is_ambiguous_failure(left_meta):
        details["error"] = "ambiguous related submission for left operand"
        return None, None, details, False

    field_b = check.get("field_b")
    has_value = check.get("value") is not None or check.get("threshold") is not None
    if field_b and has_value:
        details["error"] = "field_b and value/threshold are mutually exclusive"
        return None, None, details, False

    if field_b is not None:
        right_raw, right_meta = resolve_operand(ctx, field_b)
        details["field_b"] = field_b
        details["bound"] = right_raw
        details.update({f"right_{k}": v for k, v in right_meta.items()})
        if operand_is_ambiguous_failure(right_meta):
            details["error"] = "ambiguous related submission for right operand"
            return None, None, details, False
        if operand_is_not_applicable(left_meta) or operand_is_not_applicable(right_meta):
            return None, None, details, True
        return left_raw, right_raw, details, None

    if operand_is_not_applicable(left_meta):
        return None, None, details, True
    right = _constant_bound(ctx, check)
    details["bound"] = right
    return left_raw, right, details, None


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


def eval_compare(left: Any, right: Any, op: str) -> bool:
    """Compare operands numerically or as ISO datetimes."""
    left_n, right_n = _as_number(left), _as_number(right)
    if left_n is not None and right_n is not None:
        return eval_numeric_relation(left_n, right_n, op)
    left_d, right_d = _parse_dt(left), _parse_dt(right)
    if left_d is not None and right_d is not None:
        if op == "gt":
            return left_d > right_d
        if op == "lt":
            return left_d < right_d
        if op == "gte":
            return left_d >= right_d
        if op == "lte":
            return left_d <= right_d
    return False


def resolve_string_operands(
    ctx: EvaluationContext,
    check: dict[str, Any],
) -> tuple[str, str, dict[str, Any], bool | None]:
    left_raw, left_meta = resolve_operand(ctx, check.get("field"))
    details: dict[str, Any] = {"value": _as_str(left_raw).lower()}
    details.update({f"left_{k}": v for k, v in left_meta.items()})

    if operand_is_ambiguous_failure(left_meta):
        details["error"] = "ambiguous related submission for left operand"
        return "", "", details, False

    field_b = check.get("field_b")
    has_value = check.get("value") is not None
    if field_b and has_value:
        details["error"] = "field_b and value are mutually exclusive"
        return "", "", details, False

    if field_b is not None:
        right_raw, right_meta = resolve_operand(ctx, field_b)
        details["field_b"] = field_b
        right = _as_str(right_raw).lower()
        details["expected"] = right
        details.update({f"right_{k}": v for k, v in right_meta.items()})
        if operand_is_ambiguous_failure(right_meta):
            details["error"] = "ambiguous related submission for right operand"
            return "", "", details, False
        if operand_is_not_applicable(left_meta) or operand_is_not_applicable(right_meta):
            return "", "", details, True
        return _as_str(left_raw).lower(), right, details, None

    if operand_is_not_applicable(left_meta):
        return "", "", details, True
    right = _as_str(check.get("value")).lower()
    details["expected"] = right
    return _as_str(left_raw).lower(), right, details, None


def enrich_details_with_related(
    details: dict[str, Any], ctx: EvaluationContext
) -> dict[str, Any]:
    """Attach related submission metadata for flag diagnostics."""
    from app.domain.dqa.related import _related_submission_ref

    if not ctx.related:
        return details
    related_subs: list[dict[str, Any]] = []
    for code, res in ctx.related.items():
        if res.status == "resolved" and res.submission is not None:
            ref = _related_submission_ref(res.submission)
            ref["relationship"] = code
            ref["joinKey"] = res.join_key
            related_subs.append(ref)
        elif res.candidates:
            related_subs.extend({**c, "relationship": code} for c in res.candidates)
    if related_subs:
        details = dict(details)
        details["relatedSubmissions"] = related_subs
    return details
