"""Semantic report data sources: projections, business definitions and timezones."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

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


def _seed_projection(db: Session, study: Study) -> None:
    """Compact live seed for Phase 2 substrate-backed tools.

    Today (2026-03-15) has two enumerators with deliberately different
    individual flag rates / medians so group benchmarks cannot equal either.
    """
    db.add(
        StudyTool(
            id="t1", study_id=study.id, code="T1", label="Facility", target_count=100
        )
    )
    db.add(
        StudyTool(
            id="t2", study_id=study.id, code="T2", label="Teachers", target_count=80
        )
    )
    db.add(
        Project(
            id="p1",
            name="Facility",
            study_id=study.id,
            study_tool_id="t1",
            uid="a1",
            last_sync_at=datetime(2026, 3, 15, 10, 0, 0),
            created_at=datetime(2026, 3, 4),
            updated_at=datetime(2026, 3, 4),
        )
    )
    db.add(
        Project(
            id="p2",
            name="Teachers",
            study_id=study.id,
            study_tool_id="t2",
            uid="a2",
            last_sync_at=datetime(2026, 3, 15, 10, 0, 0),
            created_at=datetime(2026, 3, 4),
            updated_at=datetime(2026, 3, 4),
        )
    )
    db.flush()

    def add_sub(
        sid: str,
        project_id: str,
        enumerator: str,
        submitted_at: datetime,
        *,
        minutes: float | None = 40.0,
        udise: str | None = None,
    ) -> None:
        data: dict = {}
        if minutes is not None:
            data["start"] = submitted_at.isoformat()
            data["end"] = (submitted_at + timedelta(minutes=minutes)).isoformat()
        if udise is not None:
            data["udise"] = udise
        db.add(
            Submission(
                id=sid,
                project_id=project_id,
                kobo_id=sid,
                form_id="f1",
                form_name="Facility" if project_id == "p1" else "Teachers",
                enumerator=enumerator,
                submitted_at=submitted_at,
                status="complete",
                data=data,
                created_at=submitted_at,
            )
        )

    today = datetime(2026, 3, 15, 6, 0, 0)
    prior = datetime(2026, 3, 10, 8, 0, 0)

    # Ada today on T1: 6 subs; durations → median 22; 2 red + 3 amber flags
    # → individual flagRate = 5/6 ≈ 83.3 (flag-count formula).
    add_sub("s-ada-1", "p1", "Ada", today, minutes=20.0, udise="12345678")
    add_sub("s-ada-2", "p1", "Ada", today + timedelta(minutes=1), minutes=22.0)
    add_sub("s-ada-3", "p1", "Ada", today + timedelta(minutes=2), minutes=24.0)  # clean
    db.add(
        DqaFlag(
            id="f-ada-red",
            submission_id="s-ada-1",
            project_id="p1",
            rule_id="R1",
            severity="red",
            title="Missing GPS",
            message="GPS required",
            evaluated_at=today,
        )
    )
    db.add(
        DqaFlag(
            id="f-ada-amber",
            submission_id="s-ada-2",
            project_id="p1",
            rule_id="R2",
            severity="amber",
            title="Skip residue",
            message="Skip path incomplete",
            evaluated_at=today,
        )
    )
    add_sub(
        "s-ada-4", "p1", "Ada", today + timedelta(minutes=3), minutes=22.0, udise="12345678"
    )
    db.add(
        DqaFlag(
            id="f-ada-red-2",
            submission_id="s-ada-4",
            project_id="p1",
            rule_id="R1",
            severity="red",
            title="Missing GPS",
            message="GPS required",
            evaluated_at=today,
        )
    )
    for i in range(2):
        sid = f"s-ada-r2-{i}"
        add_sub(sid, "p1", "Ada", today + timedelta(minutes=10 + i), minutes=22.0)
        db.add(
            DqaFlag(
                id=f"f-ada-r2-{i}",
                submission_id=sid,
                project_id="p1",
                rule_id="R2",
                severity="amber",
                title="Skip residue",
                message="Skip path incomplete",
                evaluated_at=today,
            )
        )

    # Bo today: 2 clean T1 subs at 40 min → flagRate 0, median 40.
    # With Ada, groupFlagRate = 5 flagged / 8 today = 62.5 (≠ Ada 83.3, ≠ Bo 0).
    # groupMedianMinutes = mean(22, 40) = 31.0 (≠ either individual).
    add_sub("s-bo-1", "p1", "Bo", today + timedelta(hours=1), minutes=40.0)
    add_sub("s-bo-2", "p1", "Bo", today + timedelta(hours=1, minutes=1), minutes=40.0)

    # Prior cumulative volume: T1 and T2 (all flagged) on Mar 10 (= study D7).
    for i in range(5):
        add_sub(
            f"s-prior-t1-{i}", "p1", "Prior", prior + timedelta(minutes=i), minutes=30.0
        )
        db.add(
            DqaFlag(
                id=f"f-prior-r1-{i}",
                submission_id=f"s-prior-t1-{i}",
                project_id="p1",
                rule_id="R1",
                severity="red" if i < 3 else "amber",
                title="Missing GPS",
                message="prior",
                evaluated_at=prior + timedelta(minutes=i),
            )
        )
    for i in range(12):
        add_sub(
            f"s-prior-t2-{i}",
            "p2",
            "PriorT2",
            prior + timedelta(hours=1, minutes=i),
            minutes=30.0,
        )
        db.add(
            DqaFlag(
                id=f"f-prior-r2-{i}",
                submission_id=f"s-prior-t2-{i}",
                project_id="p2",
                rule_id="R2",
                severity="amber",
                title="Skip residue",
                message="prior",
                evaluated_at=prior + timedelta(hours=1, minutes=i),
            )
        )

    db.commit()


def _data_context(db: Session) -> tuple[ReportDataContext, Study]:
    study = _study(db)
    _seed_projection(db, study)
    return (
        ReportDataContext(db, _context(), settings=db.get(AppSettings, "settings")),
        study,
    )


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
        "query_aggregate",
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


# --- Projections (live substrate) -------------------------------------------


def test_study_totals_derives_clean_and_flagged_counts(db: Session) -> None:
    context, _study = _data_context(db)
    totals = call_tool(context, "study_totals")
    # Today: Ada 6 + Bo 2 = 8; 5 flagged (Ada), 3 clean.
    assert totals["newToday"] == 8
    assert totals["flaggedToday"] == 5
    assert totals["cleanToday"] == 3
    assert totals["flaggedPctToday"] == 62.5
    # Cumulative: 8 today + 5 prior T1 + 12 prior T2 = 25; flagged 5+5+12 = 22.
    assert totals["cumulative"] == 25
    assert totals["flaggedCumulative"] == 22
    assert totals["cleanCumulative"] == 3
    assert totals["flaggedPctCumulative"] == 88.0


def test_tool_coverage_carries_the_configured_target(db: Session) -> None:
    context, _study = _data_context(db)
    rows = call_tool(context, "tool_coverage")
    by_code = {row["toolCode"]: row for row in rows}
    assert by_code["T1"]["target"] == 100
    assert by_code["T1"]["cumulative"] == 13  # 8 today + 5 prior
    assert by_code["T1"]["coveragePct"] == 13.0
    assert by_code["T2"]["target"] == 80
    assert by_code["T2"]["cumulative"] == 12
    assert by_code["T2"]["remaining"] == 68
    assert "target" in descriptors_by_id()["tool_coverage"].benchmark_fields


def test_enumerator_performance_includes_group_benchmarks(db: Session) -> None:
    context, _study = _data_context(db)
    rows = call_tool(context, "enumerator_performance_today")
    assert len(rows) == 2
    assert rows[0]["enumerator"] == "Ada"  # RED sorts first
    ada = rows[0]
    bo = next(r for r in rows if r["enumerator"] == "Bo")

    assert ada["tools"] == "T1"
    assert ada["flagRate"] == 83.3  # (2 red + 3 amber) / 6
    assert ada["medianMinutes"] == 22.0
    assert bo["flagRate"] == 0.0
    assert bo["medianMinutes"] == 40.0

    # Group benchmarks are study-wide today — not either individual's numbers.
    assert ada["groupFlagRate"] == 62.5  # 5 flagged / 8 today
    assert bo["groupFlagRate"] == 62.5
    assert ada["groupMedianMinutes"] == 31.0  # mean(22, 40)
    assert bo["groupMedianMinutes"] == 31.0
    assert ada["groupFlagRate"] != ada["flagRate"]
    assert bo["groupFlagRate"] != bo["flagRate"]
    assert ada["groupMedianMinutes"] != ada["medianMinutes"]
    assert bo["groupMedianMinutes"] != bo["medianMinutes"]


def test_enumerator_submission_quality_splits_clean_and_flagged(db: Session) -> None:
    context, _study = _data_context(db)
    rows = call_tool(context, "enumerator_submission_quality")
    assert len(rows) == 2
    ada = next(r for r in rows if r["enumerator"] == "Ada")
    assert ada["submissionsToday"] == 6
    assert ada["redSubmissions"] == 2
    assert ada["amberSubmissions"] == 3
    assert ada["flaggedSubmissions"] == 5
    assert ada["cleanSubmissions"] == 1
    assert "Missing GPS" in ada["issues"]
    assert "Skip residue" in ada["issues"]


def test_top_failing_rules_scope_param_selects_the_window(db: Session) -> None:
    context, _study = _data_context(db)
    today = call_tool(context, "top_failing_rules", {"scope": "today"})
    cumulative = call_tool(context, "top_failing_rules", {"scope": "cumulative"})
    assert {row["ruleId"]: row["count"] for row in today} == {"R1": 2, "R2": 3}
    assert {row["ruleId"]: row["count"] for row in cumulative} == {
        "R2": 3 + 12,
        "R1": 2 + 5,
    }


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
    assert rows[0]["exampleEnumerator"] == "Ada"
    assert "UDISE 12345678" in rows[0]["example"]


def test_flag_rate_trend_is_cumulative_by_day(db: Session) -> None:
    context, _study = _data_context(db)
    rows = call_tool(context, "flag_rate_trend")
    by_day = {row["dayLabel"]: row for row in rows}
    assert rows[0]["dayLabel"] == "D1"
    assert rows[-1]["dayLabel"] == "D12"
    assert len(rows) == 12  # Mar 4 → Mar 15 inclusive

    # Exact cumulative flaggedPct at two points (proves computation, not just shape).
    # D1 (Mar 4): empty bag → 0.0
    assert by_day["D1"]["flaggedPct"] == 0.0
    assert by_day["D1"]["submissions"] == 0
    # D7 (Mar 10): 17 prior (all flagged) → 100.0
    assert by_day["D7"]["flaggedPct"] == 100.0
    assert by_day["D7"]["submissions"] == 17
    # D12 (Mar 15): 25 total, 22 flagged → 88.0
    assert by_day["D12"]["flaggedPct"] == 88.0
    assert by_day["D12"]["submissions"] == 25


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


def test_distinct_windows_share_one_orm_load_each(db: Session) -> None:
    """Phase 2 tools use windowed report_inputs — at most two ranges, each loaded once."""
    study = _study(db)
    _seed_submissions(db, study)
    context = ReportDataContext(db, _context(), settings=db.get(AppSettings, "settings"))

    with patch(
        "app.repositories.reporting.load_study_report_inputs",
        wraps=__import__(
            "app.repositories.reporting", fromlist=["load_study_report_inputs"]
        ).load_study_report_inputs,
    ) as spy:
        for source in ("study_totals", "tool_coverage", "flag_rate_trend", "signoff_checklist"):
            call_tool(context, source)
        # execution_date + study_to_date only
        assert spy.call_count == 2
        assert len(context._inputs_by_range) == 2


def test_missing_study_is_reported_clearly(db: Session) -> None:
    _study(db)
    context = ReportDataContext(db, _context(study_id="nope"))
    with pytest.raises(ValueError, match="Study not found"):
        _ = context.study
