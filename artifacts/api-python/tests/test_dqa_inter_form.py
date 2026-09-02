"""Phase 2 inter-form DQA tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import DqaRelationship, Project, RulePack, Study, StudyTool, Submission
from app.domain.dqa.context import RelatedResolution
from app.domain.dqa.eval import eval_check
from app.domain.dqa.operands import related_field_ref
from app.domain.dqa.validate import validate_rule
from app.services.dqa_evaluation import evaluate_project, evaluate_project_cascade
from app.services.dqa_relationship_resolver import resolve_relationship
from app.services.dqa_relationships import create_relationship, validate_relationship_payload


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


def _seed_inter_form_study(db: Session) -> dict[str, str]:
    study = Study(id="study-if", name="Inter-form", description=None, start_date=None, end_date=None, timezone="UTC")
    db.add(study)
    assess_tool = StudyTool(id="tool-a", study_id=study.id, code="A", label="Assessment", sort_order=0)
    enroll_tool = StudyTool(id="tool-e", study_id=study.id, code="E", label="Enrollment", sort_order=1)
    db.add_all([assess_tool, enroll_tool])
    assess = Project(
        id="proj-assess",
        uid="uid-assess",
        name="Assessment",
        study_id=study.id,
        study_tool_id=assess_tool.id,
        form_definition={"survey": [{"type": "text", "name": "student_id", "label": "Student"}], "choices": []},
    )
    enroll = Project(
        id="proj-enroll",
        uid="uid-enroll",
        name="Enrollment",
        study_id=study.id,
        study_tool_id=enroll_tool.id,
        form_definition={"survey": [{"type": "text", "name": "student_id", "label": "Student"}], "choices": []},
    )
    db.add_all([assess, enroll])
    db.add(
        RulePack(
            project_id=assess.id,
            pack={
                "fields": {"student_id": "student_id", "assessment_date": "assessment_date"},
                "rules": [
                    {
                        "id": "IF-1",
                        "severity": "red",
                        "title": "Assessment before enrollment",
                        "message": "Assessment date precedes enrollment",
                        "check": {
                            "op": "gte",
                            "field": "assessment_date",
                            "field_b": related_field_ref("student_enrollment", "enrollment_date"),
                        },
                    }
                ],
            },
        )
    )
    db.add(
        RulePack(
            project_id=enroll.id,
            pack={"fields": {"student_id": "student_id", "enrollment_date": "enrollment_date"}, "rules": []},
        )
    )
    rel = DqaRelationship(
        id="rel-1",
        study_id=study.id,
        code="student_enrollment",
        title="Student enrollment",
        source_project_id=assess.id,
        target_project_id=enroll.id,
        source_join_field="student_id",
        target_join_field="student_id",
        cardinality="one",
    )
    db.add(rel)
    db.commit()
    return {"study_id": study.id, "assess": assess.id, "enroll": enroll.id, "rel_code": rel.code}


def _submission(
    *,
    id: str,
    project_id: str,
    kobo_id: str,
    form_id: str,
    form_name: str,
    data: dict,
    submitted_at: datetime | None = None,
) -> Submission:
    return Submission(
        id=id,
        project_id=project_id,
        kobo_id=kobo_id,
        form_id=form_id,
        form_name=form_name,
        enumerator="E1",
        submitted_at=submitted_at or datetime(2026, 1, 1),
        data=data,
    )

    ids = _seed_inter_form_study(db)
    result = validate_relationship_payload(
        db,
        ids["study_id"],
        {
            "code": "bad_rel",
            "source_project_id": ids["assess"],
            "target_project_id": ids["enroll"],
            "source_join_field": "missing_field",
            "target_join_field": "enrollment_date",
        },
    )
    assert result.valid is False
    assert any(e.code == "unknown_field" for e in result.errors)


def test_resolve_one_related_record(db: Session):
    ids = _seed_inter_form_study(db)
    rel = db.get(DqaRelationship, "rel-1")
    assess_sub = _submission(
        id="sub-a1",
        project_id=ids["assess"],
        kobo_id="k-a1",
        form_id="uid-assess",
        form_name="Assessment",
        data={"student_id": "S1", "assessment_date": "2026-01-10"},
        submitted_at=datetime(2026, 1, 10),
    )
    enroll_sub = _submission(
        id="sub-e1",
        project_id=ids["enroll"],
        kobo_id="k-e1",
        form_id="uid-enroll",
        form_name="Enrollment",
        data={"student_id": "S1", "enrollment_date": "2026-01-15"},
        submitted_at=datetime(2026, 1, 5),
    )
    db.add_all([assess_sub, enroll_sub])
    db.commit()
    resolution = resolve_relationship(
        db,
        relationship=rel,
        current=assess_sub,
        source_pack={"fields": {"student_id": "student_id"}},
        target_rows=[enroll_sub],
        target_pack={"fields": {"student_id": "student_id", "enrollment_date": "enrollment_date"}},
    )
    assert resolution.status == "resolved"
    assert resolution.submission.id == "sub-e1"


def test_resolve_no_related_record(db: Session):
    ids = _seed_inter_form_study(db)
    rel = db.get(DqaRelationship, "rel-1")
    assess_sub = _submission(
        id="sub-a2",
        project_id=ids["assess"],
        kobo_id="k-a2",
        form_id="uid-assess",
        form_name="Assessment",
        data={"student_id": "S99", "assessment_date": "2026-01-10"},
    )
    db.add(assess_sub)
    db.commit()
    resolution = resolve_relationship(
        db,
        relationship=rel,
        current=assess_sub,
        source_pack={"fields": {"student_id": "student_id"}},
        target_rows=[],
        target_pack={"fields": {"student_id": "student_id"}},
    )
    assert resolution.status == "none"


def test_resolve_multiple_related_records_ambiguous(db: Session):
    ids = _seed_inter_form_study(db)
    rel = db.get(DqaRelationship, "rel-1")
    assess_sub = _submission(
        id="sub-a3",
        project_id=ids["assess"],
        kobo_id="k-a3",
        form_id="uid-assess",
        form_name="Assessment",
        data={"student_id": "S1", "assessment_date": "2026-01-10"},
    )
    enroll_a = _submission(
        id="sub-e2",
        project_id=ids["enroll"],
        kobo_id="k-e2",
        form_id="uid-enroll",
        form_name="Enrollment",
        data={"student_id": "S1", "enrollment_date": "2026-01-01"},
        submitted_at=datetime(2026, 1, 1),
    )
    enroll_b = _submission(
        id="sub-e3",
        project_id=ids["enroll"],
        kobo_id="k-e3",
        form_id="uid-enroll",
        form_name="Enrollment",
        data={"student_id": "S1", "enrollment_date": "2026-01-20"},
        submitted_at=datetime(2026, 1, 20),
    )
    db.add_all([assess_sub, enroll_a, enroll_b])
    db.commit()
    resolution = resolve_relationship(
        db,
        relationship=rel,
        current=assess_sub,
        source_pack={"fields": {"student_id": "student_id"}},
        target_rows=[enroll_a, enroll_b],
        target_pack={"fields": {"student_id": "student_id"}},
    )
    assert resolution.status == "ambiguous"
    assert len(resolution.candidates) == 2


def test_resolve_missing_join_key(db: Session):
    ids = _seed_inter_form_study(db)
    rel = db.get(DqaRelationship, "rel-1")
    assess_sub = _submission(
        id="sub-a4",
        project_id=ids["assess"],
        kobo_id="k-a4",
        form_id="uid-assess",
        form_name="Assessment",
        data={"assessment_date": "2026-01-10"},
    )
    db.add(assess_sub)
    db.commit()
    resolution = resolve_relationship(
        db,
        relationship=rel,
        current=assess_sub,
        source_pack={"fields": {"student_id": "student_id"}},
        target_rows=[],
        target_pack={"fields": {"student_id": "student_id"}},
    )
    assert resolution.status == "missing_key"


def test_inter_form_date_rule_flags(db: Session):
    ids = _seed_inter_form_study(db)
    assess_sub = _submission(
        id="sub-a5",
        project_id=ids["assess"],
        kobo_id="k-a5",
        form_id="uid-assess",
        form_name="Assessment",
        data={"student_id": "S1", "assessment_date": "2026-01-10"},
    )
    enroll_sub = _submission(
        id="sub-e5",
        project_id=ids["enroll"],
        kobo_id="k-e5",
        form_id="uid-enroll",
        form_name="Enrollment",
        data={"student_id": "S1", "enrollment_date": "2026-01-15"},
    )
    db.add_all([assess_sub, enroll_sub])
    db.commit()
    pack = {"fields": {"student_id": "student_id", "assessment_date": "assessment_date"}}
    related = {
        "student_enrollment": RelatedResolution(
            relationship_code="student_enrollment",
            status="resolved",
            submission=enroll_sub,
            data=enroll_sub.data,
            pack={"fields": {"enrollment_date": "enrollment_date"}},
            join_key="S1",
        )
    }
    ok, details = eval_check(
        {
            "op": "gte",
            "field": "assessment_date",
            "field_b": related_field_ref("student_enrollment", "enrollment_date"),
        },
        data=assess_sub.data,
        pack=pack,
        related=related,
    )
    assert ok is False
    assert details.get("relatedSubmissions")


def test_inter_form_rule_not_applicable_without_related(db: Session):
    pack = {"fields": {"assessment_date": "assessment_date"}}
    ok, details = eval_check(
        {
            "op": "lt",
            "field": "assessment_date",
            "field_b": related_field_ref("student_enrollment", "enrollment_date"),
        },
        data={"assessment_date": "2026-01-10"},
        pack=pack,
        related={
            "student_enrollment": RelatedResolution(
                relationship_code="student_enrollment",
                status="none",
                join_key="S1",
            )
        },
    )
    assert ok is True
    assert details.get("right_relatedResolution") == "none"


def test_validate_related_field_rule(db: Session):
    ids = _seed_inter_form_study(db)
    rule = {
        "severity": "amber",
        "title": "t",
        "message": "m",
        "check": {
            "op": "gte",
            "field": "assessment_date",
            "field_b": related_field_ref("student_enrollment", "enrollment_date"),
        },
    }
    result = validate_rule(
        rule,
        form_fields=[{"name": "assessment_date", "type": "text", "label": "Assessment date"}],
        pack={"fields": {"assessment_date": "assessment_date"}},
        related_fields={"student_enrollment": {"enrollment_date", "student_id"}},
    )
    assert result.valid is True


def test_recompute_cascade_on_enrollment_change(db: Session):
    ids = _seed_inter_form_study(db)
    assess_sub = _submission(
        id="sub-r1",
        project_id=ids["assess"],
        kobo_id="k-r1",
        form_id="uid-assess",
        form_name="Assessment",
        data={"student_id": "S1", "assessment_date": "2026-01-05"},
    )
    enroll_sub = _submission(
        id="sub-r2",
        project_id=ids["enroll"],
        kobo_id="k-r2",
        form_id="uid-enroll",
        form_name="Enrollment",
        data={"student_id": "S1", "enrollment_date": "2026-01-10"},
    )
    db.add_all([assess_sub, enroll_sub])
    db.commit()
    stats = evaluate_project_cascade(db, ids["enroll"])
    assert ids["assess"] in stats["cascade_projects"]
    assert stats["flags"] >= 1


def test_create_relationship(db: Session):
    ids = _seed_inter_form_study(db)
    row = create_relationship(
        db,
        ids["study_id"],
        {
            "code": "alt_link",
            "source_project_id": ids["assess"],
            "target_project_id": ids["enroll"],
            "source_join_field": "student_id",
            "target_join_field": "student_id",
        },
    )
    assert row.code == "alt_link"
