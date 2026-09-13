"""Phase 0 schema baseline assertions."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db import models as models_pkg
from app.db.models import (
    AppSettings,
    Job,
    Report,
    ReportTemplate,
    Submission,
    SubmissionAnswer,
    SubmissionQuality,
)


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


def test_no_report_run_model() -> None:
    assert not hasattr(models_pkg, "ReportRun")
    assert "ReportRun" not in models_pkg.__all__
    with pytest.raises(ImportError):
        from app.db.models import ReportRun  # noqa: F401


def test_schema_baseline_columns(db: Session) -> None:
    insp = inspect(db.get_bind())

    assert "report_runs" not in insp.get_table_names()
    assert "jobs" in insp.get_table_names()
    assert "submission_answers" in insp.get_table_names()
    assert "submission_quality" in insp.get_table_names()

    job_cols = {c["name"] for c in insp.get_columns("jobs")}
    assert "result_ref" in job_cols
    assert "result" not in job_cols
    # No result JSON/Text column by any common name.
    assert not any(name in job_cols for name in ("result_json", "result_text", "payload_result"))

    template_cols = {c["name"] for c in insp.get_columns("report_templates")}
    assert "is_system" not in template_cols
    assert "study_id" in template_cols

    report_cols = {c["name"] for c in insp.get_columns("reports")}
    assert "generated_content" not in report_cols
    assert "result_ref" in report_cols

    settings_cols = {c["name"] for c in insp.get_columns("settings")}
    assert not any(c.startswith("daily_report_") for c in settings_cols)

    submission_cols = {c["name"] for c in insp.get_columns("submissions")}
    assert {"study_id", "duration_minutes", "calendar_day"} <= submission_cols

    assert hasattr(Submission, "study_id")
    assert hasattr(Submission, "duration_minutes")
    assert hasattr(Submission, "calendar_day")
    assert hasattr(Report, "result_ref")
    assert not hasattr(Report, "generated_content")
    assert not hasattr(ReportTemplate, "is_system")
    assert not hasattr(AppSettings, "daily_report_enabled")
    assert Job.__tablename__ == "jobs"
    assert SubmissionAnswer.__tablename__ == "submission_answers"
    assert SubmissionQuality.__tablename__ == "submission_quality"
