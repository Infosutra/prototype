"""Per-execution data context shared by all report tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AppSettings, Study
from app.domain.report_spec.context import ReportExecutionContext

RangeKey = tuple[str, str]


def range_key(date_from: str | None, date_to: str | None) -> RangeKey:
    """Stable memo key for a resolved inclusive date window (empty = unbounded)."""
    return (date_from or "", date_to or "")


class ReportDataContext:
    """Holds the session plus execution context and memoizes study statistics by range.

    Certified tools must call :meth:`stats` (no args) so they always read the
    **default** range — ``context.date_from`` / ``context.date_to`` (often the
    full bag). They must never be silently repointed at a ``query_aggregate``
    window.

    ``query_aggregate`` (and any future windowed caller) uses
    :meth:`stats_for` / :meth:`report_inputs` with an explicit resolved range.
    Identical ``range_key`` values share one memoized load; distinct keys load
    separately. Spec validation (Stage 2) caps distinct resolved ranges at 2
    per report — this class does not truncate or merge at execution time.
    """

    def __init__(
        self,
        db: Session,
        context: ReportExecutionContext,
        *,
        settings: AppSettings | None = None,
        stats: dict[str, Any] | None = None,
    ) -> None:
        # TODO(rbac): when authentication lands, resolve the caller here and assert
        # they may read this study. Tools must never widen access beyond this object.
        self.db = db
        self.context = context
        self._settings = settings
        self._study: Study | None = None
        self._stats_by_range: dict[RangeKey, dict[str, Any]] = {}
        self._inputs_by_range: dict[RangeKey, dict[str, Any]] = {}
        if stats is not None:
            self._stats_by_range[self.default_range_key()] = stats

    def default_range_key(self) -> RangeKey:
        """Range key certified tools always use (execution context window)."""
        return range_key(self.context.date_from, self.context.date_to)

    @property
    def settings(self) -> AppSettings:
        if self._settings is None:
            from app.services.settings import get_or_create_settings

            self._settings = get_or_create_settings(self.db)
        return self._settings

    @property
    def study(self) -> Study:
        if self._study is None:
            study = self.db.get(Study, self.context.study_id)
            if study is None:
                raise ValueError(f"Study not found: {self.context.study_id}")
            self._study = study
        return self._study

    def stats(self) -> dict[str, Any]:
        """Authoritative DQA statistics for the **default** execution range.

        Certified catalog tools must use this method only.
        """
        return self.stats_for(self.context.date_from, self.context.date_to)

    def stats_for(
        self, date_from: str | None, date_to: str | None
    ) -> dict[str, Any]:
        """Memoized stats for an explicit inclusive range (ISO dates or None)."""
        key = range_key(date_from, date_to)
        cached = self._stats_by_range.get(key)
        if cached is not None:
            return cached

        from app.services.report_stats import build_daily_dqa_stats

        if self.context.report_kind == "final" and key == self.default_range_key():
            from app.services.dqa_final_report import build_final_dqa_stats

            built = build_final_dqa_stats(self.db, self.study, run_ai=False)
        else:
            loaded = self.report_inputs(date_from, date_to)
            built = build_daily_dqa_stats(
                self.db,
                self.study,
                report_date=self.context.execution_date,
                settings=self.settings,
                date_from=date_from,
                date_to=date_to,
                loaded=loaded,
            )
        self._stats_by_range[key] = built
        return built

    def report_inputs(
        self, date_from: str | None = None, date_to: str | None = None
    ) -> dict[str, Any]:
        """Memoized ``load_study_report_inputs`` for a resolved range."""
        key = range_key(date_from, date_to)
        cached = self._inputs_by_range.get(key)
        if cached is not None:
            return cached

        from app.repositories.reporting import load_study_report_inputs

        tz_name = self.study.timezone or self.context.timezone or "Asia/Kolkata"
        loaded = load_study_report_inputs(
            self.db,
            self.study.id,
            date_from=date_from,
            date_to=date_to,
            tz_name=tz_name,
        )
        self._inputs_by_range[key] = loaded
        return loaded
