"""Shared join-key helpers for DQA (decoupled from triangulation views)."""

from __future__ import annotations

from typing import Any

from app.domain.dqa.values import get_value


def join_key_from_submission(
    data: dict[str, Any],
    pack: dict[str, Any],
    field_ref: str,
) -> str:
    """Extract normalized join key from a submission using pack field resolution."""
    value = get_value(data, pack, field_ref)
    return str(value or "").strip()


def index_submissions_by_join_key(
    rows: list[Any],
    pack: dict[str, Any],
    field_ref: str,
) -> dict[str, list[Any]]:
    """Group submissions by join key value (empty keys omitted)."""
    groups: dict[str, list[Any]] = {}
    for row in rows:
        data = row.data if isinstance(getattr(row, "data", None), dict) else {}
        key = join_key_from_submission(data, pack, field_ref)
        if not key:
            continue
        groups.setdefault(key, []).append(row)
    return groups


def pick_latest_submission(rows: list[Any]) -> Any | None:
    best = None
    for row in rows:
        if best is None:
            best = row
            continue
        cand_at = getattr(row, "submitted_at", None)
        best_at = getattr(best, "submitted_at", None)
        if cand_at is None:
            continue
        if best_at is None or cand_at > best_at:
            best = row
    return best
