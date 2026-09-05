"""Date-range filtering for report stats (independent of today/cumulative)."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings, DqaFlag, Project, Study, StudyTool, Submission
from app.domain.report_spec.context import ReportExecutionContext
from app.services.report_tools import ReportDataContext, call_tool

STUDY_ID = "study-date-range"
EXECUTION_DATE = "2026-03-15"
TZ = "Asia/Kolkata"


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(db: Session) -> Study:
    db.add(AppSettings(id="settings", organization_name="Date Range Org", ai_enabled=False))
    study = Study(
        id=STUDY_ID,
        name="Date Range Study",
        start_date="2026-03-01",
        timezone=TZ,
        created_at=datetime(2026, 3, 1),
        updated_at=datetime(2026, 3, 1),
    )
    db.add(study)
    db.add(
        StudyTool(
            id="tool-t1",
            study_id=STUDY_ID,
            code="T1",
            label="Facility",
            target_count=100,
            sort_order=0,
        )
    )
    db.add(
        Project(
            id="proj-t1",
            uid="uid-dr-t1",
            name="Facility",
            study_id=STUDY_ID,
            study_tool_id="tool-t1",
            last_sync_at=datetime(2026, 3, 15, 3, 0, 0),
            created_at=datetime(2026, 3, 1),
            updated_at=datetime(2026, 3, 1),
        )
    )
    db.flush()

    # Outside the requested window (before date_from).
    db.add(
        Submission(
            id="sub-early",
            project_id="proj-t1",
            kobo_id="early",
            form_id="f1",
            form_name="Facility",
            enumerator="Early",
            submitted_at=datetime(2026, 3, 5, 8, 0, 0),
            status="complete",
            data={},
            created_at=datetime(2026, 3, 5, 8, 0, 0),
        )
    )
    db.add(
        DqaFlag(
            id="flag-early",
            submission_id="sub-early",
            project_id="proj-t1",
            rule_id="EARLY_ONLY",
            severity="amber",
            title="Early rule",
            message="outside window",
            evaluated_at=datetime(2026, 3, 5, 8, 0, 0),
        )
    )

    # Inside date_from..date_to (10–12 Mar).
    for i, day in enumerate((10, 11, 12)):
        sid = f"sub-win-{i}"
        submitted = datetime(2026, 3, day, 8, 0, 0)
        db.add(
            Submission(
                id=sid,
                project_id="proj-t1",
                kobo_id=sid,
                form_id="f1",
                form_name="Facility",
                enumerator="Window",
                submitted_at=submitted,
                status="complete",
                data={},
                created_at=submitted,
            )
        )
        db.add(
            DqaFlag(
                id=f"flag-win-{i}",
                submission_id=sid,
                project_id="proj-t1",
                rule_id="WINDOW_RULE",
                severity="amber",
                title="Window rule",
                message="inside window",
                evaluated_at=submitted,
            )
        )

    # On execution "today" (15 Mar) — outside the 10–12 window.
    db.add(
        Submission(
            id="sub-today",
            project_id="proj-t1",
            kobo_id="today",
            form_id="f1",
            form_name="Facility",
            enumerator="Today",
            submitted_at=datetime(2026, 3, 15, 6, 0, 0),
            status="complete",
            data={},
            created_at=datetime(2026, 3, 15, 6, 0, 0),
        )
    )
    db.add(
        DqaFlag(
            id="flag-today",
            submission_id="sub-today",
            project_id="proj-t1",
            rule_id="TODAY_ONLY",
            severity="red",
            title="Today rule",
            message="execution day",
            evaluated_at=datetime(2026, 3, 15, 6, 0, 0),
        )
    )
    db.commit()
    db.refresh(study)
    return study


def _context(**overrides) -> ReportExecutionContext:
    payload = {
        "report_kind": "daily",
        "study_id": STUDY_ID,
        "execution_date": EXECUTION_DATE,
        "timezone": TZ,
    }
    payload.update(overrides)
    return ReportExecutionContext(**payload)


def test_date_range_scopes_aggregates_without_changing_today_semantics(
    db: Session, frozen_now
) -> None:
    """date_from/date_to pre-filter row bags; today/cumulative still use execution_date."""
    _seed(db)
    settings = db.get(AppSettings, "settings")

    # Full load (no range): early + window + today = 5 submissions.
    full_ctx = ReportDataContext(db, _context(), settings=settings)
    full_totals = call_tool(full_ctx, "study_totals")
    assert full_totals["cumulative"] == 5
    full_rules = call_tool(full_ctx, "top_failing_rules", {"scope": "cumulative"})
    full_rule_ids = {r["ruleId"] for r in full_rules}
    assert "EARLY_ONLY" in full_rule_ids
    assert "WINDOW_RULE" in full_rule_ids
    assert "TODAY_ONLY" in full_rule_ids

    # Window 10–12 Mar: only the three WINDOW submissions/flags.
    ranged_ctx = ReportDataContext(
        db,
        _context(date_from="2026-03-10", date_to="2026-03-12"),
        settings=settings,
    )
    totals = call_tool(ranged_ctx, "study_totals")
    assert totals["cumulative"] == 3
    # execution_date is still 15 Mar, so "today" buckets are empty inside this window.
    assert totals["newToday"] == 0
    assert totals["redToday"] == 0
    assert totals["amberToday"] == 0
    # Cumulative-within-window still sees the amber flags on the three rows.
    assert totals["amberOpen"] == 3
    assert totals["redOpen"] == 0

    coverage = call_tool(ranged_ctx, "tool_coverage")
    assert len(coverage) == 1
    assert coverage[0]["cumulative"] == 3
    assert coverage[0]["newToday"] == 0
    assert coverage[0]["flaggedSubmissions"] == 3

    rules_cum = call_tool(ranged_ctx, "top_failing_rules", {"scope": "cumulative"})
    assert [r["ruleId"] for r in rules_cum] == ["WINDOW_RULE"]
    assert rules_cum[0]["count"] == 3

    rules_today = call_tool(ranged_ctx, "top_failing_rules", {"scope": "today"})
    assert rules_today == []
