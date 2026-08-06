"""Report stats computation (pure)."""

from app.domain.reporting.daily_stats import compute_daily_dqa_stats
from app.domain.reporting.final_stats import (
    enrich_final_checklist,
    mismatch_detail,
    _exhaustive_executive_summary,
    _pass_rate,
    _section_prose,
    _tr1_summary,
)
from app.domain.reporting.narratives import _fallback_coverage, _fallback_headline

__all__ = [
    "compute_daily_dqa_stats",
    "enrich_final_checklist",
    "mismatch_detail",
    "_exhaustive_executive_summary",
    "_pass_rate",
    "_section_prose",
    "_tr1_summary",
    "_fallback_coverage",
    "_fallback_headline",
]
