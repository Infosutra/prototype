"""Phase 4 DQA authoring and operations tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Project, Study, StudyTool, Submission
from app.domain.dqa.debug_trace import build_debug_trace
from app.domain.dqa.eval import eval_check
from app.domain.dqa.explain import explain_evaluation
from app.domain.dqa.rule_diff import compute_rule_diff
from app.domain.dqa.rule_management import active_rules, rule_enabled, set_rule_status
from app.services.dqa_test import run_rule_test


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
    )
    db.add(project)
    db.commit()
    return project


def test_explain_numeric_compare():
    check = {"op": "gt", "field": "B22", "field_b": "B21"}
    passes, details = eval_check(
        check,
        data={"B22": "14", "B21": "10"},
        pack={"fields": {"B22": "B22", "B21": "B21"}},
    )
    explanation = explain_evaluation(check=check, details=details, passes=passes)
    assert explanation["would_flag"] is False
    assert any("B22" in line or "14" in line for line in explanation["lines"])


def test_rule_diff_detects_threshold_change():
    before = {"check": {"op": "gt", "field": "score", "value": 75}}
    after = {"check": {"op": "gt", "field": "score", "value": 80}}
    diff = compute_rule_diff(before, after)
    assert diff["change_count"] >= 1


def test_active_rules_skips_disabled_and_draft():
    rules = [
        {"id": "A", "status": "active", "enabled": True, "check": {"op": "required", "field": "x"}},
        {"id": "B", "status": "draft", "check": {"op": "required", "field": "y"}},
        {"id": "C", "enabled": False, "check": {"op": "required", "field": "z"}},
    ]
    active = active_rules(rules)
    assert [r["id"] for r in active] == ["A"]


def test_set_rule_status_activate():
    rule = {"id": "R1", "check": {"op": "required", "field": "A1"}}
    activated = set_rule_status(rule, "active")
    assert activated["status"] == "active"
    assert activated["enabled"] is True
    assert activated["meta"]["audit"]["approved"] is True


def test_test_rule_workspace(db: Session):
    project = _seed(db)
    db.add(
        Submission(
            id="sub1",
            project_id=project.id,
            kobo_id="k1",
            form_id="u1",
            form_name="Form",
            enumerator="E1",
            submitted_at=datetime(2026, 1, 1),
            data={"B22": "14", "B21": "10"},
        )
    )
    db.commit()
    rule = {
        "id": "R1",
        "severity": "amber",
        "title": "Compare",
        "message": "B22 gt B21",
        "check": {"op": "gt", "field": "B22", "field_b": "B21"},
    }
    result = run_rule_test(db, project.id, rule, limit=10)
    assert result["submissions_checked"] == 1
    assert len(result["records"]) == 1
    assert result["records"][0]["explanation"]["summary"]
    assert result["records"][0]["debug_trace"]["op"] == "gt"


def test_debug_trace_from_details():
    check = {"op": "gt", "field": "B22", "field_b": "B21"}
    _, details = eval_check(check, data={"B22": "14", "B21": "10"}, pack={})
    trace = build_debug_trace(check=check, details=details, passes=True)
    assert trace["op"] == "gt"
