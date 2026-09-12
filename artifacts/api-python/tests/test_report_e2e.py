"""Prompt → plan → validate → tools → analysis → render."""

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
    NarrativeComponent,
    ReportSpec,
    Section,
)
from app.services.report_execution import execute_spec
from app.services.report_planner import plan_spec
from app.services.report_planner.prompting import PlannerReply
from app.services.dqa_final_report import generate_final_dqa_report
from app.services.report_seed_templates import FINAL_TEMPLATE_ID, seed_report_templates
from app.services.report_templates import create_template, execute_template
from tests.test_report_planner import _FakeCaller

STUDY_ID = "study-fixture"
REPORT_DATE = "2026-03-15"
TZ = "Asia/Kolkata"


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


def _seed(db: Session, *, submissions_today: int = 8, prior: int = 112) -> Study:
    """Live rows for Phase 2+ tools (stats inject no longer feeds study_totals)."""
    db.add(
        AppSettings(
            id="singleton",
            organization_name="Infosutra Test Org",
            ai_enabled=True,
            ai_api_key="sk",
        )
    )
    study = Study(
        id=STUDY_ID,
        name="Fixture Study",
        start_date="2026-03-04",
        timezone=TZ,
        created_at=datetime(2026, 3, 4),
        updated_at=datetime(2026, 3, 4),
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
            uid="uid-e2e-t1",
            name="Facility",
            study_id=STUDY_ID,
            study_tool_id="tool-t1",
            last_sync_at=datetime(2026, 3, 15, 3, 0, 0),
            created_at=datetime(2026, 3, 4),
            updated_at=datetime(2026, 3, 4),
        )
    )
    db.flush()
    for i in range(prior):
        db.add(
            Submission(
                id=f"sub-prior-{i}",
                project_id="proj-t1",
                kobo_id=f"prior-{i}",
                form_id="f1",
                form_name="Facility",
                enumerator="Ada",
                submitted_at=datetime(2026, 3, 10, 8, 0, 0),
                status="complete",
                data={},
                created_at=datetime(2026, 3, 10, 8, 0, 0),
            )
        )
    for i in range(submissions_today):
        db.add(
            Submission(
                id=f"sub-today-{i}",
                project_id="proj-t1",
                kobo_id=f"today-{i}",
                form_id="f1",
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


def _planned_spec() -> ReportSpec:
    return ReportSpec(
        title="Today's intake",
        sections=[
            Section(
                title="Totals",
                components=[
                    MetricComponent(
                        id="totals",
                        label="Submissions today",
                        data_source="study_totals",
                        field="newToday",
                        format="int",
                    ),
                    NarrativeComponent(
                        id="headline",
                        type="insight",
                        instruction="Summarise today's intake.",
                        data_sources=["study_totals"],
                        fallback="daily_headline",
                    ),
                ],
            )
        ],
    )


def test_plan_validate_tools_analyze_render(db: Session) -> None:
    _seed(db)
    _FakeCaller.queue = [PlannerReply(status="ok", spec=_planned_spec(), summary="Intake.")]
    with patch("app.services.report_planner.graph._ModelCaller", _FakeCaller):
        planned = plan_spec(db, instructions="today's submissions")
    assert planned.ok

    executed = execute_spec(
        db,
        planned.spec,
        ReportExecutionContext(
            report_kind="daily",
            study_id=STUDY_ID,
            execution_date=REPORT_DATE,
            timezone=TZ,
        ),
        run_ai=False,
    )
    html = executed.render_html()
    assert executed.errors == {}
    assert executed.data["study_totals"]["newToday"] == 8
    assert executed.data["study_totals"]["cumulative"] == 120
    assert "8" in html
    assert "8 new submission(s)" in html
    assert executed.narratives.source == "fallback"
    assert "8 new submission(s)" in html
    assert executed.render_pdf().startswith(b"%PDF")
    assert executed.render_docx().startswith(b"PK")


def test_template_round_trip_persists_the_same_spec(db: Session) -> None:
    study = _seed(db)
    spec = _planned_spec()
    template, version = create_template(
        db, name="Intake", spec=spec, prompt_text="today's submissions", report_kind="daily"
    )
    executed, loaded = execute_template(
        db,
        template,
        ReportExecutionContext(
            report_kind="daily",
            study_id=study.id,
            execution_date=REPORT_DATE,
            timezone=TZ,
        ),
        run_ai=False,
    )
    assert loaded.id == version.id
    assert executed.spec.title == spec.title
    assert executed.data["study_totals"]["cumulative"] == 120


def test_generate_final_dqa_report_executes_the_seeded_template(db: Session) -> None:
    study = _seed(db, submissions_today=0, prior=2)
    seed_report_templates(db)
    report = generate_final_dqa_report(db, study_id=study.id, run_ai=False)
    assert report.report_type == "final_dqa"
    assert report.template_id == FINAL_TEMPLATE_ID
    assert report.status == "ready"
