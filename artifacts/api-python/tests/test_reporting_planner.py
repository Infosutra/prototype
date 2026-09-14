"""Phase 4 — plan job, linear planner, prompt seeds."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Job, Study
from app.db.session import get_db
from app.domain.reporting.validation import validate_report_spec
from app.routers import jobs as jobs_router
from app.routers.prompts import router as prompts_router
from app.routers.report_templates import router as templates_router
from app.services.jobs import worker
from app.services.reporting.planner import PlanError, plan_report
from app.services.reporting.prompt_seeds import (
    DEFAULT_PLANNER_PROMPT,
    REPORT_ANALYST_PROMPT_ID,
    REPORT_PLANNER_JUDGE_PROMPT_ID,
    REPORT_PLANNER_PROMPT_ID,
    REPORT_PLANNER_REPAIR_PROMPT_ID,
    SEED_REPORTING_PROMPTS,
    seed_reporting_prompts,
)
from tests.helpers.reporting_fixture import STUDY_ID, seed_golden_reporting

_GOLDEN = Path(__file__).parent / "fixtures" / "reporting_golden_spec.json"
_FORBIDDEN = (
    "enumerator_performance",
    "study_totals",
    "signoff_checklist",
    "query_aggregate",
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    def _enable_fk(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def golden(db: Session) -> Session:
    seed_golden_reporting(db)
    seed_reporting_prompts(db)
    return db


@pytest.fixture()
def client(db: Session) -> TestClient:
    app = FastAPI()
    app.include_router(jobs_router.router, prefix="/api")
    app.include_router(prompts_router, prefix="/api")
    app.include_router(templates_router, prefix="/api")

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _golden_spec() -> dict[str, Any]:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


def _scripted_llm(responses: list[dict[str, Any]]):
    queue = list(responses)

    def _invoke(*, system: str, user: str, purpose: str) -> dict[str, Any]:
        if not queue:
            raise AssertionError(f"Unexpected LLM call purpose={purpose}")
        return queue.pop(0)

    return _invoke


def test_mock_llm_golden_spec_validates(golden: Session) -> None:
    spec = _golden_spec()
    llm = _scripted_llm(
        [
            {"spec": spec, "unmapped": []},
            {"faithful": True, "issues": []},
        ]
    )
    result = plan_report(
        golden,
        study_id=STUDY_ID,
        instructions="Golden daily snapshot",
        llm=llm,
    )
    assert validate_report_spec(result["spec"]) == []
    assert result["unmapped"] == []
    assert result["judgement"]["faithful"] is True


def test_llm_catalog_uses_query_ir_keys(golden: Session) -> None:
    from app.services.reporting.catalog_for_llm import catalog_for_llm

    catalog = catalog_for_llm(golden, STUDY_ID)
    assert catalog["query"]["required"] == ["entity", "window"]
    submission = catalog["entities"]["submission"]
    assert "groupByFields" in submission
    assert "dimensions" not in submission
    assert "dimensions" not in catalog["entities"]["flag"]
    assert "groupBy" in catalog["query"]["properties"]


def test_slack_delivery_goes_to_unmapped(golden: Session) -> None:
    spec = _golden_spec()
    llm = _scripted_llm(
        [
            {
                "spec": spec,
                "unmapped": [
                    {
                        "userIntent": "Email the PDF to Slack",
                        "reason": "Delivery is outside ReportSpec",
                    }
                ],
            },
            {"faithful": True, "issues": []},
        ]
    )
    result = plan_report(
        golden,
        study_id=STUDY_ID,
        instructions="Show today's KPIs and email the PDF to Slack",
        llm=llm,
    )
    assert len(result["unmapped"]) == 1
    blob = json.dumps(result["spec"]).lower()
    assert "slack" not in blob


def test_invalid_then_repair_still_invalid_fails(golden: Session) -> None:
    bad = {"specVersion": "1.0", "title": "Bad", "sections": "nope"}
    llm = _scripted_llm(
        [
            {"spec": bad, "unmapped": []},
            {"spec": bad, "unmapped": []},
        ]
    )
    with pytest.raises(PlanError):
        plan_report(
            golden,
            study_id=STUDY_ID,
            instructions="anything",
            llm=llm,
        )


def test_plan_compiles_analytics_query_without_repair(golden: Session) -> None:
    """LLM copied catalog 'dimensions' and omitted entity/window — compile, don't repair."""
    spec = {
        "specVersion": "1.0",
        "title": "DQA Daily Report",
        "sections": [
            {
                "id": "s1",
                "title": "Intake",
                "components": [
                    {
                        "id": "kpi",
                        "type": "kpi_group",
                        "query": {"measures": [{"id": "total", "fn": "count"}]},
                        "display": {"items": [{"label": "Total", "field": "total"}]},
                    },
                    {
                        "id": "by_tool",
                        "type": "table",
                        "query": {
                            "dimensions": ["toolCode"],
                            "measures": [{"id": "n", "fn": "count"}],
                        },
                        "display": {"columns": ["toolCode", "n"]},
                    },
                    {
                        "id": "headline",
                        "type": "narrative",
                        "uses": ["kpi"],
                        "query": {},
                        "display": {
                            "role": "insight",
                            "instruction": "Summarize today's intake.",
                        },
                    },
                ],
            }
        ],
    }
    seen: list[str] = []

    def _llm(*, system: str, user: str, purpose: str) -> dict[str, Any]:
        seen.append(purpose)
        if purpose == "plan":
            return {"spec": spec, "unmapped": []}
        if purpose == "repair":
            raise AssertionError("repair should not run after compile")
        return {"faithful": True, "issues": []}

    result = plan_report(
        golden,
        study_id=STUDY_ID,
        instructions="Daily DQA",
        llm=_llm,
    )
    assert seen == ["plan", "judge"]
    assert validate_report_spec(result["spec"]) == []
    by_tool = result["spec"]["sections"][0]["components"][1]["query"]
    assert by_tool["groupBy"] == ["toolCode"]
    assert by_tool["entity"] == "submission"
    assert by_tool["window"] == "execution_date"
    assert "dimensions" not in by_tool


