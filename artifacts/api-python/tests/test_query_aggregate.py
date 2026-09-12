"""Direct call_tool coverage for query_aggregate (Stage 1).

Planner / validation wiring is out of scope here — these tests invoke the
handler with explicit params and assert hand-computed expected rows.
"""

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
from app.services.report_tools.context import range_key
from app.services.report_tools.query_aggregate import resolve_query_date_window

STUDY_ID = "study-query-agg"
EXECUTION_DATE = "2026-03-15"
TZ = "Asia/Kolkata"
STUDY_START = "2026-03-01"


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
    """Compact fixture with known counts for the four free-form examples."""
    db.add(AppSettings(id="settings", organization_name="Query Agg Org", ai_enabled=False))
    study = Study(
        id=STUDY_ID,
        name="Query Aggregate Study",
        start_date=STUDY_START,
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
        StudyTool(
            id="tool-t2",
            study_id=STUDY_ID,
            code="T2",
            label="Teachers",
            target_count=50,
            sort_order=1,
        )
    )
    db.add(
        Project(
            id="proj-t1",
            uid="uid-qa-t1",
            name="Facility",
            study_id=STUDY_ID,
            study_tool_id="tool-t1",
            last_sync_at=datetime(2026, 3, 15, 3, 0, 0),
            created_at=datetime(2026, 3, 1),
            updated_at=datetime(2026, 3, 1),
        )
    )
    db.add(
        Project(
            id="proj-t2",
            uid="uid-qa-t2",
            name="Teachers",
            study_id=STUDY_ID,
            study_tool_id="tool-t2",
            last_sync_at=datetime(2026, 3, 15, 3, 0, 0),
            created_at=datetime(2026, 3, 1),
            updated_at=datetime(2026, 3, 1),
        )
    )
    db.flush()

    # Outside last_14_days (before 2026-03-02) and last_7_days.
    db.add(
        Submission(
            id="sub-old",
            project_id="proj-t1",
            kobo_id="old",
            form_id="f1",
            form_name="Facility",
            enumerator="Ada",
            submitted_at=datetime(2026, 2, 20, 8, 0, 0),
            status="complete",
            data={},
            created_at=datetime(2026, 2, 20, 8, 0, 0),
        )
    )
    db.add(
        DqaFlag(
            id="flag-old",
            submission_id="sub-old",
            project_id="proj-t1",
            rule_id="OLD_RULE",
            severity="amber",
            title="Old",
            message="outside windows",
            evaluated_at=datetime(2026, 2, 20, 8, 0, 0),
        )
    )

    # Inside last_14_days / study_to_date, outside last_7_days (before Mar 9).
    db.add(
        Submission(
            id="sub-mid",
            project_id="proj-t1",
            kobo_id="mid",
            form_id="f1",
            form_name="Facility",
            enumerator="Ada",
            submitted_at=datetime(2026, 3, 5, 8, 0, 0),
            status="complete",
            data={},
            created_at=datetime(2026, 3, 5, 8, 0, 0),
        )
    )
    db.add(
        DqaFlag(
            id="flag-mid-amber",
            submission_id="sub-mid",
            project_id="proj-t1",
            rule_id="RULE_A",
            severity="amber",
            title="Mid amber",
            message="mid",
            evaluated_at=datetime(2026, 3, 5, 8, 0, 0),
        )
    )

    # Last week + today: Ada / Bob flags on T1 and T2.
    rows = [
        ("sub-ada-1", "proj-t1", "Ada", "2026-03-12", "RULE_A", "amber"),
        ("sub-ada-2", "proj-t1", "Ada", "2026-03-14", "RULE_B", "red"),
        ("sub-bob-1", "proj-t2", "Bob", "2026-03-13", "RULE_A", "amber"),
        ("sub-bob-2", "proj-t2", "Bob", "2026-03-15", "RULE_C", "amber"),
        ("sub-clean", "proj-t2", "Bob", "2026-03-15", None, None),
    ]
    for sid, project_id, enumerator, day, rule_id, severity in rows:
        submitted = datetime.fromisoformat(f"{day}T10:00:00")
        db.add(
            Submission(
                id=sid,
                project_id=project_id,
                kobo_id=sid,
                form_id="f",
                form_name="Form",
                enumerator=enumerator,
                submitted_at=submitted,
                status="complete",
                data={},
                created_at=submitted,
            )
        )
        if rule_id and severity:
            db.add(
                DqaFlag(
                    id=f"flag-{sid}",
                    submission_id=sid,
                    project_id=project_id,
                    rule_id=rule_id,
                    severity=severity,
                    title=rule_id,
                    message=rule_id,
                    evaluated_at=submitted,
                )
            )

    db.commit()
    db.refresh(study)
    return study


def _ctx(db: Session, **overrides: object) -> ReportDataContext:
    _seed(db)
    payload = {
        "report_kind": "daily",
        "study_id": STUDY_ID,
        "execution_date": EXECUTION_DATE,
        "timezone": TZ,
    }
    payload.update(overrides)
    return ReportDataContext(
        db,
        ReportExecutionContext(**payload),
        settings=db.get(AppSettings, "settings"),
    )


