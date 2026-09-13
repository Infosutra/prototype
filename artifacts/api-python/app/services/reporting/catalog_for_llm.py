"""Build a compact JSON catalog for the report planner LLM."""

from __future__ import annotations

from typing import Any

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.db.models import SubmissionAnswer
from app.domain.reporting.catalog import (
    ANSWER_FACTS,
    ANSWER_FIELDS,
    FLAG_FIELDS,
    FLAG_ROW_COLUMNS,
    SUBMISSION_FACTS,
    SUBMISSION_FIELDS,
)
from app.domain.time_window import WINDOW_PRESETS

_COMPONENT_TYPES = [
    "metric",
    "kpi_group",
    "table",
    "chart",
    "progress",
    "narrative",
    "text",
]


def catalog_for_llm(db: Session, study_id: str) -> dict[str, Any]:
    """Entity/field allowlists plus this study's distinct answer fieldKeys."""
    answer_fields = _study_answer_fields(db, study_id)
    return {
        "specVersion": "1.0",
        "componentTypes": list(_COMPONENT_TYPES),
        "windowPresets": sorted(WINDOW_PRESETS),
        "entities": {
            "submission": {
                "fields": sorted(SUBMISSION_FIELDS),
                "dimensions": sorted(SUBMISSION_FIELDS - SUBMISSION_FACTS),
                "facts": sorted(SUBMISSION_FACTS),
            },
            "flag": {
                "fields": sorted(FLAG_FIELDS),
                "dimensions": sorted(FLAG_FIELDS),
                "facts": [],
                "defaultRowColumns": list(FLAG_ROW_COLUMNS),
            },
            "answer": {
                "fields": sorted(ANSWER_FIELDS),
                "dimensions": sorted(ANSWER_FIELDS - ANSWER_FACTS),
                "facts": sorted(ANSWER_FACTS),
                "studyFieldKeys": answer_fields,
            },
        },
        "measureFns": [
            "count",
            "countDistinct",
            "countWhere",
            "sum",
            "avg",
            "min",
            "max",
        ],
        "filterOps": ["eq", "neq", "in", "isTrue", "isFalse", "gt", "gte", "lt", "lte"],
        "notes": [
            "Bind components to Query IR only — never to named report recipes.",
            "If a request cannot be expressed with these entities/fields, list it in unmapped.",
        ],
    }


def _study_answer_fields(db: Session, study_id: str) -> list[dict[str, str]]:
    rows = db.execute(
        select(
            distinct(SubmissionAnswer.field_key),
            SubmissionAnswer.field_label,
        )
        .where(SubmissionAnswer.study_id == study_id)
        .order_by(SubmissionAnswer.field_key)
    ).all()
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for key, label in rows:
        if not key or key in seen:
            continue
        seen.add(key)
        item: dict[str, str] = {"fieldKey": key}
        if label:
            item["label"] = str(label)
        out.append(item)
    return out