def test_plan_accepts_kpi_group_per_item_queries(golden: Session) -> None:
    spec = {
        "specVersion": "1.0",
        "title": "DQA Daily Report",
        "sections": [
            {
                "id": "s1",
                "title": "Today at a Glance",
                "components": [
                    {
                        "id": "glance",
                        "type": "kpi_group",
                        "display": {
                            "items": [
                                {
                                    "label": "Submissions today",
                                    "query": {
                                        "entity": "submission",
                                        "window": "execution_date",
                                        "measures": [{"id": "value", "fn": "count"}],
                                    },
                                },
                                {
                                    "label": "Cumulative submissions",
                                    "query": {
                                        "entity": "submission",
                                        "window": "study_to_date",
                                        "measures": [{"id": "value", "fn": "count"}],
                                    },
                                },
                                {
                                    "label": "RED flags open",
                                    "query": {
                                        "entity": "flag",
                                        "window": "study_to_date",
                                        "measures": [
                                            {
                                                "id": "value",
                                                "fn": "countWhere",
                                                "field": "severity",
                                                "eq": "red",
                                            }
                                        ],
                                    },
                                },
                            ]
                        },
                    }
                ],
            }
        ],
    }
    llm = _scripted_llm(
        [
            {"spec": spec, "unmapped": []},
            {"faithful": True, "issues": []},
        ]
    )
    result = plan_report(
        golden,
        study_id=STUDY_ID,
        instructions=(
            "Title: DQA Daily Report. Open with today's intake as KPI cards: "
            "submissions received today, cumulative submissions, and open RED flags."
        ),
        llm=llm,
    )
    assert validate_report_spec(result["spec"]) == []
    glance = result["spec"]["sections"][0]["components"][0]
    assert glance["type"] == "kpi_group"
    assert "query" not in glance or glance.get("query") is None
    windows = [item["query"]["window"] for item in glance["display"]["items"]]
    assert "execution_date" in windows
    assert "study_to_date" in windows


def test_legacy_data_source_fails_validation(golden: Session) -> None:
    legacy = {
        "specVersion": "1.0",
        "title": "Legacy",
        "sections": [
            {
                "id": "s1",
                "title": "Totals",
                "components": [
                    {
                        "id": "s1c1",
                        "type": "metric",
                        "dataSource": "study_totals",
                        "display": {"label": "Total", "field": "total"},
                    }
                ],
            }
        ],
    }
    llm = _scripted_llm(
        [
            {"spec": legacy, "unmapped": []},
            {"spec": legacy, "unmapped": []},
        ]
    )
    with pytest.raises(PlanError):
        plan_report(
            golden,
            study_id=STUDY_ID,
            instructions="study totals",
            llm=llm,
        )


