"""Reporting ingest projections and (later) query/execute services.

Phase 1: dual-write answer/quality facts from Kobo sync and DQA evaluation.
``start`` / ``end`` feed ``duration_minutes`` only — never answer rows. Kobo
meta keys (``_id``, ``_uuid``, …) are skipped. Labels reuse ``form_labels`` /
``list_form_fields``.
"""

from app.services.reporting.answers import replace_answers_for_submission
from app.services.reporting.projections import (
    project_submission_facts,
    resync_study_id_for_project,
)
from app.services.reporting.quality import upsert_quality_for_submission

__all__ = [
    "project_submission_facts",
    "replace_answers_for_submission",
    "resync_study_id_for_project",
    "upsert_quality_for_submission",
]
