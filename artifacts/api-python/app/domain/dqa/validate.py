"""Deterministic validation for DQA rules and check trees."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.dqa.catalog import (
    COMPILER_OPERATORS,
    EVAL_OPERATORS,
    FIELD_LIST_KEYS,
    FIELD_REF_KEYS,
    LIST_VALUE_OPS,
    MAX_CHECK_DEPTH,
    MAX_CHECK_NODES,
    NUMERIC_COMPARE_OPS,
    STRING_COMPARE_OPS,
)
from app.domain.dqa.eval import eval_check


@dataclass
class ValidationIssue:
    path: str
    code: str
    message: str


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [
                {"path": e.path, "code": e.code, "message": e.message} for e in self.errors
            ],
            "warnings": list(self.warnings),
        }


def build_allowed_field_refs(
    *,
    form_fields: list[dict[str, Any]] | None,
    pack: dict[str, Any] | None,
) -> set[str]:
    allowed: set[str] = set()
    for item in form_fields or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                allowed.add(name)
    fields_map = (pack or {}).get("fields") or {}
    if isinstance(fields_map, dict):
        for alias, leaf in fields_map.items():
            alias_text = str(alias).strip()
            if alias_text:
                allowed.add(alias_text)
            leaf_text = str(leaf).strip()
            if leaf_text:
                allowed.add(leaf_text)
    return allowed


def _is_scoped_ref(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and "." in text


def validate_rule(
    rule: dict[str, Any] | None,
    *,
    form_fields: list[dict[str, Any]] | None = None,
    pack: dict[str, Any] | None = None,
    for_compile: bool = False,
) -> ValidationResult:
    result = ValidationResult(valid=True)
    if not isinstance(rule, dict):
        result.valid = False
        result.errors.append(ValidationIssue("", "invalid_rule", "Rule must be an object"))
        return result

    for key in ("severity", "title", "message", "check"):
        if key not in rule:
            result.valid = False
            result.errors.append(
                ValidationIssue(key, "missing_key", f"Missing required key: {key}")
            )
    severity = str(rule.get("severity") or "").lower()
    if severity and severity not in {"red", "amber"}:
        result.valid = False
        result.errors.append(
            ValidationIssue("severity", "invalid_severity", "severity must be red or amber")
        )

    allowed = build_allowed_field_refs(form_fields=form_fields, pack=pack)
    thresholds = (pack or {}).get("thresholds") or {}
    allowed_ops = COMPILER_OPERATORS if for_compile else EVAL_OPERATORS
    check_result = validate_check(
        rule.get("check"),
        path="check",
        allowed_fields=allowed,
        thresholds=thresholds if isinstance(thresholds, dict) else {},
        allowed_ops=allowed_ops,
    )
    result.errors.extend(check_result.errors)
    result.warnings.extend(check_result.warnings)
    if check_result.errors:
        result.valid = False

    if result.valid and isinstance(rule.get("check"), dict):
        try:
            eval_check(rule["check"], data={}, pack=pack or {})
        except Exception as exc:  # pragma: no cover - safety net
            result.valid = False
            result.errors.append(
                ValidationIssue("check", "eval_error", f"Check could not be evaluated: {exc}")
            )
    return result


def validate_check(
    check: Any,
    *,
    path: str,
    allowed_fields: set[str],
    thresholds: dict[str, Any],
    depth: int = 0,
    node_count: list[int] | None = None,
    allowed_ops: frozenset[str] | None = None,
) -> ValidationResult:
    if node_count is None:
        node_count = [0]
    result = ValidationResult(valid=True)

    if depth > MAX_CHECK_DEPTH:
        result.valid = False
        result.errors.append(
            ValidationIssue(path, "max_depth", f"Check tree exceeds depth {MAX_CHECK_DEPTH}")
        )
        return result

    node_count[0] += 1
    if node_count[0] > MAX_CHECK_NODES:
        result.valid = False
        result.errors.append(
            ValidationIssue(path, "max_nodes", f"Check tree exceeds {MAX_CHECK_NODES} nodes")
        )
        return result

    if not isinstance(check, dict):
        result.valid = False
        result.errors.append(ValidationIssue(path, "invalid_check", "Check must be an object"))
        return result

    op = str(check.get("op") or "").strip()
    if not op:
        result.valid = False
        result.errors.append(ValidationIssue(path, "missing_op", "Check missing op"))
        return result
    ops = allowed_ops or EVAL_OPERATORS
    if op not in ops:
        result.valid = False
        result.errors.append(
            ValidationIssue(f"{path}.op", "unknown_op", f"Unsupported operator: {op}")
        )
        return result

    for key in FIELD_REF_KEYS:
        if key not in check:
            continue
        ref = check.get(key)
        ref_path = f"{path}.{key}"
        if _is_scoped_ref(ref):
            result.valid = False
            result.errors.append(
                ValidationIssue(
                    ref_path,
                    "scoped_ref",
                    "Inter-form scoped field references are not supported",
                )
            )
            continue
        ref_text = str(ref or "").strip()
        if ref_text and ref_text not in allowed_fields:
            result.valid = False
            result.errors.append(
                ValidationIssue(ref_path, "unknown_field", f"Unknown field reference: {ref_text}")
            )

    for key in FIELD_LIST_KEYS:
        for idx, item in enumerate(check.get(key) or []):
            item_path = f"{path}.{key}[{idx}]"
            if _is_scoped_ref(item):
                result.valid = False
                result.errors.append(
                    ValidationIssue(item_path, "scoped_ref", "Inter-form scoped refs not supported")
                )
            elif str(item or "").strip() and str(item).strip() not in allowed_fields:
                result.valid = False
                result.errors.append(
                    ValidationIssue(
                        item_path, "unknown_field", f"Unknown field reference: {item}"
                    )
                )

    if op in NUMERIC_COMPARE_OPS:
        has_field_b = bool(str(check.get("field_b") or "").strip())
        has_value = check.get("value") is not None or check.get("threshold") is not None
        if has_field_b and has_value:
            result.valid = False
            result.errors.append(
                ValidationIssue(
                    path,
                    "ambiguous_compare",
                    "Use field_b or value/threshold, not both",
                )
            )
        if not has_field_b and not has_value:
            result.valid = False
            result.errors.append(
                ValidationIssue(path, "missing_operand", "Comparison requires value or field_b")
            )
        if check.get("threshold") is not None:
            key = str(check["threshold"])
            if key not in thresholds:
                result.warnings.append(f"Threshold key '{key}' not defined in pack.thresholds")

    if op in STRING_COMPARE_OPS:
        has_field_b = bool(str(check.get("field_b") or "").strip())
        has_value = check.get("value") is not None
        if has_field_b and has_value:
            result.valid = False
            result.errors.append(
                ValidationIssue(path, "ambiguous_compare", "Use field_b or value, not both")
            )
        if not has_field_b and not has_value:
            result.valid = False
            result.errors.append(
                ValidationIssue(path, "missing_operand", "Comparison requires value or field_b")
            )

    if op in LIST_VALUE_OPS:
        values = check.get("values") or check.get("exclusive_values")
        if not isinstance(values, list) or not values:
            result.valid = False
            result.errors.append(
                ValidationIssue(path, "missing_values", "Operator requires a non-empty values list")
            )

    if op == "regex":
        pattern = str(check.get("pattern") or "")
        if not pattern:
            result.valid = False
            result.errors.append(ValidationIssue(path, "missing_pattern", "regex requires pattern"))
        else:
            try:
                re.compile(pattern)
            except re.error as exc:
                result.valid = False
                result.errors.append(
                    ValidationIssue(f"{path}.pattern", "invalid_regex", str(exc))
                )

    if op == "between":
        has_min = check.get("min") is not None or check.get("min_threshold") is not None
        has_max = check.get("max") is not None or check.get("max_threshold") is not None
        if not has_min and not has_max:
            result.valid = False
            result.errors.append(
                ValidationIssue(path, "missing_bounds", "between requires min and/or max")
            )

    if op == "duration_minutes_gte":
        start = str(check.get("start_field") or "start").strip()
        end = str(check.get("end_field") or "end").strip()
        if start not in allowed_fields:
            result.valid = False
            result.errors.append(
                ValidationIssue(f"{path}.start_field", "unknown_field", f"Unknown field: {start}")
            )
        if end not in allowed_fields:
            result.valid = False
            result.errors.append(
                ValidationIssue(f"{path}.end_field", "unknown_field", f"Unknown field: {end}")
            )

    if op == "all" or op == "any":
        children = check.get("checks") or []
        if not isinstance(children, list) or not children:
            result.valid = False
            result.errors.append(
                ValidationIssue(f"{path}.checks", "missing_checks", f"{op} requires checks[]")
            )
        else:
            for idx, child in enumerate(children):
                child_result = validate_check(
                    child,
                    path=f"{path}.checks[{idx}]",
                    allowed_fields=allowed_fields,
                    thresholds=thresholds,
                    depth=depth + 1,
                    node_count=node_count,
                    allowed_ops=allowed_ops,
                )
                _merge_results(result, child_result)

    if op == "not":
        child_result = validate_check(
            check.get("check"),
            path=f"{path}.check",
            allowed_fields=allowed_fields,
            thresholds=thresholds,
            depth=depth + 1,
            node_count=node_count,
            allowed_ops=allowed_ops,
        )
        _merge_results(result, child_result)

    if op == "if_then":
        for branch in ("if", "then"):
            child_result = validate_check(
                check.get(branch),
                path=f"{path}.{branch}",
                allowed_fields=allowed_fields,
                thresholds=thresholds,
                depth=depth + 1,
                node_count=node_count,
                allowed_ops=allowed_ops,
            )
            _merge_results(result, child_result)

    return result


def validate_pack_rules(
    rules: list[Any] | None,
    *,
    form_fields: list[dict[str, Any]] | None = None,
    pack: dict[str, Any] | None = None,
) -> ValidationResult:
    result = ValidationResult(valid=True)
    if not isinstance(rules, list):
        result.valid = False
        result.errors.append(ValidationIssue("rules", "invalid_rules", "rules must be a list"))
        return result
    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            result.valid = False
            result.errors.append(
                ValidationIssue(f"rules[{idx}]", "invalid_rule", "Each rule must be an object")
            )
            continue
        item = validate_rule(rule, form_fields=form_fields, pack=pack)
        for err in item.errors:
            result.errors.append(
                ValidationIssue(f"rules[{idx}].{err.path}".rstrip("."), err.code, err.message)
            )
        result.warnings.extend(item.warnings)
        if not item.valid:
            result.valid = False
    return result


def _merge_results(target: ValidationResult, other: ValidationResult) -> None:
    target.errors.extend(other.errors)
    target.warnings.extend(other.warnings)
    if not other.valid:
        target.valid = False
