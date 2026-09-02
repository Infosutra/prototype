"""Rule lifecycle helpers (enable/disable, status, filtering)."""

from __future__ import annotations

from typing import Any

RULE_STATUSES = frozenset({"draft", "reviewed", "approved", "active"})


def rule_enabled(rule: dict[str, Any]) -> bool:
    if rule.get("enabled") is False:
        return False
    status = str(rule.get("status") or "active").lower()
    return status == "active"


def rule_status(rule: dict[str, Any]) -> str:
    status = str(rule.get("status") or "active").lower()
    return status if status in RULE_STATUSES else "active"


def active_rules(rules: list[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in rules or []:
        if isinstance(item, dict) and rule_enabled(item):
            out.append(item)
    return out


def set_rule_status(rule: dict[str, Any], status: str, *, enabled: bool | None = None) -> dict[str, Any]:
    if status not in RULE_STATUSES:
        raise ValueError(f"Invalid rule status: {status}")
    updated = dict(rule)
    updated["status"] = status
    if enabled is not None:
        updated["enabled"] = enabled
    elif status == "active":
        updated["enabled"] = True
    meta = dict(updated.get("meta") or {})
    audit = dict(meta.get("audit") or {})
    audit["status"] = status
    if status == "approved":
        audit["approved"] = True
    if status == "active":
        audit["approved"] = True
        audit["activated_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).replace(tzinfo=None).isoformat()
    meta["audit"] = audit
    updated["meta"] = meta
    return updated


def filter_rules(
    rules: list[Any] | None,
    *,
    query: str | None = None,
    status: str | None = None,
    group: str | None = None,
    enabled_only: bool = False,
) -> list[dict[str, Any]]:
    items = [r for r in (rules or []) if isinstance(r, dict)]
    if query:
        q = query.lower()
        items = [
            r
            for r in items
            if q in str(r.get("id") or "").lower()
            or q in str(r.get("title") or "").lower()
            or q in str(r.get("message") or "").lower()
            or q in str(r.get("english") or "").lower()
            or q in str(r.get("description") or "").lower()
        ]
    if status:
        items = [r for r in items if rule_status(r) == status.lower()]
    if group:
        items = [r for r in items if str(r.get("group") or "") == group]
    if enabled_only:
        items = [r for r in items if rule_enabled(r)]
    return items
