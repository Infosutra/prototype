"""System prompt protection and revert-to-seed behaviour."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Prompt
from app.db.session import get_db
from app.routers.prompts import router
from app.services.dqa_report_prompts import (
    DAILY_DQA_PROMPT_ID,
    DEFAULT_DAILY_DQA_PROMPT,
    SYSTEM_PROMPT_IDS,
    revert_system_prompt,
    seed_dqa_report_prompts,
)
from app.services.report_analyst import DEFAULT_ANALYST_PROMPT, REPORT_ANALYST_PROMPT_ID
from app.services.report_planner_prompts import (
    DEFAULT_PLANNER_PROMPT,
    REPORT_PLANNER_PROMPT_ID,
    seed_report_ai_prompts,
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


def test_planner_and_analyst_are_system_prompts() -> None:
    assert REPORT_PLANNER_PROMPT_ID in SYSTEM_PROMPT_IDS
    assert REPORT_ANALYST_PROMPT_ID in SYSTEM_PROMPT_IDS


def test_system_prompts_cannot_be_deleted(client: TestClient, db: Session) -> None:
    seed_report_ai_prompts(db)
    seed_dqa_report_prompts(db)
    for prompt_id in (
        REPORT_PLANNER_PROMPT_ID,
        REPORT_ANALYST_PROMPT_ID,
        DAILY_DQA_PROMPT_ID,
    ):
        response = client.delete(f"/prompts/{prompt_id}")
        assert response.status_code == 400
        assert db.get(Prompt, prompt_id) is not None


def test_system_prompts_can_be_updated(client: TestClient, db: Session) -> None:
    seed_report_ai_prompts(db)
    response = client.put(
        f"/prompts/{REPORT_PLANNER_PROMPT_ID}",
        json={"content": "Custom planner instructions for this deployment."},
    )
    assert response.status_code == 200
    assert response.json()["content"] == "Custom planner instructions for this deployment."
    assert response.json()["isSystem"] is True


def test_revert_restores_planner_and_analyst_defaults(client: TestClient, db: Session) -> None:
    seed_report_ai_prompts(db)
    client.put(
        f"/prompts/{REPORT_PLANNER_PROMPT_ID}",
        json={"content": "Edited planner prompt.", "name": "Edited Planner"},
    )
    client.put(
        f"/prompts/{REPORT_ANALYST_PROMPT_ID}",
        json={"content": "Edited analyst prompt."},
    )

    planner = client.post(f"/prompts/{REPORT_PLANNER_PROMPT_ID}/revert")
    assert planner.status_code == 200
    body = planner.json()
    assert body["content"] == DEFAULT_PLANNER_PROMPT
    assert body["name"] == "Report Planner"
    assert body["isSystem"] is True

    analyst = client.post(f"/prompts/{REPORT_ANALYST_PROMPT_ID}/revert")
    assert analyst.status_code == 200
    assert analyst.json()["content"] == DEFAULT_ANALYST_PROMPT


def test_revert_rejects_non_system_prompts(client: TestClient, db: Session) -> None:
    row = Prompt(
        id="custom-prompt",
        name="Custom",
        description="",
        content="Hello",
        category="general",
        project_ids=[],
    )
    db.add(row)
    db.commit()
    response = client.post("/prompts/custom-prompt/revert")
    assert response.status_code == 400


def test_revert_helper_restores_daily_seed(db: Session) -> None:
    seed_dqa_report_prompts(db)
    row = db.get(Prompt, DAILY_DQA_PROMPT_ID)
    assert row is not None
    row.content = "changed"
    db.commit()
    restored = revert_system_prompt(db, DAILY_DQA_PROMPT_ID)
    assert restored.content == DEFAULT_DAILY_DQA_PROMPT
