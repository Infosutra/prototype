"""Build a compact JSON catalog for the report planner LLM."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, StudyTool, Submission, SubmissionAnswer
from app.domain.reporting.catalog import (
    ANSWER_FACTS,
    ANSWER_FIELDS,
    FLAG_FIELDS,
    FLAG_ROW_COLUMNS,
    SUBMISSION_FACTS,
    SUBMISSION_FIELDS,
)
from app.domain.reporting.query import Query
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
    """Entity/field allowlists plus this study's distinct answer fieldKeys.

    Keys match Query IR (``groupByFields``, not ``dimensions``) so the planner
    copies legal query shape instead of analytics vocabulary.
    """
    answer_fields = _study_answer_fields(db, study_id)
    return {
        "specVersion": "1.0",
        "componentTypes": list(_COMPONENT_TYPES),
        "query": {
            "required": ["entity", "window"],
            "properties": ["entity", "window", "groupBy", "measures", "filters", "sort", "limit"],
            "entity": ["submission", "flag", "answer"],
            "window": sorted(WINDOW_PRESETS),
            "schema": Query.model_json_schema(),
        },
        "entities": {
            "submission": {
                "fields": sorted(SUBMISSION_FIELDS),
                "groupByFields": sorted(SUBMISSION_FIELDS - SUBMISSION_FACTS),
                "measureFields": sorted(SUBMISSION_FACTS),
            },
            "flag": {
                "fields": sorted(FLAG_FIELDS),
                "groupByFields": sorted(FLAG_FIELDS),
                "measureFields": [],
                "defaultRowColumns": list(FLAG_ROW_COLUMNS),
            },
            "answer": {
                "fields": sorted(ANSWER_FIELDS),
                "groupByFields": sorted(ANSWER_FIELDS - ANSWER_FACTS),
                "measureFields": sorted(ANSWER_FACTS),
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
            "Every query needs entity and window. Group with groupBy (not dimensions).",
            "kpi_group glance cards that mix today vs cumulative or submissions vs flags: "
            "one query per display item (no shared component query).",
            "If a request cannot be expressed with these entities/fields, list it in unmapped.",
            "studyFieldKeys list each fieldKey with the tool it came from. The same "
            "fieldKey can appear on more than one tool — pin the form with a toolCode "
            "filter instead of collapsing keys.",
        ],
    }


def _study_answer_fields(db: Session, study_id: str) -> list[dict[str, str]]:
    rows = db.execute(
        select(
            SubmissionAnswer.field_key,
            SubmissionAnswer.field_label,
            StudyTool.code,
            StudyTool.label,
        )
        .select_from(SubmissionAnswer)
        .join(Submission, Submission.id == SubmissionAnswer.submission_id)
        .join(Project, Project.id == Submission.project_id)
        .outerjoin(StudyTool, StudyTool.id == Project.study_tool_id)
        .where(SubmissionAnswer.study_id == study_id)
        .distinct()
        .order_by(SubmissionAnswer.field_key, StudyTool.code)
    ).all()
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for key, label, tool_code, tool_label in rows:
        if not key:
            continue
        code = str(tool_code or "")
        marker = (str(key), code)
        if marker in seen:
            continue
        seen.add(marker)
        item: dict[str, str] = {"fieldKey": str(key)}
        if label:
            item["label"] = str(label)
        if code:
            item["toolCode"] = code
        if tool_label:
            item["toolLabel"] = str(tool_label)
        out.append(item)
    return out
