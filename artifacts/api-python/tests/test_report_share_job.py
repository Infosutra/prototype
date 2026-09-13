"""C1 — share enqueues email job (202); router does not SMTP."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Job, Report, Study
from app.db.session import get_db
from app.routers import reports as reports_router
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
    app.include_router(reports_router.router, prefix="/api")

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_share_returns_202_email_job_without_smtp(
    client: TestClient, db: Session
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        Study(
            id="study-share",
            name="Share Study",
            timezone="Asia/Kolkata",
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()
    report = Report(
        id="report-share-1",
        title="Shared report",
        description="",
        status="ready",
        format="pdf",
        report_type="custom",
        study_id="study-share",
        created_at=now,
    )
    db.add(report)
    db.commit()

    with patch(
        "app.services.reporting.schedule_email.send_report_email",
        return_value=(report, ["ops@example.com"]),
    ) as send_mock:
        resp = client.post(
            "/api/reports/report-share-1/share",
            json={"recipients": ["ops@example.com"]},
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        job_id = body.get("jobId") or body.get("job_id")
        assert job_id

        job = db.get(Job, job_id)
        assert job is not None
        assert job.type == "email"
        assert job.status == "pending"
        send_mock.assert_not_called()

        worker.run_claimed(db, limit=1)
        db.refresh(job)
        assert job.status == "completed"
        send_mock.assert_called_once()
