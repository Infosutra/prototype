"""Highlight-field resolution for DQA flags."""

from __future__ import annotations

from typing import Any

from app.domain.dqa.values import (
    _REF_KEYS,
    _REF_LIST_KEYS,
    find_data_key,
    resolve_alias,
)

def collect_field_refs(node: Any, out: list[str] | None = None) -> list[str]:
    """Walk a check/details tree and collect logical field references."""
    if out is None:
        out = []
    if not isinstance(node, dict):
        return out
    for key in _REF_KEYS:
        value = node.get(key)
        if value:
            text = str(value).strip()
            if text and text not in out:
                out.append(text)
    for key in _REF_LIST_KEYS:
        for item in node.get(key) or []:
            text = str(item).strip()
            if text and text not in out:
                out.append(text)
    for nested_key in ("check", "if", "then", "failed", "inner"):
        if nested_key in node:
            collect_field_refs(node[nested_key], out)
    for child in node.get("checks") or []:
        collect_field_refs(child, out)
    return out

def resolve_highlight_fields(
    *,
    pack: dict[str, Any],
    check: dict[str, Any] | None,
    details: dict[str, Any] | None,
    data: dict[str, Any],
) -> list[str]:
    """Return submission data keys (and special markers) to highlight for a flag."""
    refs = collect_field_refs(check)
    collect_field_refs(details, refs)
    keys: list[str] = []

    op = str((details or {}).get("op") or (check or {}).get("op") or "")
    if op == "gps_present":
        for marker in ("_geolocation", "__location__"):
            if marker not in keys:
                keys.append(marker)
    if op == "attachment_count_gte":
        if "_attachments" not in keys:
            keys.append("_attachments")
    if op == "duration_minutes_gte":
        for meta in ("start", "end"):
            found = find_data_key(data, meta)
            if found and found not in keys:
                keys.append(found)
            elif meta not in keys:
                keys.append(meta)

    for ref in refs:
        leaf = resolve_alias(pack, ref) or ref
        found = find_data_key(data, leaf)
        candidate = found or leaf
        if candidate not in keys:
            keys.append(candidate)
    return keys


def highlight_fields_for_flag(
    *,
    pack: dict[str, Any] | None,
    rule: dict[str, Any] | None,
    details: dict[str, Any] | None,
    data: dict[str, Any],
) -> list[str]:
    if isinstance(details, dict) and details.get("highlightFields"):
        existing = details.get("highlightFields")
        if isinstance(existing, list) and existing:
            return [str(x) for x in existing]
    if not pack:
        return []
    check = None
    if rule:
        check = rule.get("check")
        if check is None and rule.get("checks"):
            check = {"op": "all", "checks": rule["checks"]}
    return resolve_highlight_fields(pack=pack, check=check, details=details, data=data)
