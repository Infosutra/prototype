"""Tests for active-study auto-sync, run lock, and pre-mail sync."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import ReportSchedule, Study
from app.db.session import get_db
from app.routers import settings as settings_router
from app.schemas.settings import (
    DailyReportSettings,
    GeneralSettings,
    SettingsOut,
    SettingsUpdate,
    SmtpSettings,
)
from app.services import kobo_auto_sync
from app.services import settings as settings_service
from app.services.dqa_daily_email import maybe_send_scheduled_dqa_daily
from app.services.kobo_sync import _SYNC_RUN_LOCK, try_sync_all_projects


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
    app.include_router(settings_router.router, prefix="/api")

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
        start_date=None,
        end_date=None,
        timezone="Asia/Kolkata",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(study)
    db.commit()
    return study


def _fake_settings_out(active_study_id: str | None = "study-a") -> SettingsOut:
    return SettingsOut(
        smtp=SmtpSettings(
            host="",
            port=587,
            username="",
            password="",
            from_name="Infosutra",
            from_email="",
            use_tls=True,
            connected=False,
        ),
        daily_report=DailyReportSettings(
            enabled=False,
            send_time="21:00",
            timezone="Asia/Kolkata",
            recipients=[],
        ),
        general=GeneralSettings(
            organization_name="Infosutra",
            timezone="UTC",
            date_format="YYYY-MM-DD",
            language="en",
            ai_enabled=False,
            ai_provider="openrouter",
            ai_api_key="",
        ),
        active_study_id=active_study_id,
    )


def test_try_sync_all_projects_skips_when_lock_held(db: Session) -> None:
    _add_study(db)
    acquired = _SYNC_RUN_LOCK.acquire(blocking=False)
    assert acquired
    try:
        with patch(
            "app.services.kobo_sync._sync_all_projects_unlocked",
            return_value={"success": True},
        ) as unlocked:
            assert try_sync_all_projects(db, "study-a") is None
            unlocked.assert_not_called()
    finally:
        _SYNC_RUN_LOCK.release()


def test_update_settings_returns_sync_id_only_when_active_study_changes(db: Session) -> None:
    _add_study(db, "study-a")
    _add_study(db, "study-b")
    settings_service.get_or_create_settings(db)

    out, sync_id = settings_service.update_settings(
        db, SettingsUpdate(active_study_id="study-a")
    )
    assert out.active_study_id == "study-a"
    assert sync_id == "study-a"

    out, sync_id = settings_service.update_settings(
        db, SettingsUpdate(active_study_id="study-a")
    )
    assert out.active_study_id == "study-a"
    assert sync_id is None

    out, sync_id = settings_service.update_settings(
        db, SettingsUpdate(active_study_id="study-b")
    )
    assert out.active_study_id == "study-b"
    assert sync_id == "study-b"


def test_put_settings_schedules_background_sync(client: TestClient) -> None:
    with (
        patch("app.routers.settings.settings_service.update_settings") as update,
        patch("app.routers.settings._background_sync_study") as bg_sync,
    ):
        update.return_value = (_fake_settings_out("study-a"), "study-a")
        response = client.put("/api/settings", json={"activeStudyId": "study-a"})
        assert response.status_code == 200
        assert response.json()["activeStudyId"] == "study-a"
        bg_sync.assert_called_once_with("study-a")


def test_put_settings_same_id_does_not_schedule_sync(client: TestClient) -> None:
    with (
        patch("app.routers.settings.settings_service.update_settings") as update,
        patch("app.routers.settings._background_sync_study") as bg_sync,
    ):
        update.return_value = (_fake_settings_out("study-a"), None)
        response = client.put("/api/settings", json={"activeStudyId": "study-a"})
        assert response.status_code == 200
        bg_sync.assert_not_called()


def test_auto_sync_uses_active_study_only(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _add_study(db, "study-a")
    row = settings_service.get_or_create_settings(db)
    row.active_study_id = "study-a"
    db.commit()

    kobo_auto_sync.reset_auto_sync_clock_for_tests()
    monkeypatch.setenv("KOBO_AUTO_SYNC_INTERVAL_MINUTES", "30")

    with patch(
        "app.services.kobo_auto_sync.try_sync_all_projects",
        return_value={"success": True, "projects_synced": 1, "errors": []},
    ) as try_sync:
        assert kobo_auto_sync.maybe_run_scheduled_kobo_sync(db) is True
        try_sync.assert_called_once_with(db, "study-a")


def test_auto_sync_skips_without_active_study(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_service.get_or_create_settings(db)
    kobo_auto_sync.reset_auto_sync_clock_for_tests()
    monkeypatch.setenv("KOBO_AUTO_SYNC_INTERVAL_MINUTES", "30")

    with patch("app.services.kobo_auto_sync.try_sync_all_projects") as try_sync:
        assert kobo_auto_sync.maybe_run_scheduled_kobo_sync(db) is False
        try_sync.assert_not_called()


def test_maybe_send_scheduled_dqa_daily_syncs_before_generate(db: Session) -> None:
    _add_study(db, "study-a")
    schedule = ReportSchedule(
        id="sched-1",
        study_id="study-a",
        enabled=True,
        time="10:00",
        timezone="Asia/Kolkata",
        report_type="daily_dqa",
        template_id=None,
        last_sent_on=None,
        recipients=[],
    )
    db.add(schedule)
    db.commit()

    fake_report = MagicMock()
    fixed = datetime(2026, 3, 15, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    with (
        patch("app.services.dqa_daily_email.datetime") as mock_dt,
        patch(
            "app.services.dqa_daily_email.sync_all_projects",
            return_value={"success": True, "errors": []},
        ) as sync_mock,
        patch(
            "app.services.dqa_daily_email._generate_for_schedule",
            return_value=fake_report,
        ) as gen,
        patch("app.services.dqa_daily_email.send_dqa_daily_email") as send,
    ):
        mock_dt.now.return_value = fixed

        assert maybe_send_scheduled_dqa_daily(db) is True
        sync_mock.assert_called_once_with(db, "study-a")
        gen.assert_called_once()
        send.assert_called_once_with(db, fake_report)
        assert schedule.last_sent_on == "2026-03-15"
