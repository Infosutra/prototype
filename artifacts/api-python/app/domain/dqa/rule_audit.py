"""Rule audit metadata embedded in rule documents."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any


MAX_ENGLISH_LEN = 4000


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def sanitize_english(text: str | None) -> str:
    """Truncate natural-language input; do not store unbounded user text."""
    cleaned = " ".join(str(text or "").split())
    return cleaned[:MAX_ENGLISH_LEN]


def attach_compile_audit(
    rule: dict[str, Any],
    *,
    english: str,
    compile_session_id: str,
    model: str,
    provider: str,
    prompt_id: str | None,
    pack_version: int | None = None,
) -> dict[str, Any]:
    out = copy.deepcopy(rule)
    meta = dict(out.get("meta") or {})
    meta["audit"] = {
        "source": "compile",
        "english": sanitize_english(english),
        "compile_session_id": compile_session_id,
        "model": model,
        "provider": provider,
        "prompt_id": prompt_id,
        "compiled_at": _now_iso(),
        "human_edited": False,
        "approved": False,
        "pack_version": pack_version,
    }
    out["meta"] = meta
    return out


def attach_manual_save_audit(
    rule: dict[str, Any],
    *,
    pack_version: int,
    previous: dict[str, Any] | None = None,
    compile_session_id: str | None = None,
) -> dict[str, Any]:
    out = copy.deepcopy(rule)
    meta = dict(out.get("meta") or {})
    prev_audit = (previous or {}).get("meta", {}).get("audit") if previous else None
    audit = dict(prev_audit or {})
    audit.update(
        {
            "source": audit.get("source") or "manual",
            "saved_at": _now_iso(),
            "pack_version": pack_version,
            "human_edited": bool(prev_audit) or audit.get("source") == "compile",
            "approved": audit.get("approved", False),
        }
    )
    if compile_session_id:
        audit["compile_session_id"] = compile_session_id
    meta["audit"] = audit
    out["meta"] = meta
    return out


def stamp_rules_for_save(
    rules: list[Any],
    *,
    pack_version: int,
    previous_rules: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    prev = previous_rules or {}
    stamped: list[dict[str, Any]] = []
    for item in rules:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("id") or "")
        stamped.append(
            attach_manual_save_audit(
                item,
                pack_version=pack_version,
                previous=prev.get(rule_id),
            )
        )
    return stamped
