"""Shared value handling for the specification renderers.

All three output formats (HTML, PDF, DOCX) read component data through these
helpers so a number is formatted identically wherever it appears.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.report_spec.keys import component_data_key
from app.domain.report_spec.spec import (
    HighlightRule,
    ReportSpec,
    SortSpec,
    ValueFormat,
)

UNAVAILABLE = "Not available"


@dataclass
class RenderPayload:
    """Everything a renderer needs: the definition, the data, and the prose."""

    spec: ReportSpec
    data: dict[str, Any] = field(default_factory=dict)
    narratives: dict[str, str] = field(default_factory=dict)
    # data key -> human-readable reason the source could not be resolved
    errors: dict[str, str] = field(default_factory=dict)
    # Header metadata (study, organization, reporting day) resolved at execution.
    meta: dict[str, Any] = field(default_factory=dict)

    def payload_for(self, component: Any) -> tuple[Any, str | None]:
        """Return (payload, error). Payload is None when the source failed."""
        key = component_data_key(component)
        if key is None:
            return None, None
        if key in self.errors:
            return None, self.errors[key]
        if key not in self.data:
            return None, UNAVAILABLE
        return self.data[key], None

    def rows_for(self, component: Any) -> tuple[list[dict[str, Any]], str | None]:
        payload, error = self.payload_for(component)
        if error is not None:
            return [], error
        if payload is None:
            return [], None
        if isinstance(payload, list):
            rows = [row for row in payload if isinstance(row, dict)]
            return prepare_rows(rows, getattr(component, "sort", None), getattr(component, "limit", None)), None
        return [], "Expected a row set."

    def record_for(self, component: Any) -> tuple[dict[str, Any], str | None]:
        payload, error = self.payload_for(component)
        if error is not None:
            return {}, error
        if isinstance(payload, dict):
            return payload, None
        return {}, "Expected a single record."


def prepare_rows(
    rows: list[dict[str, Any]], sort: SortSpec | None, limit: int | None
) -> list[dict[str, Any]]:
    out = list(rows)
    if sort is not None:
        out.sort(
            key=lambda row: _sort_key(row.get(sort.field)),
            reverse=sort.direction == "desc",
        )
    if limit is not None:
        out = out[:limit]
    return out


def _sort_key(value: Any) -> tuple[int, float, str]:
    if value is None:
        return (2, 0.0, "")
    if isinstance(value, bool):
        return (0, float(value), "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    return (1, 0.0, str(value).lower())


def format_value(value: Any, fmt: ValueFormat, unit: str | None = None) -> str:
    """Format an authoritative value for display. Never alters the underlying number."""
    if value is None or value == "":
        return "—"
    text: str
    if fmt == "int":
        try:
            text = f"{int(round(float(value))):,}"
        except (TypeError, ValueError):
            text = str(value)
    elif fmt == "float":
        try:
            text = f"{float(value):g}"
        except (TypeError, ValueError):
            text = str(value)
    elif fmt == "percent":
        try:
            text = f"{float(value):.1f}%"
        except (TypeError, ValueError):
            text = str(value)
    elif fmt == "severity":
        text = str(value).upper()
    else:
        text = str(value)
    if unit:
        text = f"{text} {unit}"
    return text


def numeric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def highlight_matches(row: dict[str, Any], rule: HighlightRule | None) -> bool:
    """Compare a row against its authoritative benchmark field.

    Returns False when either side is missing rather than guessing a threshold.
    """
    if rule is None:
        return False
    value = row.get(rule.field)
    benchmark = row.get(rule.benchmark_field)
    if value is None or benchmark is None:
        return False
    if rule.comparison == "below_benchmark":
        return numeric(value) < numeric(benchmark)
    return numeric(value) > numeric(benchmark)


def series_values(rows: list[dict[str, Any]], field_name: str) -> list[float]:
    return [numeric(row.get(field_name)) for row in rows]


def category_labels(rows: list[dict[str, Any]], field_name: str) -> list[str]:
    return [str(row.get(field_name) if row.get(field_name) is not None else "—") for row in rows]
