"""Allowlists and limits for the ``query_aggregate`` report data source.

Shared by the tool handler (services) and ``validate_spec`` (domain) so planner
rejects and runtime behavior stay aligned.
"""

from __future__ import annotations

from typing import Any

ENTITY_IDS = frozenset({"submission", "flag"})

MEASURE_IDS = frozenset({"count", "countDistinct", "sum", "median"})

FILTER_OPS = frozenset({"eq", "in"})

DATE_WINDOW_TOKENS = frozenset(
    {"execution_date", "last_7_days", "last_14_days", "study_to_date"}
)

# groupBy / filterField allowlists per entity (no high-cardinality ids).
ENTITY_DIMENSIONS: dict[str, frozenset[str]] = {
    "submission": frozenset({"enumerator", "toolCode", "projectId", "day"}),
    "flag": frozenset(
        {"enumerator", "toolCode", "projectId", "severity", "ruleId", "day"}
    ),
}

# measureField allowlists (countDistinct / sum / median).
ENTITY_MEASURE_FIELDS: dict[str, frozenset[str]] = {
    "submission": frozenset(
        {"enumerator", "toolCode", "projectId", "submissionId", "durationMinutes"}
    ),
    "flag": frozenset(
        {
            "enumerator",
            "toolCode",
            "projectId",
            "severity",
            "ruleId",
            "submissionId",
        }
    ),
}

# Rejected as groupBy targets even if present on rows.
HIGH_CARDINALITY_GROUP_BY = frozenset({"submissionId"})

DEFAULT_LIMIT = 50
HARD_MAX_LIMIT = 100
MAX_GROUP_BY_FIELDS = 2

# Spec may use at most this many distinct resolved ranges (Option A).
MAX_DISTINCT_DATE_RANGES = 2

# Sentinel for the execution-context / certified-tool default bag.
DEFAULT_RANGE_TOKEN = "default"

MEASURES_REQUIRING_FIELD = frozenset({"countDistinct", "sum", "median"})


def parse_group_by(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def semantic_date_range_token(date_window: Any) -> str:
    """Map omit / dateWindow param to a validation-time range identity.

    Distinct tokens imply distinct resolved loads. Omitted window shares the
    query_aggregate default bag (execution context ``date_from``/``date_to``).
    """
    if date_window is None or (isinstance(date_window, str) and not date_window.strip()):
        return DEFAULT_RANGE_TOKEN
    return str(date_window).strip()


def certified_cumulative_date_range_token(date_window: Any) -> str:
    """Range identity for cumulative certified tools that accept dateWindow.

    Omitted ``dateWindow`` resolves at runtime to ``study_to_date`` (Phase 2
    default) — not the query_aggregate context-bag default.
    """
    if date_window is None or (isinstance(date_window, str) and not date_window.strip()):
        return "study_to_date"
    return str(date_window).strip()
