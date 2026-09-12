from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import DqaFlag, Project, Study, Submission
from app.services.kobo_sync import (
    _full_reconcile_due,
    _prune_missing_submissions,
    _remote_submission_count,
    _sync_asset,
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

    from sqlalchemy import event

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_project(db: Session, *, uid: str = "asset1") -> Project:
    study = Study(
        id="study1",
        name="Study",
        description=None,
        start_date=None,
        end_date=None,
        timezone="UTC",
    )
    db.add(study)
    project = Project(
        id=uid,
        uid=uid,
        name="Form",
        study_id=study.id,
        form_definition={
            "survey": [{"type": "text", "name": "assessor_name", "label": "Assessor"}],
            "choices": [],
        },
    )
    db.add(project)
    db.commit()
    return project


def _add_submission(db: Session, project: Project, kobo_id: str) -> Submission:
    row = Submission(
        id=f"{project.id}:{kobo_id}",
        kobo_id=kobo_id,
        project_id=project.id,
        form_id=project.uid,
        form_name=project.name,
        enumerator="Ada",
        submitted_at=datetime(2026, 1, 1),
        data={"_id": kobo_id},
    )
    db.add(row)
    db.commit()
    return row


def _deployed_asset(project: Project, *, submission_count: int | None = None) -> dict:
    payload = {
        "uid": project.uid,
        "name": "Form",
        "deployment_status": "deployed",
        "deployment__active": True,
        "content": project.form_definition,
        "version_count": 1,
    }
    if submission_count is not None:
        payload["deployment__submission_count"] = submission_count
    return payload


def test_prune_missing_submissions_deletes_orphans_and_cascades_flags(db: Session):
    project = _seed_project(db)
    keep = _add_submission(db, project, "1")
    gone = _add_submission(db, project, "2")
    db.add(
        DqaFlag(
            id="flag-gone",
            project_id=project.id,
            submission_id=gone.id,
            rule_id="R1",
            severity="red",
            title="t",
            message="m",
        )
    )
    db.commit()

    deleted = _prune_missing_submissions(db, project.id, {"1"})
    db.commit()

    assert deleted == 1
    ids = {row.kobo_id for row in db.scalars(select(Submission)).all()}
    assert ids == {"1"}
    assert db.get(Submission, keep.id) is not None
    assert db.get(DqaFlag, "flag-gone") is None


def test_prune_missing_submissions_noop_when_in_sync(db: Session):
    project = _seed_project(db)
    _add_submission(db, project, "1")
    assert _prune_missing_submissions(db, project.id, {"1"}) == 0


def test_remote_submission_count_reads_deployment_field():
    assert _remote_submission_count({"deployment__submission_count": 12}) == 12
    assert _remote_submission_count({"summary": {"submission_count": "3"}}) == 3
    assert _remote_submission_count({}) is None


def test_full_reconcile_due_after_18h_utc():
    # 19:00 UTC on 2026-09-11 → anchor is 18:00 that day
    now = datetime(2026, 9, 11, 19, 0, tzinfo=timezone.utc)
    assert _full_reconcile_due(
        last_full_reconcile_at=datetime(2026, 9, 11, 10, 0),
        now_utc=now,
        study_timezone="UTC",
    )
    assert not _full_reconcile_due(
        last_full_reconcile_at=datetime(2026, 9, 11, 18, 30),
        now_utc=now,
        study_timezone="UTC",
    )


def test_sync_asset_prunes_deleted_remote_submissions(db: Session):
    project = _seed_project(db)
    _add_submission(db, project, "1")
    _add_submission(db, project, "2")
    project.last_submission_at = datetime(2026, 1, 1)
    project.last_full_reconcile_at = datetime(2026, 9, 11, 19, 0)
    project.submission_count = 2
    db.commit()

    client = MagicMock()
    client.get_asset.return_value = _deployed_asset(project, submission_count=1)
    client.list_versions.return_value = []
    client.list_submissions.return_value = [
        {
            "_id": "1",
            "_uuid": "u1",
            "_submission_time": "2026-01-02T00:00:00Z",
            "assessor_name": "Ada",
        }
    ]
    client.list_submission_ids.return_value = {"1"}

    with patch("app.services.dqa_engine.evaluate_project") as evaluate:
        result = _sync_asset(
            db,
            client,
            {
                "uid": project.uid,
                "name": "Form",
                "deployment_status": "deployed",
                "deployment__submission_count": 1,
            },
            study_id="study1",
            study_timezone="UTC",
        )

    assert result["deleted_submissions"] == 1
    assert result["new_submissions"] == 0
    client.list_submission_ids.assert_called_once_with(project.uid)
    evaluate.assert_called_once()
    ids = {row.kobo_id for row in db.scalars(select(Submission)).all()}
    assert ids == {"1"}
    refreshed = db.get(Project, project.id)
    assert refreshed is not None
    assert refreshed.submission_count == 1


def test_sync_asset_skips_id_inventory_when_counts_match(db: Session):
    project = _seed_project(db)
    _add_submission(db, project, "1")
    project.last_submission_at = datetime(2026, 1, 2)
    project.last_full_reconcile_at = datetime(2026, 9, 11, 18, 30)
    project.submission_count = 1
    db.commit()

    client = MagicMock()
    client.get_asset.return_value = _deployed_asset(project, submission_count=1)
    client.list_versions.return_value = []
    client.list_submissions.return_value = []

    with patch("app.services.kobo_sync._full_reconcile_due", return_value=False):
        with patch("app.services.dqa_engine.evaluate_project") as evaluate:
            result = _sync_asset(
                db,
                client,
                {
                    "uid": project.uid,
                    "name": "Form",
                    "deployment_status": "deployed",
                    "deployment__submission_count": 1,
                },
                study_id="study1",
                study_timezone="UTC",
            )

    assert result["deleted_submissions"] == 0
    assert result["reconciled"] is False
    client.list_submission_ids.assert_not_called()
    evaluate.assert_not_called()


def test_sync_asset_forces_daily_reconcile_after_18h(db: Session):
    project = _seed_project(db)
    _add_submission(db, project, "1")
    project.last_submission_at = datetime(2026, 1, 2)
    project.last_full_reconcile_at = datetime(2026, 9, 11, 10, 0)
    project.submission_count = 1
    db.commit()

    client = MagicMock()
    client.get_asset.return_value = _deployed_asset(project, submission_count=1)
    client.list_versions.return_value = []
    client.list_submissions.return_value = []
    client.list_submission_ids.return_value = {"1"}

    with patch("app.services.kobo_sync._full_reconcile_due", return_value=True):
        with patch("app.services.dqa_engine.evaluate_project"):
            result = _sync_asset(
                db,
                client,
                {
                    "uid": project.uid,
                    "name": "Form",
                    "deployment_status": "deployed",
                    "deployment__submission_count": 1,
                },
                study_id="study1",
                study_timezone="UTC",
            )

    assert result["reconciled"] is True
    client.list_submission_ids.assert_called_once_with(project.uid)


def test_sync_asset_skips_dqa_when_nothing_touched(db: Session):
    project = _seed_project(db)
    _add_submission(db, project, "1")
    project.last_submission_at = datetime(2026, 1, 2)
    project.last_full_reconcile_at = datetime(2026, 9, 11, 18, 30)
    project.submission_count = 1
    db.commit()

    client = MagicMock()
    client.get_asset.return_value = _deployed_asset(project, submission_count=1)
    client.list_versions.return_value = []
    client.list_submissions.return_value = []

    with patch("app.services.kobo_sync._full_reconcile_due", return_value=False):
        with patch("app.services.dqa_engine.evaluate_project") as evaluate:
            _sync_asset(
                db,
                client,
                {
                    "uid": project.uid,
                    "name": "Form",
                    "deployment_status": "deployed",
                    "deployment__submission_count": 1,
                },
                study_id="study1",
                study_timezone="UTC",
            )

    evaluate.assert_not_called()


def test_sync_asset_does_not_prune_draft_projects(db: Session):
    project = _seed_project(db)
    _add_submission(db, project, "1")

    client = MagicMock()
    client.get_asset.return_value = {
        "uid": project.uid,
        "name": "Form",
        "deployment_status": "draft",
        "content": project.form_definition,
        "version_count": 1,
    }
    client.list_versions.return_value = []

    with patch("app.services.dqa_engine.evaluate_project"):
        result = _sync_asset(
            db,
            client,
            {"uid": project.uid, "name": "Form", "deployment_status": "draft"},
            study_id="study1",
        )

    assert result["deleted_submissions"] == 0
    client.list_submission_ids.assert_not_called()
    assert db.scalar(select(Submission).where(Submission.kobo_id == "1")) is not None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 4),
        ("", 4),
        ("2", 2),
        ("1", 1),
        ("8", 8),
        ("99", 8),
        ("0", 1),
        ("-3", 1),
        ("nope", 4),
    ],
)
def test_sync_concurrency_clamp(raw: str | None, expected: int, monkeypatch: pytest.MonkeyPatch):
    from app.services.kobo_sync import _sync_concurrency

    if raw is None:
        monkeypatch.delenv("KOBO_SYNC_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("KOBO_SYNC_CONCURRENCY", raw)
    assert _sync_concurrency() == expected


def test_slowest_form_s():
    from app.services.kobo_sync import _slowest_form_s

    slowest = _slowest_form_s(
        [
            {
                "metadata": 1000.0,
                "delta_fetch": 2000.0,
                "db_write": 100.0,
            },
            {
                "metadata": 3000.0,
                "delta_fetch": 500.0,
                "db_write": 50.0,
            },
        ]
    )
    assert slowest == {
        "kobo_metadata": 3.0,
        "kobo_delta_fetch": 2.0,
        "db_write": 0.1,
    }


def test_seconds_rounding():
    from app.services.kobo_sync import _seconds

    assert _seconds(0.0) == 0.0
    assert _seconds(840.5) == 0.84
    assert _seconds(7929.5) == 7.9
    assert _seconds(9992.7) == 10.0


def test_sync_all_projects_aggregates_parallel_worker_results(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services import kobo_sync

    study = Study(
        id="study1",
        name="Study",
        description=None,
        start_date=None,
        end_date=None,
        timezone="UTC",
    )
    db.add(study)
    db.commit()

    assets = [
        {"uid": "a1", "name": "Form A", "asset_type": "survey"},
        {"uid": "a2", "name": "Form B", "asset_type": "survey"},
        {"uid": "a3", "name": "Form C", "asset_type": "survey"},
    ]

    def fake_worker(*, client, asset, study_id, study_timezone):
        uid = asset["uid"]
        if uid == "a2":
            return {
                "ok": False,
                "asset_uid": uid,
                "asset_name": asset["name"],
                "error": "boom",
            }
        return {
            "ok": True,
            "asset_uid": uid,
            "asset_name": asset["name"],
            "result": {
                "project_id": uid,
                "submissions_fetched": 2,
                "new_submissions": 1,
                "deleted_submissions": 0,
                "touched_submission_ids": {f"{uid}:1"},
            },
        }

    client = MagicMock()
    client.list_assets.return_value = assets

    monkeypatch.setenv("KOBO_SYNC_CONCURRENCY", "2")
    monkeypatch.setattr(kobo_sync, "_configured_client", lambda _db, _sid: client)
    monkeypatch.setattr(kobo_sync, "_sync_one_asset_worker", fake_worker)
    monkeypatch.setattr(kobo_sync, "_canonicalize_study_enumerators", lambda *_a, **_k: None)
    monkeypatch.setattr(kobo_sync, "_run_dqa_for_touched", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.services.studies.apply_all_study_form_maps",
        lambda *_a, **_k: 0,
    )

    result = kobo_sync.sync_all_projects(db, "study1")

    assert result["projects_synced"] == 2
    assert result["submissions_fetched"] == 4
    assert result["new_submissions"] == 2
    assert result["success"] is False
    assert result["errors"] == ["Form B: boom"]
