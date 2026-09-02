"""Phase 4 end-to-end DQA authoring and operations flow (deterministic paths)."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    AppSettings,
    DqaRelationship,
    Project,
    RulePack,
    Study,
    StudyTool,
    Submission,
)
from app.domain.dqa.operands import related_field_ref
from app.domain.dqa.rule_diff import compute_rule_diff
from app.domain.dqa.rule_management import active_rules, set_rule_status
from app.integrations.llm.types import CompletionResult, TokenUsage
from app.services.dqa_compile import compile_dqa_rule, validate_dqa_rule_for_project
from app.services.dqa_evaluation import evaluate_project
from app.services.dqa_test import explain_flag, run_rule_test


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


def _mock_completion(payload: dict) -> CompletionResult:
    return CompletionResult(
        text=json.dumps(payload),
        model="test-model",
        provider="openrouter",
        latency_ms=1.0,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _seed_intra_form(db: Session) -> tuple[Project, AppSettings]:
    study = Study(id="s-e2e", name="E2E", description=None, start_date=None, end_date=None, timezone="UTC")
    db.add(study)
    tool = StudyTool(id="t-e2e", study_id=study.id, code="T", label="T", sort_order=0)
    db.add(tool)
    project = Project(
        id="p-e2e",
        uid="u-e2e",
        name="Assessment",
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
    settings = AppSettings(id="singleton", ai_enabled=True, ai_api_key="sk-test", ai_model="test-model")
    db.add(settings)
    db.add(
        Submission(
            id="sub-pass",
            project_id=project.id,
            kobo_id="k-pass",
            form_id="u-e2e",
            form_name="Assessment",
            enumerator="E1",
            submitted_at=datetime(2026, 1, 1),
            data={"B22": "8", "B21": "10"},
        )
    )
    db.add(
        Submission(
            id="sub-fail",
            project_id=project.id,
            kobo_id="k-fail",
            form_id="u-e2e",
            form_name="Assessment",
            enumerator="E2",
            submitted_at=datetime(2026, 1, 2),
            data={"B22": "14", "B21": "10"},
        )
    )
    db.commit()
    return project, settings


def _seed_inter_form(db: Session) -> tuple[Project, AppSettings]:
    study = Study(id="s-if-e2e", name="IF", description=None, start_date=None, end_date=None, timezone="UTC")
    db.add(study)
    assess_tool = StudyTool(id="ta", study_id=study.id, code="A", label="Assessment", sort_order=0)
    enroll_tool = StudyTool(id="te", study_id=study.id, code="E", label="Enrollment", sort_order=1)
    db.add_all([assess_tool, enroll_tool])
    assess = Project(
        id="p-assess-e2e",
        uid="u-assess",
        name="Assessment",
        study_id=study.id,
        study_tool_id=assess_tool.id,
        form_definition={
            "survey": [
                {"type": "text", "name": "student_id", "label": "Student"},
                {"type": "date", "name": "assessment_date", "label": "Assessment date"},
            ],
            "choices": [],
        },
    )
    enroll = Project(
        id="p-enroll-e2e",
        uid="u-enroll",
        name="Enrollment",
        study_id=study.id,
        study_tool_id=enroll_tool.id,
        form_definition={
            "survey": [
                {"type": "text", "name": "student_id", "label": "Student"},
                {"type": "date", "name": "enrollment_date", "label": "Enrollment date"},
            ],
            "choices": [],
        },
    )
    db.add_all([assess, enroll])
    db.add(
        DqaRelationship(
            id="rel-e2e",
            study_id=study.id,
            code="student_enrollment",
            title="Student enrollment",
            source_project_id=assess.id,
            target_project_id=enroll.id,
            source_join_field="student_id",
            target_join_field="student_id",
            cardinality="one",
        )
    )
    db.add(
        RulePack(
            project_id=enroll.id,
            pack={"fields": {"student_id": "student_id", "enrollment_date": "enrollment_date"}, "rules": []},
        )
    )
    db.add(
        RulePack(
            project_id=assess.id,
            pack={"fields": {"student_id": "student_id", "assessment_date": "assessment_date"}},
        )
    )
    db.add(
        Submission(
            id="enroll-1",
            project_id=enroll.id,
            kobo_id="ke1",
            form_id="u-enroll",
            form_name="Enrollment",
            enumerator="E1",
            submitted_at=datetime(2026, 1, 1),
            data={"student_id": "S1", "enrollment_date": "2026-01-10"},
        )
    )
    db.add(
        Submission(
            id="assess-1",
            project_id=assess.id,
            kobo_id="ka1",
            form_id="u-assess",
            form_name="Assessment",
            enumerator="E1",
            submitted_at=datetime(2026, 1, 5),
            data={"student_id": "S1", "assessment_date": "2026-01-05"},
        )
    )
    settings = AppSettings(id="singleton", ai_enabled=True, ai_api_key="sk-test", ai_model="test-model")
    db.add(settings)
    db.commit()
    return assess, settings


def test_e2e_intra_form_author_compile_validate_test_activate_evaluate_explain(db: Session):
    project, settings = _seed_intra_form(db)

    clarify = {
        "clarifying_question": "Should B22 be greater than B21?",
        "rule": None,
        "explanation": None,
    }
    with patch("app.services.dqa_compile.chat_completion_detailed", return_value=_mock_completion(clarify)):
        clarify_result = compile_dqa_rule(
            db,
            project,
            english="Flag when participation at 45 min exceeds 15 min",
            settings=settings,
        )
    assert clarify_result["status"] == "needs_clarification"

    compiled_rule = {
        "id": "R-E2E-1",
        "severity": "amber",
        "title": "Participation compare",
        "message": "B22 greater than B21",
        "check": {"op": "gt", "field": "B22", "field_b": "B21"},
    }
    success = {
        "clarifying_question": None,
        "rule": compiled_rule,
        "explanation": "Flags when B22 exceeds B21.",
    }
    with patch("app.services.dqa_compile.chat_completion_detailed", return_value=_mock_completion(success)):
        compile_result = compile_dqa_rule(
            db,
            project,
            english="Yes, flag when B22 is greater than B21",
            conversation=[{"role": "user", "content": "Flag when participation at 45 min exceeds 15 min"}],
            settings=settings,
        )
    assert compile_result["status"] == "success"
    rule = compile_result["rule"]
    assert compile_result["validation"]["valid"] is True
    assert compile_result["preview"]["submissions_checked"] == 2

    validate_result = validate_dqa_rule_for_project(db, project, rule)
    assert validate_result["status"] == "success"
    assert validate_result["test"]["submissions_checked"] == 2
    assert validate_result["test"]["flag_count"] == 1

    draft = set_rule_status(rule, "draft")
    assert draft["status"] == "draft"
    assert active_rules([draft]) == []

    activated = set_rule_status(draft, "active")
    diff = compute_rule_diff(rule, {**rule, "check": {"op": "gt", "field": "B22", "field_b": "B21", "value": 80}})
    assert diff["change_count"] >= 0

    edit_payload = {
        "clarifying_question": None,
        "rule": {
            **compiled_rule,
            "message": "B22 greater than 80",
            "check": {"op": "gt", "field": "B22", "value": 80},
        },
        "explanation": "Threshold raised to 80.",
    }
    with patch(
        "app.services.dqa_compile.chat_completion_detailed",
        return_value=_mock_completion(edit_payload),
    ):
        edit_result = compile_dqa_rule(
            db,
            project,
            english="Change the threshold from 75% to 80%.",
            existing_rule=rule,
            settings=settings,
        )
    assert edit_result["status"] == "success"
    assert edit_result.get("diff", {}).get("change_count", 0) >= 1

    test = run_rule_test(db, project.id, activated, limit=10)
    assert test["pass_count"] == 1
    assert test["flag_count"] == 1
    failing = next(r for r in test["records"] if r["outcome"] == "fail")
    explained = explain_flag(rule=activated, details=failing["details"], passes=False)
    assert explained["explanation"]["would_flag"] is True
    assert explained["debug_trace"]["op"] == "gt"

    pack = {"rules": [activated], "fields": {"B21": "B21", "B22": "B22"}}
    db.add(RulePack(project_id=project.id, pack=pack))
    db.commit()
    flags = evaluate_project(db, project.id)
    assert flags["flags"] >= 1


def test_e2e_inter_form_validate_test_explain(db: Session):
    project, _settings = _seed_inter_form(db)
    rule = {
        "id": "IF-E2E",
        "severity": "red",
        "title": "Assessment before enrollment",
        "message": "Assessment date precedes enrollment",
        "check": {
            "op": "lt",
            "field": "assessment_date",
            "field_b": related_field_ref("student_enrollment", "enrollment_date"),
        },
    }

    validate_result = validate_dqa_rule_for_project(db, project, rule)
    assert validate_result["status"] == "success"
    test = validate_result["test"]
    assert test["submissions_checked"] == 1
    record = test["records"][0]
    assert record["related"]
    assert record["explanation"]["summary"]
    explained = explain_flag(rule=rule, details=record["details"], passes=record["outcome"] == "pass")
    assert explained["debug_trace"]

    activated = set_rule_status(rule, "active")
    pack = RulePack(
        project_id=project.id,
        pack={
            "fields": {"student_id": "student_id", "assessment_date": "assessment_date"},
            "rules": [activated],
        },
    )
    db.merge(pack)
    db.commit()
    result = evaluate_project(db, project.id)
    assert result["submissions"] == 1
    assert result["metrics"]["rules_evaluated"] == 1
