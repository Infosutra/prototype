"""Map unknown Query IR names onto catalog allowlist names. Never invent SQL."""

from __future__ import annotations

import copy
import json
from typing import Any

from app.domain.reporting.catalog import ANSWER_FIELDS, FLAG_FIELDS, SUBMISSION_FIELDS
from app.domain.reporting.spec_walk import iter_queries, query_field_names, rename_query_field
from app.integrations.llm.json_object import parse_json_object
from app.services.reporting.planner import LlmInvoker, PlanError

DEFAULT_BINDER_PROMPT = """You bind informal field names in a ReportSpec to catalog names.

Return JSON only:
{
  "mappings": [{"from": "interviewer", "to": "enumerator"}],
  "unmapped": [{"name": "...", "reason": "..."}]
}

Rules:
- `to` MUST be an exact catalog field name or a studyFieldKeys.fieldKey.
- Never invent SQL, numbers, or new field names.
- If you are not sure, put the name in unmapped instead of guessing.
- Do not map names that are already legal catalog fields.
"""


def catalog_allowlist(catalog: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    names.update(SUBMISSION_FIELDS)
    names.update(FLAG_FIELDS)
    names.update(ANSWER_FIELDS)
    entities = catalog.get("entities") or {}
    if isinstance(entities, dict):
        for entity in entities.values():
            if not isinstance(entity, dict):
                continue
            for key in ("fields", "groupByFields", "measureFields"):
                for item in entity.get(key) or []:
                    names.add(str(item))
            for row in entity.get("studyFieldKeys") or []:
                if isinstance(row, dict) and row.get("fieldKey"):
                    names.add(str(row["fieldKey"]))
                elif isinstance(row, str):
                    names.add(row)
    return {name for name in names if name}


def unknown_field_names(spec: dict[str, Any], allowlist: set[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for _path, query in iter_queries(spec):
        for name in query_field_names(query):
            if name in allowlist or name in seen:
                continue
            seen.add(name)
            out.append(name)
    return out


def apply_mappings(spec: dict[str, Any], mappings: list[dict[str, str]]) -> dict[str, Any]:
    for item in mappings:
        old = str(item.get("from") or "").strip()
        new = str(item.get("to") or "").strip()
        if not old or not new or old == new:
            continue
        for _path, query in iter_queries(spec):
            rename_query_field(query, old, new)
    return spec


def bind_spec(
    spec: dict[str, Any],
    catalog: dict[str, Any],
    *,
    invoker: LlmInvoker,
) -> dict[str, Any]:
    """Run the binder LLM if the spec uses unknown field names.

    Returns ``{spec, mappings, unmapped}``. Mappings are applied only when
    ``to`` is on the catalog allowlist.
    """
    allowlist = catalog_allowlist(catalog)
    spec = copy.deepcopy(spec)
    unknown = unknown_field_names(spec, allowlist)
    if not unknown:
        return {"spec": spec, "mappings": [], "unmapped": []}

    raw = invoker(
        system=DEFAULT_BINDER_PROMPT,
        user=json.dumps(
            {"unknownNames": unknown, "catalog": catalog, "spec": spec},
            default=str,
        ),
        purpose="bind",
    )
    parsed = raw if isinstance(raw, dict) else {}
    mappings: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for item in parsed.get("mappings") or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("from") or item.get("source") or "").strip()
        dest = str(item.get("to") or item.get("target") or "").strip()
        if not source or not dest:
            continue
        if dest not in allowlist:
            rejected.append(
                {"name": source, "reason": f"binder proposed '{dest}', which is not in the catalog"}
            )
            continue
        mappings.append({"from": source, "to": dest})
    extra_unmapped: list[dict[str, str]] = []
    for item in parsed.get("unmapped") or []:
        if isinstance(item, dict):
            extra_unmapped.append(
                {
                    "name": str(item.get("name") or item.get("from") or ""),
                    "reason": str(item.get("reason") or "unmapped"),
                }
            )
    apply_mappings(spec, mappings)
    still_unknown = unknown_field_names(spec, allowlist)
    for name in still_unknown:
        extra_unmapped.append(
            {"name": name, "reason": "no catalog field matched this name"}
        )
    return {
        "spec": spec,
        "mappings": mappings,
        "unmapped": rejected + extra_unmapped,
    }


def parse_binder_reply(text: str) -> dict[str, Any]:
    parsed = parse_json_object(text, log_label="report-binder")
    if parsed.data is None:
        raise PlanError(parsed.error or "Binder returned invalid JSON")
    return parsed.data
