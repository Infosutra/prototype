"""DQA filter and flag summaries on the submissions list."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import DqaFlag, Project, Study, StudyTool, Submission
from app.routers.submissions import list_submissions
from app.schemas.common import SubmissionsListQuery


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


def _seed(db: Session) -> str:
    study = Study(id="s1", name="S", description=None, start_date=None, end_date=None, timezone="UTC")
    db.add(study)
    tool = StudyTool(id="t1", study_id=study.id, code="T1", label="T", sort_order=0)
    db.add(tool)
    project = Project(id="p1", uid="u1", name="Form", study_id=study.id, study_tool_id=tool.id)
    db.add(project)
    now = datetime(2026, 9, 1, 12, 0, 0)
    for index, status in enumerate(["clean", "red", "amber"], start=1):
        db.add(
            Submission(
                id=f"sub-{status}",
                project_id=project.id,
                kobo_id=str(index),
                form_id="form",
                form_name="Form",
                enumerator="enum",
                status="pending",
                submitted_at=now,
                data={},
            )
        )
    db.add(
        DqaFlag(
            id="f-red",
            submission_id="sub-red",
            project_id="p1",
            rule_id="R1",
            severity="red",
            title="Missing GPS",
            message="No GPS",
        )
    )
    db.add(
        DqaFlag(
            id="f-amber",
            submission_id="sub-amber",
            project_id="p1",
            rule_id="A1",
            severity="amber",
            title="Short session",
            message="Too short",
        )
    )
    db.commit()
    return project.id


def test_list_includes_dqa_summary(db: Session):
    project_id = _seed(db)
    page = list_submissions(SubmissionsListQuery(project_id=project_id, page=1, limit=20), db)
    by_id = {row.id: row for row in page.data}
    assert page.total == 3
    assert by_id["sub-clean"].dqa_severity is None
    assert by_id["sub-clean"].red_flags == 0
    assert by_id["sub-red"].dqa_severity == "red"
    assert by_id["sub-red"].red_flags == 1
    assert by_id["sub-amber"].dqa_severity == "amber"
    assert by_id["sub-amber"].amber_flags == 1


def test_list_filters_by_dqa(db: Session):
    project_id = _seed(db)
    red = list_submissions(
        SubmissionsListQuery(project_id=project_id, dqa="red", page=1, limit=20), db
    )
    assert [row.id for row in red.data] == ["sub-red"]
    clean = list_submissions(
        SubmissionsListQuery(project_id=project_id, dqa="clean", page=1, limit=20), db
    )
    assert [row.id for row in clean.data] == ["sub-clean"]
    flagged = list_submissions(
        SubmissionsListQuery(project_id=project_id, dqa="flagged", page=1, limit=20), db
    )
    assert {row.id for row in flagged.data} == {"sub-red", "sub-amber"}
