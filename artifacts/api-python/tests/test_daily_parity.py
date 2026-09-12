"""Daily DQA template reproduces legacy sections from live tool data.

Phase 2+ tools read entity_rows, not an injected stats dict. This suite seeds
the golden study graph and asserts the same *kinds* of checks the former
sample_daily_stats inject path locked — translated to golden fixture values
(not weakened).
"""

from __future__ import annotations

import html

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Study
from app.domain.report_spec.context import ReportExecutionContext
from app.services.dqa_daily_report import generate_daily_dqa_report
from app.services.report_execution import execute_spec
from app.services.report_seed_templates import DAILY_TEMPLATE_ID, build_daily_dqa_spec, seed_report_templates
from app.services.report_templates import execute_template, resolve_template
from tests.fixtures.report_tools_golden.seed import (
    REPORT_DATE,
    STUDY_ID,
    TIMEZONE,
    seed_golden_study,
)

# Locked against fixtures/report_tools_golden/* (same categories as the old
# sample_daily_stats HEADLINE_NUMBERS list).
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
    "34",  # newToday (was 8)
    "111",  # cumulative (was 120)
    "0",  # redToday (was 2) — golden today has no RED
    "33",  # amberToday (was 3)
    "23",  # redOpen (was 5)
    "54",  # amberOpen (was 14)
    "94",  # T1 cumulative (was 45)
    "100",  # T1 target (unchanged category)
    "11",  # T2 cumulative (was 75)
    "50",  # T2 target (was 80)
    "100.0%",  # enumerator / today flag rate surface (was 66.7%)
    "Day 15",  # dayNumber (was Day 12; golden start 2026-03-01)
)


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
    study = seed_golden_study(db)
    seed_report_templates(db)
    db.commit()
    return study


def _context() -> ReportExecutionContext:
    return ReportExecutionContext(
        report_kind="daily",
        study_id=STUDY_ID,
        execution_date=REPORT_DATE,
        timezone=TIMEZONE,
    )


def test_seeded_daily_template_reproduces_legacy_sections_and_numbers(db: Session) -> None:
    _seed(db)
    executed = execute_spec(
        db,
        build_daily_dqa_spec(),
        _context(),
        run_ai=False,
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

    # Tool rows, RED grouping, enumerator, amber rule, and sign-off (translated).
    assert "T1" in visible and "T2" in visible
    assert "Prior red 00" in visible  # was "Missing GPS" (RED rule title)
    assert "AmberOnly" in visible  # was "Ada"
    assert "Field supervisor" in visible
    assert "Today rule TODAY_R00" in visible  # was "Skip residue" (AMBER rule title)
    assert executed.errors == {}

    # Fallback narratives from live tool data (translated fixture copy).
    assert "34 new submission(s)" in visible
    assert "0 RED" in visible
    assert "T1 94/100" in visible
    assert "T2 11/50" in visible
    assert "Coverage —" in visible

    # Charts are application-rendered images, not model output.
    assert markup.count("data:image/png;base64,") >= 4

    # Same fixture through the stored template, not a hand-built spec.
    template = resolve_template(db, db.get(Study, STUDY_ID), "daily")
    assert template is not None
    assert template.id == DAILY_TEMPLATE_ID
    via_template, version = execute_template(
        db, template, _context(), run_ai=False
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
