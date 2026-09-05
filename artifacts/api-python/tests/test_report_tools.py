"""Semantic report data sources: projections, business definitions and timezones."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings, DqaFlag, Project, Study, StudyTool, Submission
from app.domain.report_spec.context import ReportExecutionContext
from app.services.report_tools import (
    ReportDataContext,
    ReportToolError,
    all_descriptors,
    call_tool,
    descriptors_by_id,
)
from tests.test_report_stats import _load

STUDY_ID = "study-fixture"
REPORT_DATE = "2026-03-15"


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _settings() -> AppSettings:
    return AppSettings(id="settings", organization_name="Infosutra Test Org", ai_enabled=False)


def _study(db: Session) -> Study:
    settings = _settings()
    db.add(settings)
    study = Study(
        id=STUDY_ID,
        name="Fixture Study",
        start_date="2026-03-04",
        timezone="Asia/Kolkata",
        created_at=datetime(2026, 3, 4),
        updated_at=datetime(2026, 3, 4),
    )
    db.add(study)
    db.commit()
    return study


def _context(**overrides) -> ReportExecutionContext:
    payload = {
        "report_kind": "daily",
        "study_id": STUDY_ID,
        "execution_date": REPORT_DATE,
        "timezone": "Asia/Kolkata",
    }
    payload.update(overrides)
    return ReportExecutionContext(**payload)


def _data_context(db: Session) -> ReportDataContext:
    """Context wired to the shared fixture statistics."""
    study = _study(db)
    return ReportDataContext(
        db, _context(), settings=db.get(AppSettings, "settings"), stats=_load("sample_daily_stats.json")
    ), study


# --- Registry ---------------------------------------------------------------


def test_registry_exposes_the_phase_one_sources() -> None:
    ids = {descriptor.id for descriptor in all_descriptors()}
    assert ids == {
        "study_metadata",
        "study_totals",
        "tool_coverage",
        "enumerator_performance_today",
        "enumerator_submission_quality",
        "top_failing_rules",
        "red_priority_items",
        "flag_rate_trend",
        "signoff_checklist",
        "enumerator_performance_study",
        "findings_by_tool",
        "triangulation_summary",
    }


def test_every_source_documents_its_business_definitions() -> None:
    for descriptor in all_descriptors():
        assert descriptor.description.strip(), descriptor.id
        assert descriptor.business_definition.strip(), descriptor.id
        assert descriptor.fields, descriptor.id


def test_unknown_source_is_refused(db: Session) -> None:
    context, _study = _data_context(db)
    with pytest.raises(ReportToolError, match="Unknown data source"):
        call_tool(context, "drop_table_submissions")


def test_declared_fields_match_returned_keys(db: Session) -> None:
    context, _study = _data_context(db)
    for descriptor in all_descriptors():
        payload = call_tool(context, descriptor.id)
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            unexpected = set(row) - descriptor.field_names()
            assert not unexpected, f"{descriptor.id} returned undeclared keys {unexpected}"


# --- Projections ------------------------------------------------------------


def test_study_totals_derives_clean_and_flagged_counts(db: Session) -> None:
    context, _study = _data_context(db)
    totals = call_tool(context, "study_totals")
    # Fixture: 8 today, 2+3 flagged submissions today across T1/T2
    assert totals["newToday"] == 8
    assert totals["flaggedToday"] == 5
    assert totals["cleanToday"] == 3
    assert totals["flaggedPctToday"] == 62.5
    assert totals["cumulative"] == 120
    assert totals["flaggedCumulative"] == 18
    assert totals["cleanCumulative"] == 102
    assert totals["flaggedPctCumulative"] == 15.0


def test_tool_coverage_carries_the_configured_target(db: Session) -> None:
    context, _study = _data_context(db)
    rows = call_tool(context, "tool_coverage")
    by_code = {row["toolCode"]: row for row in rows}
    assert by_code["T1"]["target"] == 100
    assert by_code["T1"]["cumulative"] == 45
    assert by_code["T1"]["coveragePct"] == 45.0
    assert by_code["T2"]["remaining"] == 5
    assert "target" in descriptors_by_id()["tool_coverage"].benchmark_fields


def test_enumerator_performance_includes_group_benchmarks(db: Session) -> None:
    context, _study = _data_context(db)
    rows = call_tool(context, "enumerator_performance_today")
    assert rows[0]["enumerator"] == "Ada"
    assert rows[0]["tools"] == "T1"
    assert rows[0]["flagRate"] == 66.7
    # Benchmarks are computed, never invented: study-wide values for the same day.
    assert rows[0]["groupFlagRate"] == 62.5
    assert rows[0]["groupMedianMinutes"] == 22.0


def test_enumerator_submission_quality_splits_clean_and_flagged(db: Session) -> None:
    context, _study = _data_context(db)
    rows = call_tool(context, "enumerator_submission_quality")
    assert len(rows) == 1
    row = rows[0]
    assert row["submissionsToday"] == 3
    assert row["redSubmissions"] == 1
    assert row["amberSubmissions"] == 1
    assert row["flaggedSubmissions"] == 2
    assert row["cleanSubmissions"] == 1
    assert "Missing GPS" in row["issues"]
    assert "Skip residue" in row["issues"]


def test_top_failing_rules_scope_param_selects_the_window(db: Session) -> None:
    context, _study = _data_context(db)
    today = call_tool(context, "top_failing_rules", {"scope": "today"})
    cumulative = call_tool(context, "top_failing_rules", {"scope": "cumulative"})
    assert {row["ruleId"]: row["count"] for row in today} == {"R1": 2, "R2": 3}
    assert {row["ruleId"]: row["count"] for row in cumulative} == {"R2": 14, "R1": 5}


def test_scope_defaults_to_today(db: Session) -> None:
    context, _study = _data_context(db)
    assert call_tool(context, "top_failing_rules") == call_tool(
        context, "top_failing_rules", {"scope": "today"}
    )


def test_red_priority_items_include_a_worked_example(db: Session) -> None:
    context, _study = _data_context(db)
    rows = call_tool(context, "red_priority_items")
    assert rows[0]["ruleId"] == "R1"
    assert rows[0]["count"] == 2
    assert rows[0]["example"] == "Ada · UDISE 12345678"


def test_flag_rate_trend_is_cumulative_by_day(db: Session) -> None:
    context, _study = _data_context(db)
    rows = call_tool(context, "flag_rate_trend")
    assert [row["dayLabel"] for row in rows] == ["D1", "D12"]
    assert [row["flaggedPct"] for row in rows] == [10.0, 15.0]


def test_signoff_checklist_resolves_the_owner(db: Session) -> None:
    context, _study = _data_context(db)
    rows = call_tool(context, "signoff_checklist")
    assert rows[0]["owner"] == "Field supervisor"
    assert rows[0]["severity"] == "red"


def test_study_metadata_reports_the_reporting_day(db: Session) -> None:
    context, _study = _data_context(db)
    meta = call_tool(context, "study_metadata")
    assert meta["studyName"] == "Fixture Study"
    assert meta["dayNumber"] == 12
    assert meta["timezone"] == "Asia/Kolkata"


# --- Live computation -------------------------------------------------------


def _seed_submissions(db: Session, study: Study) -> None:
    db.add(StudyTool(id="t1", study_id=study.id, code="T1", label="Facility", target_count=10))
    db.add(
        Project(
            id="p1",
            name="Facility",
            study_id=study.id,
            study_tool_id="t1",
            uid="a1",
            created_at=datetime(2026, 3, 4),
            updated_at=datetime(2026, 3, 4),
        )
    )
    db.flush()
    # 18:30 UTC on 14 Mar is 00:00 on 15 Mar in Asia/Kolkata: the day boundary case.
    rows = [
        ("s1", "Ada", datetime(2026, 3, 14, 18, 30)),
        ("s2", "Ada", datetime(2026, 3, 15, 6, 0)),
        ("s3", "Bo", datetime(2026, 3, 14, 18, 0)),
    ]
    for sid, enumerator, submitted_at in rows:
        db.add(
            Submission(
                id=sid,
                project_id="p1",
                kobo_id=sid,
                form_id="f1",
                form_name="Facility",
                enumerator=enumerator,
                submitted_at=submitted_at,
                status="complete",
                created_at=submitted_at,
            )
        )
    db.add(
        DqaFlag(
            id="flag-1",
            submission_id="s2",
            project_id="p1",
            rule_id="R1",
            severity="red",
            title="Missing GPS",
            message="GPS required",
            evaluated_at=datetime(2026, 3, 15, 6, 0),
        )
    )
    db.commit()


def test_timezone_boundary_excludes_the_previous_local_day(db: Session) -> None:
    study = _study(db)
    _seed_submissions(db, study)
    context = ReportDataContext(db, _context(), settings=db.get(AppSettings, "settings"))
    totals = call_tool(context, "study_totals")
    # s1 (18:30 UTC on 14 Mar) and s2 fall on 15 Mar in Asia/Kolkata; s3 (18:00 UTC) does not.
    assert totals["newToday"] == 2
    assert totals["cumulative"] == 3


def test_coverage_math_uses_the_study_tool_target(db: Session) -> None:
    study = _study(db)
    _seed_submissions(db, study)
    context = ReportDataContext(db, _context(), settings=db.get(AppSettings, "settings"))
    rows = call_tool(context, "tool_coverage")
    assert rows[0]["target"] == 10
    assert rows[0]["cumulative"] == 3
    assert rows[0]["remaining"] == 7
    assert rows[0]["coveragePct"] == 30.0


def test_statistics_are_computed_once_per_execution(db: Session) -> None:
    study = _study(db)
    _seed_submissions(db, study)
    context = ReportDataContext(db, _context(), settings=db.get(AppSettings, "settings"))
    calls = {"n": 0}
    real = context.stats

    def counted():
        if context._stats is None:
            calls["n"] += 1
        return real()

    context.stats = counted  # type: ignore[method-assign]
    for source in ("study_totals", "tool_coverage", "flag_rate_trend", "signoff_checklist"):
        call_tool(context, source)
    assert calls["n"] == 1


def test_missing_study_is_reported_clearly(db: Session) -> None:
    _study(db)
    context = ReportDataContext(db, _context(study_id="nope"))
    with pytest.raises(ValueError, match="Study not found"):
        _ = context.study