def test_patch_keeps_unrelated_sections(golden: Session) -> None:
    current = _golden_spec()
    assert len(current["sections"]) == 3
    patched = copy.deepcopy(current)
    patched["sections"].append(
        {
            "id": "s4",
            "title": "Trend",
            "components": [
                {
                    "id": "s4c1",
                    "type": "chart",
                    "query": {
                        "entity": "submission",
                        "window": "last_7_days",
                        "groupBy": ["day"],
                        "measures": [{"id": "total", "fn": "count"}],
                    },
                    "display": {"kind": "bar", "x": "day", "y": ["total"]},
                }
            ],
        }
    )
    llm = _scripted_llm(
        [
            {"spec": patched, "unmapped": []},
            {"faithful": True, "issues": []},
        ]
    )
    result = plan_report(
        golden,
        study_id=STUDY_ID,
        instructions="Also add a 7-day submissions bar chart",
        current_spec=current,
        llm=llm,
    )
    ids = [s["id"] for s in result["spec"]["sections"]]
    assert ids[:3] == ["s1", "s2", "s3"]
    assert "s4" in ids


def test_plan_job_202_and_get_result(client: TestClient, golden: Session) -> None:
    spec = _golden_spec()

    def _fake_plan(db: Session, job: Job) -> dict[str, Any]:
        return {
            "spec": spec,
            "unmapped": [{"userIntent": "Slack", "reason": "unsupported"}],
            "judgement": {"faithful": True, "issues": []},
        }

    worker.register_handler("plan", _fake_plan)
    try:
        resp = client.post(
            "/api/jobs",
            json={
                "type": "plan",
                "studyId": STUDY_ID,
                "payload": {"instructions": "today's KPIs"},
            },
        )
        assert resp.status_code == 202
        job_id = resp.json()["jobId"]
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "pending"

        assert worker.run_claimed(golden, limit=1) == 1
        body = client.get(f"/api/jobs/{job_id}").json()
        assert body["status"] == "completed"
        assert body["result"]["unmapped"]
        assert body["result"]["judgement"]["faithful"] is True
        assert "resultRef" not in body
        assert "report_runs" not in inspect(golden.bind).get_table_names()
    finally:
        from app.services.jobs.worker import _plan_handler

        worker.register_handler("plan", _plan_handler)


def test_seeded_prompts_on_get_prompts(client: TestClient, golden: Session) -> None:
    resp = client.get("/api/prompts")
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert REPORT_PLANNER_PROMPT_ID in ids
    assert REPORT_PLANNER_REPAIR_PROMPT_ID in ids
    assert REPORT_PLANNER_JUDGE_PROMPT_ID in ids
    assert REPORT_ANALYST_PROMPT_ID in ids


def test_planner_loads_db_prompt_content(golden: Session) -> None:
    from app.db.models import Prompt

    row = golden.get(Prompt, REPORT_PLANNER_PROMPT_ID)
    assert row is not None
    custom = "CUSTOM_PLANNER_MARKER_FOR_TEST — emit ReportSpec 1.0 only."
    row.content = custom
    golden.commit()

    seen: list[str] = []

    def _llm(*, system: str, user: str, purpose: str) -> dict[str, Any]:
        seen.append(system)
        if purpose == "plan":
            return {"spec": _golden_spec(), "unmapped": []}
        return {"faithful": True, "issues": []}

    plan_report(
        golden,
        study_id=STUDY_ID,
        instructions="KPIs",
        llm=_llm,
    )
    assert any("CUSTOM_PLANNER_MARKER_FOR_TEST" in s for s in seen)
    assert not any(DEFAULT_PLANNER_PROMPT[:40] == s[:40] for s in seen if "CUSTOM" in s)


def test_prompt_content_has_no_forbidden_legacy_strings() -> None:
    for _id, _name, _desc, content, _cat in SEED_REPORTING_PROMPTS:
        for token in _FORBIDDEN:
            assert token not in content, f"{_id} contains {token}"


def test_template_crud_spec_version_1_0(client: TestClient, golden: Session) -> None:
    spec = _golden_spec()
    create = client.post(
        "/api/report-templates",
        json={
            "name": "Golden template",
            "studyId": STUDY_ID,
            "prompt": "Golden daily snapshot",
            "spec": spec,
            "reportKind": "adhoc",
        },
    )
    assert create.status_code == 200, create.text
    body = create.json()
    assert body["status"] == "ok"
    assert body["template"]["id"]
    detail = client.get(f"/api/report-templates/{body['template']['id']}")
    assert detail.status_code == 200
    assert detail.json()["spec"]["specVersion"] == "1.0"


def test_app_has_no_legacy_planner_paths() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    hits: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("plan_spec(", "/create/stream"):
            if needle in text:
                hits.append(f"{path}:{needle}")
        # Package path leftovers
        if "services/report_planner" in str(path) or path.name == "report_planner_prompts.py":
            hits.append(str(path))
    assert hits == []
