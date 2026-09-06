"""Daily DQA template reproduces the legacy report's sections and headline numbers."""

from __future__ import annotations

import html
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings, Study
from app.domain.report_spec.context import ReportExecutionContext
from app.services.dqa_daily_report import generate_daily_dqa_report
from app.services.report_execution import execute_spec
from app.services.report_seed_templates import DAILY_TEMPLATE_ID, build_daily_dqa_spec, seed_report_templates
from app.services.report_templates import execute_template, resolve_template
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


def _seed(db: Session) -> Study:
    db.add(AppSettings(id="settings", organization_name="Infosutra Test Org", ai_enabled=False))
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
    seed_report_templates(db)
    return study


def _context() -> ReportExecutionContext:
    return ReportExecutionContext(
        report_kind="daily",
        study_id=STUDY_ID,
        execution_date=REPORT_DATE,
        timezone="Asia/Kolkata",
    )


# Headline numbers and section titles the legacy Daily report always surfaces.
# HTML escapes `&`; plaintext keeps the authored title.
LEGACY_SECTIONS = (
    "Today at a glance",
    "1.1 Today's intake",
    "1.2 RED items to correct or back-check",
    "1.3 Enumerators to back-check tomorrow",
    "1.4 Coverage",
    "1.5 Submission quality by enumerator",
    "Sign-off checklist (read-only)",
)

HEADLINE_NUMBERS = (
    "8",  # newToday
    "120",  # cumulative
    "2",  # redToday / red grouped count
    "3",  # amberToday
    "5",  # redOpen
    "14",  # amberOpen
    "45",  # T1 cumulative
    "100",  # T1 target
    "75",  # T2 cumulative
    "80",  # T2 target
    "66.7%",  # Ada flag rate / T1 flagged today
    "Day 12",
)


def test_seeded_daily_template_reproduces_legacy_sections_and_numbers(db: Session) -> None:
    study = _seed(db)
    stats = _load("sample_daily_stats.json")
    executed = execute_spec(
        db,
        build_daily_dqa_spec(),
        _context(),
        run_ai=False,
        stats=stats,
    )
    markup = executed.render_html()
    visible = html.unescape(markup)
    text = executed.render_plaintext()

    for title in LEGACY_SECTIONS:
        assert title in visible, f"missing section in HTML: {title}"
        assert title in text, f"missing section in plaintext: {title}"

    for token in HEADLINE_NUMBERS:
        assert token in visible, f"missing headline number {token!r} in HTML"
        assert token in text, f"missing headline number {token!r} in plaintext"

    # Tool rows, RED grouping, enumerator, and sign-off from the fixture.
    assert "T1" in visible and "T2" in visible
    assert "Missing GPS" in visible
    assert "Ada" in visible
    assert "Field supervisor" in visible
    assert "Skip residue" in visible
    assert executed.errors == {}

    # Fallback narratives reuse the same deterministic copy as the legacy path.
    assert "8 new submission(s)" in visible
    assert "2 RED" in visible
    assert "T1 45/100" in visible
    assert "Coverage —" in visible

    # Charts are application-rendered images, not model output.
    assert markup.count("data:image/png;base64,") >= 4

    # Same fixture through the stored template, not a hand-built spec.
    template = resolve_template(db, study, "daily")
    assert template is not None
    assert template.id == DAILY_TEMPLATE_ID
    via_template, version = execute_template(
        db, template, _context(), run_ai=False, stats=stats
    )
    assert version.template_id == DAILY_TEMPLATE_ID
    assert via_template.render_html() == markup


def test_generate_daily_dqa_report_executes_the_seeded_template(db: Session) -> None:
    _seed(db)
    report = generate_daily_dqa_report(
        db, study_id=STUDY_ID, report_date=REPORT_DATE, run_ai=False
    )
    assert report.report_type == "daily_dqa"
    assert report.template_id == DAILY_TEMPLATE_ID
    assert report.template_version_id
    assert report.spec_json
    assert report.execution_context_json
    assert report.execution_context_json["executionDate"] == REPORT_DATE
    assert report.status == "ready"
