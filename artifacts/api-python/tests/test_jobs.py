"""Phase 0 jobs platform tests (G2: HTTP returns 202 before work finishes)."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor  # noqa: F401 — unused after SQLite-safe rewrite
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Job, Study
from app.db.session import get_db
from app.routers import jobs as jobs_router
from app.services.jobs import artifacts, store, worker


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
    app.include_router(jobs_router.router, prefix="/api")

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _add_study(db: Session, study_id: str = "study-a") -> Study:
    study = Study(
        id=study_id,
        name="Study A",
        description="",
        timezone="Asia/Kolkata",
    )
    db.add(study)
    db.commit()
    return study


def test_post_returns_202_and_get_pending(client: TestClient, db: Session) -> None:
    _add_study(db)
    resp = client.post(
        "/api/jobs",
        json={"type": "echo", "studyId": "study-a", "payload": {"hello": "world"}},
    )
    assert resp.status_code == 202
    job_id = resp.json()["jobId"]
    assert job_id

    pending = client.get(f"/api/jobs/{job_id}")
    assert pending.status_code == 200
    body = pending.json()
    assert body["status"] == "pending"
    assert "result" not in body or body.get("result") is None
    assert "resultRef" not in body


def test_worker_completes_echo_file_and_hydrate(client: TestClient, db: Session) -> None:
    _add_study(db)
    job_id = client.post(
        "/api/jobs",
        json={"type": "echo", "studyId": "study-a", "payload": {"n": 1}},
    ).json()["jobId"]

    processed = worker.run_claimed(db, limit=1)
    assert processed == 1

    row = db.get(Job, job_id)
    assert row is not None
    assert row.status == "completed"
    assert row.result_ref
    assert not hasattr(row, "result") or getattr(row, "result", None) is None
    path = Path(artifacts.job_result_path(job_id))
    assert path.is_file()

    done = client.get(f"/api/jobs/{job_id}")
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "completed"
    assert body["result"] == {"n": 1}
    assert "resultRef" not in body


def test_get_404(client: TestClient) -> None:
    assert client.get("/api/jobs/missing-id").status_code == 404


def test_fail_sets_error_no_traceback_no_file(client: TestClient, db: Session) -> None:
    _add_study(db)
    job_id = client.post(
        "/api/jobs",
        json={"type": "echo", "studyId": "study-a", "payload": {}},
    ).json()["jobId"]

    claimed = store.claim(db, limit=1)
    assert len(claimed) == 1

    def boom(_db: Session, _job: Job):
        raise RuntimeError("boom detail for clients")

    with patch.dict(worker._HANDLERS, {"echo": boom}):
        worker.process_job(db, claimed[0])

    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["status"] == "failed"
    assert body["error"] == "boom detail for clients"
    assert "Traceback" not in (body.get("error") or "")
    assert "result" not in body or body.get("result") is None
    assert not artifacts.job_result_path(job_id).is_file()


def test_g2_post_returns_before_slow_handler(client: TestClient, db: Session) -> None:
    """POST /jobs must return 202 while work is still pending (G2)."""
    _add_study(db)

    def slow(_db: Session, job: Job):
        time.sleep(0.4)
        return {"ok": True, "echo": job.payload}

    with patch.dict(worker._HANDLERS, {"echo": slow}):
        started = time.perf_counter()
        resp = client.post(
            "/api/jobs",
            json={"type": "echo", "studyId": "study-a", "payload": {"x": 1}},
        )
        elapsed = time.perf_counter() - started
        assert resp.status_code == 202
        assert elapsed < 0.3
        job_id = resp.json()["jobId"]
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        assert status in {"pending", "processing"}


def test_concurrent_two_jobs_complete(client: TestClient, db: Session) -> None:
    _add_study(db)
    ids = []
    for i in range(2):
        ids.append(
            client.post(
                "/api/jobs",
                json={"type": "echo", "studyId": "study-a", "payload": {"i": i}},
            ).json()["jobId"]
        )

    # Claim budget of 2 processes both without threaded SQLite races.
    processed = worker.run_claimed(db, limit=2)
    assert processed == 2

    for job_id in ids:
        body = client.get(f"/api/jobs/{job_id}").json()
        assert body["status"] == "completed"
        assert "result" in body
        assert artifacts.job_result_path(job_id).is_file()


def test_fail_orphaned_processing_clears_inflight(db: Session) -> None:
    _add_study(db)
    job = store.enqueue(db, job_type="echo", payload={"n": 1}, study_id="study-a")
    claimed = store.claim(db, limit=1)
    assert claimed[0].id == job.id
    assert claimed[0].status == "processing"

    n = store.fail_orphaned_processing(db)
    assert n == 1
    db.refresh(job)
    assert job.status == "failed"
    assert job.error == "Interrupted by server restart"
