"""Unit tests for study-defined triangulation evaluators."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Project, Study, StudyTool, Submission, TriangulationView
from app.seeds import load_triangulation_seed_definitions
from app.services import triangulation as tri
from app.services.triangulation import TriangulationError


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


def _seed_study(db: Session) -> Study:
    study = Study(
        id="study-test",
        name="Test Study",
        description=None,
        start_date=None,
        end_date=None,
        timezone="UTC",
    )
    db.add(study)
    tools = {
        "T1": StudyTool(id="tool-t1", study_id=study.id, code="T1", label="Facility", sort_order=0),
        "T2": StudyTool(id="tool-t2", study_id=study.id, code="T2", label="Teachers", sort_order=1),
        "T3": StudyTool(id="tool-t3", study_id=study.id, code="T3", label="Parents", sort_order=2),
    }
    for t in tools.values():
        db.add(t)
    db.flush()

    facility = Project(
        id="proj-t1",
        uid="uid-t1",
        name="Facility",
        study_id=study.id,
        study_tool_id=tools["T1"].id,
    )
    teachers = Project(
        id="proj-t2",
        uid="uid-t2",
        name="Teachers",
        study_id=study.id,
        study_tool_id=tools["T2"].id,
    )
    parents = Project(
        id="proj-t3",
        uid="uid-t3",
        name="Parents",
        study_id=study.id,
        study_tool_id=tools["T3"].id,
    )
    db.add_all([facility, teachers, parents])
    db.flush()

    # Rule packs via direct table (RulePack model)
    from app.db.models import RulePack

    db.add(
        RulePack(
            project_id=facility.id,
            pack={
                "join_key": "udise",
                "fields": {
                    "udise": "UDISE",
                    "institution_name": "NAME",
                    "meetings_held": "MEET",
                    "cwd_discussed": "CWD",
                },
            },
        )
    )
    db.add(
        RulePack(
            project_id=teachers.id,
            pack={
                "join_key": "udise",
                "fields": {
                    "udise": "UDISE",
                    "institution_name": "NAME",
                    "has_cwd": "D1",
                    "practice_d4": "D4",
                    "observe_front_seating": "CO1",
                    "observe_differentiated": "CO2",
                    "observe_multi_sensory": "CO3",
                    "observe_peer_group": "CO4",
                    "observe_adapted_materials": "CO8",
                },
            },
        )
    )
    db.add(
        RulePack(
            project_id=parents.id,
            pack={
                "join_key": "udise",
                "fields": {
                    "udise": "UDISE",
                    "reports_disability": "P5",
                    "attended_pta": "P17",
                    "pta_issues": "P18",
                },
            },
        )
    )

    now = datetime(2026, 8, 1, 12, 0, 0)
    # Teacher submission: claims front_seating (e) + differentiated (a);
    # CO1=3 → gap; CO2=1 → observed; CO3=4 → excluded from n; CO4 blank; CO8=2 observed
    db.add(
        Submission(
            id="sub-t2-1",
            project_id=teachers.id,
            kobo_id="100",
            form_id="uid-t2",
            form_name="Teachers",
            enumerator="E1",
            submitted_at=now,
            data={
                "UDISE": "111",
                "NAME": "School A",
                "D1": "0",
                "D4": "e a",
                "CO1": "3",
                "CO2": "1",
                "CO3": "4",
                "CO4": "",
                "CO8": "2",
            },
        )
    )
    # Facility + parent for cross-form joins
    db.add(
        Submission(
            id="sub-t1-1",
            project_id=facility.id,
            kobo_id="200",
            form_id="uid-t1",
            form_name="Facility",
            enumerator="E1",
            submitted_at=now,
            data={"UDISE": "111", "NAME": "School A", "MEET": "2", "CWD": "1"},
        )
    )
    db.add(
        Submission(
            id="sub-t3-1",
            project_id=parents.id,
            kobo_id="300",
            form_id="uid-t3",
            form_name="Parents",
            enumerator="E1",
            submitted_at=now + timedelta(hours=1),
            data={"UDISE": "111", "P5": "1", "P17": "0", "P18": "0"},
        )
    )

    # Seed view definitions from YAML
    for definition in load_triangulation_seed_definitions():
        code = definition["code"]
        db.add(
            TriangulationView(
                id=f"tv-{code}",
                study_id=study.id,
                code=code,
                title=str(definition.get("title") or code),
                description=str(definition.get("description") or "") or None,
                definition=definition,
            )
        )
    db.commit()
    return study


def test_missing_study_id_errors(db: Session):
    with pytest.raises(TriangulationError) as exc:
        tri.list_views(db, None)
    assert exc.value.status_code == 400

    with pytest.raises(TriangulationError) as exc2:
        tri.build_view(db, "TR-1", study_id=None)
    assert exc2.value.status_code == 400


def test_tr1_gap_n_concordance(db: Session):
    study = _seed_study(db)
    view = tri.build_view(db, "TR-1", study_id=study.id)

    assert view.mismatch_count == 1
    assert len(view.rows) == 1
    row = view.rows[0]
    assert row.mismatch is True
    gap_cell = next(c for c in row.cells if c.key == "practice_gap")
    assert gap_cell.value == 1  # only CO1=="3" with claim

    by_id = {p.id: p for p in view.practices}
    # front_seating: claimed, obs=3 → counts in n, claimed; not observed; gap
    assert by_id["front_seating"].n == 1
    assert by_id["front_seating"].claimed_count == 1
    assert by_id["front_seating"].observed_count == 0
    # differentiated: claimed, obs=1 → claimed+observed
    assert by_id["differentiated"].n == 1
    assert by_id["differentiated"].claimed_count == 1
    assert by_id["differentiated"].observed_count == 1
    # multi_sensory: obs=4 → excluded from n
    assert by_id["multi_sensory_visual"].n == 0
    # peer_group: blank obs (!=4) → in n, not claimed
    assert by_id["peer_group"].n == 1
    assert by_id["peer_group"].claimed_count == 0
    # adapted: not claimed, obs=2 → in n, observed
    assert by_id["adapted_materials"].n == 1
    assert by_id["adapted_materials"].observed_count == 1

    # concordance = max(0, 100 - |claimed_pct - observed_pct|)
    fs = by_id["front_seating"]
    assert fs.claimed_pct == 100.0
    assert fs.observed_pct == 0.0
    assert fs.concordance_pct == 0.0

    diff = by_id["differentiated"]
    assert diff.concordance_pct == 100.0


def test_tr5_and_tr3_cross_form(db: Session):
    study = _seed_study(db)

    tr5 = tri.build_view(db, "TR-5", study_id=study.id)
    assert tr5.mismatch_count == 1  # parent reports disability, teacher has_cwd False
    assert len(tr5.rows) == 1
    assert tr5.rows[0].mismatch is True

    tr3 = tri.build_view(db, "TR-3", study_id=study.id)
    # school active (meetings>0 and cwd) but parents neither attended nor issues
    assert tr3.mismatch_count == 1
    assert tr3.rows[0].mismatch is True
