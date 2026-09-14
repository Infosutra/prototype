"""Salvage + plain-language plan failures for interactive authoring."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain.reporting.validation import validate_report_spec
from app.services.report_templates import create_draft
from app.services.reporting.authoring import author_turn
from app.services.reporting.plan_explain import explain_validation_error
from app.services.reporting.plan_salvage import autofix_narratives, salvage_report_spec
from app.services.reporting.planner import plan_report
from app.services.reporting.prompt_seeds import seed_reporting_prompts
from tests.helpers.reporting_fixture import STUDY_ID, seed_golden_reporting

BASELINE = {
    "specVersion": "1.0",
    "title": "DQA Daily Report",
    "sections": [
        {
            "id": "s1",
            "title": "Today's intake",
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

BAD_CANDIDATE = {
    "specVersion": "1.0",
    "title": "DQA Daily Report",
    "sections": [
        BASELINE["sections"][0],
        {
            "id": "s2",
            "title": "By tool",
            "components": [
                {
                    "id": "tbl",
                    "type": "table",
                    "query": {
                        "entity": "submission",
                        "window": "execution_date",
                        "groupBy": ["toolCode"],
                        "measures": [{"id": "total", "fn": "count"}],
                    },
                    "display": {"columns": ["toolCode", "total"]},
                }
            ],
        },
        {
            "id": "s6",
            "title": "Impossible duration block",
            "components": [
                {
                    "id": "median_tbl",
                    "type": "table",
                    "query": {
                        "entity": "submission",
                        "window": "execution_date",
                        "groupBy": ["notARealField"],
                        "measures": [{"id": "total", "fn": "count"}],
                    },
                    "display": {"columns": ["notARealField", "total"]},
                }
            ],
        },
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


def test_explain_extra_inputs_names_concrete_ask() -> None:
    instructions = (
        "Section 1.1 — Today's intake and flags by tool. Show a table… "
        "Add a stacked bar chart of today's RED and AMBER by tool, and a horizontal bar "
        "chart of the rules failing most often today."
    )
    msg = explain_validation_error(
        "sections.0.components.2.display.orientation: Extra inputs are not permitted",
        spec={
            "sections": [
                {
                    "title": "Today's Intake and Flags by Tool",
                    "components": [
                        {"id": "t", "type": "table", "display": {"columns": ["toolCode"]}},
                        {
                            "id": "c1",
                            "type": "chart",
                            "display": {"kind": "stacked_bar", "x": "toolCode", "y": ["red"]},
                        },
                        {
                            "id": "c2",
                            "type": "chart",
                            "display": {
                                "kind": "bar_horizontal",
                                "orientation": "horizontal",
                                "x": "ruleTitle",
                                "y": ["total"],
                            },
                        },
                    ],
                }
            ]
        },
        instructions=instructions,
    )
    assert "extra inputs" not in msg.lower()
    assert "rules failing" in msg.lower() or "horizontal" in msg.lower()
    assert "specific data query" not in msg.lower()


def test_humanize_uses_llm_prompt_when_available() -> None:
    from app.services.reporting.plan_explain import humanize_validation_error

    def invoker(*, system: str, user: str, purpose: str) -> dict:
        assert purpose == "explain"
        assert "Extra inputs" in user
        return {
            "prompt": (
                "I couldn't include the horizontal bar chart of rules failing most often "
                "today. That chart layout isn't supported as drafted. Keep the table and "
                "stacked chart, rephrase the rules chart, or leave it off."
            ),
            "failedAsk": "horizontal bar chart of rules failing most often",
        }

    msg = humanize_validation_error(
        "sections.0.components.2.display.orientation: Extra inputs are not permitted",
        spec={
            "sections": [
                {
                    "title": "Today's intake and flags by tool",
                    "components": [
                        {"type": "table"},
                        {"type": "chart", "display": {"kind": "stacked_bar"}},
                        {"type": "chart", "display": {"kind": "bar_horizontal"}},
                    ],
                }
            ]
        },
        instructions=(
            "stacked bar chart of RED and AMBER by tool, and a horizontal bar "
            "chart of the rules failing most often today"
        ),
        invoker=invoker,
    )
    assert "extra inputs" not in msg.lower()
    assert "rules failing" in msg.lower()



def test_autofix_attaches_uses_to_orphan_narrative() -> None:
    fixed = autofix_narratives(
        {
            "specVersion": "1.0",
            "title": "T",
            "sections": [
                {
                    "id": "s1",
                    "title": "Intake",
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
                        },
                        {
                            "id": "headline",
                            "type": "narrative",
                            "display": {
                                "role": "insight",
                                "instruction": "Write a short headline.",
                            },
                        },
                    ],
                }
            ],
        }
    )
    narr = fixed["sections"][0]["components"][1]
    assert narr["uses"] == ["kpi"]
    assert validate_report_spec(fixed) == []


def test_salvage_keeps_earlier_sections_and_baseline() -> None:
    result = salvage_report_spec(BAD_CANDIDATE, baseline=BASELINE)
    assert result["spec"] is not None
    assert validate_report_spec(result["spec"]) == []
    titles = [s["title"] for s in result["spec"]["sections"]]
    assert "Today's intake" in titles
    assert "By tool" in titles
    assert "Impossible duration block" not in titles
    assert result["issues"]


def test_plan_report_partial_ok_keeps_valid_subset(golden: Session) -> None:
    llm = _scripted_llm(
        [
            {"spec": BAD_CANDIDATE, "unmapped": []},
            {"spec": BAD_CANDIDATE, "unmapped": []},
        ]
    )
    result = plan_report(
        golden,
        study_id=STUDY_ID,
        instructions="Add RED items narrative",
        current_spec=BASELINE,
        llm=llm,
        judge=False,
        partial_ok=True,
    )
    assert result["partial"] is True
    assert validate_report_spec(result["spec"]) == []
    assert result["issues"]
    assert len(result["spec"]["sections"]) >= 1


def test_author_turn_keeps_prior_spec_on_partial_failure(golden: Session) -> None:
    template = create_draft(golden, study_id=STUDY_ID, name="Draft")
    template.working_spec_json = BASELINE
    template.authoring_json = {
        "status": "awaiting_user",
        "pendingQuestions": [],
        "promptText": "Today's intake KPIs",
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

    llm = _scripted_llm(
        [
            {"spec": BAD_CANDIDATE, "unmapped": []},
            {"spec": BAD_CANDIDATE, "unmapped": []},
        ]
    )
    events = list(
        author_turn(
            golden,
            template,
            message="Add a section with an unknown field",
            llm=llm,
        )
    )
    golden.refresh(template)
    titles = [s["title"] for s in template.working_spec_json["sections"]]
    assert "Today's intake" in titles
    assert "By tool" in titles
    assert "Impossible duration block" not in titles
    assert any(e.get("event") == "questions" for e in events)
    assistant = next(e for e in events if e.get("event") == "assistant")
    assert "ReportSpec failed validation" not in assistant["text"]
    assert "kept" in assistant["text"].lower() or "help" in assistant["text"].lower()
    assert not any(e.get("event") == "error" for e in events)


def test_salvage_retries_chart_kind_before_drop() -> None:
    from app.services.reporting.plan_salvage import _chart_kind_attempts

    component = {
        "id": "by_day",
        "type": "chart",
        "query": {
            "entity": "flag",
            "window": "study_to_date",
            "groupBy": ["day"],
            "measures": [{"id": "total", "fn": "count"}],
        },
        "display": {"kind": "line", "x": "day", "y": ["total"]},
    }
    kinds = [row["display"]["kind"] for row in _chart_kind_attempts(component)]
    assert kinds[0] == "line"
    assert "bar" in kinds
    assert "bar_horizontal" in kinds

    candidate = {
        "specVersion": "1.0",
        "title": "Trend",
        "sections": [
            {
                "id": "s1",
                "title": "1.4 — Coverage and Trend",
                "components": [component],
            }
        ],
    }
    out = salvage_report_spec(candidate, baseline=None, errors=["x"])
    titles = [s.get("title") for s in (out.get("spec") or {}).get("sections") or []]
    assert "1.4 — Coverage and Trend" in titles


def test_explain_flag_rate_prefers_user_ask_over_line_chart() -> None:
    instructions = (
        "Section 1.4 — Coverage and trend. Explain coverage against plan and how the "
        "cumulative flag rate has moved, then show cumulative submissions against target "
        "by tool and the flag rate by study day."
    )
    dropped = {
        "id": "flag_rate_chart",
        "type": "chart",
        "query": {
            "entity": "flag",
            "window": "study_to_date",
            "groupBy": ["day"],
            "measures": [{"id": "rate", "fn": "rate"}],
        },
        "display": {"kind": "line", "x": "day", "y": ["rate"]},
    }
    msg = explain_validation_error(
        "sections.0.components.0.query.measures.0.fn: Input should be 'count', "
        "'countDistinct', 'countWhere', 'sum', 'avg', 'min' or 'max'",
        instructions=instructions,
        section_draft={"title": "1.4 — Coverage and Trend", "components": [dropped]},
        dropped_component=dropped,
    ).lower()
    assert "flag rate" in msg
    assert "line chart of flag rates" not in msg
    assert "specific condition" not in msg
    assert "rate" in msg or "count" in msg


def test_partial_question_offers_chart_alternatives() -> None:
    from app.services.reporting.plan_explain import partial_issue_question

    q = partial_issue_question(
        "Could not include flag rate by study day.",
        dropped_component={
            "type": "chart",
            "display": {"kind": "line", "x": "day", "y": ["total"]},
        },
    )
    labels = [o["label"].lower() for o in q["options"]]
    assert any("bar chart" in label for label in labels)
    assert any("table" in label for label in labels)
    assert any("leave" in label for label in labels)
    assert not any(o["id"] == "as_line" for o in q["options"])
