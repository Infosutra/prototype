"""Project scalar submission answers for Query IR.

``start`` / ``end`` update ``submissions.duration_minutes`` only — they are not
stored as answer rows. Skip Kobo meta keys (``_id``, ``_uuid``, ``_notes``,
``_attachments``, and any key starting with ``_``). Prefer field keys/labels
from ``list_form_fields`` / ``pick_translated_label`` when a form definition
is available.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import Project, Study, Submission, SubmissionAnswer
from app.domain.dqa.form_fields import list_form_fields, prefer_label_text
from app.domain.reporting.helpers import duration_minutes, local_calendar_day, parse_meta_dt
from app.services.form_labels import pick_translated_label

ANSWER_ID_NAMESPACE = uuid.UUID("b8e2d4a1-6c3f-4a9e-8d1b-2e5f7a9c0b4d")

# Never project these as answers (duration sources + explicit meta).
_SKIP_ANSWER_KEYS = frozenset({"start", "end"})


def _answer_id(submission_id: str, field_key: str) -> str:
    return str(uuid.uuid5(ANSWER_ID_NAMESPACE, f"{submission_id}:{field_key}"))


def _is_meta_key(key: str) -> bool:
    return key.startswith("_") or key in _SKIP_ANSWER_KEYS


def _is_scalar(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (dict, list, tuple, set)):
        return False
    return True


def _field_label(
    field_key: str,
    *,
    form_definition: dict[str, Any] | None,
    form_labels: dict[str, str],
) -> str | None:
    if field_key in form_labels:
        return form_labels[field_key]
    if not isinstance(form_definition, dict):
        return field_key
    survey = form_definition.get("survey") or []
    for item in survey:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "") != field_key:
            continue
        picked = pick_translated_label(item.get("label"), form_definition, None)
        if picked:
            return picked
        text = prefer_label_text(item.get("label"))
        return text or field_key
    return field_key


def _typed_columns(value: Any) -> tuple[str, str | None, float | None, bool | None, datetime | None] | None:
    """Return (value_type, value_text, value_number, value_bool, value_datetime) or None to skip."""
    if isinstance(value, bool):
        return ("boolean", None, None, value, None)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ("number", None, float(value), None, None)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=None) if value.tzinfo else value
        return ("datetime", None, None, None, dt)
    if isinstance(value, date) and not isinstance(value, datetime):
        return ("datetime", None, None, None, datetime(value.year, value.month, value.day))

    text = str(value).strip()
    if not text:
        return None

    dt = parse_meta_dt(value)
    # Treat ISO-like strings as datetime when parseable and not a plain number.
    if dt is not None and any(ch in text for ch in ("-", "T", ":", "Z", "+")) and not _is_plain_number(text):
        return ("datetime", None, None, None, dt)

    if _is_plain_number(text):
        try:
            return ("number", None, float(text), None, None)
        except ValueError:
            pass

    lowered = text.lower()
    if lowered in {"true", "false"}:
        return ("boolean", None, None, lowered == "true", None)

    return ("string", text, None, None, None)


def _is_plain_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    # Reject bare dates like 2026 that happen to parse — require digit/dot/sign only.
    return bool(text) and all(c.isdigit() or c in ".-+" for c in text) and any(c.isdigit() for c in text)


def _form_field_labels(form_definition: dict[str, Any] | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    for field in list_form_fields(form_definition):
        name = str(field.get("name") or "")
        if not name or _is_meta_key(name):
            continue
        label = str(field.get("label") or "").strip() or name
        # Prefer translated label when survey item has bilingual label arrays.
        if isinstance(form_definition, dict):
            for item in form_definition.get("survey") or []:
                if isinstance(item, dict) and str(item.get("name") or "") == name:
                    picked = pick_translated_label(item.get("label"), form_definition, None)
                    if picked:
                        label = picked
                    break
        labels[name] = label
    return labels


def replace_answers_for_submission(
    db: Session,
    submission: Submission,
    *,
    project: Project | None = None,
    study_timezone: str | None = None,
) -> None:
    """Replace answer rows and denormalize study_id / duration / calendar_day.

    When the project has no ``study_id``, existing answers are deleted and no
    projection is written.
    """
    if project is None:
        project = db.get(Project, submission.project_id)

    study_id = project.study_id if project is not None else None
    if not study_id:
        submission.study_id = None
        submission.duration_minutes = None
        submission.calendar_day = None
        db.execute(
            delete(SubmissionAnswer).where(SubmissionAnswer.submission_id == submission.id)
        )
        return

    submission.study_id = study_id
    submission.duration_minutes = duration_minutes(submission)

    if study_timezone is None:
        study = db.get(Study, study_id)
        study_timezone = study.timezone if study else "Asia/Kolkata"
    day_str = local_calendar_day(submission.submitted_at, study_timezone or "Asia/Kolkata")
    submission.calendar_day = date.fromisoformat(day_str) if day_str else None

    db.execute(delete(SubmissionAnswer).where(SubmissionAnswer.submission_id == submission.id))

    data = submission.data if isinstance(submission.data, dict) else {}
    form_definition = (
        project.form_definition if project is not None and isinstance(project.form_definition, dict) else None
    )
    form_labels = _form_field_labels(form_definition)

    keys: list[str] = []
    seen: set[str] = set()
    # Prefer form field order/labels when available.
    for name in form_labels:
        if name in data and name not in seen:
            keys.append(name)
            seen.add(name)
    for key in data:
        key_s = str(key)
        if key_s in seen or _is_meta_key(key_s):
            continue
        if not _is_scalar(data[key]):
            continue
        keys.append(key_s)
        seen.add(key_s)

    rows: list[SubmissionAnswer] = []
    for field_key in keys:
        raw = data.get(field_key)
        if not _is_scalar(raw):
            continue
        typed = _typed_columns(raw)
        if typed is None:
            continue
        value_type, value_text, value_number, value_bool, value_datetime = typed
        rows.append(
            SubmissionAnswer(
                id=_answer_id(submission.id, field_key),
                submission_id=submission.id,
                project_id=submission.project_id,
                study_id=study_id,
                field_key=field_key,
                field_label=_field_label(
                    field_key, form_definition=form_definition, form_labels=form_labels
                ),
                value_type=value_type,
                value_text=value_text,
                value_number=value_number,
                value_bool=value_bool,
                value_datetime=value_datetime,
            )
        )
    if rows:
        db.add_all(rows)
