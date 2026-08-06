"""Build a spreadsheet-style grid of submissions x form questions with DQA severity per cell."""

from __future__ import annotations

import json
from math import ceil
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models import DqaFlag, Project, Submission
from app.services import dqa_engine
from app.services.form_labels import (
    META_TYPES,
    build_form_responses,
    pick_translated_label,
    resolve_label_language,
)

MAX_LIMIT = 200
DEFAULT_LIMIT = 50

_SEVERITY_RANK = {"amber": 1, "red": 2}

# Flag targets that are not form questions but still deserve a column: key -> (code, label, type).
_META_COLUMNS: dict[str, tuple[str, str, str]] = {
    "__location__": ("GPS", "GPS / location", "geopoint"),
    "_attachments": ("Photos", "Attachments", "attachments"),
    "start": ("start", "Interview start", "datetime"),
    "end": ("end", "Interview end", "datetime"),
}

# GPS rules highlight both markers; keep a single column for them.
_CODE_ALIASES = {"_geolocation": "__location__"}


def _leaf(key: str) -> str:
    return key.split("/")[-1] or key


def _code_of(key: str) -> str:
    leaf = _leaf(key)
    return _CODE_ALIASES.get(leaf, leaf)


def _humanize(key: str) -> str:
    leaf = _leaf(key).lstrip("_")
    if "_" not in leaf:
        return leaf
    words = leaf.replace("_", " ").split()
    if not words:
        return leaf
    return " ".join(words).capitalize()


