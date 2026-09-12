"""Study-scoped dashboard summary and activity."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Project, Study, StudyTool, Submission
from app.db.session import get_db
from app.routers.dashboard import router


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


@pytest.fixture()
def client(db: Session) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _seed_study(db: Session, study_id: str, project_id: str, submissions: int) -> None:
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
        submission_count=submissions,
        last_sync_at=datetime(2026, 3, 1, 12, 0, 0),
    )
    db.add(project)
    for i in range(submissions):
        db.add(
            Submission(
                id=f"{project_id}-s{i}",
                project_id=project_id,
                kobo_id=f"k{i}",
                form_id=project.uid,
                form_name=project.name,
                enumerator=f"E-{study_id}",
                submitted_at=datetime(2026, 3, 2, 10, i),
                data={},
            )
        )


def test_dashboard_requires_study_id(client: TestClient) -> None:
    assert client.get("/dashboard/summary").status_code == 400
    assert client.get("/dashboard/activity").status_code == 400


def test_dashboard_summary_and_activity_are_study_scoped(client: TestClient, db: Session) -> None:
    _seed_study(db, "study-a", "pa", 2)
    _seed_study(db, "study-b", "pb", 5)
    db.commit()

    summary = client.get("/dashboard/summary", params={"studyId": "study-a"})
    assert summary.status_code == 200
    body = summary.json()
    assert body["totalProjects"] == 1
    assert body["totalSubmissions"] == 2
    assert body["activeEnumerators"] == 1
    assert body["topProjects"][0]["id"] == "pa"

    activity = client.get("/dashboard/activity", params={"studyId": "study-a"})
    assert activity.status_code == 200
    assert len(activity.json()) == 2
    assert all(
        row["message"] == "E-study-a submitted pa" and row["projectName"] == "pa"
        for row in activity.json()
    )


def test_dashboard_filters_by_date_range(client: TestClient, db: Session) -> None:
    db.add(
        Study(
            id="study-a",
            name="study-a",
            description=None,
            start_date=None,
            end_date=None,
            timezone="UTC",
        )
    )
    db.flush()
    tool = StudyTool(
        id="tool-pa",
        study_id="study-a",
        code="T",
        label="T",
        sort_order=0,
    )
    db.add(tool)
    db.add(
        Project(
            id="pa",
            uid="uid-pa",
            name="pa",
            study_id="study-a",
            study_tool_id=tool.id,
            submission_count=2,
        )
    )
    db.add_all(
        [
            Submission(
                id="early",
                project_id="pa",
                kobo_id="k1",
                form_id="uid-pa",
                form_name="pa",
                enumerator="Early",
                submitted_at=datetime(2026, 3, 1, 10, 0, 0),
                data={},
            ),
            Submission(
                id="late",
                project_id="pa",
                kobo_id="k2",
                form_id="uid-pa",
                form_name="pa",
                enumerator="Late",
                submitted_at=datetime(2026, 3, 20, 10, 0, 0),
                data={},
            ),
        ]
    )
    db.commit()

    summary = client.get(
        "/dashboard/summary",
        params={"studyId": "study-a", "dateFrom": "2026-03-10", "dateTo": "2026-03-31"},
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["totalSubmissions"] == 1
    assert body["activeEnumerators"] == 1
    assert body["topProjects"][0]["submissionCount"] == 1

    activity = client.get(
        "/dashboard/activity",
        params={"studyId": "study-a", "dateFrom": "2026-03-10"},
    )
    assert activity.status_code == 200
    rows = activity.json()
    assert len(rows) == 1
    assert rows[0]["message"] == "Late submitted pa"

