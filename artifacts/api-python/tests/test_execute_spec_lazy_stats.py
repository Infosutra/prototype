"""Phase 3: execute_spec must not eagerly build the daily stats collapse."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings, Project, Study, StudyTool, Submission
from app.domain.report_spec.context import ReportExecutionContext
from app.domain.report_spec.spec import (
    MetricComponent,
    ReportSpec,
    Section,
    TableColumn,
    TableComponent,
)
from app.services.report_execution import execute_spec
from app.services.report_stats import build_daily_dqa_stats


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
    db.add(AppSettings(id="settings", organization_name="Lazy Stats Org", ai_enabled=False))
    study = Study(
        id="study-lazy",
        name="Lazy Stats Study",
        start_date="2026-03-01",
        timezone="Asia/Kolkata",
        created_at=datetime(2026, 3, 1),
        updated_at=datetime(2026, 3, 1),
    )
    db.add(study)
    db.add(
        StudyTool(
            id="t1",
            study_id="study-lazy",
            code="T1",
            label="Facility",
            target_count=10,
            sort_order=0,
        )
    )
    db.add(
        Project(
            id="p1",
            uid="uid-lazy",
            name="Facility",
            study_id="study-lazy",
            study_tool_id="t1",
            created_at=datetime(2026, 3, 1),
            updated_at=datetime(2026, 3, 1),
        )
    )
    db.add(
        Submission(
            id="s1",
            project_id="p1",
            kobo_id="1",
            form_id="f",
            form_name="Facility",
            enumerator="Ada",
            submitted_at=datetime(2026, 3, 15, 6, 0, 0),
            status="complete",
            data={},
            created_at=datetime(2026, 3, 15, 6, 0, 0),
        )
    )
    db.commit()
    return study


def test_execute_spec_skips_stats_collapse_for_common_daily_spec(db: Session) -> None:
    """Common daily/adhoc specs must not call build_daily_dqa_stats (was eager)."""
    _seed(db)
    spec = ReportSpec(
        title="Common daily",
        sections=[
            Section(
                title="Totals",
                components=[
                    MetricComponent(
                        id="m",
                        label="Today",
                        data_source="study_totals",
                        field="newToday",
                        format="int",
                    ),
                    TableComponent(
                        id="t",
                        data_source="tool_coverage",
                        columns=[TableColumn(field="toolCode", label="Tool")],
                    ),
                ],
            )
        ],
    )
    context = ReportExecutionContext(
        report_kind="daily",
        study_id="study-lazy",
        execution_date="2026-03-15",
        timezone="Asia/Kolkata",
    )

    with patch(
        "app.services.report_stats.build_daily_dqa_stats",
        wraps=build_daily_dqa_stats,
    ) as spy:
        executed = execute_spec(db, spec, context, run_ai=False)
        assert executed.data["study_totals"]["newToday"] == 1
        assert spy.call_count == 0
