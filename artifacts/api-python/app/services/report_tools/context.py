"""Per-execution data context shared by all report tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AppSettings, Study
from app.domain.report_spec.context import ReportExecutionContext
from app.domain.reporting.date_windows import resolve_query_date_window
from app.domain.reporting.entity_rows import (
    build_flag_entity_rows,
    build_submission_entity_rows,
)

RangeKey = tuple[str, str]
EntityKind = str  # "submission" | "flag"
EntityRowsKey = tuple[RangeKey, EntityKind]


def range_key(date_from: str | None, date_to: str | None) -> RangeKey:
    """Stable memo key for a resolved inclusive date window (empty = unbounded)."""
    return (date_from or "", date_to or "")


class ReportDataContext:
    """Holds the session plus execution context and memoizes study data by range.

    Certified tools must call :meth:`stats` (no args) so they always read the
    **default** range — ``context.date_from`` / ``context.date_to`` (often the
    full bag). They must never be silently repointed at a windowed query.

    Windowed callers use :meth:`window` to resolve a dateWindow token, then
    :meth:`entity_rows` / :meth:`report_inputs` / :meth:`stats_for` with that
    explicit range. Identical ``range_key`` values share one memoized ORM load;
    ``entity_rows`` additionally memoizes flattened bags per ``(range, kind)``.
    Spec validation (Stage 2) caps distinct resolved ranges at 2 per report —
    this class does not truncate or merge at execution time.
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
        self._entity_rows_by_key: dict[EntityRowsKey, list[dict[str, Any]]] = {}
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

    def window(self, token: str | None) -> tuple[str | None, str | None]:
        """Resolve a dateWindow token against this execution context."""
        return resolve_query_date_window(
            token,
            execution_date=self.context.execution_date,
            study_start_date=self.study.start_date,
            context_date_from=self.context.date_from,
            context_date_to=self.context.date_to,
        )

    def entity_rows(
        self,
        date_from: str | None,
        date_to: str | None,
        kind: EntityKind,
    ) -> list[dict[str, Any]]:
        """Memoized flattened submission/flag rows for a resolved inclusive range.

        Shares the ORM load with :meth:`report_inputs` for the same range key.
        Flattened bags are memoized separately per ``(range_key, kind)``.
        """
        kind_norm = str(kind).strip()
        if kind_norm not in ("submission", "flag"):
            raise ValueError(f"Unknown entity kind '{kind}'")

        memo_key: EntityRowsKey = (range_key(date_from, date_to), kind_norm)
        cached = self._entity_rows_by_key.get(memo_key)
        if cached is not None:
            return cached

        loaded = self.report_inputs(date_from, date_to)
        projects = loaded["projects"]
        all_subs = loaded["all_subs"]
        all_flags = loaded["all_flags"]

        if kind_norm == "submission":
            rows = build_submission_entity_rows(projects, all_subs)
        else:
            rows = build_flag_entity_rows(projects, all_subs, all_flags)

        self._entity_rows_by_key[memo_key] = rows
        return rows
