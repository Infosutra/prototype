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
        {"op": "all", "params": ["checks[]"], "passes_when": "every child passes"},
        {"op": "any", "params": ["checks[]"], "passes_when": "at least one child passes"},
        {"op": "not", "params": ["check"], "passes_when": "inner check fails (use sparingly; prefer a positive validity op)"},
        {"op": "if_then", "params": ["if", "then"], "passes_when": "if antecedent fails → N/A pass; else consequent must pass"},
        {"op": "equals", "params": ["field", "value|field_b"], "passes_when": "values are equal (use for must-match)"},
        {"op": "equals_any", "params": ["field", "values[]"], "passes_when": "field is one of values"},
        {"op": "not_equals", "params": ["field", "value|field_b"], "passes_when": "values differ (only when they must differ)"},
        {"op": "in", "params": ["field", "values[]"], "passes_when": "field is in values"},
        {"op": "not_in", "params": ["field", "values[]"], "passes_when": "field is not in forbidden values"},
        {
            "op": "gt|lt|gte|lte",
            "params": ["field", "value|field_b|related_field|threshold"],
            "passes_when": "numeric relation holds (e.g. must-not-exceed → lte)",
        },
        {"op": "between", "params": ["field", "min|min_threshold", "max|max_threshold"], "passes_when": "value inside inclusive range"},
        {"op": "required", "params": ["field"], "passes_when": "field is non-blank"},
        {"op": "blank", "params": ["field"], "passes_when": "field is blank"},
        {"op": "regex", "params": ["field", "pattern"], "passes_when": "value full-matches pattern"},
        {"op": "min_length", "params": ["field", "min"], "passes_when": "string length >= min"},
        {"op": "integer", "params": ["field"], "passes_when": "value is an integer string"},
        {
            "op": "duration_minutes_gte",
            "params": ["start_field", "end_field", "min|threshold", "max|max_threshold?"],
            "passes_when": "duration minutes within min/max band (do not wrap in not)",
        },
        {"op": "exclusive_choice", "params": ["field", "exclusive_values[]"], "passes_when": "exclusive option not combined with others"},
        {"op": "selected_count_lte", "params": ["field", "max|threshold"], "passes_when": "selected count <= max"},
        {"op": "any_section_filled", "params": ["prefix"], "passes_when": "any field under prefix has data"},
    ]
