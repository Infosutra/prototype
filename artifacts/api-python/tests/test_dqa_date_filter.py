"""DQA dashboard endpoints honour optional submitted_at date windows."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import DqaFlag, Project, Study, StudyTool, Submission
from app.db.session import get_db
from app.routers.dqa import router


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


def _seed(db: Session) -> None:
    db.add(
        Study(
            id="study-a",
            name="Study A",
            description=None,
            start_date=None,
            end_date=None,
            timezone="UTC",
        )
    )
    db.flush()
    tool = StudyTool(
        id="tool-a",
        study_id="study-a",
        code="A",
        label="A",
        sort_order=0,
    )
    db.add(tool)
    db.add(
        Project(
            id="proj-a",
            uid="uid-a",
            name="Form A",
            study_id="study-a",
            study_tool_id=tool.id,
        )
    )
    early = Submission(
        id="sub-early",
        project_id="proj-a",
        kobo_id="k1",
        form_id="uid-a",
        form_name="Form A",
        enumerator="E1",
        submitted_at=datetime(2026, 3, 1, 10, 0, 0),
        data={},
    )
    late = Submission(
        id="sub-late",
        project_id="proj-a",
        kobo_id="k2",
        form_id="uid-a",
        form_name="Form A",
        enumerator="E2",
        submitted_at=datetime(2026, 3, 15, 14, 30, 0),
        data={},
    )
    db.add_all([early, late])
    db.add_all(
        [
            DqaFlag(
                id="flag-early",
                project_id="proj-a",
                submission_id="sub-early",
                rule_id="r1",
                title="Early rule",
                message="early",
                severity="amber",
                details={"op": "required"},
                evaluated_at=datetime(2026, 3, 1, 11, 0, 0),
            ),
            DqaFlag(
                id="flag-late",
                project_id="proj-a",
                submission_id="sub-late",
                rule_id="r1",
                title="Late rule",
                message="late",
                severity="red",
                details={"op": "required"},
                evaluated_at=datetime(2026, 3, 15, 15, 0, 0),
            ),
        ]
    )
    db.commit()


def test_summary_defaults_to_all_dates(client: TestClient, db: Session) -> None:
    _seed(db)
    response = client.get("/dqa/summary", params={"studyId": "study-a"})
    assert response.status_code == 200
    body = response.json()
    assert body["totalSubmissions"] == 2
    assert body["flaggedSubmissions"] == 2
    assert body["redFlags"] == 1
    assert body["amberFlags"] == 1


def test_summary_filters_by_date_range(client: TestClient, db: Session) -> None:
    _seed(db)
    response = client.get(
        "/dqa/summary",
        params={"studyId": "study-a", "dateFrom": "2026-03-10", "dateTo": "2026-03-20"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["totalSubmissions"] == 1
    assert body["flaggedSubmissions"] == 1
    assert body["redFlags"] == 1
    assert body["amberFlags"] == 0


def test_flags_filter_by_date_range(client: TestClient, db: Session) -> None:
    _seed(db)
    all_flags = client.get("/dqa/flags", params={"studyId": "study-a"})
    assert all_flags.status_code == 200
    assert len(all_flags.json()) == 2

    window = client.get(
        "/dqa/flags",
        params={"studyId": "study-a", "dateFrom": "2026-03-01", "dateTo": "2026-03-05"},
    )
    assert window.status_code == 200
    rows = window.json()
    assert len(rows) == 1
    assert rows[0]["submissionId"] == "sub-early"


def test_enumerators_filter_by_date_range(client: TestClient, db: Session) -> None:
    _seed(db)
    response = client.get(
        "/dqa/enumerators",
        params={"studyId": "study-a", "dateFrom": "2026-03-10"},
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["enumerator"] == "E2"
    assert rows[0]["submissions"] == 1
