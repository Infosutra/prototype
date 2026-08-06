"""DQA rule evaluation domain."""

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

__all__ = [
    "YES_VALUES",
    "NO_VALUES",
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
    "prefer_label_text",
    "list_form_fields",
]
