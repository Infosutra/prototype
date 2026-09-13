"""Reporting config knobs (query limits, window caps, spec size).

Defaults live here; tests may pass ``overrides``. No Alembic migration in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class ReportingConfig:
    query_limit_default: int = 50
    query_limit_max: int = 500
    query_group_by_max: int = 2
    time_range_max_days: int = 366
    spec_sections_max: int = 12
    spec_components_per_section_max: int = 8
    job_plan_result_ttl_hours: int = 24
    job_poll_interval_ms: int = 2000
    job_poll_backoff_cap_ms: int = 10000


_DEFAULT = ReportingConfig()


def get_reporting_config(
    db: Any = None,
    overrides: Mapping[str, Any] | None = None,
) -> ReportingConfig:
    """Return reporting knobs.

    ``db`` is accepted for future AppSettings reads; Phase 2 uses module defaults
    plus optional ``overrides`` (tests / callers).
    """
    del db  # reserved; no settings columns required in Phase 2
    cfg = _DEFAULT
    if not overrides:
        return cfg
    allowed = {f.name for f in fields(ReportingConfig)}
    kwargs = {k: v for k, v in overrides.items() if k in allowed}
    return replace(cfg, **kwargs) if kwargs else cfg
