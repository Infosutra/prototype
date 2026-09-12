"""Recompute DQA must honour study scope when studyId is provided."""

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
from app.routers.dqa import router
from app.services.dqa_rule_packs import save_pack


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


def _add_project(
    db: Session,
    *,
    study_id: str,
    project_id: str,
    uid: str,
    submissions: int,
) -> None:
    tool = StudyTool(
        id=f"tool-{project_id}",
        study_id=study_id,
        code=project_id.upper(),
        label=project_id,
        sort_order=0,
    )
    db.add(tool)
    project = Project(
        id=project_id,
        uid=uid,
        name=project_id,
        study_id=study_id,
        study_tool_id=tool.id,
        form_definition={"survey": [{"type": "text", "name": "A1", "label": "A1"}], "choices": []},
    )
    db.add(project)
    save_pack(
        db,
        project.id,
        {
            "fields": {"f": "A1"},
            "rules": [
                {
                    "id": "R1",
                    "severity": "red",
                    "title": "required",
                    "message": "need A1",
                    "check": {"op": "required", "field": "f"},
                }
            ],
        },
    )
    for i in range(submissions):
        db.add(
            Submission(
                id=f"{project_id}-sub-{i}",
                project_id=project.id,
                kobo_id=f"k-{project_id}-{i}",
                form_id=uid,
                form_name=project_id,
                enumerator="E1",
                submitted_at=datetime(2026, 1, 1),
                data={},  # missing A1 → flagged
            )
        )


def test_recompute_with_study_id_excludes_other_studies(client: TestClient, db: Session) -> None:
    db.add(Study(id="study-a", name="A", description=None, start_date=None, end_date=None, timezone="UTC"))
    db.add(Study(id="study-b", name="B", description=None, start_date=None, end_date=None, timezone="UTC"))
    db.flush()
    _add_project(db, study_id="study-a", project_id="pa", uid="ua", submissions=2)
    _add_project(db, study_id="study-b", project_id="pb", uid="ub", submissions=5)
    db.commit()

    scoped = client.post("/dqa/recompute", params={"studyId": "study-a"})
    assert scoped.status_code == 200
    body = scoped.json()
    assert body["submissions"] == 2
    assert body["flaggedSubmissions"] == 2
    assert body["flags"] == 2

    unscoped = client.post("/dqa/recompute")
    assert unscoped.status_code == 400


def test_recompute_unknown_study_returns_404(client: TestClient) -> None:
    response = client.post("/dqa/recompute", params={"studyId": "missing"})
    assert response.status_code == 404
