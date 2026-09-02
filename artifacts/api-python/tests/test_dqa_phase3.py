"""Phase 3 production hardening tests."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings, DqaCompileSession, DqaFlag, Project, RulePackVersion, Study, StudyTool, Submission, UsageEvent
from app.domain.dqa.rule_audit import attach_compile_audit, sanitize_english
from app.integrations.llm.types import CompletionResult, TokenUsage
from app.services.dqa_compile import compile_dqa_rule
from app.services.dqa_evaluation import evaluate_project, evaluate_submission, stable_flag_id
from app.services.dqa_rule_packs import get_pack_version, list_pack_versions, save_pack


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


def _seed(db: Session) -> Project:
    study = Study(id="s1", name="S", description=None, start_date=None, end_date=None, timezone="UTC")
    db.add(study)
    tool = StudyTool(id="t1", study_id=study.id, code="T", label="T", sort_order=0)
    db.add(tool)
    project = Project(
        id="p1",
        uid="u1",
        name="Form",
        study_id=study.id,
        study_tool_id=tool.id,
        form_definition={"survey": [{"type": "text", "name": "A1", "label": "A1"}], "choices": []},
    )
    db.add(project)
    db.add(AppSettings(id="singleton", ai_enabled=True, ai_api_key="sk-test", ai_model="test"))
    db.commit()
    return project


def test_sanitize_english_truncates():
    assert len(sanitize_english("x" * 5000)) <= 4000


def test_rule_pack_versioning_on_save(db: Session):
    project = _seed(db)
    save_pack(
        db,
        project.id,
        {"fields": {}, "thresholds": {}, "rules": [{"id": "R1", "severity": "amber", "title": "t", "message": "m", "check": {"op": "required", "field": "A1"}}]},
    )
    save_pack(
        db,
        project.id,
        {"fields": {}, "thresholds": {}, "rules": [{"id": "R1", "severity": "red", "title": "t2", "message": "m2", "check": {"op": "required", "field": "A1"}}]},
    )
    assert get_pack_version(db, project.id) == 2
    versions = list_pack_versions(db, project.id)
    assert len(versions) == 2
    assert versions[0].status == "active"
    assert versions[1].status == "superseded"


def test_stable_flag_id_is_idempotent(db: Session):
    project = _seed(db)
    pack = {
        "fields": {"f": "A1"},
        "rules": [{"id": "R1", "severity": "amber", "title": "t", "message": "m", "check": {"op": "required", "field": "f"}}],
    }
    save_pack(db, project.id, pack)
    sub = Submission(
        id="sub1",
        project_id=project.id,
        kobo_id="k1",
        form_id="u1",
        form_name="Form",
        enumerator="E1",
        submitted_at=datetime(2026, 1, 1),
        data={},
    )
    db.add(sub)
    db.commit()
    evaluate_submission(db, sub, commit=True)
    evaluate_submission(db, sub, commit=True)
    flags = list(db.scalars(select(DqaFlag).where(DqaFlag.submission_id == sub.id)).all())
    assert len(flags) == 1
    assert flags[0].id == stable_flag_id(sub.id, "R1")


def test_evaluate_project_returns_metrics(db: Session):
    project = _seed(db)
    save_pack(
        db,
        project.id,
        {"fields": {"f": "A1"}, "rules": [{"id": "R1", "severity": "amber", "title": "t", "message": "m", "check": {"op": "required", "field": "f"}}]},
    )
    db.add(
        Submission(
            id="sub2",
            project_id=project.id,
            kobo_id="k2",
            form_id="u1",
            form_name="Form",
            enumerator="E1",
            submitted_at=datetime(2026, 1, 1),
            data={"A1": "x"},
        )
    )
    db.commit()
    stats = evaluate_project(db, project.id)
    assert stats["metrics"]["submissions"] == 1
    assert stats["metrics"]["rules_evaluated"] >= 1
    assert stats["metrics"]["duration_ms"] >= 0


def test_compile_records_session_and_usage(db: Session):
    project = _seed(db)
    settings = db.get(AppSettings, "singleton")
    payload = {
        "clarifying_question": None,
        "rule": {
            "severity": "amber",
            "title": "Req",
            "message": "Need A1",
            "check": {"op": "required", "field": "A1"},
        },
        "explanation": "Requires A1",
    }
    completion = CompletionResult(
        text=__import__("json").dumps(payload),
        model="test-model",
        provider="openrouter",
        latency_ms=120.5,
        usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )
    with patch("app.services.dqa_compile.chat_completion_detailed", return_value=completion):
        result = compile_dqa_rule(
            db,
            project,
            english="Require field A1",
            settings=settings,
        )
    assert result["status"] == "success"
    assert result["session_id"]
    session = db.get(DqaCompileSession, result["session_id"])
    assert session is not None
    assert session.status == "success"
    assert session.prompt_tokens == 100
    usage = list(db.scalars(select(UsageEvent).where(UsageEvent.category == "llm")).all())
    assert len(usage) >= 1
    assert result["rule"]["meta"]["audit"]["compile_session_id"] == session.id


def test_attach_compile_audit_metadata():
    rule = attach_compile_audit(
        {"id": "R1", "severity": "amber", "title": "t", "message": "m", "check": {"op": "required", "field": "A1"}},
        english="Require A1",
        compile_session_id=str(uuid.uuid4()),
        model="m",
        provider="p",
        prompt_id="prompt-1",
        pack_version=3,
    )
    audit = rule["meta"]["audit"]
    assert audit["source"] == "compile"
    assert audit["model"] == "m"
    assert audit["human_edited"] is False
