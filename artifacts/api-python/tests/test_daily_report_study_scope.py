"""Study-scoped legacy daily submission digest."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Project, Study, StudyTool, Submission
from app.services.daily_report import build_daily_report


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


def _seed(db: Session, study_id: str, project_id: str, today_count: int) -> None:
    db.add(
        Study(
            id=study_id,
            name=study_id,
            description=None,
            start_date=None,
            end_date=None,
            timezone="UTC",
        )
    )
    db.flush()
    tool = StudyTool(
        id=f"tool-{project_id}",
        study_id=study_id,
        code="T",
        label="T",
        sort_order=0,
    )
    db.add(tool)
    project = Project(
        id=project_id,
        uid=f"uid-{project_id}",
        name=project_id,
        study_id=study_id,
        study_tool_id=tool.id,
        submission_count=today_count,
    )
    db.add(project)
    for i in range(today_count):
        db.add(
            Submission(
                id=f"{project_id}-s{i}",
                project_id=project_id,
                kobo_id=f"k{i}",
                form_id=project.uid,
                form_name=project.name,
                enumerator="E1",
                submitted_at=datetime(2026, 3, 15, 8, i),
                data={"enumerator": "E1"},
            )
        )


def test_build_daily_report_excludes_other_studies(db: Session) -> None:
    _seed(db, "study-a", "pa", 2)
    _seed(db, "study-b", "pb", 7)
    db.commit()

    report = build_daily_report(
        db,
        "2026-03-15",
        "UTC",
        "Org",
        study_id="study-a",
    )
    assert report.study_id == "study-a"
    assert report.study_name == "study-a"
    assert report.grand_total == 2
    assert [p.project_name for p in report.projects] == ["pa"]
