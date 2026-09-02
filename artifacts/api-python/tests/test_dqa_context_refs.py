"""Unit tests for Phase 0 evaluation context and intra-form refs."""

from __future__ import annotations

from app.domain.dqa.context import EvaluationContext
from app.domain.dqa.refs import (
    eval_numeric_relation,
    resolve_field_value,
    resolve_numeric_operands,
    resolve_string_operands,
)


def _ctx(data: dict | None = None) -> EvaluationContext:
    pack = {"fields": {"score_a": "B22", "score_b": "B21"}}
    return EvaluationContext.from_eval_args(
        data=data or {},
        pack=pack,
    )


def test_resolve_field_value_uses_pack_alias():
    ctx = _ctx({"B22": "10", "B21": "5"})
    assert resolve_field_value(ctx, "score_a") == "10"
    assert resolve_field_value(ctx, "score_b") == "5"


def test_resolve_field_value_rejects_scoped_ref_in_phase0():
    ctx = _ctx({"A10": "12"})
    assert resolve_field_value(ctx, "register.A10") is None


def test_resolve_numeric_operands_field_vs_constant():
    ctx = _ctx({"B22": "10"})
    left, right, details, na = resolve_numeric_operands(
        ctx, {"field": "score_a", "value": 5}
    )
    assert na is None
    assert left == "10"
    assert right == 5.0
    assert details["bound"] == 5.0


def test_resolve_numeric_operands_field_vs_field():
    ctx = _ctx({"B22": "10", "B21": "5"})
    left, right, details, na = resolve_numeric_operands(
        ctx, {"field": "score_a", "field_b": "score_b"}
    )
    assert na is None
    assert left == "10"
    assert right == "5"
    assert details["field_b"] == "score_b"


def test_resolve_numeric_operands_rejects_field_b_and_value():
    ctx = _ctx({"B22": "10", "B21": "5"})
    _, _, details, na = resolve_numeric_operands(
        ctx, {"field": "score_a", "field_b": "score_b", "value": 1}
    )
    assert na is False
    assert "error" in details


def test_eval_numeric_relation():
    assert eval_numeric_relation(10.0, 5.0, "gt") is True
    assert eval_numeric_relation(5.0, 10.0, "gt") is False
    assert eval_numeric_relation(5.0, 5.0, "lte") is True


def test_resolve_string_operands_field_vs_field():
    ctx = _ctx({"A3": "Yes", "A4_1": "yes"})
    left, right, _, na = resolve_string_operands(
        ctx, {"field": "A3", "field_b": "A4_1"}
    )
    assert na is None
    assert left == "yes"
    assert right == "yes"
