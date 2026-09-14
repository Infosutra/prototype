"""Fix-3: catalog tools, field clashes, binder, authoring pauses."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Project, StudyTool, Submission, SubmissionAnswer
from app.domain.reporting.conflicts import find_field_tool_conflicts
from app.services.report_templates import create_draft
from app.services.reporting.authoring import author_turn
from app.services.reporting.binder import apply_mappings, bind_spec, catalog_allowlist
from app.services.reporting.catalog_for_llm import catalog_for_llm
from app.services.reporting.planner import plan_report
from app.services.reporting.prompt_seeds import seed_reporting_prompts
from tests.helpers.reporting_fixture import STUDY_ID, seed_golden_reporting

A10_SPEC = {
    "specVersion": "1.0",
    "title": "A10 counts",
    "sections": [
        {
            "id": "s1",
            "title": "Answers",
            "components": [
                {
                    "id": "c1",
                    "type": "metric",
                    "query": {
                        "entity": "answer",
                        "window": "execution_date",
                        "filters": [{"field": "fieldKey", "op": "eq", "value": "A10"}],
                        "measures": [{"id": "total", "fn": "count"}],
                    },
                    "display": {"label": "A10", "field": "total"},
                }
            ],
        }
    ],
}

INTERVIEWER_SPEC = {
    "specVersion": "1.0",
    "title": "By interviewer",
    "sections": [
        {
            "id": "s1",
            "title": "Staff",
            "components": [
                {
                    "id": "c1",
                    "type": "table",
                    "query": {
                        "entity": "submission",
                        "window": "execution_date",
                        "groupBy": ["interviewer"],
                        "measures": [{"id": "total", "fn": "count"}],
                    },
                    "display": {"columns": ["interviewer", "total"]},
                }
            ],
        }
    ],
}


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
def golden(db: Session) -> Session:
    seed_golden_reporting(db)
    seed_reporting_prompts(db)
    return db


def _scripted_llm(responses: list[dict]):
    queue = list(responses)

    def _invoke(*, system: str, user: str, purpose: str) -> dict:
        if not queue:
            raise AssertionError(f"Unexpected LLM call purpose={purpose}")
        return queue.pop(0)

    return _invoke


def _seed_duplicate_a10(db: Session) -> None:
    t5 = StudyTool(
        id="tool-t5",
        study_id=STUDY_ID,
        code="T5",
        label="Class-3 Assessment",
        sort_order=5,
    )
    t6 = StudyTool(
        id="tool-t6",
        study_id=STUDY_ID,
        code="T6",
        label="Class-5 Assessment",
        sort_order=6,
    )
    db.add_all([t5, t6])
    db.flush()
    p5 = Project(
        id="proj-t5",
        uid="proj-t5",
        name="Class 3",
        study_id=STUDY_ID,
        study_tool_id=t5.id,
        form_definition={"survey": [], "choices": []},
    )
    p6 = Project(
        id="proj-t6",
        uid="proj-t6",
        name="Class 5",
        study_id=STUDY_ID,
        study_tool_id=t6.id,
        form_definition={"survey": [], "choices": []},
    )
    db.add_all([p5, p6])
    db.flush()
    day = date(2026, 9, 12)
    for project_id, kobo in (("proj-t5", "501"), ("proj-t6", "601")):
        sub = Submission(
            id=f"{project_id}:{kobo}",
            kobo_id=kobo,
            project_id=project_id,
            study_id=STUDY_ID,
            form_id=project_id,
            form_name=project_id,
            enumerator="Meena",
            submitted_at=datetime(2026, 9, 12, 10, 0, 0),
            data={},
            calendar_day=day,
            status="pending",
        )
        db.add(sub)
        db.flush()
        db.add(
            SubmissionAnswer(
                id=f"ans-{kobo}",
                submission_id=sub.id,
                project_id=project_id,
                study_id=STUDY_ID,
                field_key="A10",
                field_label="Item A10",
                value_type="number",
                value_number=1.0,
            )
        )
    db.commit()


def test_catalog_lists_field_key_per_tool(golden: Session) -> None:
    _seed_duplicate_a10(golden)
    catalog = catalog_for_llm(golden, STUDY_ID)
    keys = catalog["entities"]["answer"]["studyFieldKeys"]
    a10 = [row for row in keys if row["fieldKey"] == "A10"]
    assert {row["toolCode"] for row in a10} == {"T5", "T6"}
    q_age = [row for row in keys if row["fieldKey"] == "q_age"]
    assert q_age and q_age[0].get("toolCode") == "T1"


def test_conflict_asks_which_form() -> None:
    keys = [
        {"fieldKey": "A10", "toolCode": "T5", "toolLabel": "Class-3 Assessment"},
        {"fieldKey": "A10", "toolCode": "T6", "toolLabel": "Class-5 Assessment"},
    ]
    questions = find_field_tool_conflicts(A10_SPEC, keys)
    assert len(questions) == 1
    assert questions[0]["kind"] == "field_tool_conflict"
    assert "T5" in questions[0]["prompt"]
    assert "T6" in questions[0]["prompt"]


def test_conflict_skipped_when_tool_pinned() -> None:
    spec = {
        **A10_SPEC,
        "sections": [
            {
                "id": "s1",
                "title": "Answers",
                "components": [
                    {
                        "id": "c1",
                        "type": "metric",
                        "query": {
                            "entity": "answer",
                            "window": "execution_date",
                            "filters": [
                                {"field": "fieldKey", "op": "eq", "value": "A10"},
                                {"field": "toolCode", "op": "eq", "value": "T5"},
                            ],
                            "measures": [{"id": "total", "fn": "count"}],
                        },
                        "display": {"label": "A10", "field": "total"},
                    }
                ],
            }
        ],
    }
    keys = [
        {"fieldKey": "A10", "toolCode": "T5", "toolLabel": "Class-3"},
        {"fieldKey": "A10", "toolCode": "T6", "toolLabel": "Class-5"},
    ]
    assert find_field_tool_conflicts(spec, keys) == []


def test_binder_maps_allowlisted_names_only() -> None:
    catalog = {
        "entities": {
            "submission": {"fields": ["enumerator", "toolCode"]},
        }
    }
    allow = catalog_allowlist(catalog)
    assert "enumerator" in allow
    spec = apply_mappings(
        {
            "sections": [
                {
                    "components": [
                        {
                            "query": {
                                "entity": "submission",
                                "groupBy": ["interviewer"],
                                "filters": [],
                                "measures": [],
                            }
                        }
                    ]
                }
            ]
        },
        [{"from": "interviewer", "to": "enumerator"}],
    )
    query = spec["sections"][0]["components"][0]["query"]
    assert query["groupBy"] == ["enumerator"]


def test_binder_rejects_unknown_target(golden: Session) -> None:
    catalog = catalog_for_llm(golden, STUDY_ID)
    llm = _scripted_llm(
        [{"mappings": [{"from": "interviewer", "to": "notARealField"}], "unmapped": []}]
    )
    result = bind_spec(dict(INTERVIEWER_SPEC), catalog, invoker=llm)
    assert result["mappings"] == []
    assert result["unmapped"]
    assert "interviewer" in result["spec"]["sections"][0]["components"][0]["query"]["groupBy"]


def test_plan_skips_judge_when_requested(golden: Session) -> None:
    llm = _scripted_llm([{"spec": A10_SPEC, "unmapped": []}])
    result = plan_report(
        golden,
        study_id=STUDY_ID,
        instructions="Count A10",
        llm=llm,
        judge=False,
    )
    assert result["judgement"]["faithful"] is True


def test_author_turn_pauses_on_field_clash(golden: Session) -> None:
    _seed_duplicate_a10(golden)
    template = create_draft(golden, study_id=STUDY_ID, name="Draft")
    llm = _scripted_llm([{"spec": A10_SPEC, "unmapped": []}])
    events = list(author_turn(golden, template, message="Count A10", llm=llm))
    kinds = [e["event"] for e in events]
    assert "step" in kinds
    assert "questions" in kinds
    questions = next(e["questions"] for e in events if e.get("event") == "questions")
    assert questions[0]["kind"] == "field_tool_conflict"
    golden.refresh(template)
    assert template.authoring_json["status"] == "awaiting_user"
    assert template.working_spec_json["title"] == "A10 counts"

    events2 = list(
        author_turn(
            golden,
            template,
            message="T5",
            answer={"questionId": questions[0]["id"], "value": "T5"},
            llm=llm,
        )
    )
    filters = template.working_spec_json["sections"][0]["components"][0]["query"]["filters"]
    assert {"field": "toolCode", "op": "eq", "value": "T5"} in filters
    follow_up = next(e for e in events2 if e.get("event") == "questions")
    assert follow_up["questions"][0]["kind"] == "confirm_spec"


def test_placement_question_options_include_existing_sections() -> None:
    from app.services.reporting.authoring import (
        _is_unplaced_content_request,
        _placement_question,
        _resolve_answer,
    )

    ask = "Close with a read-only sign-off checklist of open RED and AMBER items."
    assert _is_unplaced_content_request(ask)
    assert not _is_unplaced_content_request("yes")
    assert not _is_unplaced_content_request("Section 1.6 — Sign-off checklist")

    spec = {
        "specVersion": "1.0",
        "title": "DQA",
        "sections": [
            {
                "id": "s1",
                "title": "1.1 — Today's intake",
                "components": [
                    {
                        "id": "kpi",
                        "type": "kpi_group",
                        "query": {
                            "entity": "submission",
                            "window": "execution_date",
                            "measures": [{"id": "total", "fn": "count"}],
                        },
                        "display": {"items": [{"label": "Total", "field": "total"}]},
                    }
                ],
            }
        ],
    }
    question = _placement_question(ask, spec)
    assert question["kind"] == "section_placement"
    values = [o["value"] for o in question["options"]]
    assert values[0] == "new"
    assert "section:s1" in values
    assert values[-1] == "leave"

    resolved, note, replan = _resolve_answer(spec, question, "new")
    assert resolved is True
    assert replan is False
    assert "Added a new section" in note
    assert any("sign" in str(s.get("title") or "").lower() for s in spec["sections"])

    # Append into existing section on a fresh copy.
    spec2 = {
        "specVersion": "1.0",
        "title": "DQA",
        "sections": [
            {
                "id": "s1",
                "title": "1.1 — Today's intake",
                "components": [
                    {
                        "id": "kpi",
                        "type": "kpi_group",
                        "query": {
                            "entity": "submission",
                            "window": "execution_date",
                            "measures": [{"id": "total", "fn": "count"}],
                        },
                        "display": {"items": [{"label": "Total", "field": "total"}]},
                    }
                ],
            }
        ],
    }
    q2 = _placement_question(ask, spec2)
    resolved2, note2, replan2 = _resolve_answer(spec2, q2, "section:s1")
    assert resolved2 is True
    assert replan2 is False
    assert "Added into existing section" in note2
    assert len(spec2["sections"][0]["components"]) > 1


def test_author_turn_asks_section_placement_when_spec_unchanged(golden: Session) -> None:
    template = create_draft(golden, study_id=STUDY_ID, name="Draft")
    prior = {
        "specVersion": "1.0",
        "title": "DQA Daily Report",
        "sections": [
            {
                "id": "s1",
                "title": "1.1 — Today's intake",
                "components": [
                    {
                        "id": "kpi",
                        "type": "kpi_group",
                        "query": {
                            "entity": "submission",
                            "window": "execution_date",
                            "measures": [{"id": "total", "fn": "count"}],
                        },
                        "display": {"items": [{"label": "Total", "field": "total"}]},
                    }
                ],
            }
        ],
    }
    template.working_spec_json = prior
    template.authoring_json = {
        "status": "awaiting_user",
        "pendingQuestions": [],
        "promptText": "Section 1.1 — Today's intake",
        "messages": [
            {
                "id": "m1",
                "role": "assistant",
                "content": "Draft ready",
                "createdAt": "2026-09-14T00:00:00Z",
                "steps": [],
            }
        ],
        "unmapped": [],
        "binderMappings": [],
    }
    golden.commit()

    # Planner returns the same structure — unnumbered ask is ignored.
    llm = _scripted_llm(
        [
            {"spec": prior, "unmapped": []},
            {"spec": prior, "unmapped": []},
        ]
    )
    ask = "Close with a read-only sign-off checklist of open RED and AMBER items."
    events = list(author_turn(golden, template, message=ask, llm=llm))
    questions_event = next(e for e in events if e.get("event") == "questions")
    kinds = [q["kind"] for q in questions_event["questions"]]
    assert "section_placement" in kinds
    placement = next(q for q in questions_event["questions"] if q["kind"] == "section_placement")
    assert placement["userAsk"] == ask
    assert any(o["value"] == "new" for o in placement["options"])
    assert any(str(o["value"]).startswith("section:") for o in placement["options"])
