"""Tests for DQA compile orchestration (mocked LLM)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings, Project, Study, StudyTool
from app.integrations.llm.types import CompletionResult, TokenUsage
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


def _mock_completion(payload: dict) -> CompletionResult:
    return CompletionResult(
        text=json.dumps(payload),
        model="test-model",
        provider="openrouter",
        latency_ms=1.0,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def test_compile_needs_clarification(db: Session):
    project = _seed_project(db)
    settings = db.get(AppSettings, "singleton")
    payload = {
        "clarifying_question": "Which two fields should be compared?",
        "rule": None,
        "explanation": None,
    }
    with patch(
        "app.services.dqa_compile.chat_completion_detailed",
        return_value=_mock_completion(payload),
    ):
        result = compile_dqa_rule(
            db,
            project,
            english="Compare participation counts",
            settings=settings,
        )
    assert result["status"] == "needs_clarification"
    assert "fields" in result["question"].lower() or "field" in result["question"].lower()
    assert result.get("session_id")


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
    with patch(
        "app.services.dqa_compile.chat_completion_detailed",
        return_value=_mock_completion(payload),
    ):
        result = compile_dqa_rule(
            db,
            project,
            english="Flag when B22 is greater than B21",
            settings=settings,
        )
    assert result["status"] == "success"
    assert result["rule"]["check"]["op"] == "gt"
    assert result["preview"]["submissions_checked"] == 0
    assert result["meta"]["prompt_tokens"] == 10


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
        "app.services.dqa_compile.chat_completion_detailed",
        return_value=_mock_completion(payload),
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


def test_resolve_compile_home_picks_form_that_owns_fields(db: Session) -> None:
    from app.services.dqa_compile import resolve_compile_home

    host = _seed_project(db)
    other = Project(
        id="proj-2",
        uid="uid-2",
        name="Interview",
        study_id=host.study_id,
        form_definition={
            "survey": [
                {"type": "text", "name": "D4", "label": "Centre id"},
            ],
            "choices": [],
        },
    )
    db.add(other)
    db.commit()

    home = resolve_compile_home(
        db,
        host,
        {"check": {"op": "required", "field": "D4"}},
        [],
    )
    assert home.id == "proj-2"


def test_normalize_related_field_sibling_to_field_b() -> None:
    from app.services.dqa_compile import _finalize_rule

    rule = _finalize_rule(
        {
            "severity": "amber",
            "title": "Cross",
            "message": "T1 A5 > T2 D3",
            "check": {
                "op": "gt",
                "field": "A5",
                "related_field": {
                    "type": "related_field",
                    "relationship": "t1_to_t2",
                    "field": "D3",
                },
            },
        },
        english="T1 A5 > T2 D3",
        existing_rule=None,
    )
    assert "related_field" not in rule["check"]
    assert rule["check"]["field_b"] == {
        "type": "related_field",
        "relationship": "t1_to_t2",
        "field": "D3",
    }


def test_resolve_compile_home_prefers_tool_code_in_english(db: Session) -> None:
    from app.services.dqa_compile import resolve_compile_home

    host = _seed_project(db)
    t2 = StudyTool(id="tool-2", study_id=host.study_id, code="T2", label="Tool 2", sort_order=1)
    db.add(t2)
    other = Project(
        id="proj-2",
        uid="uid-2",
        name="Interview",
        study_id=host.study_id,
        study_tool_id=t2.id,
        form_definition={
            "survey": [{"type": "integer", "name": "D3", "label": "Books"}],
            "choices": [],
        },
    )
    db.add(other)
    db.commit()
    db.refresh(host)

    home = resolve_compile_home(
        db,
        other,
        {"check": {"op": "gt", "field": "B21", "field_b": "B22"}},
        [],
        english="T1 form's B21 should always be greater than T2 D3",
    )
    assert home.id == host.id