def _worse(current: str | None, candidate: str) -> str:
    if current is None:
        return candidate
    return candidate if _SEVERITY_RANK.get(candidate, 0) > _SEVERITY_RANK.get(current, 0) else current


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(part for part in (_display(item) for item in value) if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _column(
    key: str,
    label: str,
    qtype: str,
    *,
    code: str | None = None,
    extra: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "code": code or key,
        "label": label or key,
        "type": qtype,
        "filled": 0,
        "flagged": 0,
        "extra": extra,
    }


def _survey_columns(
    form_definition: dict[str, Any] | None,
    language: str | None,
) -> list[dict[str, Any]]:
    survey = (form_definition or {}).get("survey")
    if not isinstance(survey, list):
        return []
    columns: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in survey:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        qtype = item.get("type")
        if not isinstance(name, str) or not isinstance(qtype, str):
            continue
        if qtype in META_TYPES or name in seen or qtype.startswith(("begin_", "end_")):
            continue
        label = pick_translated_label(item.get("label"), form_definition, language) or name
        columns.append(_column(name, label, qtype))
        seen.add(name)
    return columns


def _raw_values(data: dict[str, Any]) -> dict[str, str]:
    """Values keyed by leaf field name, skipping Kobo internals."""
    values: dict[str, str] = {}
    for key, value in data.items():
        code = _leaf(str(key))
        if code.startswith("_") or code in {"meta", "instanceID"}:
            continue
        text = _display(value)
        if text:
            values[code] = text
    return values


def _flag_ref(flag: DqaFlag) -> dict[str, Any]:
    return {
        "id": flag.id,
        "rule_id": flag.rule_id,
        "severity": "red" if flag.severity == "red" else "amber",
        "title": flag.title,
        "message": flag.message,
    }


def _row_filter(project_id: str, severity: str | None, enumerator: str | None):
    conditions: list[Any] = [Submission.project_id == project_id]
    flagged_ids = select(DqaFlag.submission_id).where(DqaFlag.project_id == project_id)
    sev = (severity or "").strip().lower()
    if sev in {"red", "amber"}:
        conditions.append(
            Submission.id.in_(flagged_ids.where(DqaFlag.severity == sev))
        )
    elif sev == "flagged":
        conditions.append(Submission.id.in_(flagged_ids))
    elif sev == "clean":
        conditions.append(~Submission.id.in_(flagged_ids))
    if enumerator and enumerator.strip():
        conditions.append(Submission.enumerator.ilike(f"%{enumerator.strip()}%"))
    return and_(*conditions)


def build_submission_grid(
    db: Session,
    project: Project,
    *,
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
    severity: str | None = None,
    enumerator: str | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    page = max(1, int(page or 1))
    form_definition = (
        project.form_definition if isinstance(project.form_definition, dict) else None
    )
    language = resolve_label_language(project.label_language, form_definition)

    where = _row_filter(project.id, severity, enumerator)
    total = db.scalar(select(func.count()).select_from(Submission).where(where)) or 0
    submissions = list(
        db.scalars(
            select(Submission)
            .where(where)
            .order_by(Submission.submitted_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        ).all()
    )

    pack = dqa_engine.get_pack_for_project(db, project.id)
    rules_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(pack, dict):
        for rule in pack.get("rules") or []:
            if isinstance(rule, dict) and rule.get("id"):
                rules_by_id[str(rule["id"])] = rule

    flags_by_submission: dict[str, list[DqaFlag]] = {}
    if submissions:
        ids = [row.id for row in submissions]
        for flag in db.scalars(select(DqaFlag).where(DqaFlag.submission_id.in_(ids))).all():
            flags_by_submission.setdefault(flag.submission_id, []).append(flag)

    columns = _survey_columns(form_definition, language)
    columns_by_key = {column["key"]: column for column in columns}

    # Pass 1: resolve values and flag targets, discovering columns the survey does not cover.
    prepared: list[dict[str, Any]] = []
    for submission in submissions:
        data = submission.data if isinstance(submission.data, dict) else {}
        values = _raw_values(data)
        for response in build_form_responses(data, form_definition, language):
            text = _display(response.get("value"))
            if text:
                values[_leaf(str(response.get("key") or ""))] = text
        if submission.location:
            values.setdefault("__location__", submission.location)
        if submission.attachment_count:
            values.setdefault("_attachments", str(submission.attachment_count))

        flag_targets: list[tuple[DqaFlag, list[str]]] = []
        for flag in flags_by_submission.get(submission.id, []):
            details = flag.details if isinstance(flag.details, dict) else {}
            targets = dqa_engine.highlight_fields_for_flag(
                pack=pack,
                rule=rules_by_id.get(flag.rule_id),
                details=details,
                data=data,
            )
            codes: list[str] = []
            for target in targets:
                code = _code_of(str(target))
                if code and code not in codes:
                    codes.append(code)
            flag_targets.append((flag, codes))

        prepared.append({"submission": submission, "values": values, "flags": flag_targets})

    def ensure_column(key: str, values: dict[str, str]) -> dict[str, Any] | None:
        existing = columns_by_key.get(key)
        if existing:
            return existing
        meta = _META_COLUMNS.get(key)
        if meta is None and key not in values:
            return None
        code, label, qtype = meta if meta else (key, _humanize(key), "")
        column = _column(key, label, qtype, code=code, extra=True)
        columns.append(column)
        columns_by_key[key] = column
        return column

    if not columns:
        for item in prepared:
            for code in item["values"]:
                ensure_column(code, item["values"])

    for item in prepared:
        for _flag, codes in item["flags"]:
            for code in codes:
                ensure_column(code, item["values"])

    # Pass 2: build cells now that the column set is final.
    rows: list[dict[str, Any]] = []
    for item in prepared:
        submission: Submission = item["submission"]
        values: dict[str, str] = item["values"]
        cells: dict[str, dict[str, Any]] = {}
        for key, column in columns_by_key.items():
            text = values.get(key, "")
            if not text:
                continue
            cells[key] = {"value": text, "severity": None, "flags": []}
            column["filled"] += 1

        row_severity: str | None = None
        red = 0
        amber = 0
        row_flags: list[dict[str, Any]] = []
        for flag, codes in item["flags"]:
            ref = _flag_ref(flag)
            if ref["severity"] == "red":
                red += 1
            else:
                amber += 1
            row_severity = _worse(row_severity, ref["severity"])
            placed = False
            for code in codes:
                column = columns_by_key.get(code)
                if column is None:
                    continue
                cell = cells.get(code)
                if cell is None:
                    cell = {"value": values.get(code, ""), "severity": None, "flags": []}
                    cells[code] = cell
                if not cell["flags"]:
                    column["flagged"] += 1
                cell["flags"].append(ref)
                cell["severity"] = _worse(cell["severity"], ref["severity"])
                placed = True
            if not placed:
                row_flags.append(ref)

        rows.append(
            {
                "submission_id": submission.id,
                "display_id": f"Submission-{submission.kobo_id}",
                "kobo_id": submission.kobo_id,
                "enumerator": submission.enumerator or "",
                "submitted_at": submission.submitted_at.isoformat()
                if submission.submitted_at
                else "",
                "status": submission.status or "",
                "location": submission.location,
                "severity": row_severity,
                "red_flags": red,
                "amber_flags": amber,
                "cells": cells,
                "row_flags": row_flags,
            }
        )

    return {
        "project_id": project.id,
        "project_name": project.name,
        "label_language": language,
        "columns": columns,
        "rows": rows,
        "total": int(total),
        "page": page,
        "limit": limit,
        "total_pages": ceil(total / limit) if limit else 0,
    }
