"""Phase 4: dateWindow on cumulative certified tools."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings, DqaFlag, Project, Study, StudyTool, Submission
from app.domain.report_spec.context import ReportExecutionContext
from app.domain.report_spec.spec import (
    ReportSpec,
    Section,
    TableColumn,
    TableComponent,
)
from app.domain.report_spec.validation import validate_spec
from app.services.report_tools import ReportDataContext, all_descriptors, call_tool, descriptors_by_id

STUDY_ID = "study-phase4-window"
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
    db.add(AppSettings(id="settings", organization_name="Phase4 Org", ai_enabled=False))
    study = Study(
        id=STUDY_ID,
        name="Phase4 Study",
        start_date="2026-03-01",
        timezone=TZ,
        created_at=datetime(2026, 3, 1),
        updated_at=datetime(2026, 3, 1),
    )
    db.add(study)
    db.add(
        StudyTool(
            id="t1",
            study_id=STUDY_ID,
            code="T1",
            label="Facility",
            target_count=100,
            sort_order=0,
        )
    )
    db.add(
        Project(
            id="p1",
            uid="uid-p4",
            name="Facility",
            study_id=STUDY_ID,
            study_tool_id="t1",
            created_at=datetime(2026, 3, 1),
            updated_at=datetime(2026, 3, 1),
        )
    )
    # Outside last_7_days of execution_date 15 Mar (window starts 9 Mar).
    early = Submission(
        id="sub-early",
        project_id="p1",
        kobo_id="early",
        form_id="f",
        form_name="Facility",
        enumerator="EarlyEnum",
        submitted_at=datetime(2026, 3, 3, 8, 0, 0),
        status="complete",
        data={},
        created_at=datetime(2026, 3, 3, 8, 0, 0),
    )
    # Inside last_7_days.
    late = Submission(
        id="sub-late",
        project_id="p1",
        kobo_id="late",
        form_id="f",
        form_name="Facility",
        enumerator="LateEnum",
        submitted_at=datetime(2026, 3, 12, 8, 0, 0),
        status="complete",
        data={},
        created_at=datetime(2026, 3, 12, 8, 0, 0),
    )
    db.add_all([early, late])
    db.add(
        DqaFlag(
            id="flag-early",
            submission_id="sub-early",
            project_id="p1",
            rule_id="EARLY_RULE",
            severity="amber",
            title="Early rule",
            message="early",
            evaluated_at=datetime(2026, 3, 3, 9, 0, 0),
        )
    )
    db.add(
        DqaFlag(
            id="flag-late",
            submission_id="sub-late",
            project_id="p1",
            rule_id="LATE_RULE",
            severity="amber",
            title="Late rule",
            message="late",
            evaluated_at=datetime(2026, 3, 12, 9, 0, 0),
        )
    )
    db.commit()
    return study


def _ctx(db: Session) -> ReportDataContext:
    return ReportDataContext(
        db,
        ReportExecutionContext(
            report_kind="adhoc",
            study_id=STUDY_ID,
            execution_date=EXECUTION_DATE,
            timezone=TZ,
        ),
        settings=db.get(AppSettings, "settings"),
    )


def _table(source: str, params: dict | None = None) -> ReportSpec:
    return ReportSpec(
        title="Phase4",
        sections=[
            Section(
                title="S",
                components=[
                    TableComponent(
                        id="t",
                        data_source=source,
                        params=params or {},
                        columns=[TableColumn(field="enumerator", label="E")]
                        if source == "enumerator_performance_study"
                        else [TableColumn(field="toolCode", label="Tool")],
                    )
                ],
            )
        ],
    )


def test_flag_rate_trend_has_no_date_window_param() -> None:
    desc = descriptors_by_id()["flag_rate_trend"]
    assert desc.supports_date_window is False
    assert desc.param("dateWindow") is None


def test_enumerator_performance_study_date_window_scopes_rows(db: Session) -> None:
    _seed(db)
    ctx = _ctx(db)
    full = call_tool(ctx, "enumerator_performance_study", {})
    windowed = call_tool(
        ctx, "enumerator_performance_study", {"dateWindow": "last_7_days"}
    )
    full_enums = {r["enumerator"] for r in full}
    window_enums = {r["enumerator"] for r in windowed}
    assert full_enums == {"EarlyEnum", "LateEnum"}
    assert window_enums == {"LateEnum"}
    assert sum(int(r["submissions"]) for r in full) == 2
    assert sum(int(r["submissions"]) for r in windowed) == 1


def test_findings_by_tool_date_window_scopes_rules(db: Session) -> None:
    _seed(db)
    ctx = _ctx(db)
    full = call_tool(ctx, "findings_by_tool", {})
    windowed = call_tool(ctx, "findings_by_tool", {"dateWindow": "last_7_days"})
    assert full[0]["topRule"].startswith("EARLY_RULE") or "EARLY_RULE" in full[0]["summary"]
    # Windowed bag only has LATE_RULE.
    assert "LATE_RULE" in (windowed[0].get("topRule") or "")
    assert "EARLY_RULE" not in (windowed[0].get("topRule") or "")


def test_top_failing_rules_rejects_date_window_with_scope_today() -> None:
    sources = descriptors_by_id()
    spec = ReportSpec(
        title="Bad",
        sections=[
            Section(
                title="S",
                components=[
                    TableComponent(
                        id="t",
                        data_source="top_failing_rules",
                        params={"scope": "today", "dateWindow": "last_7_days"},
                        columns=[
                            TableColumn(field="ruleId", label="Rule"),
                            TableColumn(field="count", label="N", format="int"),
                        ],
                    )
                ],
            )
        ],
    )
    result = validate_spec(spec, sources)
    assert not result.valid
    msgs = [e.message for e in result.errors]
    assert any("dateWindow is only valid with scope=cumulative" in m for m in msgs)


def test_top_failing_rules_accepts_date_window_with_scope_cumulative(db: Session) -> None:
    _seed(db)
    sources = descriptors_by_id()
    spec = ReportSpec(
        title="Ok",
        sections=[
            Section(
                title="S",
                components=[
                    TableComponent(
                        id="t",
                        data_source="top_failing_rules",
                        params={"scope": "cumulative", "dateWindow": "last_7_days"},
                        columns=[
                            TableColumn(field="ruleId", label="Rule"),
                            TableColumn(field="count", label="N", format="int"),
                        ],
                    )
                ],
            )
        ],
    )
    result = validate_spec(spec, sources)
    assert result.valid, [e.message for e in result.errors]
    rows = call_tool(
        _ctx(db),
        "top_failing_rules",
        {"scope": "cumulative", "dateWindow": "last_7_days"},
    )
    assert [r["ruleId"] for r in rows] == ["LATE_RULE"]


def _qa_and_certified(certified_window: str, qa_window: str) -> ReportSpec:
    return ReportSpec(
        title="Ranges",
        sections=[
            Section(
                title="S",
                components=[
                    TableComponent(
                        id="c",
                        data_source="enumerator_performance_study",
                        params={"dateWindow": certified_window},
                        columns=[TableColumn(field="enumerator", label="E")],
                    ),
                    TableComponent(
                        id="q",
                        data_source="query_aggregate",
                        params={
                            "entity": "submission",
                            "measure": "count",
                            "dateWindow": qa_window,
                        },
                        columns=[TableColumn(field="value", label="N", format="int")],
                    ),
                ],
            )
        ],
    )


def test_distinct_range_cap_counts_certified_and_query_aggregate_same_token() -> None:
    sources = descriptors_by_id()
    same = validate_spec(_qa_and_certified("last_7_days", "last_7_days"), sources)
    assert same.valid, [e.message for e in same.errors]
    different = validate_spec(_qa_and_certified("last_7_days", "last_14_days"), sources)
    assert different.valid, [e.message for e in different.errors]
    # At the cap (2). Adding a third distinct token must fail.
    overcrowded = ReportSpec(
        title="Too many",
        sections=[
            Section(
                title="S",
                components=[
                    TableComponent(
                        id="c",
                        data_source="findings_by_tool",
                        params={"dateWindow": "last_7_days"},
                        columns=[TableColumn(field="toolCode", label="T")],
                    ),
                    TableComponent(
                        id="q1",
                        data_source="query_aggregate",
                        params={
                            "entity": "submission",
                            "measure": "count",
                            "dateWindow": "last_14_days",
                        },
                        columns=[TableColumn(field="value", label="N", format="int")],
                    ),
                    TableComponent(
                        id="q2",
                        data_source="query_aggregate",
                        params={
                            "entity": "flag",
                            "measure": "count",
                            "dateWindow": "study_to_date",
                        },
                        columns=[TableColumn(field="value", label="N", format="int")],
                    ),
                ],
            )
        ],
    )
    bad = validate_spec(overcrowded, sources)
    assert not bad.valid
    assert any(e.code == "too_many_date_ranges" for e in bad.errors)


def test_phase4_date_window_capable_flags() -> None:
    by_id = descriptors_by_id()
    assert by_id["enumerator_performance_study"].supports_date_window is True
    assert by_id["findings_by_tool"].supports_date_window is True
    assert by_id["top_failing_rules"].supports_date_window is True
    assert by_id["flag_rate_trend"].supports_date_window is False
    assert by_id["study_totals"].supports_date_window is False
    assert by_id["tool_coverage"].supports_date_window is False
    assert by_id["red_priority_items"].supports_date_window is False
