"""Tests for DQA compile orchestration (mocked LLM)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings, Project, Study, StudyTool
from app.services.dqa_compile import compile_dqa_rule


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


def _seed_project(db: Session) -> Project:
    study = Study(id="study-1", name="Study", description=None, start_date=None, end_date=None, timezone="UTC")
    db.add(study)
    tool = StudyTool(id="tool-1", study_id=study.id, code="T1", label="Tool", sort_order=0)
    db.add(tool)
    project = Project(
        id="proj-1",
        uid="uid-1",
        name="Form",
        study_id=study.id,
        study_tool_id=tool.id,
        form_definition={
            "survey": [
                {"type": "integer", "name": "B21", "label": "At 15 min"},
                {"type": "integer", "name": "B22", "label": "At 45 min"},
            ],
            "choices": [],
        },
    )
    db.add(project)
    settings = AppSettings(
        id="singleton",
        ai_enabled=True,
        ai_api_key="sk-test",
        ai_model="test-model",
    )
    db.add(settings)
    db.commit()
    return project


def test_compile_needs_clarification(db: Session):
    project = _seed_project(db)
    settings = db.get(AppSettings, "singleton")
    payload = {
        "clarifying_question": "Which two fields should be compared?",
        "rule": None,
        "explanation": None,
    }
    with patch("app.services.dqa_compile.chat_completion", return_value=__import__("json").dumps(payload)):
        result = compile_dqa_rule(
            db,
            project,
            english="Compare participation counts",
            settings=settings,
        )
    assert result["status"] == "needs_clarification"
    assert "fields" in result["question"].lower() or "field" in result["question"].lower()


def test_compile_success_with_valid_rule(db: Session):
    project = _seed_project(db)
    settings = db.get(AppSettings, "singleton")
    payload = {
        "clarifying_question": None,
        "rule": {
            "severity": "amber",
            "title": "Participation compare",
            "message": "B22 greater than B21",
            "check": {"op": "gt", "field": "B22", "field_b": "B21"},
        },
        "explanation": "Flags when B22 exceeds B21.",
    }
    with patch("app.services.dqa_compile.chat_completion", return_value=__import__("json").dumps(payload)):
        result = compile_dqa_rule(
            db,
            project,
            english="Flag when B22 is greater than B21",
            settings=settings,
        )
    assert result["status"] == "success"
    assert result["rule"]["check"]["op"] == "gt"
    assert result["preview"]["submissions_checked"] == 0


def test_compile_invalid_after_repair_exhausted(db: Session):
    project = _seed_project(db)
    settings = db.get(AppSettings, "singleton")
    payload = {
        "clarifying_question": None,
        "rule": {
            "severity": "amber",
            "title": "Bad",
            "message": "Unknown field",
            "check": {"op": "required", "field": "NOPE"},
        },
        "explanation": "bad",
    }
    with patch(
        "app.services.dqa_compile.chat_completion",
        return_value=__import__("json").dumps(payload),
    ) as mocked:
        result = compile_dqa_rule(
            db,
            project,
            english="Require NOPE",
            settings=settings,
        )
        assert mocked.call_count == 3
    assert result["status"] == "invalid"
    assert result["validation"]["valid"] is False
