"""Compute JSON diff summary between rule versions."""

from __future__ import annotations

from typing import Any


def _flatten(obj: Any, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for key, val in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            _flatten(val, path, out)
    elif isinstance(obj, list):
        out[prefix or "[]"] = obj
    else:
        out[prefix] = obj
    return out


def compute_rule_diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    left = _flatten(before or {})
    right = _flatten(after or {})
    changes: list[dict[str, Any]] = []
    keys = sorted(set(left.keys()) | set(right.keys()))
    for key in keys:
        if key not in left:
            changes.append({"path": key, "change": "added", "after": right[key]})
        elif key not in right:
            changes.append({"path": key, "change": "removed", "before": left[key]})
        elif left[key] != right[key]:
            changes.append({"path": key, "change": "modified", "before": left[key], "after": right[key]})
    return {"change_count": len(changes), "changes": changes}
