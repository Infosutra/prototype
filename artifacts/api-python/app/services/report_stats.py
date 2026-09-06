"""Authoritative study DQA statistics used by every report flow.

Lives outside the report orchestrators so the semantic tool layer can depend on it
without importing the renderers.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AppSettings, Study
from app.domain.reporting.daily_stats import compute_daily_dqa_stats
from app.domain.reporting.helpers import day_bounds, today_in_tz
from app.repositories.reporting import load_study_report_inputs
from app.services.settings import get_or_create_settings
from app.services.studies import study_day_number


def build_daily_dqa_stats(
    db: Session,
    study: Study,
    *,
    report_date: str | None = None,
    settings: AppSettings | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    loaded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate today + cumulative DQA stats for one study. Local DB only.

    Optional ``date_from`` / ``date_to`` pre-filter the submission/flag bags
    before today-vs-cumulative bucketing. Omitting both preserves the full
    cumulative load used by existing callers and golden tests.

    Pass ``loaded`` to reuse a memoized ``load_study_report_inputs`` result
    for the same range (avoids a second DB round-trip).
    """
    settings = settings or get_or_create_settings(db)
    tz_name = study.timezone or "Asia/Kolkata"
    date_key = report_date or today_in_tz(tz_name)
    start_utc, end_utc = day_bounds(date_key, tz_name)
    day_n = study_day_number(study, on=date.fromisoformat(date_key))
    if loaded is None:
        loaded = load_study_report_inputs(
            db,
            study.id,
            date_from=date_from,
            date_to=date_to,
            tz_name=tz_name,
        )
    return compute_daily_dqa_stats(
        study_id=study.id,
        study_name=study.name,
        study_start_date=study.start_date,
        tz_name=tz_name,
        date_key=date_key,
        day_n=day_n,
        organization_name=settings.organization_name,
        projects=loaded["projects"],
        targets=loaded["targets"],
        all_subs=loaded["all_subs"],
        all_flags=loaded["all_flags"],
        pack_cache=loaded["pack_cache"],
        start_utc=start_utc,
        end_utc=end_utc,
    )
