"""Phase 1 — ingest projection writers (answers, quality, study_id denorm)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    DqaFlag,
    Project,
    Study,
    Submission,
    SubmissionAnswer,
    SubmissionQuality,
)
from app.services.dqa_evaluation import evaluate_submission, stable_flag_id
from app.services.reporting.answers import replace_answers_for_submission
from app.services.reporting.projections import (
    project_submission_facts,
    resync_study_id_for_project,
)
from app.services.reporting.quality import upsert_quality_for_submission
from app.services.studies import assign_project, unassign_project


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


FORM_DEFINITION = {
    "survey": [
        {"type": "text", "name": "q_name", "label": "Respondent name"},
        {"type": "integer", "name": "q_age", "label": "Age"},
        {"type": "start", "name": "start", "label": "Start"},
        {"type": "end", "name": "end", "label": "End"},
    ],
    "choices": [],
}


def _seed(
    db: Session,
    *,
    study_id: str | None = "study-1",
    timezone_name: str = "Asia/Kolkata",
    project_id: str = "proj-1",
) -> tuple[Study | None, Project]:
    study = None
    if study_id is not None:
        study = Study(
            id=study_id,
            name="Study",
            description=None,
            start_date=None,
            end_date=None,
            timezone=timezone_name,
        )
        db.add(study)
        db.flush()
    project = Project(
        id=project_id,
        uid=project_id,
        name="Form",
        study_id=study_id,
        form_definition=FORM_DEFINITION,
    )
    db.add(project)
    db.commit()
    return study, project


def _submission(
    db: Session,
    project: Project,
    *,
    kobo_id: str = "100",
    data: dict | None = None,
    submitted_at: datetime | None = None,
) -> Submission:
    row = Submission(
        id=f"{project.id}:{kobo_id}",
        kobo_id=kobo_id,
        project_id=project.id,
        form_id=project.uid,
        form_name=project.name,
        enumerator="Ada",
        submitted_at=submitted_at or datetime(2026, 3, 12, 18, 30, 0),
        data=data
        or {
            "_id": 100,
            "_uuid": "u-100",
            "_notes": [],
            "_attachments": [],
            "start": "2026-03-12T10:00:00",
            "end": "2026-03-12T10:45:00",
            "q_name": "Meena",
            "q_age": 32,
        },
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_two_questions_project_two_answers_with_labels(db: Session) -> None:
    _, project = _seed(db)
    sub = _submission(db, project)

    replace_answers_for_submission(db, sub, project=project)
    db.commit()

    answers = list(
        db.scalars(
            select(SubmissionAnswer)
            .where(SubmissionAnswer.submission_id == sub.id)
            .order_by(SubmissionAnswer.field_key)
        ).all()
    )
    assert len(answers) == 2
    by_key = {a.field_key: a for a in answers}
    assert set(by_key) == {"q_age", "q_name"}
    assert by_key["q_name"].field_label == "Respondent name"
    assert by_key["q_name"].value_type == "string"
    assert by_key["q_name"].value_text == "Meena"
    assert by_key["q_age"].field_label == "Age"
    assert by_key["q_age"].value_type == "number"
    assert by_key["q_age"].value_number == 32.0
    assert by_key["q_name"].study_id == "study-1"


def test_reupsert_replaces_answers_no_duplicates(db: Session) -> None:
    _, project = _seed(db)
    sub = _submission(db, project)
    replace_answers_for_submission(db, sub, project=project)
    db.commit()

    sub.data = {
        "_id": 100,
        "start": "2026-03-12T10:00:00",
        "end": "2026-03-12T10:30:00",
        "q_name": "Ravi",
        "q_age": 40,
    }
    replace_answers_for_submission(db, sub, project=project)
    db.commit()

    answers = list(
        db.scalars(select(SubmissionAnswer).where(SubmissionAnswer.submission_id == sub.id)).all()
    )
    assert len(answers) == 2
    by_key = {a.field_key: a for a in answers}
    assert by_key["q_name"].value_text == "Ravi"
    assert by_key["q_age"].value_number == 40.0


def test_meta_and_start_end_not_answers_duration_set(db: Session) -> None:
    _, project = _seed(db)
    sub = _submission(db, project)
    replace_answers_for_submission(db, sub, project=project)
    db.commit()
    db.refresh(sub)

    keys = {
        a.field_key
        for a in db.scalars(
            select(SubmissionAnswer).where(SubmissionAnswer.submission_id == sub.id)
        ).all()
    }
    assert "_id" not in keys
    assert "_uuid" not in keys
    assert "_notes" not in keys
    assert "_attachments" not in keys
    assert "start" not in keys
    assert "end" not in keys
    assert sub.duration_minutes == 45.0
    assert sub.study_id == "study-1"


def test_calendar_day_matches_study_timezone(db: Session) -> None:
    # 2026-03-12 18:30 UTC → 2026-03-13 00:00 Asia/Kolkata
    _, project = _seed(db, timezone_name="Asia/Kolkata")
    sub = _submission(
        db,
        project,
        submitted_at=datetime(2026, 3, 12, 18, 30, 0),
    )
    replace_answers_for_submission(db, sub, project=project, study_timezone="Asia/Kolkata")
    db.commit()
    db.refresh(sub)
    assert sub.calendar_day == date(2026, 3, 13)


def test_study_id_on_submission_and_flags(db: Session) -> None:
    _, project = _seed(db)
    sub = _submission(db, project)
    project_submission_facts(db, sub, project=project)
    db.commit()
    db.refresh(sub)
    assert sub.study_id == "study-1"

    flag = DqaFlag(
        id=stable_flag_id(sub.id, "R1"),
        submission_id=sub.id,
        project_id=project.id,
        study_id=project.study_id,
        rule_id="R1",
        severity="amber",
        title="t",
        message="m",
        evaluated_at=datetime(2026, 3, 12),
    )
    db.add(flag)
    db.commit()
    stored = db.get(DqaFlag, flag.id)
    assert stored is not None
    assert stored.study_id == "study-1"


def test_zero_flags_is_clean(db: Session) -> None:
    _, project = _seed(db)
    sub = _submission(db, project)
    sub.study_id = project.study_id
    db.commit()

    evaluate_submission(db, sub, pack={}, commit=True)
    quality = db.get(SubmissionQuality, sub.id)
    assert quality is not None
    assert quality.is_clean is True
    assert quality.max_severity is None
    assert quality.flag_count == 0
    assert quality.red_count == 0
    assert quality.amber_count == 0
    assert quality.study_id == "study-1"


def test_one_amber_not_clean(db: Session) -> None:
    _, project = _seed(db)
    sub = _submission(db, project)
    sub.study_id = project.study_id
    db.commit()

    pack = {
        "fields": {"name": "q_name"},
        "rules": [
            {
                "id": "amber_rule",
                "severity": "amber",
                "title": "Amber",
                "message": "missing",
                "check": {"op": "required", "field": "missing_field"},
            }
        ],
    }
    sub.data = {"q_name": "Meena"}
    evaluate_submission(db, sub, pack=pack, study_id=project.study_id, commit=True)

    quality = db.get(SubmissionQuality, sub.id)
    assert quality is not None
    assert quality.is_clean is False
    assert quality.max_severity == "amber"
    assert quality.flag_count == 1
    assert quality.amber_count == 1
    assert quality.red_count == 0

    flags = list(db.scalars(select(DqaFlag).where(DqaFlag.submission_id == sub.id)).all())
    assert len(flags) == 1
    assert flags[0].study_id == "study-1"
    assert flags[0].severity == "amber"


def test_amber_plus_red_max_severity_red(db: Session) -> None:
    _, project = _seed(db)
    sub = _submission(db, project)
    sub.study_id = project.study_id
    db.commit()

    pack = {
        "fields": {},
        "rules": [
            {
                "id": "amber_rule",
                "severity": "amber",
                "title": "Amber",
                "message": "a",
                "check": {"op": "required", "field": "missing_a"},
            },
            {
                "id": "red_rule",
                "severity": "red",
                "title": "Red",
                "message": "r",
                "check": {"op": "required", "field": "missing_b"},
            },
        ],
    }
    evaluate_submission(db, sub, pack=pack, study_id=project.study_id, commit=True)

    quality = db.get(SubmissionQuality, sub.id)
    assert quality is not None
    assert quality.is_clean is False
    assert quality.max_severity == "red"
    assert quality.flag_count == 2
    assert quality.amber_count == 1
    assert quality.red_count == 1


def test_delete_reeval_updates_quality(db: Session) -> None:
    _, project = _seed(db)
    sub = _submission(db, project)
    sub.study_id = project.study_id
    db.commit()

    failing = {
        "fields": {},
        "rules": [
            {
                "id": "r1",
                "severity": "red",
                "title": "Red",
                "message": "r",
                "check": {"op": "required", "field": "gone"},
            }
        ],
    }
    evaluate_submission(db, sub, pack=failing, study_id=project.study_id, commit=True)
    assert db.get(SubmissionQuality, sub.id).is_clean is False

    clean_pack = {"fields": {}, "rules": []}
    evaluate_submission(db, sub, pack=clean_pack, study_id=project.study_id, commit=True)
    quality = db.get(SubmissionQuality, sub.id)
    assert quality is not None
    assert quality.is_clean is True
    assert quality.flag_count == 0
    assert quality.max_severity is None
    assert db.scalar(select(DqaFlag).where(DqaFlag.submission_id == sub.id)) is None


def test_prune_submission_cascades_answers_and_quality(db: Session) -> None:
    _, project = _seed(db)
    sub = _submission(db, project)
    replace_answers_for_submission(db, sub, project=project)
    upsert_quality_for_submission(
        db, sub.id, project_id=project.id, study_id=project.study_id
    )
    db.commit()
    assert db.scalar(
        select(SubmissionAnswer).where(SubmissionAnswer.submission_id == sub.id)
    )
    assert db.get(SubmissionQuality, sub.id) is not None

    db.delete(sub)
    db.commit()

    assert (
        db.scalar(select(SubmissionAnswer).where(SubmissionAnswer.submission_id == sub.id))
        is None
    )
    assert db.get(SubmissionQuality, sub.id) is None


def test_null_study_no_projection(db: Session) -> None:
    _, project = _seed(db, study_id=None)
    sub = _submission(db, project)
    # Seed stale projections then clear via writer
    db.add(
        SubmissionAnswer(
            id="stale",
            submission_id=sub.id,
            project_id=project.id,
            study_id="old-study",
            field_key="q_name",
            field_label="Name",
            value_type="string",
            value_text="x",
        )
    )
    db.add(
        SubmissionQuality(
            submission_id=sub.id,
            study_id="old-study",
            project_id=project.id,
            is_clean=True,
            max_severity=None,
            flag_count=0,
            red_count=0,
            amber_count=0,
        )
    )
    db.commit()

    replace_answers_for_submission(db, sub, project=project)
    upsert_quality_for_submission(db, sub.id, project_id=project.id, study_id=None)
    db.commit()
    db.refresh(sub)

    assert sub.study_id is None
    assert (
        db.scalar(select(SubmissionAnswer).where(SubmissionAnswer.submission_id == sub.id))
        is None
    )
    assert db.get(SubmissionQuality, sub.id) is None


def test_reassign_study_id_rewrite_and_clear(db: Session) -> None:
    study_a, project = _seed(db, study_id="study-a")
    assert study_a is not None
    study_b = Study(
        id="study-b",
        name="B",
        description=None,
        start_date=None,
        end_date=None,
        timezone="UTC",
    )
    db.add(study_b)
    db.commit()

    sub = _submission(db, project)
    replace_answers_for_submission(db, sub, project=project)
    upsert_quality_for_submission(
        db, sub.id, project_id=project.id, study_id="study-a"
    )
    db.add(
        DqaFlag(
            id=stable_flag_id(sub.id, "R1"),
            submission_id=sub.id,
            project_id=project.id,
            study_id="study-a",
            rule_id="R1",
            severity="amber",
            title="t",
            message="m",
            evaluated_at=datetime(2026, 3, 12),
        )
    )
    db.commit()

    assign_project(db, study_b, project)
    db.refresh(sub)
    answer = db.scalars(
        select(SubmissionAnswer).where(SubmissionAnswer.submission_id == sub.id)
    ).first()
    quality = db.get(SubmissionQuality, sub.id)
    flag = db.scalars(select(DqaFlag).where(DqaFlag.submission_id == sub.id)).first()
    assert sub.study_id == "study-b"
    assert answer is not None and answer.study_id == "study-b"
    assert quality is not None and quality.study_id == "study-b"
    assert flag is not None and flag.study_id == "study-b"

    # Old study no longer owns these projection rows
    assert (
        db.scalar(
            select(SubmissionAnswer).where(
                SubmissionAnswer.study_id == "study-a",
                SubmissionAnswer.submission_id == sub.id,
            )
        )
        is None
    )

    unassign_project(db, project)
    db.refresh(sub)
    assert sub.study_id is None
    assert (
        db.scalar(select(SubmissionAnswer).where(SubmissionAnswer.submission_id == sub.id))
        is None
    )
    assert db.get(SubmissionQuality, sub.id) is None
    flag2 = db.scalars(select(DqaFlag).where(DqaFlag.submission_id == sub.id)).first()
    assert flag2 is not None
    assert flag2.study_id is None


def test_resync_helper_direct(db: Session) -> None:
    _, project = _seed(db, study_id="study-x")
    sub = _submission(db, project)
    replace_answers_for_submission(db, sub, project=project)
    db.commit()

    resync_study_id_for_project(db, project.id, "study-y")
    db.commit()
    db.refresh(sub)
    assert sub.study_id == "study-y"
    assert (
        db.scalars(select(SubmissionAnswer).where(SubmissionAnswer.submission_id == sub.id))
        .first()
        .study_id
        == "study-y"
    )

    resync_study_id_for_project(db, project.id, None)
    db.commit()
    assert (
        db.scalar(select(SubmissionAnswer).where(SubmissionAnswer.submission_id == sub.id))
        is None
    )
