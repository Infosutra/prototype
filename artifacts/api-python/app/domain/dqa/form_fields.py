"""Kobo form-definition field listing helpers."""

from __future__ import annotations

from typing import Any

def prefer_label_text(label: Any) -> str:
    """Pick a readable label from Kobo bilingual arrays (prefer English when last)."""
    if label is None:
        return ""
    if isinstance(label, list):
        parts = [str(x).strip() for x in label if str(x).strip()]
        if not parts:
            return ""
        # Kobo bilingual labels are usually [Hindi, English]
        return parts[-1] if len(parts) > 1 else parts[0]
    if isinstance(label, dict):
        for key in ("en", "English", "english"):
            if label.get(key):
                return str(label[key]).strip()
        parts = [str(v).strip() for v in label.values() if str(v).strip()]
        return parts[-1] if parts else ""
    return str(label).strip()


def list_form_fields(form_definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(form_definition, dict):
        return []
    survey = form_definition.get("survey") or []
    choices = form_definition.get("choices") or []
    by_list: dict[str, list[dict[str, Any]]] = {}
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        list_name = str(choice.get("list_name") or "")
        by_list.setdefault(list_name, []).append(
            {
                "name": str(choice.get("name") or ""),
                "label": prefer_label_text(choice.get("label")),
            }
        )

    skip = {
        "start",
        "end",
        "begin_group",
        "end_group",
        "begin_repeat",
        "end_repeat",
        "note",
        "calculate",
        "acknowledge",
    }
    fields: list[dict[str, Any]] = []
    for item in survey:
        if not isinstance(item, dict):
            continue
        qtype = str(item.get("type") or "")
        name = str(item.get("name") or "")
        if not name or qtype in skip or qtype.startswith("begin_") or qtype.startswith("end_"):
            continue
        list_name = item.get("select_from_list_name")
        fields.append(
            {
                "name": name,
                "type": qtype,
                "label": prefer_label_text(item.get("label")) or name,
                "list_name": list_name,
                "choices": by_list.get(str(list_name), []) if list_name else [],
            }
        )
    # Always expose Kobo meta start/end if present in submissions convention
    fields.extend(
        [
            {
                "name": "start",
                "type": "datetime",
                "label": "Start time",
                "list_name": None,
                "choices": [],
            },
            {
                "name": "end",
                "type": "datetime",
                "label": "End time",
                "list_name": None,
                "choices": [],
            },
        ]
    )
    return fields
