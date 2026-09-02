"""DQA engine public facade — re-exports domain + pack + evaluation APIs.

Callers may keep importing from ``app.services.dqa_engine``; implementation
lives in ``app.domain.dqa``, ``dqa_rule_packs``, and ``dqa_evaluation``.
"""

from __future__ import annotations

from app.domain.dqa.eval import eval_check
from app.domain.dqa.form_fields import list_form_fields, prefer_label_text
from app.domain.dqa.highlights import (
    collect_field_refs,
    highlight_fields_for_flag,
    resolve_highlight_fields,
)
from app.domain.dqa.related import enrich_flag_related_submissions, find_related_submissions
from app.domain.dqa.values import (
    NO_VALUES,
    YES_VALUES,
    find_data_key,
    find_field_value,
    get_value,
    resolve_alias,
)
from app.services.dqa_evaluation import evaluate_project, evaluate_project_cascade, evaluate_rule, evaluate_submission
from app.services.dqa_rule_packs import (
    SEED_DIR,
    get_pack_for_project,
    get_pack_version,
    list_pack_versions,
    load_seed_packs,
    save_pack,
    seed_rule_packs,
)

__all__ = [
    "YES_VALUES",
    "NO_VALUES",
    "SEED_DIR",
    "find_field_value",
    "resolve_alias",
    "get_value",
    "find_data_key",
    "collect_field_refs",
    "find_related_submissions",
    "enrich_flag_related_submissions",
    "resolve_highlight_fields",
    "highlight_fields_for_flag",
    "eval_check",
    "evaluate_rule",
    "evaluate_submission",
    "evaluate_project",
    "evaluate_project_cascade",
    "load_seed_packs",
    "get_pack_version",
    "list_pack_versions",
    "seed_rule_packs",
    "save_pack",
    "prefer_label_text",
    "list_form_fields",
]
