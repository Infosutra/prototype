"""Per-execution data context shared by all report tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AppSettings, Study
from app.domain.report_spec.context import ReportExecutionContext


class ReportDataContext:
    """Holds the session plus execution context and memoizes the study statistics.

    Every tool projects a slice of one authoritative computation, so a report with
    ten components still runs the underlying aggregation once.
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
        self._stats = stats

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
        """Authoritative DQA statistics for the execution date, computed once."""
        if self._stats is None:
            from app.services.report_stats import build_daily_dqa_stats

            if self.context.report_kind == "final":
                from app.services.dqa_final_report import build_final_dqa_stats

                self._stats = build_final_dqa_stats(
                    self.db, self.study, run_ai=False
                )
            else:
                self._stats = build_daily_dqa_stats(
                    self.db,
                    self.study,
                    report_date=self.context.execution_date,
                    settings=self.settings,
                    date_from=self.context.date_from,
                    date_to=self.context.date_to,
                )
        return self._stats
