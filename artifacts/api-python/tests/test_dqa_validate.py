"""Tests for deterministic DQA rule validation."""

from __future__ import annotations

from app.domain.dqa.validate import validate_check, validate_rule


def _fields(*names: str) -> list[dict]:
    return [{"name": n, "type": "text", "label": n} for n in names]


def test_valid_field_to_field_rule():
    rule = {
        "severity": "amber",
        "title": "Compare",
        "message": "B22 > B21",
        "check": {"op": "gt", "field": "B22", "field_b": "B21"},
    }
    result = validate_rule(rule, form_fields=_fields("B22", "B21"))
    assert result.valid is True


def test_unknown_field_fails():
    rule = {
        "severity": "amber",
        "title": "Bad",
        "message": "Missing field",
        "check": {"op": "required", "field": "MISSING"},
    }
    result = validate_rule(rule, form_fields=_fields("B22"))
    assert result.valid is False
    assert any(err.code == "unknown_field" for err in result.errors)


def test_scoped_ref_rejected():
    result = validate_check(
        {"op": "equals", "field": "register.A10", "field_b": "worker.D4"},
        path="check",
        allowed_fields={"A10", "D4"},
        thresholds={},
    )
    assert result.valid is False
    assert any(err.code == "scoped_ref" for err in result.errors)


def test_unknown_operator_fails():
    result = validate_check(
        {"op": "cross_form_compare", "field": "A10"},
        path="check",
        allowed_fields={"A10"},
        thresholds={},
    )
    assert result.valid is False
    assert any(err.code == "unknown_op" for err in result.errors)


def test_gt_field_b_and_value_ambiguous():
    result = validate_check(
        {"op": "gt", "field": "B22", "field_b": "B21", "value": 1},
        path="check",
        allowed_fields={"B22", "B21"},
        thresholds={},
    )
    assert result.valid is False
    assert any(err.code == "ambiguous_compare" for err in result.errors)


def test_duration_min_max_fields():
    rule = {
        "severity": "amber",
        "title": "Duration",
        "message": "Out of band",
        "check": {
            "op": "duration_minutes_gte",
            "start_field": "B2",
            "end_field": "B3",
            "min": 20,
            "max": 180,
        },
    }
    result = validate_rule(rule, form_fields=_fields("B2", "B3"))
    assert result.valid is True


def test_nested_if_then_valid():
    rule = {
        "severity": "red",
        "title": "Conditional",
        "message": "Conditional fail",
        "check": {
            "op": "if_then",
            "if": {"op": "equals", "field": "B7", "value": "1"},
            "then": {"op": "gt", "field": "B22", "field_b": "B21"},
        },
    }
    result = validate_rule(rule, form_fields=_fields("B7", "B22", "B21"))
    assert result.valid is True
