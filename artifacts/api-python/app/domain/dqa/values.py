"""Field access and value coercion for DQA evaluation."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

YES_VALUES = {"1", "yes", "y", "true"}
NO_VALUES = {"2", "0", "no", "n", "false"}

def find_field_value(data: dict[str, Any], field_name: str | None) -> Any:
    if not field_name:
        return None
    if field_name in data:
        return data[field_name]
    suffix = f"/{field_name}"
    for key, value in data.items():
        if key.endswith(suffix):
            return value
    return None


def resolve_alias(pack: dict[str, Any], alias: str) -> str | None:
    fields = pack.get("fields") or {}
    if alias in fields:
        return str(fields[alias])
    return alias


def get_value(data: dict[str, Any], pack: dict[str, Any], field_ref: str | None) -> Any:
    if not field_ref:
        return None
    # Prefer alias resolution; fall back to treating field_ref as leaf name.
    leaf = resolve_alias(pack, field_ref) or field_ref
    return find_field_value(data, leaf)


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part for part in re.split(r"[\s,]+", text) if part]


def _as_number(value: Any) -> float | None:
    text = _as_str(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _threshold(pack: dict[str, Any], name: str, default: float | int | None = None) -> float | int | None:
    thresholds = pack.get("thresholds") or {}
    if name in thresholds:
        return thresholds[name]
    return default


def _parse_dt(value: Any) -> datetime | None:
    text = _as_str(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return _as_str(value) == ""


def _any_section_filled(data: dict[str, Any], prefix: str) -> bool:
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if prefix and not (key.startswith(prefix) or f"/{prefix}" in key or key.startswith(prefix.rstrip("/"))):
            # Also match keys containing the prefix segment
            if prefix.rstrip("/") not in key:
                continue
        if not _is_blank(value):
            return True
    return False

_REF_KEYS = (
    "field",
    "field_b",
    "parent_field",
    "trigger_field",
    "text_field",
    "start_field",
    "end_field",
    "child_field",
)
_REF_LIST_KEYS = ("fields", "child_fields")

def find_data_key(data: dict[str, Any], field_name: str | None) -> str | None:
    if not field_name:
        return None
    if field_name in data:
        return field_name
    suffix = f"/{field_name}"
    for key in data:
        if key.endswith(suffix):
            return key
    return None
