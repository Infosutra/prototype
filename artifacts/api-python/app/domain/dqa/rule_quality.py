"""Deterministic rule quality warnings."""

from __future__ import annotations

from typing import Any

from app.domain.dqa.operands import collect_relationship_codes, is_related_field_operand


def _walk_operands(node: Any, out: list[Any]) -> None:
    if not isinstance(node, dict):
        return
    for key in ("field", "field_b", "start_field", "end_field"):
        if key in node:
            out.append(node.get(key))
    for child in node.get("checks") or []:
        _walk_operands(child, out)
    for nested in ("check", "if", "then"):
        if nested in node:
            _walk_operands(node[nested], out)


def analyze_rule_quality(
    rule: dict[str, Any],
    *,
    preview: dict[str, Any] | None = None,
    form_field_stats: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    check = rule.get("check")
    if not isinstance(check, dict):
        warnings.append({"code": "missing_check", "message": "Rule has no check definition"})
        return warnings

    operands: list[Any] = []
    _walk_operands(check, operands)
    if not operands:
        warnings.append({"code": "no_operands", "message": "Rule may have no meaningful field constraints"})

    if str(check.get("op") or "") in {"blank"} and len(operands) <= 1:
        warnings.append({"code": "broad_condition", "message": "Condition may match too many records"})

    rel_codes = collect_relationship_codes(check)
    if rel_codes:
        warnings.append(
            {
                "code": "inter_form",
                "message": f"Rule uses inter-form relationships: {', '.join(sorted(rel_codes))}",
            }
        )

    for operand in operands:
        if is_related_field_operand(operand):
            continue
        field = str(operand or "").strip()
        stats = (form_field_stats or {}).get(field) if field else None
        if stats and stats.get("null_rate", 0) >= 0.5:
            warnings.append(
                {
                    "code": "often_null_field",
                    "message": f"Field {field} is blank in about {int(stats['null_rate'] * 100)}% of submissions",
                }
            )

    if isinstance(preview, dict):
        checked = int(preview.get("submissions_checked") or 0)
        na = int(preview.get("not_applicable_count") or 0)
        if checked > 0 and na / checked >= 0.8:
            warnings.append(
                {
                    "code": "mostly_not_applicable",
                    "message": "Rule is not applicable for most tested submissions",
                }
            )
        ambiguous = int(preview.get("ambiguous_related_count") or 0)
        if ambiguous > 0:
            warnings.append(
                {
                    "code": "ambiguous_relationship",
                    "message": f"{ambiguous} tested record(s) had ambiguous related submissions",
                }
            )

    return warnings


def compute_field_null_rates(
    submissions: list[Any],
    pack: dict[str, Any],
    fields: set[str],
) -> dict[str, dict[str, Any]]:
    from app.domain.dqa.values import get_value, _is_blank

    stats: dict[str, dict[str, Any]] = {}
    total = len(submissions) or 1
    for field in fields:
        nulls = 0
        for row in submissions:
            data = row.data if isinstance(getattr(row, "data", None), dict) else {}
            if _is_blank(get_value(data, pack, field)):
                nulls += 1
        stats[field] = {"null_rate": nulls / total, "null_count": nulls, "total": total}
    return stats
