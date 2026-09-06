from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import DqaFlag, Project, Study, Submission
from app.services.kobo_sync import _prune_missing_submissions, _sync_asset


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


def test_sync_asset_prunes_deleted_remote_submissions(db: Session):
    project = _seed_project(db)
    _add_submission(db, project, "1")
    _add_submission(db, project, "2")

    client = MagicMock()
    client.get_asset.return_value = {
        "uid": project.uid,
        "name": "Form",
        "deployment_status": "deployed",
        "deployment__active": True,
        "content": project.form_definition,
        "version_count": 1,
    }
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

    result = _sync_asset(
        db,
        client,
        {"uid": project.uid, "name": "Form", "deployment_status": "deployed"},
        study_id="study1",
    )

    assert result["deleted_submissions"] == 1
    assert result["new_submissions"] == 0
    ids = {row.kobo_id for row in db.scalars(select(Submission)).all()}
    assert ids == {"1"}
    refreshed = db.get(Project, project.id)
    assert refreshed is not None
    assert refreshed.submission_count == 1


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

    result = _sync_asset(
        db,
        client,
        {"uid": project.uid, "name": "Form", "deployment_status": "draft"},
        study_id="study1",
    )

    assert result["deleted_submissions"] == 0
    client.list_submission_ids.assert_not_called()
    assert db.scalar(select(Submission).where(Submission.kobo_id == "1")) is not None
