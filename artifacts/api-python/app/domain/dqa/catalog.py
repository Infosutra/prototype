"""Operator catalog for DQA rule compilation and validation."""

from __future__ import annotations

from typing import Any

# Operators the LLM compiler may emit (subset of eval.py catalog).
COMPILER_OPERATORS: frozenset[str] = frozenset(
    {
        "all",
        "any",
        "not",
        "if_then",
        "equals",
        "equals_any",
        "not_equals",
        "in",
        "not_in",
        "gt",
        "lt",
        "gte",
        "lte",
        "between",
        "required",
        "blank",
        "regex",
        "min_length",
        "integer",
        "duration_minutes_gte",
        "exclusive_choice",
        "selected_count_lte",
        "any_section_filled",
    }
)

# Full eval catalog — used when validating persisted rule packs.
EVAL_OPERATORS: frozenset[str] = COMPILER_OPERATORS | frozenset(
    {
        "unique_in_project",
        "group_count_lte",
        "gps_present",
        "attachment_count_gte",
        "match_density_gt",
        "skip_residue",
        "all_equal",
        "specify_valid",
    }
)

NUMERIC_COMPARE_OPS = frozenset({"gt", "lt", "gte", "lte"})
STRING_COMPARE_OPS = frozenset({"equals", "not_equals"})
LIST_VALUE_OPS = frozenset({"equals_any", "in", "not_in", "exclusive_choice"})

FIELD_REF_KEYS = (
    "field",
    "field_b",
    "parent_field",
    "trigger_field",
    "text_field",
    "start_field",
    "end_field",
)
FIELD_LIST_KEYS = ("fields", "child_fields")

MAX_CHECK_DEPTH = 12
MAX_CHECK_NODES = 64


def operator_catalog_for_prompt() -> list[dict[str, Any]]:
    """Compact operator list embedded in compiler prompts."""
    return [
        {"op": "all", "params": ["checks[]"]},
        {"op": "any", "params": ["checks[]"]},
        {"op": "not", "params": ["check"]},
        {"op": "if_then", "params": ["if", "then"]},
        {"op": "equals", "params": ["field", "value|field_b"]},
        {"op": "equals_any", "params": ["field", "values[]"]},
        {"op": "not_equals", "params": ["field", "value|field_b"]},
        {"op": "in", "params": ["field", "values[]"]},
        {"op": "not_in", "params": ["field", "values[]"]},
        {"op": "gt|lt|gte|lte", "params": ["field", "value|field_b|threshold"]},
        {"op": "between", "params": ["field", "min|min_threshold", "max|max_threshold"]},
        {"op": "required", "params": ["field"]},
        {"op": "blank", "params": ["field"]},
        {"op": "regex", "params": ["field", "pattern"]},
        {"op": "min_length", "params": ["field", "min"]},
        {"op": "integer", "params": ["field"]},
        {
            "op": "duration_minutes_gte",
            "params": ["start_field", "end_field", "min|threshold", "max|max_threshold?"],
        },
        {"op": "exclusive_choice", "params": ["field", "exclusive_values[]"]},
        {"op": "selected_count_lte", "params": ["field", "max|threshold"]},
        {"op": "any_section_filled", "params": ["prefix"]},
    ]