def test_resolve_date_window_tokens() -> None:
    assert resolve_query_date_window(
        None,
        execution_date=EXECUTION_DATE,
        study_start_date=STUDY_START,
        context_date_from=None,
        context_date_to=None,
    ) == (None, None)
    assert resolve_query_date_window(
        "execution_date",
        execution_date=EXECUTION_DATE,
        study_start_date=STUDY_START,
    ) == ("2026-03-15", "2026-03-15")
    assert resolve_query_date_window(
        "last_7_days",
        execution_date=EXECUTION_DATE,
        study_start_date=STUDY_START,
    ) == ("2026-03-09", "2026-03-15")
    assert resolve_query_date_window(
        "last_14_days",
        execution_date=EXECUTION_DATE,
        study_start_date=STUDY_START,
    ) == ("2026-03-02", "2026-03-15")
    assert resolve_query_date_window(
        "study_to_date",
        execution_date=EXECUTION_DATE,
        study_start_date=STUDY_START,
    ) == ("2026-03-01", "2026-03-15")
    # Adhoc date_from/date_to clamps named windows (pre-filter semantics).
    assert resolve_query_date_window(
        "study_to_date",
        execution_date=EXECUTION_DATE,
        study_start_date=STUDY_START,
        context_date_from="2026-03-10",
        context_date_to="2026-03-12",
    ) == ("2026-03-10", "2026-03-12")
    # execution_date outside the adhoc window → empty intersection (from > to).
    assert resolve_query_date_window(
        "execution_date",
        execution_date=EXECUTION_DATE,
        study_start_date=STUDY_START,
        context_date_from="2026-03-10",
        context_date_to="2026-03-12",
    ) == ("2026-03-15", "2026-03-12")


def test_example_flag_counts_by_enumerator(db: Session) -> None:
    """PART 1 #1 — flag counts grouped by enumerator."""
    ctx = _ctx(db)
    rows = call_tool(
        ctx,
        "query_aggregate",
        {
            "entity": "flag",
            "measure": "count",
            "groupBy": "enumerator",
            "orderBy": "enumerator:asc",
        },
    )
    # Full bag: Ada (old+mid+2 recent)=4, Bob (2)=2
    assert rows == [
        {"enumerator": "Ada", "value": 4},
        {"enumerator": "Bob", "value": 2},
    ]


def test_example_last_two_weeks_counts(db: Session) -> None:
    """PART 1 #2 — submission and flag counts for last_14_days only."""
    ctx = _ctx(db)
    subs = call_tool(
        ctx,
        "query_aggregate",
        {
            "entity": "submission",
            "measure": "count",
            "dateWindow": "last_14_days",
        },
    )
    flags = call_tool(
        ctx,
        "query_aggregate",
        {
            "entity": "flag",
            "measure": "count",
            "dateWindow": "last_14_days",
        },
    )
    # Excludes sub-old / flag-old (Feb 20). Remaining: mid + 5 recent = 6 subs;
    # flags: mid + 4 flagged recent = 5.
    assert subs == [{"value": 6}]
    assert flags == [{"value": 5}]


def test_example_findings_by_rule(db: Session) -> None:
    """PART 1 #3 — flag counts grouped by ruleId (all rules, no top-N)."""
    ctx = _ctx(db)
    rows = call_tool(
        ctx,
        "query_aggregate",
        {
            "entity": "flag",
            "measure": "count",
            "groupBy": "ruleId",
            "orderBy": "ruleId:asc",
        },
    )
    # RULE_A: mid + ada-1 + bob-1 = 3
    assert rows == [
        {"ruleId": "OLD_RULE", "value": 1},
        {"ruleId": "RULE_A", "value": 3},
        {"ruleId": "RULE_B", "value": 1},
        {"ruleId": "RULE_C", "value": 1},
    ]


def test_example_amber_flag_counts_by_tool(db: Session) -> None:
    """PART 1 #4 — amber-only flag counts by tool (rate residual noted in design)."""
    ctx = _ctx(db)
    rows = call_tool(
        ctx,
        "query_aggregate",
        {
            "entity": "flag",
            "measure": "count",
            "groupBy": "toolCode",
            "filterField": "severity",
            "filterOp": "eq",
            "filterValue": "amber",
            "orderBy": "toolCode:asc",
        },
    )
    # T1 amber: old + mid + ada-1 = 3; T2 amber: bob-1 + bob-2 = 2
    assert rows == [
        {"toolCode": "T1", "value": 3},
        {"toolCode": "T2", "value": 2},
    ]


def test_same_date_window_shares_one_inputs_memo(db: Session) -> None:
    ctx = _ctx(db)
    call_tool(
        ctx,
        "query_aggregate",
        {"entity": "submission", "measure": "count", "dateWindow": "last_14_days"},
    )
    call_tool(
        ctx,
        "query_aggregate",
        {"entity": "flag", "measure": "count", "dateWindow": "last_14_days"},
    )
    key = range_key("2026-03-02", "2026-03-15")
    assert key in ctx._inputs_by_range
    assert len(ctx._inputs_by_range) == 1


