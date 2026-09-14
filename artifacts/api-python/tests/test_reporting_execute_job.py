"""Phase 3 — execute job via POST /jobs + worker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Job, Report
from app.db.session import get_db
from app.routers import jobs as jobs_router
from app.services.jobs import artifacts, worker
from app.services.report_storage import pdf_path_for
from tests.helpers.reporting_fixture import (
    EXECUTION_DATE,
    STUDY_ID,
    seed_golden_reporting,
)

_GOLDEN = Path(__file__).parent / "fixtures" / "reporting_golden_spec.json"


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
def client(db: Session) -> TestClient:
    app = FastAPI()
    app.include_router(jobs_router.router, prefix="/api")

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


@pytest.fixture()
def golden(db: Session) -> Session:
    seed_golden_reporting(db)
    return db


def test_execute_job_202_worker_hydrates(client: TestClient, golden: Session) -> None:
    spec = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    resp = client.post(
        "/api/jobs",
        json={
            "type": "execute",
            "studyId": STUDY_ID,
            "payload": {
                "spec": spec,
                "window": {"preset": "execution_date", "executionDate": EXECUTION_DATE},
            },
        },
    )
    assert resp.status_code == 202
    job_id = resp.json()["jobId"]

    pending = client.get(f"/api/jobs/{job_id}")
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

    processed = worker.run_claimed(golden, limit=1)
    assert processed == 1

    row = golden.get(Job, job_id)
    assert row is not None
    assert row.status == "completed"
    assert row.result_ref
    assert row.result_ref.startswith("data/jobs/")
    # DB column is path only — not an inline ExecuteResult blob
    assert not hasattr(Job, "result") or "result" not in {c.key for c in inspect(Job).mapper.column_attrs}

    # result file on disk
    loaded = artifacts.read_job_result(row.result_ref)
    assert loaded["sections"]
    kpis = next(
        c
        for s in loaded["sections"]
        for c in s["components"]
        if c["id"] == "s1c1"
    )
    assert kpis["data"] == {"total": 25, "clean": 20, "flagged": 5}

    hydrated = client.get(f"/api/jobs/{job_id}")
    assert hydrated.status_code == 200
    body = hydrated.json()
    assert body["status"] == "completed"
    assert "resultRef" not in body
    assert body["result"]["sections"]
    assert body["result"]["sections"][0]["components"][0]["data"]["total"] == 25

    report_id = body["result"]["reportId"]
    report = golden.get(Report, report_id)
    assert report is not None
    assert report.result_ref
    assert report.result_ref.startswith("data/reports/")
    pdf = pdf_path_for(report_id)
    assert pdf.is_file()
    assert pdf.stat().st_size > 100

    # No ReportRun table / rows
    assert "report_runs" not in Base.metadata.tables
    # Also ensure we did not create a sneaky table
    tables = set(Base.metadata.tables.keys())
    assert "report_runs" not in tables


def test_execute_job_preview_does_not_persist_report(
    client: TestClient, golden: Session
) -> None:
    before = len(golden.scalars(select(Report)).all())
    spec = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    resp = client.post(
        "/api/jobs",
        json={
            "type": "execute",
            "studyId": STUDY_ID,
            "payload": {
                "spec": spec,
                "window": {"preset": "execution_date", "executionDate": EXECUTION_DATE},
                "preview": True,
            },
        },
    )
    assert resp.status_code == 202
    job_id = resp.json()["jobId"]
    assert worker.run_claimed(golden, limit=1) == 1

    hydrated = client.get(f"/api/jobs/{job_id}")
    assert hydrated.status_code == 200
    body = hydrated.json()
    assert body["status"] == "completed"
    assert body["result"]["preview"] is True
    assert "reportId" not in body["result"]
    assert body["result"]["sections"]

    after = golden.scalars(select(Report)).all()
    assert len(after) == before


def test_routers_do_not_import_query_engine_run() -> None:
    """G2: jobs/report routers enqueue only — no inline query_engine / LLM."""
    routers_dir = Path(__file__).resolve().parents[1] / "app" / "routers"
    for name in ("jobs.py", "reports.py", "report_templates.py", "report_conversations.py"):
        path = routers_dir / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "query_engine.run" not in text, name
        assert "chat_completion" not in text, name
        assert "execute_report" not in text, name
