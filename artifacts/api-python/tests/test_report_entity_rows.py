"""Unit tests for the shared entity-row / date-window substrate (Phase 1)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings, DqaFlag, Project, Study, StudyTool, Submission
from app.domain.report_spec import SPEC_VERSION, parse_spec, validate_spec
from app.domain.report_spec.context import ReportExecutionContext
from app.domain.reporting.date_windows import resolve_query_date_window
from app.domain.reporting.query_aggregate_catalog import MAX_DISTINCT_DATE_RANGES
from app.services.report_tools import ReportDataContext, descriptors_by_id
from app.services.report_tools.context import range_key

STUDY_ID = "study-entity-rows"
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
    db.add(AppSettings(id="settings", organization_name="Entity Rows Org", ai_enabled=False))
    study = Study(
        id=STUDY_ID,
        name="Entity Rows Study",
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
        Project(
            id="proj-t1",
            uid="uid-er-t1",
            name="Facility",
            study_id=STUDY_ID,
            study_tool_id="tool-t1",
            last_sync_at=datetime(2026, 3, 15, 3, 0, 0),
            created_at=datetime(2026, 3, 1),
            updated_at=datetime(2026, 3, 1),
        )
    )
    db.flush()

    # Outside last_14_days.
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

    # Inside last_14_days.
    for sid, day, rule_id, severity in (
        ("sub-a", "2026-03-05", "RULE_A", "amber"),
        ("sub-b", "2026-03-12", "RULE_B", "red"),
        ("sub-c", "2026-03-15", None, None),
    ):
        submitted = datetime.fromisoformat(f"{day}T10:00:00")
        db.add(
            Submission(
                id=sid,
                project_id="proj-t1",
                kobo_id=sid,
                form_id="f1",
                form_name="Facility",
                enumerator="Ada",
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
                    project_id="proj-t1",
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


def _ctx(db: Session) -> ReportDataContext:
    _seed(db)
    return ReportDataContext(
        db,
        ReportExecutionContext(
            report_kind="daily",
            study_id=STUDY_ID,
            execution_date=EXECUTION_DATE,
            timezone=TZ,
        ),
        settings=db.get(AppSettings, "settings"),
    )


def test_window_resolves_all_tokens(db: Session) -> None:
    ctx = _ctx(db)
    assert ctx.window(None) == (None, None)
    assert ctx.window("") == (None, None)
    assert ctx.window("execution_date") == ("2026-03-15", "2026-03-15")
    assert ctx.window("last_7_days") == ("2026-03-09", "2026-03-15")
    assert ctx.window("last_14_days") == ("2026-03-02", "2026-03-15")
    assert ctx.window("study_to_date") == ("2026-03-01", "2026-03-15")

    # Shared resolver matches the context wrapper.
    assert resolve_query_date_window(
        "last_14_days",
        execution_date=EXECUTION_DATE,
        study_start_date=STUDY_START,
    ) == ctx.window("last_14_days")


def test_entity_rows_returns_flattened_rows_for_range(db: Session) -> None:
    ctx = _ctx(db)
    date_from, date_to = ctx.window("last_14_days")

    subs = ctx.entity_rows(date_from, date_to, "submission")
    flags = ctx.entity_rows(date_from, date_to, "flag")

    # last_14_days excludes sub-old / flag-old; keeps sub-a, sub-b, sub-c.
    assert sorted(r["submissionId"] for r in subs) == ["sub-a", "sub-b", "sub-c"]
    assert all(r["enumerator"] == "Ada" for r in subs)
    assert all(r["toolCode"] == "T1" for r in subs)
    assert all("submitted_at" in r for r in subs)
    assert all("day" not in r for r in subs)  # day is not part of the substrate bag

    assert sorted(r["submissionId"] for r in flags) == ["sub-a", "sub-b"]
    assert {r["ruleId"] for r in flags} == {"RULE_A", "RULE_B"}
    assert all("day" not in r for r in flags)


def test_entity_rows_same_range_reuses_one_orm_load_two_kinds(db: Session) -> None:
    """Second kind on the same range shares the ORM memo; two entity-row keys."""
    ctx = _ctx(db)
    date_from, date_to = "2026-03-02", "2026-03-15"
    key = range_key(date_from, date_to)

    with patch(
        "app.repositories.reporting.load_study_report_inputs",
        wraps=__import__(
            "app.repositories.reporting", fromlist=["load_study_report_inputs"]
        ).load_study_report_inputs,
    ) as spy:
        first = ctx.entity_rows(date_from, date_to, "submission")
        second = ctx.entity_rows(date_from, date_to, "submission")
        flags = ctx.entity_rows(date_from, date_to, "flag")

        assert spy.call_count == 1
        assert first is second  # flattened bag memoized
        assert len(first) == 3
        assert len(flags) == 2

    assert key in ctx._inputs_by_range
    assert len(ctx._inputs_by_range) == 1
    assert (key, "submission") in ctx._entity_rows_by_key
    assert (key, "flag") in ctx._entity_rows_by_key
    assert len(ctx._entity_rows_by_key) == 2


def test_distinct_date_ranges_cap_still_rejects_third() -> None:
    """≤2-range cap remains validate_spec-only (semantic tokens), unchanged by entity_rows."""

    def _qa(**param_overrides: object) -> dict:
        params: dict = {"entity": "flag", "measure": "count", "groupBy": "enumerator"}
        params.update(param_overrides)
        columns = [{"field": "value", "label": "Value"}]
        if params.get("groupBy"):
            first = str(params["groupBy"]).split(",")[0].strip()
            if first:
                columns.insert(0, {"field": first, "label": first})
        return {
            "type": "table",
            "dataSource": "query_aggregate",
            "columns": columns,
            "params": params,
        }

    three = parse_spec(
        {
            "specVersion": SPEC_VERSION,
            "title": "Three ranges",
            "sections": [
                {
                    "title": "S",
                    "components": [
                        {
                            "type": "metric",
                            "label": "Total",
                            "dataSource": "study_totals",
                            "field": "cumulative",
                            "format": "int",
                        },
                        _qa(dateWindow="last_7_days"),
                        _qa(dateWindow="last_14_days", groupBy="ruleId"),
                    ],
                }
            ],
        }
    )
    assert three.spec is not None
    result = validate_spec(three.spec, descriptors_by_id())
    assert not result.valid
    err = next(e for e in result.errors if e.code == "too_many_date_ranges")
    assert "max 2 per report" in err.message
    assert MAX_DISTINCT_DATE_RANGES == 2