def test_certified_stats_stay_on_default_range(db: Session) -> None:
    """query_aggregate windows must not repoint certified tools' stats() memo."""
    ctx = _ctx(db)
    defaults = ctx.stats()
    call_tool(
        ctx,
        "query_aggregate",
        {"entity": "flag", "measure": "count", "dateWindow": "last_7_days"},
    )
    assert ctx.default_range_key() in ctx._stats_by_range
    assert ctx.stats() is defaults
    # Windowed query used inputs memo, not a redirected default stats blob.
    assert range_key("2026-03-09", "2026-03-15") in ctx._inputs_by_range


def test_day_is_allowlisted_group_by_dimension() -> None:
    from app.domain.reporting.query_aggregate_catalog import ENTITY_DIMENSIONS
    from app.services.report_planner.prompting import data_source_brief
    from app.services.report_tools import all_descriptors

    assert "day" in ENTITY_DIMENSIONS["submission"]
    assert "day" in ENTITY_DIMENSIONS["flag"]
    brief = {e["id"]: e for e in data_source_brief(all_descriptors())}
    assert "day" in brief["query_aggregate"]["entities"]["submission"]["groupBy"]
    assert "day" in brief["query_aggregate"]["entities"]["flag"]["groupBy"]
    field_names = {f["name"] for f in brief["query_aggregate"]["fields"]}
    assert "day" in field_names


def test_flag_day_buckets_by_submission_submitted_at_not_evaluated_at(db: Session) -> None:
    """Flag day uses joined submission submitted_at (window clock), not evaluated_at."""
    from app.domain.reporting.helpers import local_calendar_day
    from app.services.report_tools.query_aggregate import (
        build_flag_entity_rows,
        derive_entity_day_column,
    )

    # UTC-naive 2026-03-11 20:00 → Asia/Kolkata calendar day 2026-03-12.
    submitted = datetime(2026, 3, 11, 20, 0, 0)
    evaluated = datetime(2026, 3, 13, 10, 0, 0)
    assert local_calendar_day(submitted, TZ) == "2026-03-12"
    assert local_calendar_day(evaluated, TZ) == "2026-03-13"

    _seed(db)
    db.add(
        Submission(
            id="sub-tz-cross",
            project_id="proj-t1",
            kobo_id="tz-cross",
            form_id="f1",
            form_name="Facility",
            enumerator="Cross",
            submitted_at=submitted,
            status="complete",
            data={},
            created_at=submitted,
        )
    )
    db.add(
        DqaFlag(
            id="flag-tz-cross",
            submission_id="sub-tz-cross",
            project_id="proj-t1",
            rule_id="TZ_RULE",
            severity="amber",
            title="Cross day",
            message="evaluated later",
            evaluated_at=evaluated,
        )
    )
    db.commit()

    ctx = ReportDataContext(
        db,
        ReportExecutionContext(
            report_kind="daily",
            study_id=STUDY_ID,
            execution_date=EXECUTION_DATE,
            timezone=TZ,
        ),
        settings=db.get(AppSettings, "settings"),
    )
    loaded = ctx.report_inputs(None, None)
    rows = derive_entity_day_column(
        build_flag_entity_rows(
            loaded["projects"], loaded["all_subs"], loaded["all_flags"]
        ),
        tz_name=TZ,
    )
    cross = next(r for r in rows if r["submissionId"] == "sub-tz-cross")
    assert cross["day"] == "2026-03-12"
    assert cross["day"] != local_calendar_day(evaluated, TZ)

    agg = call_tool(
        ctx,
        "query_aggregate",
        {
            "entity": "flag",
            "measure": "count",
            "groupBy": "enumerator,day",
            "filterField": "enumerator",
            "filterOp": "eq",
            "filterValue": "Cross",
        },
    )
    assert agg == [{"enumerator": "Cross", "day": "2026-03-12", "value": 1}]


def test_group_by_enumerator_day_last_7_days_is_sparse(db: Session) -> None:
    """One row per observed (enumerator, day); no zero-fill for empty calendar days."""
    ctx = _ctx(db)
    rows = call_tool(
        ctx,
        "query_aggregate",
        {
            "entity": "flag",
            "measure": "count",
            "groupBy": "enumerator,day",
            "dateWindow": "last_7_days",
            "orderBy": "day:asc",
        },
    )
    # last_7_days = Mar 9–15. Observed flag days only (no Mar 9–11 empty days):
    expected = {
        ("Ada", "2026-03-12"): 1,
        ("Ada", "2026-03-14"): 1,
        ("Bob", "2026-03-13"): 1,
        ("Bob", "2026-03-15"): 1,
    }
    got = {(r["enumerator"], r["day"]): r["value"] for r in rows}
    assert got == expected
    # Sparse: fewer rows than enumerators × 7 calendar days.
    assert len(rows) == 4
    assert len(rows) < 2 * 7
    window_days = {
        f"2026-03-{d:02d}" for d in range(9, 16)
    }
    observed_days = {r["day"] for r in rows}
    assert observed_days < window_days
    assert "2026-03-09" not in observed_days
    assert "2026-03-10" not in observed_days
    assert "2026-03-11" not in observed_days
