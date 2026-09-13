"""Kobo sync enqueues a job (202); worker runs sync_all_projects."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Job, Study
from app.db.session import get_db
from app.routers import projects as projects_router
from app.services.jobs import worker


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
    app.include_router(projects_router.router, prefix="/api")

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_sync_projects_returns_202_job_without_running_sync(
    client: TestClient, db: Session
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        Study(
            id="study-sync",
            name="Sync Study",
            timezone="Asia/Kolkata",
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()

    fake_result = {
        "success": True,
        "projects_synced": 2,
        "submissions_fetched": 10,
        "new_submissions": 3,
        "deleted_submissions": 0,
        "synced_at": now.isoformat(),
        "errors": [],
    }

    with patch(
        "app.services.kobo_sync.sync_all_projects",
        return_value=fake_result,
    ) as sync_mock, patch(
        "app.services.jobs.worker.kick_in_thread",
    ):
        resp = client.post("/api/projects/sync?studyId=study-sync")
        assert resp.status_code == 202, resp.text
        body = resp.json()
        job_id = body.get("jobId") or body.get("job_id")
        assert job_id

        job = db.get(Job, job_id)
        assert job is not None
        assert job.type == "kobo_sync"
        assert job.status == "pending"
        assert job.study_id == "study-sync"
        sync_mock.assert_not_called()

        worker.run_claimed(db, limit=1)
        db.refresh(job)
        assert job.status == "completed"
        sync_mock.assert_called_once()


def test_sync_projects_409_when_already_queued(
    client: TestClient, db: Session
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        Study(
            id="study-busy",
            name="Busy Study",
            timezone="Asia/Kolkata",
            created_at=now,
            updated_at=now,
        )
    )
    db.add(
        Job(
            id="job-busy",
            type="kobo_sync",
            status="pending",
            study_id="study-busy",
            payload={},
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()

    with patch("app.services.jobs.worker.kick_in_thread"):
        resp = client.post("/api/projects/sync?studyId=study-busy")
    assert resp.status_code == 409


def test_sync_projects_returns_202_before_worker_finishes(
    client: TestClient, db: Session
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        Study(
            id="study-fast-202",
            name="Fast 202",
            timezone="Asia/Kolkata",
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()

    release = threading.Event()

    def blocking_kick(*, limit: int = 2) -> int:
        release.wait(timeout=5)
        return 0

    try:
        with patch(
            "app.services.jobs.worker.kick_own_session",
            side_effect=blocking_kick,
        ):
            started = time.monotonic()
            resp = client.post("/api/projects/sync?studyId=study-fast-202")
            elapsed = time.monotonic() - started
        assert resp.status_code == 202, resp.text
        assert elapsed < 1.0, f"POST /sync waited {elapsed:.2f}s for the worker"
    finally:
        release.set()
