"""Generic in-memory aggregation primitives for report stats.

No domain thresholds, top-N business cuts, severity coercion, or narrative
templates belong here — those live in ``domain_rules``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.domain.reporting.helpers import median as median_of


@dataclass(frozen=True)
class Measure:
    """One named aggregation over rows in a group (or the full set)."""

    op: str
    field: str | None = None
    pred: Callable[[Mapping[str, Any]], bool] | None = None


def count() -> Measure:
    return Measure(op="count")


def count_where(pred: Callable[[Mapping[str, Any]], bool]) -> Measure:
    return Measure(op="count_where", pred=pred)


def count_distinct(field: str) -> Measure:
    return Measure(op="count_distinct", field=field)


def first(field: str) -> Measure:
    """First non-None value in encounter order."""
    return Measure(op="first", field=field)


def sum_(field: str) -> Measure:
    return Measure(op="sum", field=field)


def collect_set(
    field: str, *, where: Callable[[Mapping[str, Any]], bool] | None = None
) -> Measure:
    return Measure(op="collect_set", field=field, pred=where)


def collect_list(
    field: str, *, where: Callable[[Mapping[str, Any]], bool] | None = None
) -> Measure:
    return Measure(op="collect_list", field=field, pred=where)


def any_(pred: Callable[[Mapping[str, Any]], bool]) -> Measure:
    return Measure(op="any", pred=pred)


def project_fields(source: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    """Pick named fields from a mapping (missing keys → None)."""
    return {name: source.get(name) for name in fields}


def with_derived_columns(
    rows: Sequence[Mapping[str, Any]],
    derivations: Mapping[str, Callable[[Mapping[str, Any]], Any]],
) -> list[dict[str, Any]]:
    """Return copies of rows with extra derived columns."""
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for name, fn in derivations.items():
            item[name] = fn(item)
        out.append(item)
    return out


def _passes(
    row: Mapping[str, Any], filters: Sequence[Callable[[Mapping[str, Any]], bool]] | None
) -> bool:
    if not filters:
        return True
    return all(pred(row) for pred in filters)


def _group_key(row: Mapping[str, Any], group_by: Sequence[str]) -> tuple[Any, ...]:
    return tuple(row.get(name) for name in group_by)


def _apply_measures(
    members: Sequence[Mapping[str, Any]], measures: Mapping[str, Measure]
) -> dict[str, Any]:
    """Compute measures over ``members`` in the given encounter order."""
    out: dict[str, Any] = {}
    for name, measure in measures.items():
        if measure.op == "count":
            out[name] = len(members)
        elif measure.op == "count_where":
            assert measure.pred is not None
            out[name] = sum(1 for row in members if measure.pred(row))
        elif measure.op == "count_distinct":
            assert measure.field is not None
            out[name] = len({row.get(measure.field) for row in members})
        elif measure.op == "first":
            assert measure.field is not None
            value = None
            for row in members:
                candidate = row.get(measure.field)
                if candidate is not None:
                    value = candidate
                    break
            out[name] = value
        elif measure.op == "sum":
            assert measure.field is not None
            total = 0
            for row in members:
                raw = row.get(measure.field)
                if raw is None:
                    continue
                total += raw
            out[name] = total
        elif measure.op == "collect_set":
            assert measure.field is not None
            values: set[Any] = set()
            for row in members:
                if measure.pred is not None and not measure.pred(row):
                    continue
                value = row.get(measure.field)
                if value is not None:
                    values.add(value)
            out[name] = sorted(values)
        elif measure.op == "collect_list":
            assert measure.field is not None
            values = []
            for row in members:
                if measure.pred is not None and not measure.pred(row):
                    continue
                value = row.get(measure.field)
                if value is not None:
                    values.append(value)
            out[name] = values
        elif measure.op == "any":
            assert measure.pred is not None
            out[name] = any(measure.pred(row) for row in members)
        elif measure.op == "median":
            assert measure.field is not None
            values = [
                row.get(measure.field)
                for row in members
                if row.get(measure.field) is not None
            ]
            out[name] = median_of(values)  # type: ignore[arg-type]
        else:
            raise ValueError(f"Unknown measure op: {measure.op}")
    return out


def scalar_aggregate(
    rows: Sequence[Mapping[str, Any]],
    *,
    measures: Mapping[str, Measure],
    filters: Sequence[Callable[[Mapping[str, Any]], bool]] | None = None,
) -> dict[str, Any]:
    """Aggregate the full (filtered) row set into one object — no group_by."""
    members = [row for row in rows if _passes(row, filters)]
    return _apply_measures(members, measures)


def aggregate(
    rows: Sequence[Mapping[str, Any]],
    *,
    group_by: Sequence[str],
    measures: Mapping[str, Measure],
    filters: Sequence[Callable[[Mapping[str, Any]], bool]] | None = None,
    order_by: Sequence[tuple[str, str]] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """GROUP BY ``group_by`` preserving first-seen group order and row encounter order.

    ``order_by`` entries are ``(field, "asc"|"desc")``. Optional ``limit`` is a
    generic SQL-style cap supplied by the caller — domain constants must not be
    hardcoded here.
    """
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    order: list[tuple[Any, ...]] = []
    for row in rows:
        if not _passes(row, filters):
            continue
        key = _group_key(row, group_by)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)

    results: list[dict[str, Any]] = []
    for key in order:
        members = grouped[key]
        item = {name: key[idx] for idx, name in enumerate(group_by)}
        item.update(_apply_measures(members, measures))
        results.append(item)

    if order_by:
        for field, direction in reversed(list(order_by)):
            reverse = direction.lower() == "desc"

            def sort_key(row: dict[str, Any], field: str = field) -> Any:
                value = row.get(field)
                return (value is None, value)

            results.sort(key=sort_key, reverse=reverse)

    if limit is not None:
        results = results[:limit]
    return results
