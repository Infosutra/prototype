"""Allowlists and SQL column maps for Query IR entities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Boolean, ColumnElement, Integer
from sqlalchemy.orm import InstrumentedAttribute

from app.db.models import (
    DqaFlag,
    Project,
    StudyTool,
    Submission,
    SubmissionAnswer,
    SubmissionQuality,
)

EntityName = Literal["submission", "flag", "answer"]

# Catalog IR names (camelCase) — only these may appear in queries.
_IDENT_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")

SUBMISSION_DIMENSIONS: frozenset[str] = frozenset(
    {"enumerator", "toolCode", "projectId", "day"}
)
SUBMISSION_FACTS: frozenset[str] = frozenset(
    {
        "isClean",
        "maxSeverity",
        "flagCount",
        "redCount",
        "amberCount",
        "durationMinutes",
        "targetCount",
    }
)
SUBMISSION_FIELDS: frozenset[str] = SUBMISSION_DIMENSIONS | SUBMISSION_FACTS

FLAG_DIMENSIONS: frozenset[str] = frozenset(
    {
        "enumerator",
        "toolCode",
        "projectId",
        "severity",
        "ruleId",
        "ruleTitle",
        "day",
        "submissionId",
    }
)
FLAG_FIELDS: frozenset[str] = FLAG_DIMENSIONS

ANSWER_DIMENSIONS: frozenset[str] = frozenset(
    {"fieldKey", "enumerator", "toolCode", "day", "submissionId"}
)
ANSWER_FACTS: frozenset[str] = frozenset({"valueNumber"})
ANSWER_FIELDS: frozenset[str] = ANSWER_DIMENSIONS | ANSWER_FACTS

# Default columns returned for flag row lists (no measures).
FLAG_ROW_COLUMNS: tuple[str, ...] = ("enumerator", "ruleTitle", "toolCode", "severity")

# Joins required when a field is referenced.
JoinNeed = Literal["quality", "project", "study_tool", "submission"]


@dataclass(frozen=True)
class FieldRef:
    """Allowlisted IR field → SQLAlchemy column expression metadata."""

    name: str
    column: InstrumentedAttribute | ColumnElement
    joins: frozenset[JoinNeed]
    kind: Literal["dimension", "fact"]


def _submission_fields() -> dict[str, FieldRef]:
    return {
        "enumerator": FieldRef(
            "enumerator", Submission.enumerator, frozenset(), "dimension"
        ),
        "toolCode": FieldRef(
            "toolCode", StudyTool.code, frozenset({"project", "study_tool"}), "dimension"
        ),
        "projectId": FieldRef(
            "projectId", Submission.project_id, frozenset(), "dimension"
        ),
        "day": FieldRef("day", Submission.calendar_day, frozenset(), "dimension"),
        "isClean": FieldRef(
            "isClean", SubmissionQuality.is_clean, frozenset({"quality"}), "fact"
        ),
        "maxSeverity": FieldRef(
            "maxSeverity",
            SubmissionQuality.max_severity,
            frozenset({"quality"}),
            "fact",
        ),
        "flagCount": FieldRef(
            "flagCount", SubmissionQuality.flag_count, frozenset({"quality"}), "fact"
        ),
        "redCount": FieldRef(
            "redCount", SubmissionQuality.red_count, frozenset({"quality"}), "fact"
        ),
        "amberCount": FieldRef(
            "amberCount", SubmissionQuality.amber_count, frozenset({"quality"}), "fact"
        ),
        "durationMinutes": FieldRef(
            "durationMinutes", Submission.duration_minutes, frozenset(), "fact"
        ),
        "targetCount": FieldRef(
            "targetCount",
            StudyTool.target_count,
            frozenset({"project", "study_tool"}),
            "fact",
        ),
    }


def _flag_fields() -> dict[str, FieldRef]:
    return {
        "enumerator": FieldRef(
            "enumerator",
            Submission.enumerator,
            frozenset({"submission"}),
            "dimension",
        ),
        "toolCode": FieldRef(
            "toolCode",
            StudyTool.code,
            frozenset({"submission", "project", "study_tool"}),
            "dimension",
        ),
        "projectId": FieldRef(
            "projectId", DqaFlag.project_id, frozenset(), "dimension"
        ),
        "severity": FieldRef("severity", DqaFlag.severity, frozenset(), "dimension"),
        "ruleId": FieldRef("ruleId", DqaFlag.rule_id, frozenset(), "dimension"),
        "ruleTitle": FieldRef("ruleTitle", DqaFlag.title, frozenset(), "dimension"),
        "day": FieldRef(
            "day", Submission.calendar_day, frozenset({"submission"}), "dimension"
        ),
        "submissionId": FieldRef(
            "submissionId", DqaFlag.submission_id, frozenset(), "dimension"
        ),
    }


def _answer_fields() -> dict[str, FieldRef]:
    return {
        "fieldKey": FieldRef(
            "fieldKey", SubmissionAnswer.field_key, frozenset(), "dimension"
        ),
        "enumerator": FieldRef(
            "enumerator",
            Submission.enumerator,
            frozenset({"submission"}),
            "dimension",
        ),
        "toolCode": FieldRef(
            "toolCode",
            StudyTool.code,
            frozenset({"submission", "project", "study_tool"}),
            "dimension",
        ),
        "day": FieldRef(
            "day", Submission.calendar_day, frozenset({"submission"}), "dimension"
        ),
        "submissionId": FieldRef(
            "submissionId", SubmissionAnswer.submission_id, frozenset(), "dimension"
        ),
        "valueNumber": FieldRef(
            "valueNumber", SubmissionAnswer.value_number, frozenset(), "fact"
        ),
    }


ENTITY_FIELDS: dict[str, dict[str, FieldRef]] = {
    "submission": _submission_fields(),
    "flag": _flag_fields(),
    "answer": _answer_fields(),
}

ENTITY_DIMENSIONS: dict[str, frozenset[str]] = {
    "submission": SUBMISSION_DIMENSIONS,
    "flag": FLAG_DIMENSIONS,
    "answer": ANSWER_DIMENSIONS,
}


def validate_identifier(name: str) -> str:
    """Reject SQL-injection-shaped identifiers; allow catalog camelCase keys."""
    if not isinstance(name, str) or not name:
        raise ValueError("Empty identifier")
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid identifier '{name}'")
    return name


def resolve_field(entity: str, name: str) -> FieldRef:
    validate_identifier(name)
    fields = ENTITY_FIELDS.get(entity)
    if fields is None:
        raise ValueError(f"Unknown entity '{entity}'")
    ref = fields.get(name)
    if ref is None:
        raise ValueError(f"Unknown field '{name}' for entity '{entity}'")
    return ref


def is_bool_column(ref: FieldRef) -> bool:
    col = ref.column
    try:
        return isinstance(col.type, Boolean)
    except Exception:
        return False


def is_numeric_column(ref: FieldRef) -> bool:
    col = ref.column
    try:
        t = col.type
        return isinstance(t, (Integer,)) or t.python_type in {int, float}
    except Exception:
        return ref.name in {
            "flagCount",
            "redCount",
            "amberCount",
            "durationMinutes",
            "targetCount",
            "valueNumber",
        }


# Re-export table handles used by the engine for joins.
__all__ = [
    "ANSWER_DIMENSIONS",
    "ANSWER_FACTS",
    "ANSWER_FIELDS",
    "ENTITY_DIMENSIONS",
    "ENTITY_FIELDS",
    "FLAG_DIMENSIONS",
    "FLAG_FIELDS",
    "FLAG_ROW_COLUMNS",
    "FieldRef",
    "JoinNeed",
    "Project",
    "SUBMISSION_DIMENSIONS",
    "SUBMISSION_FACTS",
    "SUBMISSION_FIELDS",
    "StudyTool",
    "DqaFlag",
    "Submission",
    "SubmissionAnswer",
    "SubmissionQuality",
    "is_bool_column",
    "is_numeric_column",
    "resolve_field",
    "validate_identifier",
]
